"""The Vox daemon: a small state machine over wake phrases.

IDLE waits (via the configured wake backend) for an activation phrase. The control
label enters CONTROL mode (Dragon-style: transcribe + execute each command until a
sleep phrase). The assistant label enters ASSISTANT mode (one-shot LLM request).
See docs/plan/modes.md.
"""

import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

from vox import actions, assistant, dispatch, executor, sounds, tts
from vox.audio import MicStreamDead, NoInputDevice, capture_utterance, open_mic_stream
from vox.config import CONFIG
from vox.io.console import ConsoleOutput
from vox.stats import Timer, process_stats
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.backends import make_backend, normalize, phrase_match


def _record_turn(role: str, text: str, *, brain=None, kind=None) -> None:
    """Publish one conversation turn to the live dashboard feed (idea #43). Fully guarded:
    the web package is an additive convenience, so a missing/broken vox.web.conversation must
    NEVER break the voice daemon. Ephemeral by design — record_turn writes nothing to disk."""
    if not text or not str(text).strip():
        return
    try:
        from vox.web import conversation
        conversation.record_turn(role, text, brain=brain, kind=kind)
    except Exception:
        pass


def _setting(key: str, fallback):
    """Read a runtime override from the dashboard's settings_store, else fall back to Config.
    Fully guarded (mirrors assistant._setting): if vox.web.settings_store is missing or errors,
    return the fallback so the daemon behaves exactly as before. None from the store means
    'unset' → fallback. This is what lets dashboard toggles take effect on the NEXT relevant
    action without a restart."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


class _Quit(Exception):
    """Raised to exit the whole program by voice."""


class _Restart(Exception):
    """Raised to re-exec the program (pick up code changes) by voice."""


def relaunch() -> None:
    """Spawn a fresh Vox and hard-exit this one. Used by the voice "restart vox" and the dashboard's
    Restart button. Fresh process + hard exit instead of os.execv (which only ran AFTER the mic close,
    so the deadlock there meant restart never fired). start_new_session detaches it so it survives
    this process exiting; stdout still goes to the terminal."""
    subprocess.Popen([sys.executable, "-m", "vox"], start_new_session=True,
                     env={**os.environ, "VOX_RESTART": "1"})
    os._exit(0)


def _start_dashboard(cfg, out) -> None:
    """Launch the embedded dashboard web server in a background daemon thread. Fully guarded:
    a missing or broken vox.web package must NEVER stop the voice daemon (the dashboard is an
    additive convenience). Only runs when cfg.dashboard_enabled."""
    if not getattr(cfg, "dashboard_enabled", False):
        return
    try:
        from vox.web import server
        server.start_in_background(cfg)
        out.emit(f"  [dashboard] http://{cfg.dashboard_host}:{cfg.dashboard_port}  (say \"open dashboard\")")
    except Exception as exc:  # web package missing/broken → log and carry on
        if cfg.debug:
            out.emit(f"  [dashboard] not started: {exc}")


def _start_scheduler(cfg, out) -> None:
    """Start the background scheduler thread (timers / alarms / reminders, idea #16). Fully
    guarded, like _start_dashboard: a missing/broken vox.scheduler must NEVER stop the voice
    daemon. Only runs when cfg.scheduler_enabled."""
    if not getattr(cfg, "scheduler_enabled", True):
        return
    try:
        from vox import scheduler
        if scheduler.start() is not None:
            out.emit("  [scheduler] timers / alarms / reminders armed")
    except Exception as exc:  # scheduler module missing/broken → log and carry on
        if cfg.debug:
            out.emit(f"  [scheduler] not started: {exc}")


def _start_command_cache(cfg, out):
    """Boot-load the command DB (global + mode/system) into memory and install query logging.
    Returns command_cache.on_focus (the per-app loader the focus watcher hooks), or None. Fully
    guarded + additive: a missing/broken store must never stop the voice daemon."""
    try:
        from vox import command_cache
        command_cache.boot(out, cfg)
        return command_cache.on_focus
    except Exception as exc:  # command_cache/command_store missing or broken → carry on as today
        if getattr(cfg, "command_db_log", True) or cfg.debug:
            out.emit(f"  [cmddb] not started: {exc}")
        return None


def _start_focus_watch(cfg, out, on_change=None) -> None:
    """Start the background focus-watch thread (logs "window in view: <App>" on each app switch,
    and triggers the command DB's per-app load via ``on_change``). Guarded like _start_scheduler:
    a missing/broken vox.focus_watch must NEVER stop the voice daemon. Only runs when enabled."""
    if not getattr(cfg, "focus_watch_enabled", True):
        return
    try:
        from vox import focus_watch
        if focus_watch.start(out, on_change=on_change) is not None:
            out.emit("  [focus] watching the frontmost app")
    except Exception as exc:  # focus_watch module missing/broken → log and carry on
        if cfg.debug:
            out.emit(f"  [focus] not started: {exc}")


def _open_dashboard(cfg, out) -> None:
    """Open the dashboard in its own window (Arc opens external localhost links as a standalone
    'Little Arc' window), reusing an already-open dashboard window/tab so 'open dashboard' never
    stacks. Closing is non-disruptive — actions.close_dashboard presses the window's close button
    via accessibility (no Space-switch). Guarded so a failure can't break the wake loop."""
    url = f"http://{cfg.dashboard_host}:{cfg.dashboard_port}"
    try:
        if actions._focus_dashboard(url):  # reuse the existing dashboard window/tab
            out.emit("🖥  Dashboard already open — focused it.")
            return
        subprocess.run(["open", url], capture_output=True, text=True)  # own window (Arc → Little Arc)
        out.emit(f"🖥  Opening dashboard → {url}")
    except Exception:
        try:  # last-resort fallback to the system default browser
            webbrowser.open(url)
            out.emit(f"🖥  Opening dashboard → {url}")
        except Exception as exc:
            out.emit(f"  [dashboard] couldn't open browser: {exc}")


def _open_mic_or_wait(cfg, out):
    """``open_mic_stream``, but if NO microphone can be opened, keep the daemon alive and wait for one
    instead of dying at startup (a Mac mini with its AirPods off has no input at all). Opens the
    dashboard's Settings page at the Voice group — its Microphone dropdown is read live from the Mac —
    so the user can connect or pick one, then retries every few seconds. The dashboard, scheduler and
    MCP keep working meanwhile; Vox just can't hear yet."""
    import sounddevice as sd
    waiting = False
    while True:
        try:
            stream = open_mic_stream(cfg, out)
        except NoInputDevice as exc:
            if not waiting:
                waiting = True
                out.emit(f"⚠️  {exc}\n"
                         f"   {cfg.assistant_name} is up (dashboard, scheduler, MCP) but can't hear. "
                         f"Connect a microphone or pick one in Settings → Voice → Microphone — "
                         f"listening starts the moment one appears.")
                url = f"http://{cfg.dashboard_host}:{cfg.dashboard_port}/settings#voice"
                try:
                    subprocess.run(["open", url], capture_output=True, text=True)
                except Exception:
                    webbrowser.open(url)
            time.sleep(5)
            try:
                sd._terminate(); sd._initialize()  # re-enumerate — PortAudio's device list is frozen at init
            except Exception:
                pass
            continue
        if waiting:
            out.emit("🎙️  Microphone found — listening.")
        return stream


def _is_quit(text: str, cfg) -> bool:
    return phrase_match(normalize(text), cfg.quit_phrases)


def _is_restart(text: str, cfg) -> bool:
    return phrase_match(normalize(text), cfg.restart_phrases)


def _is_open_dashboard(text: str, cfg) -> bool:
    return phrase_match(normalize(text), cfg.open_dashboard_phrases)


def _is_close_dashboard(text: str, cfg) -> bool:
    return phrase_match(normalize(text), getattr(cfg, "close_dashboard_phrases", ()))


def _is_sleep(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.sleep_phrases)


def _is_abort(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.abort_phrases)


_AGENT_STOP = ("stop", "cancel", "stop it", "cancel that", "never mind", "nevermind", "abort")


def _is_agent_stop(text: str) -> bool:
    """True when an agent run is in flight and the user just told it to stop.

    Deliberately only consulted while a run is live — "stop" means other things the rest of the
    time (sleep, abort), and we don't want to change any of those. Guarded so a missing/broken
    agent module can never affect the command path."""
    try:
        from vox import agent
        if not agent.is_running():
            return False
        t = normalize(text)
        return any(t == p or t.startswith(p + " ") for p in _AGENT_STOP)
    except Exception:
        return False


def _is_assistant(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.assistant_phrases)


def _is_control(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.control_phrases)


def _is_dictate(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.dictate_phrases)


_NOISE_WORDS = {"and", "uh", "um", "ah", "oh", "so", "the", "a", "i", "yeah", "yep", "no",
                "okay", "ok", "hmm", "mm", "mhm", "like", "you", "well", "but", "or", "is", "it"}


_recent_single_words: dict[str, float] = {}  # one-word utterance → when we last heard it (monotonic)
_SINGLE_WORD_REPEAT_SECONDS = 90.0


def _is_known_command_phrase(word: str, cfg) -> bool:
    """Is this single word a command Vox already knows, on its own?

    The vocabulary is the command DB's active phrases for the focused app (which is where anything
    TAUGHT ends up) plus the code-parser phrases already enumerated for the Vosk grammar — i.e. the
    same "known phrase set" the fast lane recognizes against, no new source of truth.

    Compared space-stripped as well as verbatim, exactly like wakeword.phrase_match: Whisper runs
    short phrases together, and "show tabs" arriving as "showtabs" is a real, repeated entry in
    vox.log. Membership must be the WHOLE phrase — matching individual words inside multi-word
    phrases pulls in "to" (go to sleep), "good" (good bye) and "alright" (alright bye), which are
    exactly the stray words the gate exists to stop. Guarded: no cache → no vocabulary → the word
    falls through to the repeat test, i.e. today's behaviour."""
    phrases: list[str] = []
    try:
        from vox import command_cache
        phrases += command_cache.active_phrases(command_cache.current_app())
    except Exception:
        pass
    try:
        phrases += _fast_lane_extra_phrases(cfg)
    except Exception:
        pass
    return any(word == normalize(p).replace(" ", "") for p in phrases)


def _looks_like_noise(text: str, cfg=None) -> bool:
    """Short fragments / fillers — almost always background (a video, chatter). Don't escalate
    these to the LLM.

    A bare "len(words) <= 1" used to be the whole rule, which is why genuine one-word commands
    ("settings", "refresh", "show tabs" heard as "showtabs") were dropped before the brain ever saw
    them (issues.md O20) — and, worse, why a one-word command could never be LEARNED: the learning
    path only ever sees commands the brain resolved, and these never reached it. The gate still
    exists for a real reason (O7: the mic hears the room, and Whisper turns ambient audio into
    exactly these stray single words — 'courtesy', 'karassik', 'chaploo', 'unfettered'), so one word
    is still chatter BY DEFAULT. It escapes the gate only on evidence that it was addressed to Vox:

      • it is itself a command Vox already knows (the DB — including anything taught — or the Vosk
        fast-lane grammar), or
      • you just said the same single word a moment ago. Ambient speech doesn't repeat one isolated
        word inside a minute and a half; a person whose command didn't land does.

    Replayed over the 64 one-word utterances vox.log actually gated: this lets through 'enter',
    'refresh' and 'showtabs' and keeps holding back every ambient one ('courtesy', 'karassik',
    'chaploo', 'tenant', 'johnny', 'unfettered', …) — no false positives."""
    words = normalize(text).split()
    if not words:
        return True
    if all(w in _NOISE_WORDS for w in words):
        return True   # pure filler at any length — unchanged
    if len(words) > 1:
        return False
    word = words[0]
    now = time.monotonic()
    said_before = now - _recent_single_words.get(word, -1e9) <= _SINGLE_WORD_REPEAT_SECONDS
    _recent_single_words[word] = now
    if len(_recent_single_words) > 64:  # bounded: drop anything past the repeat window
        for w, seen in list(_recent_single_words.items()):
            if now - seen > _SINGLE_WORD_REPEAT_SECONDS:
                _recent_single_words.pop(w, None)
    if said_before:
        return False
    return not _is_known_command_phrase(word, cfg)


def _wants_escalation(text: str, cfg) -> bool:
    """Whether an utterance the deterministic parser couldn't handle should reach the brain.
    In "auto" mode (default) everything does. In "keywords" mode it must contain an escalation
    keyword — you opt the brain in by phrasing ("Vox, write me…"), so ambient audio stops tripping
    the LLM (issues.md O7). A pending clarification bypasses this (handled by the caller)."""
    if _setting("escalation_mode", cfg.escalation_mode) != "keywords":
        return True
    t = normalize(text)
    return any(k in t for k in cfg.escalation_keywords)


_MISSED_GRAMMAR: list = []  # phrase set from the last Vosk miss, consumed by the drift hint


def _transcribe(transcriber, audio, cfg, out, hotwords: str = "") -> str:
    dur = len(audio) / cfg.sample_rate
    with Timer() as stt:
        text = transcriber.transcribe(audio, hotwords=hotwords)
    cpu, mem = process_stats()
    # Mic LEVEL, so an empty transcription is diagnosable. `heard: ''` has two completely different
    # causes that look identical in the log: the mic delivered near-silence (wrong input device,
    # muted, AirPods across the room), or it delivered real speech and STT failed. Without a level
    # you cannot tell them apart — which is how a session spent 34% of its utterances empty while
    # the log looked healthy. int16 RMS: under ~40 is effectively silence, speech is hundreds+.
    try:
        from vox.audio import rms as _rms
        level = _rms(audio)
        quiet = "  ⚠ NEAR-SILENT (check the input device)" if level < 40 else ""
    except Exception:
        level, quiet = -1.0, ""
    out.emit(f"  ⏱  audio {dur:.1f}s · stt {stt.seconds:.2f}s "
             f"(rtf {stt.seconds / max(dur, 0.01):.2f}) · level {level:.0f} · "
             f"cpu {cpu:.0f}% · mem {mem:.0f}MB{quiet}")
    if cfg.debug:
        out.emit(f"  [debug] heard: {text!r}")
    # DRIFT HINT. A short fixed phrase that the parser handles but Vosk didn't know is exactly the
    # shape that bit as "scroll down" → "stand down": Vosk is grammar-constrained, so a command it
    # has never been told about gets force-aligned onto the nearest phrase it HAS. Surfacing it the
    # first time it happens is far cheaper than finding it in 54k log lines afterwards.
    try:
        if text and len(text.split()) <= 3 and _MISSED_GRAMMAR:
            from vox import actions
            known = _MISSED_GRAMMAR.pop()
            if text.lower() not in known and actions.parse(text) is not None:
                out.emit(f"  ⓘ fast-lane drift: {text!r} parses as a command but is NOT on the "
                         f"Vosk grammar — add it to _fast_lane_extra_phrases()")
    except Exception:
        pass
    return text


# Control phrases that must work INSIDE dictation. Dictation can't use the command grammar (you're
# typing arbitrary prose, so a constrained grammar would mangle it), which is why it went straight to
# Whisper — and that made the one phrase you need most, "stop typing", the slowest thing in the app:
# a full Whisper pass on top of dictation's longer silence wait. Recognising JUST these against a
# tiny grammar first is cheap (~5ms), and anything that isn't one of them still falls through to
# Whisper untouched, so dictated text is unaffected.
_DICTATION_CONTROL_PHRASES = (
    "stop typing", "stop dictation", "stop dictating", "enter", "new line", "new paragraph",
)


def _dictation_control(audio, cfg) -> str | None:
    """Vosk-match an utterance against the dictation control phrases only. Returns the phrase on a
    confident match, else None so the caller runs Whisper as before. Fully guarded."""
    if not _setting("vosk_commands_enabled", getattr(cfg, "vosk_commands_enabled", False)):
        return None
    try:
        from vox import command_cache
        from vox.stt import vosk_recognizer
        log = command_cache.log if getattr(cfg, "vosk_log", True) else None
        r = vosk_recognizer.recognize(audio, list(_DICTATION_CONTROL_PHRASES), cfg.sample_rate,
                                      model_path=getattr(cfg, "vosk_model_path", ""), log=None)
        min_conf = float(_setting("vosk_min_conf", getattr(cfg, "vosk_min_conf", 0.0)))
        if r and r["conf"] >= min_conf:
            if log:
                log(f"  [vosk] ⚡ dictation control {r['text']!r} conf {r['conf']} → FAST LANE")
            return r["text"]
    except Exception:
        pass
    return None


def check_fast_lane_drift(cfg, out=None) -> list[str]:
    """Report fast-lane phrases the command parser can't actually handle.

    The Vosk grammar and the command parser are two lists that must agree, and when they drift you
    get bugs that appear and vanish depending on which lane wins — which is what made them so hard
    to see (issues.md O21/O22). This catches the direction that IS checkable: a phrase Vosk will
    happily snap to that then falls through to the brain. The opposite direction — a parser command
    missing from the grammar, which is what "scroll down" → "stand down" was — can't be derived,
    because the parser is regexes with no phrase inventory to enumerate. That one is caught at
    runtime by the hint in _recognize()."""
    from vox import actions
    # Only phrases that are SUPPOSED to reach actions.parse can be checked against it. Mode
    # switches, wake phrases, dashboard and overlay triggers are handled by dispatch and the mode
    # machinery instead, and parse() returns None for all of them by design — checking those
    # produced 51 false positives on the first attempt, which is worse than no check at all.
    handled_elsewhere = {p.lower() for p in _DICTATION_CONTROL_PHRASES}
    for attr in ("sleep_phrases", "dictate_phrases", "control_phrases", "assistant_phrases",
                 "open_dashboard_phrases", "close_dashboard_phrases", "wake_phrases"):
        handled_elsewhere |= {p.lower() for p in (getattr(cfg, attr, ()) or ())}
    try:
        handled_elsewhere |= {p.lower() for p in dispatch._SHOW_CLICKABLE_PHRASES}
        handled_elsewhere |= {p.lower() for p in dispatch._HIDE_CLICKABLE_PHRASES}
    except Exception:
        pass
    orphans = []
    for phrase in _fast_lane_extra_phrases(cfg):
        if phrase.lower() in handled_elsewhere:
            continue
        try:
            if actions.parse(phrase) is None:
                orphans.append(phrase)
        except Exception:
            continue
    if orphans and out is not None:
        out.emit(f"  ⚠ fast-lane drift: {len(orphans)} grammar phrase(s) the parser won't handle: "
                 f"{', '.join(sorted(orphans)[:8])}")
    return orphans


def _is_spent_dictation_control(text: str) -> bool:
    """True for a dictation-control phrase heard OUTSIDE dictation, where it is a no-op.

    This function is only ever reached from control/assistant/idle — dictation runs its own loop —
    so a dictation control phrase arriving here is by definition already spent."""
    t = normalize(text or "")
    return bool(t) and t in {p.lower() for p in _DICTATION_CONTROL_PHRASES}


def _fast_lane_extra_phrases(cfg) -> list[str]:
    """Put common PARAMETERISED app commands on the Vosk fast lane by enumerating known apps — they
    live in the code parser (not the command DB), so ``active_phrases`` doesn't include them. Vosk
    recognizes e.g. "switch cursor" / "open slack" and dispatch's parser handles them exactly as if
    Whisper had transcribed it. The app list comes from ``command_hotwords`` (the curated app names).
    Truly-open commands ("search X", dictation) can't be enumerated and stay on Whisper."""
    apps = [w for w in (getattr(cfg, "command_hotwords", "") or "").split() if w and w != "switch"]
    out: list[str] = []
    for a in apps:
        out.append(f"switch {a}")   # app-cycle (the "switch cursor" case)
        out.append(f"open {a}")     # launch/focus the app
    # The numbered-overlay triggers live in dispatch (not the command DB), so add them here — this
    # puts "show clickable" on the fast lane and lets it snap mis-hears ("hard clickable" → the real
    # phrase) instead of escalating to the LLM. The HIDE phrases need it just as much: only the show
    # half was listed here, so "hide clickable" fell through to Whisper, which clips the short word
    # to "hi"/"high" — and those reached the LLM. Seen repeatedly in vox.log.
    try:
        out += list(dispatch._SHOW_CLICKABLE_PHRASES) + list(dispatch._HIDE_CLICKABLE_PHRASES)
    except Exception:
        pass
    # Reload lives in the code parser, so active_phrases() (which reads the DB) doesn't include it.
    # Only the canonical wording — a phrase TAUGHT for it lands in the command DB and reaches the
    # grammar through active_phrases() on its own.
    out += ["reload", "reload the page"]
    # MODE-SWITCH phrases. These live in the code parser too, so nothing was putting them on the
    # grammar — and they are among the most-spoken things in the whole app. Measured over vox.log
    # (scripts/perf_report.py): "go to sleep" 50x, "stop typing" 61x, "enter" 71x, "start typing"
    # 24x — every one paying a full Whisper pass to recognise two short words. They're a closed set,
    # so there's no reason for them to be on the slow lane at all.
    for attr in ("sleep_phrases", "dictate_phrases", "control_phrases", "assistant_phrases",
                 "open_dashboard_phrases", "close_dashboard_phrases"):
        out += [p for p in (getattr(cfg, attr, ()) or ())]
    out += list(_DICTATION_CONTROL_PHRASES)
    # SCROLL / PAGE (ideas #61). Same reason as everything above — they live in the code parser, so
    # active_phrases() never sees them. Leaving them off the grammar is not neutral: Vosk is
    # grammar-CONSTRAINED, so an utterance it doesn't know is force-aligned onto the nearest phrase
    # it does. On 2026-09-08 "scroll down" snapped to "stand down" (a sleep phrase) at conf 1.0 and
    # silently ended control mode mid-session — see issues.md O21. Confidence can't catch that: it's
    # the mean per-word score of an alignment the grammar itself forced, so it reads 1.0 precisely
    # BECAUSE the real words weren't available. The only fix is giving Vosk the right phrase to win.
    # Counts ("scroll down three") stay on Whisper — the extra word makes the utterance unknown to
    # this grammar, which is the correct outcome rather than snapping and losing the number.
    out += ["scroll", "scroll up", "scroll down", "scroll left", "scroll right",
            "scroll to the top", "scroll to the bottom", "page up", "page down"]
    return out


def _recognize(audio, cfg, transcriber, out, hotwords: str = "") -> str:
    """Two-lane recognition (idea #53). If the Vosk fast lane is on, run the utterance through Vosk
    constrained to the CURRENT command phrases (from the command DB): a confident grammar match
    returns instantly (no Whisper, no LLM) and snaps mis-hears to the nearest command
    ("necks tab" → "next tab"). Anything Vosk can't match falls through to Whisper. Fully guarded —
    any Vosk problem uses the Whisper lane. All `[vosk]` lines go to vox.log for visibility."""
    if _setting("vosk_commands_enabled", getattr(cfg, "vosk_commands_enabled", False)):
        try:
            from vox import command_cache
            from vox.stt import vosk_recognizer
            log = command_cache.log if getattr(cfg, "vosk_log", True) else None
            app = command_cache.current_app()
            phrases = command_cache.active_phrases(app) + _fast_lane_extra_phrases(cfg)
            if log:
                log(f"  [vosk] grammar: {len(phrases)} phrases [app={app or '-'}] — recognizing…")
            r = vosk_recognizer.recognize(audio, phrases, cfg.sample_rate,
                                          model_path=getattr(cfg, "vosk_model_path", ""), log=log)
            min_conf = float(_setting("vosk_min_conf", getattr(cfg, "vosk_min_conf", 0.0)))
            if r and r["conf"] >= min_conf:
                if log:
                    snap = f" (heard {r['raw']!r})" if r["raw"].lower() != r["text"].lower() else ""
                    log(f"  [vosk] ⚡ {r['text']!r} conf {r['conf']}{snap} → FAST LANE (skipped Whisper)")
                    # A snap onto a mode-EXIT phrase ends the session, so it deserves its own line:
                    # correlating "⚡ 'stand down'" with "○ Sleeping." two lines later, and knowing
                    # 'stand down' is a sleep phrase, is what made O21 take an hour to see. Grep
                    # `[vosk] ⚠ MODE EXIT` to find every unverified exit.
                    if r["text"].lower() in {p.lower() for p in (getattr(cfg, "sleep_phrases", ()) or ())}:
                        log(f"  [vosk] ⚠ MODE EXIT on an UNVERIFIED grammar snap: {r['text']!r} "
                            f"(Whisper was skipped — if you didn't say this, it was force-aligned)")
                if cfg.debug:
                    out.emit(f"  [debug] heard (vosk): {r['text']!r}")
                return r["text"]
            if log:
                log(f"  [vosk] {'low conf ' + str(r['conf']) if r else 'no match [unk]'} → Whisper lane")
                _MISSED_GRAMMAR.append({p.lower() for p in phrases})  # for the drift hint below
        except Exception as exc:  # any Vosk problem → Whisper, never break the loop
            try:
                from vox import command_cache
                if getattr(cfg, "vosk_log", True):
                    command_cache.log(f"  [vosk] unavailable ({exc}) → Whisper lane")
            except Exception:
                pass
    return _transcribe(transcriber, audio, cfg, out, hotwords=hotwords)


def _passes_interrupt_gate(audio, text, cfg) -> bool:
    """A mid-call barge-in must be REAL speech, not a blip (loop 1, O7/O8). Require the captured
    audio to be sustained ≥ interrupt_min_seconds AND carry ≥ interrupt_min_words transcribed
    words — mirrors livekit min_interruption_duration/min_interruption_words + pipecat's
    MinWords strategy. Ambient TV/chatter that leaks one short word no longer cancels the call.
    Read via the guarded _setting path so defaults are pure wins and dashboard toggles apply live."""
    min_secs = _setting("interrupt_min_seconds", cfg.interrupt_min_seconds)
    if min_secs and len(audio) / cfg.sample_rate < min_secs:
        return False
    min_words = _setting("interrupt_min_words", cfg.interrupt_min_words)
    if min_words and len(normalize(text).split()) < min_words:
        return False
    return True


_CALL_STOP = ("stop", "stop it", "cancel", "cancel it", "wait", "hold on", "hang on",
              "no stop", "stop stop")


def _is_call_stop(text: str) -> bool:
    """A bare "stop" while a call is in flight. Deliberately its OWN set, separate from
    sleep_phrases / abort_phrases: "stop" on its own matched none of those, so during a ~20s
    escalation the one word the user reaches for did literally nothing (issues.md O19). It only
    means cancel while we're waiting on a call, exactly like _is_agent_stop only means cancel while
    an agent run is live — so nothing outside this window changes. Whole-utterance match only, so
    "stop typing" / "don't stop the timer" still route where they always did."""
    t = normalize(text)
    return t in _CALL_STOP


def _run_interruptible(work, frames, cfg, transcriber, out=None, slow=True):
    """Run work() (a blocking LLM call) on a thread while still listening, so the user can cancel
    it by speaking a stop/sleep/quit/restart phrase (barge-in, idea #19). No echo worries — Vox
    isn't speaking during the call. Returns (result, interrupt): interrupt is None if work
    finished, else 'cancel' | 'sleep' | 'quit' | 'restart'. An abandoned call finishes in the
    background and its result is dropped (Python can't kill a thread).

    `slow` marks calls expected to outrun the poll loop (big-brain / vision / compose). When
    interrupt_slow_calls_only is on (default), barge-in is NOT armed for fast calls — those finish
    before the poll fires anyway, so arming there only wastes a capture window and risks a spurious
    cancel (loop 1, part of O8)."""
    arm = _setting("barge_in_enabled", cfg.barge_in_enabled)
    if arm and _setting("interrupt_slow_calls_only", cfg.interrupt_slow_calls_only) and not slow:
        arm = False
    if not arm:
        return work(), None
    box: dict = {}

    def runner():
        try:
            box["result"] = work()
        except Exception as exc:  # callees normally catch their own; don't lose it
            box["error"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    while t.is_alive():
        audio = capture_utterance(frames, cfg, listen_timeout=cfg.barge_in_poll_seconds)
        if audio is None:
            continue  # silence — loop and re-check whether work() finished
        # Recognize the mid-call utterance via the fast lane first (Vosk ~5ms) so a re-said command
        # cuts the LLM off INSTANTLY — you never wait on the LLM to give a command. `out` enables the
        # fast lane + logging; without it, plain Whisper.
        text = (_recognize(audio, cfg, transcriber, out, hotwords=cfg.command_hotwords)
                if out is not None else transcriber.transcribe(audio, hotwords=cfg.command_hotwords))
        if not text:
            continue
        # "stop" is checked BEFORE the blip gate. A bare "stop" is ~0.4s of audio and one word, so
        # it sits right on interrupt_min_seconds/interrupt_min_words and was being thrown away as a
        # blip — the exact word the user needs during a 20s escalation. Cancelling is also the
        # safest thing a false positive can do (nothing runs; you just say it again), unlike the
        # redirect below, which is why only this one branch skips the gate.
        if _is_call_stop(text):
            if out is not None:
                out.emit(f"  ⛔ heard {text!r} — cancelling the request.")
            return None, "cancel"
        if not _passes_interrupt_gate(audio, text, cfg):
            continue  # too short / too few words → a blip, not a barge-in; keep waiting for work()
        if _is_abort(text, cfg) or _is_sleep(text, cfg):
            return None, "sleep"
        if _is_quit(text, cfg):
            return None, "quit"
        if _is_restart(text, cfg):
            return None, "restart"
        # a clear new command / mode-switch mid-call → cut the LLM off and do THAT instead
        if actions.parse(text) is not None or _is_assistant(text, cfg) or _is_dictate(text, cfg):
            return None, ("redirect", text)
        # anything else (chatter / fuzzy / background) → ignore and keep waiting for work()
    if "error" in box:
        raise box["error"]
    return box.get("result"), None


def _speak_interruptible(spoken, frames, cfg, transcriber, mic):
    """Speak `spoken` while still listening, so the user can talk over the reply (loop 3 / R5).

    Returns (interrupt, text):
      • (None, None)            — the reply finished uninterrupted (the normal case).
      • ("sleep", None)         — a stop/sleep/abort phrase cut the reply → caller goes idle.
      • ("quit"|"restart", None)— those phrases cut the reply → caller raises.
      • ("redirect", text)      — a real new utterance cut the reply → caller handles `text` next.

    tts.speak() runs on a worker thread (it BLOCKS until the phrase finishes). Meanwhile we capture
    utterances and apply the loop-1 _passes_interrupt_gate, so ambient blips don't cut the voice.
    On a gated barge-in we call tts.stop_speaking() to halt Kokoro's streaming player immediately
    and drop the unplayed audio, then return the decision.

    IMPORTANT — HEADPHONES ONLY: Vox has no echo cancellation yet (loop 5 / AEC). On SPEAKERS the
    mic hears the TTS and will interrupt Vox with its own voice. This whole path is gated OFF by
    default (cfg.tts_interruptible) and is only armed for tts_engine=="kokoro" (the only engine
    stop_speaking() can actually halt) — so the default speak path stays byte-for-byte unchanged."""
    done = threading.Event()

    def speaker():
        try:
            tts.speak(spoken)
        finally:
            done.set()

    t = threading.Thread(target=speaker, daemon=True)
    t.start()
    try:
        while not done.is_set():
            audio = capture_utterance(frames, cfg, listen_timeout=cfg.barge_in_poll_seconds)
            if audio is None:
                continue  # silence — keep speaking
            text = transcriber.transcribe(audio, hotwords=cfg.command_hotwords)
            if not text or not _passes_interrupt_gate(audio, text, cfg):
                continue  # blip / too short → not a real barge-in; let the reply continue
            tts.stop_speaking()  # gated, real speech over the reply → cut the voice now
            if _is_abort(text, cfg) or _is_sleep(text, cfg):
                return "sleep", None
            if _is_quit(text, cfg):
                return "quit", None
            if _is_restart(text, cfg):
                return "restart", None
            return "redirect", text  # anything else → handle it as the next turn
        return None, None
    finally:
        done.wait()  # the speak thread BLOCKS to completion; if we cut it, stop_speaking already fired


def _control_mode(frames, cfg, transcriber, out, mic) -> None:
    out.emit(f'● CONTROL MODE — e.g. "open Safari" or "go to GitHub". Say "{cfg.sleep_spoken}" to stop.')
    pending = []  # short clarification memory: when the brain asks a question, the next answer gets context
    redirect = None  # a clear command captured mid-LLM-call, to run instead of the cancelled one
    while True:
        if redirect is not None:
            text, redirect = redirect, None
        else:
            audio = capture_utterance(frames, cfg)
            if audio is None:
                continue  # stay in control mode — only the sleep phrase (or Ctrl+C) exits
            text = _recognize(audio, cfg, transcriber, out, hotwords=cfg.command_hotwords)
            if not text:
                continue
        # An agent run (idea #57) works the screen for up to a minute on its own thread. While one
        # is in flight a plain "stop" should cancel IT and leave us in control mode — not drop Vox
        # to idle, which is what the same word means the rest of the time.
        if _is_agent_stop(text):
            from vox import agent
            agent.abort()
            sounds.play(cfg.sound_abort)
            out.emit("🛑 Stopping the agent.")
            pending = []
            continue
        if _is_abort(text, cfg):  # emergency stop → straight to idle, whatever mode we're in
            sounds.play(cfg.sound_abort)
            out.emit("🛑 Stopped.")
            return None
        if _is_quit(text, cfg):
            raise _Quit
        if _is_restart(text, cfg):
            raise _Restart
        if _is_sleep(text, cfg):
            sounds.play(cfg.sound_sleep)
            out.emit("○ Sleeping.")
            return None
        if _is_assistant(text, cfg):
            out.emit("→ switching to assistant…")
            return "assistant"
        if _is_dictate(text, cfg):
            out.emit("→ entering dictation…")
            return "dictation"
        # Dashboard open/close also work from CONTROL mode (not just idle) — caught before the
        # generic "open <app>" parser, which would otherwise try to open an app called "dashboard".
        if _is_open_dashboard(text, cfg):
            sounds.play(cfg.sound_dashboard_open)
            _open_dashboard(cfg, out)
            pending = []
            continue
        if _is_close_dashboard(text, cfg):
            sounds.play(cfg.sound_dashboard_close)
            out.emit(f"🖥  {actions.close_dashboard()}")
            pending = []
            continue
        out.emit(f"  you: {text!r}")
        _record_turn("user", text)
        # Shared deterministic layer (vox.dispatch) — ONE place for all three modes: "what app is
        # this", the scheduler (timers/alarms/reminders), then the command parser. acted → a silent
        # "did it" cue; else → a spoken answer/confirmation. None → escalate to the brain below.
        det = dispatch.try_deterministic(text)
        if det is not None:
            acted, msg = det
            # A refused click is the one "acted" result that MUST be spoken. Staying silent is
            # indistinguishable from Vox ignoring you — the exact complaint that surfaced O18.
            if acted and not str(msg).startswith(actions.FOCUS_MOVED):
                out.emit(f"  → {msg}")
            else:
                out.emit(f"  🔊 {msg}")
                tts.speak(msg)
                mic.flush()  # drop our own confirmation TTS the mic caught
            _record_turn("assistant", str(msg), kind="command")
            pending = []  # handled deterministically → drop any pending clarification
        elif not pending and _is_spent_dictation_control(text):
            # "stop typing" means something in dictation and nothing outside it. Saying it once
            # exits dictation; the repeat (or the tail of the same phrase re-captured after the
            # exit chime) lands in CONTROL mode, where the parser has no such command — so it went
            # to the brain and cost a ~20s round-trip to be told nothing. It's already satisfied.
            out.emit("  (already stopped typing)")
        elif not pending and _looks_like_noise(text, cfg):  # filler / unknown 1-word → background
            out.emit("  (ignored — too short / background)")
            pending = []
        elif not pending and not _wants_escalation(text, cfg):  # keyword mode: no trigger → don't escalate
            out.emit("  (ignored — no escalation keyword)")
            pending = []
        else:  # unparsed, or the deterministic attempt found no target → let the brain try
            sounds.play(cfg.sound_thinking)  # "thinking…" cue — the LLM can take a moment
            # ARM barge-in on control escalations: the small brain can be a SLOW cloud model
            # (DeepSeek etc.), and a mis-heard command shouldn't lock you out while it loads. So keep
            # listening — a re-said command (recognized instantly by the Vosk fast lane) cuts the LLM
            # off and runs instead. `slow=True` arms it regardless of interrupt_slow_calls_only.
            result, interrupt = _run_interruptible(
                lambda: executor.execute(text, pending), frames, cfg, transcriber, out=out, slow=True)
            if interrupt == "quit":
                raise _Quit
            if interrupt == "restart":
                raise _Restart
            if interrupt == "cancel":  # a bare "stop" mid-call → drop the request, STAY in control
                sounds.play(cfg.sound_abort)
                out.emit("  🛑 Cancelled — still listening.")
                pending = []
                continue
            if interrupt == "sleep":  # "stand down"/"sleep" said mid-call → cancel and go idle
                sounds.play(cfg.sound_sleep)
                out.emit("○ Stopped (cancelled the request).")
                return None
            if isinstance(interrupt, tuple) and interrupt[0] == "redirect":  # new command mid-call
                out.emit(f"  ⤳ cancelled — doing {interrupt[1]!r} instead")
                redirect, pending = interrupt[1], []
                continue
            acted, msg = result
            if msg == executor.ENTER_DICTATION:  # brain heard "start typing" → switch to dictation
                out.emit("→ entering dictation…")
                return "dictation"
            if acted:
                sounds.play(cfg.sound_oneshot)  # quiet "did it" cue — action-first (#13)
                out.emit(f"  ⚡ {msg}")
                _record_turn("assistant", msg, brain="small", kind="command")
                pending = []
            elif msg:
                shown, spoken = assistant.split_say(msg)
                out.emit(f"  🔊 {shown}")
                _record_turn("assistant", shown, brain="small", kind="reply")
                tts.speak(spoken)
                mic.flush()  # drop our own voice the mic caught while speaking (no self-feedback)
                # brain asked something → remember this exchange so the next answer has context
                pending = (pending + [("user", text), ("assistant", shown)])[-4:] \
                    if shown.rstrip().endswith("?") else []
            else:  # the brain judged it chatter / not meant for Vox → stay silent
                out.emit("  (ignored — sounded like chatter)")
                pending = []


def _assistant_mode(frames, cfg, transcriber, out, mic, return_to=None):
    out.emit('● ASSISTANT MODE — chat with me. Say "stand down" when done.')
    history = []
    expecting_answer = False  # set when the model tags its reply [OPEN] → wait patiently for you
    redirect = None  # an utterance captured mid-reply, to handle instead of the cancelled one
    while True:
        if redirect is not None:
            text, redirect = redirect, None
        else:
            timeout = cfg.assistant_open_timeout_seconds if expecting_answer else cfg.assistant_idle_timeout_seconds
            audio = capture_utterance(frames, cfg,
                                      silence_seconds=cfg.assistant_silence_seconds,
                                      listen_timeout=timeout)
            if audio is None:
                out.emit("  (no reply — back to idle)")
                return return_to
            text = _transcribe(transcriber, audio, cfg, out)
            if not text:
                continue
        if _is_abort(text, cfg):  # emergency stop → straight to idle, whatever mode we're in
            sounds.play(cfg.sound_abort)
            out.emit("🛑 Stopped.")
            return None
        if _is_quit(text, cfg):
            raise _Quit
        if _is_restart(text, cfg):
            raise _Restart
        if _is_sleep(text, cfg):
            sounds.play(cfg.sound_sleep)
            out.emit("○ Sleeping.")
            return None
        if _is_control(text, cfg):
            out.emit("→ switching to control…")
            return "control"
        if _is_open_dashboard(text, cfg):  # a control command said mid-chat → do it, keep chatting
            sounds.play(cfg.sound_dashboard_open)
            _open_dashboard(cfg, out)
            mic.flush()
            continue
        if _is_close_dashboard(text, cfg):
            sounds.play(cfg.sound_dashboard_close)
            out.emit(f"🖥  {actions.close_dashboard()}")
            mic.flush()
            continue
        # Shared deterministic layer (vox.dispatch) — the SAME "one place" control & one-shot use:
        # "what app is this", the scheduler (timers/alarms/reminders), then a deterministic command.
        # Runs mid-chat so you can act without leaving the conversation.
        det = dispatch.try_deterministic(text)
        if det is not None:
            acted, msg = det
            sounds.play(cfg.sound_oneshot)
            if acted:
                out.emit(f"  ⚡ {msg}")
            else:
                out.emit(f"  🔊 {msg}")
                tts.speak(msg)
            _record_turn("user", text)
            _record_turn("assistant", str(msg), kind="command")
            mic.flush()
            expecting_answer = False
            continue
        # Action intents (write / "make this pretty" / "what's on my screen" / a fuzzy command) →
        # run the executor, so assistant mode has the SAME do-powers as control. Chat-first:
        # only clear action requests reach the executor; everything else falls through to chat.
        if dispatch.looks_like_action(text, cfg):
            sounds.play(cfg.sound_thinking)
            # Same barge-in arming as control's escalation and the chat call below. This one call
            # was the odd one out — a plain blocking executor.execute(), so a slow brain wedged the
            # listening loop for its whole duration and nothing, not even "stop", could reach it
            # (issues.md O19).
            result, interrupt = _run_interruptible(
                lambda: executor.execute(text), frames, cfg, transcriber, out=out, slow=True)
            if interrupt == "quit":
                raise _Quit
            if interrupt == "restart":
                raise _Restart
            if interrupt == "cancel":  # a bare "stop" mid-call → drop it, stay in the conversation
                sounds.play(cfg.sound_abort)
                out.emit("  🛑 Cancelled — still listening.")
                expecting_answer = False
                continue
            if interrupt == "sleep":
                sounds.play(cfg.sound_sleep)
                out.emit("○ Sleeping.")
                return None
            if isinstance(interrupt, tuple) and interrupt[0] == "redirect":  # new command mid-call
                out.emit(f"  ⤳ cancelled — doing {interrupt[1]!r} instead")
                redirect, expecting_answer = interrupt[1], False
                continue
            acted, msg = result
            if msg == executor.ENTER_DICTATION:  # brain heard "start typing" → switch to dictation
                out.emit("→ entering dictation…")
                return "dictation"
            if acted:
                _record_turn("user", text)
                sounds.play(cfg.sound_oneshot)
                out.emit(f"  ⚡ {msg}")
                _record_turn("assistant", str(msg), brain="small", kind="command")
                mic.flush()
                expecting_answer = False
                continue
            if msg:  # a spoken answer (vision / a short reply)
                _record_turn("user", text)
                shown, spoken = assistant.split_say(msg)
                out.emit(f"  🔊 {shown}")
                _record_turn("assistant", shown, brain="small", kind="reply")
                tts.speak(spoken)
                mic.flush()
                expecting_answer = shown.rstrip().endswith("?")
                continue
            # executor judged it chatter / not an action → fall through to conversational chat
        sounds.play(cfg.sound_send)  # captured → "sending to the AI"
        out.emit(f"  you: {text!r}")
        _record_turn("user", text)
        # Assistant chat is the slow path (full conversational reply, may escalate to the big
        # brain) — worth arming barge-in so a long answer can be cut off (loop 1).
        result, interrupt = _run_interruptible(
            lambda: assistant.respond_turn(text, history), frames, cfg, transcriber, out=out, slow=True)
        if interrupt == "quit":
            raise _Quit
        if interrupt == "restart":
            raise _Restart
        if interrupt == "cancel":  # a bare "stop" mid-reply → drop it, stay in the conversation
            sounds.play(cfg.sound_abort)
            out.emit("  🛑 Cancelled — still listening.")
            expecting_answer = False
            continue
        if interrupt == "sleep":  # "sleep"/"stand down" said while the AI was responding → go idle
            sounds.play(cfg.sound_sleep)
            out.emit("○ Sleeping.")
            return None
        if isinstance(interrupt, tuple) and interrupt[0] == "redirect":  # new utterance mid-reply
            out.emit(f"  ⤳ switching to {interrupt[1]!r}")
            redirect = interrupt[1]
            continue
        reply, expecting_answer = result  # model tags [OPEN]/[DONE]
        shown, spoken = assistant.split_say(reply)  # brain may pick a shorter spoken version
        history += [("user", text), ("assistant", shown)]
        _record_turn("assistant", shown, brain="small", kind="chat")
        out.emit(f"  🔊 {shown}" + ("  (…your turn)" if expecting_answer else ""))
        # Interruptible speaking (loop 3): only when tts_interruptible is ON *and* the engine is
        # kokoro (the streaming player stop_speaking() can actually halt). HEADPHONES-only — no AEC
        # yet, so on speakers the mic would hear the TTS. OFF by default → the original blocking
        # speak + mic.flush path below, byte-for-byte unchanged.
        if _setting("tts_interruptible", cfg.tts_interruptible) \
                and _setting("tts_engine", cfg.tts_engine) == "kokoro":
            interrupt, spoke_text = _speak_interruptible(spoken, frames, cfg, transcriber, mic)
            mic.flush()  # drop any residual audio captured during/after the reply
            if interrupt == "quit":
                raise _Quit
            if interrupt == "restart":
                raise _Restart
            if interrupt == "sleep":  # talked "stop"/"sleep" over the reply → cancel, go idle
                sounds.play(cfg.sound_sleep)
                out.emit("○ Sleeping.")
                return None
            if interrupt == "redirect":  # talked a new utterance over the reply → handle it next
                out.emit(f"  ⤳ you cut in — handling {spoke_text!r}")
                redirect = spoke_text
                continue
            if not expecting_answer:  # [DONE] → spoke through, exchange is over → back to idle
                out.emit("  ✓ done — back to idle (say \"Hey Vox\" to chat again)")
                return return_to
            continue
        tts.speak(spoken)
        mic.flush()  # drop our own TTS audio so we don't hear ourselves
        if not expecting_answer:  # [DONE] → the exchange reached a stopping point → back to idle
            out.emit("  ✓ done — back to idle (say \"Hey Vox\" to chat again)")
            return return_to


# How long to let the exit chime finish before flushing the mic. sounds.play is fire-and-forget
# (subprocess.Popen), so flushing on the next line drained the buffer BEFORE afplay had made a
# sound — the chime (Sosumi, 1.54s) still landed in the mic and still became the first "utterance"
# of the next mode. Waiting the cue out first is what actually drops it, and it's cheaper than the
# alternative: idle would otherwise spend ~2s capturing + transcribing the chime and then flush
# the words you said behind it.
_CHIME_SETTLE_SECONDS = 1.6


def _flush(mic, settle: float = 0.0) -> None:
    """Drop whatever the mic captured while we were making noise, after waiting `settle` seconds
    for the cue to finish playing.

    The dictation-exit chime was landing in the buffer and becoming the FIRST "utterance" of the
    next mode — which is why leaving dictation felt frozen: 28% of first hears after an exit came
    back empty against a 6% baseline, so you'd speak, get nothing, and say it again. Every other
    noise-making path in this file already flushes; these three didn't. Guarded because `mic` is
    optional here (older callers pass none) and a flush must never be the thing that breaks an exit."""
    if settle:
        time.sleep(settle)
    try:
        if mic is not None:
            mic.flush()
    except Exception:
        pass


def _dictation_idle_exit_seconds(cfg) -> float:
    """How long dictation tolerates continuous silence before it exits on its own. A live setting
    (dashboard-tunable) with the Config value as the floor; the default is deliberately far longer
    than one `listen_timeout_seconds` window — see _dictation_mode."""
    return float(_setting("dictation_idle_exit_seconds",
                          getattr(cfg, "dictation_idle_exit_seconds", 45.0)))


def _dictation_mode(frames, cfg, transcriber, out, mic=None, return_to=None):
    sounds.play(cfg.sound_dictate_start)
    out.emit('✎ DICTATION — click where you want text, then speak. Say "stop typing" to stop.')
    actions.reset_dictation()  # fresh spacing/capitalization state for this session
    # A think-pause is NOT the end of dictation. capture_utterance returns None after
    # listen_timeout_seconds (6s) with no speech onset, and that single empty window used to exit
    # on its own — which is exactly the "dictation randomly stops mid-sentence" report. Measured
    # over vox.log: 82 of 158 dictation exits (52%) were this timeout, every one of them firing
    # 4-6 wall-clock seconds after the last word. (4-6 rather than a flat 6 because the window is
    # counted in FRAMES, and the backlog that piled up during the previous Whisper pass is consumed
    # instantly — the worse the machine load, the shorter the real pause you're allowed. See O17.)
    # So: an empty window now only re-arms the mic, and we exit only once the silence has actually
    # lasted `dictation_idle_exit_seconds` of WALL-CLOCK time, which the backlog can't shorten.
    idle_exit = _dictation_idle_exit_seconds(cfg)
    last_speech = time.monotonic()
    while True:
        audio = capture_utterance(frames, cfg, silence_seconds=cfg.assistant_silence_seconds)
        if audio is None:  # a quiet window — a pause, not necessarily the end
            if not _setting("dictation_exit_on_silence", cfg.dictation_exit_on_silence):
                continue  # setting: stay in dictation until an explicit "stop typing"
            if time.monotonic() - last_speech < idle_exit:
                continue  # still inside the silence budget → keep listening
            sounds.play(cfg.sound_dictate_stop)
            _flush(mic, settle=_CHIME_SETTLE_SECONDS)
            out.emit(f"✎ Stopped typing (nothing said for {idle_exit:.0f}s).")
            return return_to
        last_speech = time.monotonic()
        # Check the control phrases BEFORE paying for Whisper — "stop typing" is the phrase you say
        # most in dictation and it was the slowest to land.
        ctrl = _dictation_control(audio, cfg)
        if ctrl in ("stop typing", "stop dictation", "stop dictating"):
            sounds.play(cfg.sound_dictate_stop)
            _flush(mic, settle=_CHIME_SETTLE_SECONDS)
            out.emit("✎ Stopped typing.")
            return return_to
        if ctrl in ("enter", "new line", "new paragraph"):
            # Hand the PHRASE to dictate(), not a newline character. dictate() opens with
            # `raw = text.strip()`, so "\n" becomes "" and it returns at `if not raw` having done
            # nothing at all — all three of these were silent no-ops, while the log printed
            # "typed: enter" regardless so it looked like they had worked. The phrase routes into
            # dictate()'s specials map instead: "enter" → key code 36 (a real Return that SENDS),
            # "new line"/"new paragraph" → Shift+Return (a soft break that doesn't). This also puts
            # the fast lane and the Whisper lane on one implementation rather than two that drift —
            # which is what hid the bug, since "enter" worked whenever Vosk happened to miss it.
            actions.dictate(ctrl)
            out.emit(f"  typed: {ctrl}")
            continue
        text = _transcribe(transcriber, audio, cfg, out)
        if not text:
            continue
        if _is_abort(text, cfg):  # emergency stop → straight to idle, whatever mode we're in
            sounds.play(cfg.sound_abort)
            out.emit("🛑 Stopped.")
            return None
        if _is_quit(text, cfg):
            raise _Quit
        if _is_restart(text, cfg):
            raise _Restart
        if "stop typing" in normalize(text) or _is_sleep(text, cfg):
            sounds.play(cfg.sound_dictate_stop)
            _flush(mic, settle=_CHIME_SETTLE_SECONDS)
            out.emit("✎ Stopped typing.")
            return return_to
        actions.dictate(text)
        out.emit(f"  typed: {text!r}")


# --- PID file + clean stop ------------------------------------------------------------------------
# Vox restarts itself by spawning a detached process (start_new_session=True), so after a voice
# "restart" or an auto-restart it's no longer attached to the terminal and Ctrl+C can't reach it.
# A PID file gives a reliable way to stop it (`vox --stop` / `vox --replace`) regardless.
_PIDFILE = Path(__file__).resolve().parents[3] / "data" / "vox.pid"


def _write_pidfile() -> None:
    try:
        _PIDFILE.parent.mkdir(parents=True, exist_ok=True)
        _PIDFILE.write_text(str(os.getpid()))
    except Exception:
        pass  # the daemon must start even if we can't write the pidfile


def _read_pidfile() -> "int | None":
    try:
        return int(_PIDFILE.read_text().strip())
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # signal 0 = existence check, doesn't actually signal
        return True
    except OSError:
        return False


def _pid_on_port(cfg) -> "int | None":
    """Best-effort: the PID listening on the dashboard port (macOS `lsof`). Covers instances with a
    stale/missing pidfile — e.g. one started before this feature, or a detached auto-restart."""
    try:
        r = subprocess.run(["lsof", "-nP", f"-iTCP:{cfg.dashboard_port}", "-sTCP:LISTEN", "-t"],
                           capture_output=True, text=True, timeout=3)
        pids = [int(x) for x in r.stdout.split() if x.strip()]
        return next((p for p in pids if p != os.getpid()), None)
    except Exception:
        return None


def _running_pid(cfg) -> "int | None":
    """The live Vox daemon's PID: trust the pidfile if it points at a live process, else fall back
    to whatever holds the dashboard port."""
    pid = _read_pidfile()
    if pid and pid != os.getpid() and _pid_alive(pid):
        return pid
    return _pid_on_port(cfg)


def _stop_running(cfg, out) -> bool:
    """Stop a running Vox daemon: SIGTERM, wait for it to release the port, SIGKILL as a backstop.
    Returns True if something was stopped. Used by `--stop`, `--replace`, and the guard."""
    pid = _running_pid(cfg)
    if not pid:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    for _ in range(50):  # up to ~5s for a graceful exit + port release
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)  # didn't go quietly → force it
        except OSError:
            pass
    try:
        _PIDFILE.unlink(missing_ok=True)
    except Exception:
        pass
    out.emit(f"🛑 Stopped {cfg.assistant_name} (PID {pid}).")
    return True


def _another_instance_running(cfg) -> bool:
    """True if a Vox daemon is already running — detected by its dashboard port being held.
    Two daemons fight over the mic + duck the audio (the recurring duplicate-instance bug), so
    main() refuses to start a second one. Cheap TCP connect, guarded → False on any error so we
    never wrongly block startup. Only meaningful when the dashboard is enabled (the port is our
    liveness marker); a stray second daemon with the dashboard off is the rare case we don't catch."""
    if not getattr(cfg, "dashboard_enabled", True):
        return False
    import socket
    try:
        with socket.create_connection((cfg.dashboard_host, cfg.dashboard_port), timeout=0.3):
            return True
    except OSError:
        return False


def main() -> None:
    cfg = CONFIG
    args = set(sys.argv[1:])
    out = ConsoleOutput(cfg.log_file)

    # `vox --stop`: stop a running (possibly detached) daemon and exit. The reliable way to kill a
    # Vox that auto-restarted into the background where Ctrl+C can no longer reach it.
    if "--stop" in args:
        if not _stop_running(cfg, out):
            out.emit(f"No running {cfg.assistant_name} found.")
        return

    load_dotenv()  # load ANTHROPIC_API_KEY etc. from .env

    # Single-instance guard: a second daemon fights the first over the mic + ducks the audio (and
    # leaves the dashboard served by a stale process). Refuse to start a second copy — EXCEPT on a
    # restart, where the process we're replacing is exiting and may still briefly hold the port
    # (restart spawns us with VOX_RESTART=1; pop it so our own child processes don't inherit it).
    if os.environ.pop("VOX_RESTART", "") != "1" and _another_instance_running(cfg):
        if args & {"--replace", "--force"}:  # `vox --replace`: stop the old one, then start fresh
            out.emit(f"↻ --replace: stopping the running {cfg.assistant_name} first…")
            _stop_running(cfg, out)
        else:
            pid = _running_pid(cfg)
            pid_hint = f" (PID {pid})" if pid else ""
            out.emit(
                f"⚠️  {cfg.assistant_name} is already running{pid_hint} (port {cfg.dashboard_port} "
                f"is in use). Two daemons fight over the mic, so this won't start a second copy.\n"
                f"   • Stop it:    uv run vox --stop\n"
                f"   • Replace it: uv run vox --replace\n"
                f"   • Or say \"quit {cfg.assistant_name}\".\n"
                f"   (If it auto-restarted into the background, Ctrl+C in this terminal can't reach it"
                f" — that's why it kept running.)"
            )
            return

    _write_pidfile()  # we're cleared to run — record our PID so `--stop`/`--replace` can find us

    out.emit(f"Loading {cfg.assistant_name}… (first run downloads models)")
    with Timer() as load:
        transcriber = WhisperTranscriber(cfg.whisper_model, cfg.whisper_compute_type,
                                         cpu_threads=cfg.whisper_cpu_threads)
        wake = make_backend(cfg, transcriber, out)
    out.emit(f"Models loaded in {load.seconds:.1f}s.  [wake backend: {cfg.wake_backend}]")

    _start_dashboard(cfg, out)  # additive; non-fatal if the web package is missing/broken
    _start_scheduler(cfg, out)  # additive; non-fatal if the scheduler module is missing/broken
    _cmd_on_focus = _start_command_cache(cfg, out)  # boot-load the command DB + install query logging
    _start_focus_watch(cfg, out, on_change=_cmd_on_focus)  # logs app switches + loads each app's commands

    idle_msg = f"Idle. {wake.prompt} (Ctrl+C to quit)"
    out.emit(idle_msg)
    try:
        with _open_mic_or_wait(cfg, out) as mic:
            frames = mic.frames()
            # _Quit/_Restart are handled INSIDE the `with` (not propagated out) so we never run
            # MicStream.__exit__: PortAudio's Pa_StopStream → CoreAudio DeviceStop can deadlock and
            # wedge the process (the "restart got stuck" hang). os._exit skips that teardown; the OS
            # frees the mic when we exit, so a clean re-open works.
            try:
                while True:
                    label = wake.listen(frames, mic)
                    if label == "quit":
                        raise _Quit
                    if label == "restart":
                        raise _Restart
                    if label == "dashboard":  # "open dashboard" → open the web UI, stay idle
                        sounds.play(cfg.sound_dashboard_open)
                        _open_dashboard(cfg, out)
                        out.emit(idle_msg)
                        continue
                    if label == "close_dashboard":  # "close dashboard" → close its tab in place
                        sounds.play(cfg.sound_dashboard_close)
                        out.emit(f"🖥  {actions.close_dashboard()}")
                        out.emit(idle_msg)
                        continue
                    if label.startswith("do:"):  # one-shot from idle ("Vox, open Safari" / "Vox, write me…")
                        cmd = label[3:]
                        sounds.play(cfg.sound_oneshot)  # quick "got it" cue
                        # Same shared dispatch as control/assistant: deterministic (what-app /
                        # scheduler / command) first, else the executor (write / make-pretty /
                        # vision / fuzzy) — so one-shots cover everything the other modes do.
                        det = dispatch.try_deterministic(cmd)
                        if det is not None:
                            acted, msg = det
                            if acted:
                                out.emit(f"⚡ {cmd!r} → {msg}")
                            else:
                                out.emit(f"  🔊 {msg}")
                                tts.speak(msg)
                                mic.flush()
                            out.emit(idle_msg)
                            continue
                        sounds.play(cfg.sound_thinking)
                        acted, msg = executor.execute(cmd)
                        if msg == executor.ENTER_DICTATION:  # garbled "start typing" → dictate
                            out.emit("→ entering dictation…")
                            label = "dictation"  # fall through to the mode-chaining loop below
                        else:
                            if acted:
                                out.emit(f"⚡ {msg}")
                            elif msg:
                                shown, spoken = assistant.split_say(msg)
                                out.emit(f"  🔊 {shown}")
                                tts.speak(spoken)
                                mic.flush()
                            out.emit(idle_msg)
                            continue
                    # A mode may return a follow-on label to chain into the other mode
                    # without dropping to idle. If the assistant was reached *from* control,
                    # it returns to control when done (instead of idling).
                    from_control = False
                    while label in ("control", "assistant", "dictation"):
                        if label == "control":
                            sounds.play(cfg.sound_control)
                            label = _control_mode(frames, cfg, transcriber, out, mic)
                            from_control = label in ("assistant", "dictation")
                        elif label == "assistant":
                            sounds.play(cfg.sound_assistant)
                            label = _assistant_mode(frames, cfg, transcriber, out, mic,
                                                    return_to="control" if from_control else None)
                            from_control = False
                        else:  # dictation
                            label = _dictation_mode(frames, cfg, transcriber, out, mic,
                                                    return_to="control" if from_control else None)
                            from_control = False
                    out.emit(idle_msg)
            except MicStreamDead as exc:
                # The mic died and in-process recovery couldn't bring it back (usually an audio-device
                # change PortAudio can't re-bind). Self-restart: a fresh process re-acquires the mic
                # cleanly — same proven path as a voice "restart Vox" — so Vox never wedges silently.
                out.emit(f"\n⚠️  Mic unrecoverable ({exc}) — auto-restarting Vox to re-acquire it…")
                subprocess.Popen([sys.executable, "-m", "vox"], start_new_session=True,
                                 env={**os.environ, "VOX_RESTART": "1"})
                os._exit(0)
            except _Restart:
                out.emit("\n↻ Restarting Vox…")
                relaunch()
            except (KeyboardInterrupt, _Quit):
                sounds.play(cfg.sound_sleep)
                out.emit("\n👋 Quitting Vox.")
                os._exit(0)  # same reason — don't risk hanging on the mic-stream close on the way out
    except (KeyboardInterrupt, _Quit):  # Ctrl+C during startup (model load / mic open), before the loop
        out.emit("\n👋 Quitting Vox.")


if __name__ == "__main__":
    main()
