"""Cross-process speech queue — one voice at a time.

Vox's daemon and every agent's vox-speak MCP server are **separate processes**, each free to start
speaking the moment it has something to say. Two agents finishing inside a minute, or Vox answering
you while an agent announces a build, produces overlapping audio that is not just untidy — it's
unlistenable, and you lose both messages. This is the "overlapping speech" risk called out in
``docs/plan/named-agents.md``.

The fix that doc recommends: a small central speak-queue. This is it — an ``fcntl.flock`` on a file
under ``data/``, which is the one coordination primitive every process already shares without any
IPC, survives a crashed holder (the OS drops the lock when the process dies), and needs no daemon to
be running.

**The timeout is a deadlock guard, not a queue policy.** If the process ahead never releases, we
speak anyway rather than block. A voice assistant that has gone silent is a worse failure than two
voices overlapping once — and this codebase has already been bitten by exactly that shape of bug
(the Kokoro streaming player deadlocking the voice loop).

**The HOLD is bounded too, not just the wait** (issue O13). A holder that never returns from inside
the ``with`` block — a wedged MCP server sat in the Kokoro streaming player, exactly the deadlock
commit ``13c9129`` fixed for the voice loop — keeps the lock until its process dies, and every other
speaker then pays the full wait on every single utterance, indefinitely. One stuck process must not
tax the whole system, so ``speech_queue_max_hold`` bounds a hold from both ends: a watchdog releases
it in the holder, and — for a holder whose watchdog never ran — a waiter that sees a hold older than
the max stops waiting and speaks.
"""

from __future__ import annotations

import contextlib
import os
import re
import threading
import time
from pathlib import Path

from vox.config import CONFIG

try:
    import fcntl
except ImportError:  # non-POSIX: every lock operation degrades to "speak immediately"
    fcntl = None  # type: ignore[assignment]

# src/vox/speech_lock.py → parents[2] is the repo root, matching settings_store's convention.
_LOCK_PATH = Path(__file__).resolve().parents[2] / "data" / "speaking.lock"

# Lock-file line: "<label> (pid 1234) since <unix seconds>". Human-readable on purpose — `cat
# data/speaking.lock` should still answer "who is talking?" — with the start time appended so a
# waiter can tell a long utterance from a wedged process.
_SINCE = " since "
_PID_RE = re.compile(r"\(pid (\d+)\)")

# How far past the maximum a hold must run before a WAITER stops waiting for it. A holder's own
# watchdog fires exactly at the maximum, and should win this race — it frees the lock properly,
# so the next speaker gets a real turn instead of talking over an unreleased one. This margin is
# the fallback, for holders whose watchdog never ran: code from before it existed, or a process so
# wedged that even its timer thread never got scheduled.
_STALE_GRACE = 1.0


def _setting(key: str, fallback):
    """Runtime override from the dashboard's settings_store, else the Config default. Fully guarded
    (mirrors tts._setting) so a missing store never stops anything from speaking."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def _read_state() -> tuple[str, int, float]:
    """``(text, pid, started)`` from the lock file — ``("", 0, 0.0)`` if it says nothing useful."""
    try:
        raw = _LOCK_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "", 0, 0.0
    if not raw:
        return "", 0, 0.0
    text, _, since = raw.partition(_SINCE)
    text = text.strip()
    try:
        started = float(since)
    except ValueError:
        # A holder from before this change wrote no timestamp; the file's mtime is the instant it
        # wrote its label, which is the same thing.
        try:
            started = _LOCK_PATH.stat().st_mtime
        except OSError:
            started = 0.0
    m = _PID_RE.search(text)
    return text, int(m.group(1)) if m else 0, started


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True  # e.g. EPERM: it exists, it just isn't ours


def _is_free() -> bool:
    """True if nobody holds the lock right now. Tests it for real by taking a shared lock on a
    fresh handle (flock conflicts per open file description, so this is honest even when called
    from the holding process). The lock is held for microseconds; a waiter that collides just polls
    again."""
    if fcntl is None:
        return False
    try:
        with open(_LOCK_PATH, "a+") as probe:
            try:
                fcntl.flock(probe.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                return False
            fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
            return True
    except Exception:
        return False


def holder() -> str:
    """Who is speaking right now (the label written by the current holder), or "" if nobody is.
    Best-effort and inherently racy — for logs and the dashboard, never for control flow.

    The file's text is only cleared on a *clean* release, so it outlives a holder that died or was
    killed; that stale name made O13 look like a free queue when it wasn't. So check the lock
    itself, and the pid, before believing the text."""
    text, pid, _ = _read_state()
    if not text:
        return ""
    if _is_free():
        return ""  # leftover text from a holder that died — the lock is genuinely free
    if pid and not _pid_alive(pid):
        return ""
    return text


@contextlib.contextmanager
def hold(label: str = "vox", timeout: float | None = None):
    """Hold the speech lock for the duration of the block, waiting for whoever is ahead.

    Yields True if the lock was actually acquired, False if we gave up waiting and are proceeding
    anyway (see the module docstring on why that beats blocking). Never raises: any failure to lock
    at all — a missing directory, a filesystem without flock, a non-POSIX platform — degrades to
    "speak immediately", which is exactly today's behaviour.
    """
    if not _setting("speech_queue_enabled", CONFIG.speech_queue_enabled):
        yield True
        return

    wait = float(timeout if timeout is not None else
                 _setting("speech_queue_timeout", CONFIG.speech_queue_timeout))
    max_hold = float(_setting("speech_queue_max_hold", CONFIG.speech_queue_max_hold))
    fh = None
    locked = False
    release = None
    timer = None
    try:
        if fcntl is None:
            raise RuntimeError("no flock on this platform")

        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = open(_LOCK_PATH, "a+")
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline or _held_too_long(max_hold):
                    break
                time.sleep(0.05)  # short poll: speech is a human-timescale queue
        if locked:
            # Record who's talking and since when, so `holder()` and the log can say what you're
            # waiting for, and so waiters can spot a hold that has clearly wedged.
            try:
                fh.seek(0)
                fh.truncate()
                fh.write(f"{label} (pid {os.getpid()}){_SINCE}{time.time():.3f}")
                fh.flush()
            except Exception:
                pass
            release = _releaser(fh)
            if max_hold > 0:
                # WATCHDOG — bound the hold, not just the wait. If this process never comes back
                # out of the block (the Kokoro streaming player has deadlocked exactly like this),
                # the `finally` below never runs and the lock is ours until we die, taxing every
                # other speaker the full wait on every utterance.
                #
                # TRADEOFF: releasing early can let the next speaker start while this one is still
                # producing audio. That's the right way round. The overlap is bounded — one
                # utterance, and only after a hold that has already run far longer than any real
                # phrase — while a stuck holder is unbounded and degrades everyone, which is the
                # same call the wait timeout already makes: one overlap beats a mute assistant.
                # Keep speech_queue_max_hold comfortably longer than the longest real utterance.
                timer = threading.Timer(max_hold, release)
                timer.daemon = True
                timer.start()
    except Exception:
        fh = None  # no lock available on this platform/filesystem → don't block speech

    try:
        yield locked
    finally:
        if timer is not None:
            timer.cancel()
        if release is not None:
            release()
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass


def _held_too_long(max_hold: float) -> bool:
    """Is the current holder past its maximum hold? Then it is wedged (or running code from before
    the watchdog), and a waiter should go ahead now rather than serve out the whole timeout."""
    if max_hold <= 0:
        return False
    _, _, started = _read_state()
    return bool(started) and (time.time() - started) > max_hold + _STALE_GRACE


def _releaser(fh):
    """A release-once function for this handle, shared by the watchdog and the `finally`.

    Once only, and under a mutex: if the watchdog has already released, another process may hold
    the lock and own the file's text by now, so a second release must not truncate its label out."""
    guard = threading.Lock()
    done = [False]

    def _release() -> None:
        with guard:
            if done[0]:
                return
            done[0] = True
            try:
                fh.seek(0)
                fh.truncate()
                fh.flush()
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass

    return _release
