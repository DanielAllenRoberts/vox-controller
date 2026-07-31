"""Focus watcher — logs the frontmost app whenever it changes (observability).

A tiny background thread that polls ``actions.frontmost_app()`` and emits a
``window in view: <App>`` line to the daemon log (``vox.log``) on every change. It's the
focus-change DETECTION primitive the app-scoped command DB (idea #36, phase 2) will build
on — for now it just makes the switch visible so you can confirm Vox notices when you move
between apps (Arc ↔ Slack ↔ Cursor …).

Fully guarded, like the scheduler thread: it never raises out, so a wedged AppleScript or a
bad poll can't take down the voice daemon. Runs only when ``focus_watch_enabled``.
"""

from __future__ import annotations

import threading

from vox.config import CONFIG

# Singleton background thread (started once from the daemon).
_THREAD: "_FocusThread | None" = None


class _FocusThread(threading.Thread):
    """Polls the frontmost app every ~poll seconds; logs each change. Guarded so a bad poll
    is swallowed rather than raised — it can never crash the daemon."""

    def __init__(self, out, poll_seconds: float, on_change=None):
        super().__init__(name="vox-focus-watch", daemon=True)
        self._out = out
        self._poll = max(0.3, float(poll_seconds))
        self._stop = threading.Event()
        self._last = ""
        self._on_change = on_change  # called with the new app name on each switch (e.g. command_cache.on_focus)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        from vox import actions
        self._poll_once(actions)  # log the starting app once, so the baseline is visible
        while not self._stop.wait(self._poll):
            self._poll_once(actions)

    def _poll_once(self, actions) -> None:
        try:
            app = actions.frontmost_app()
            if app and app != self._last:
                self._last = app
                self._out.emit(f"  👁  window in view: {app}")
                if self._on_change is not None:
                    try:
                        self._on_change(app)  # load this app's command set into the cache (logs its own queries)
                    except Exception:
                        pass  # a broken cache load must never take down the focus thread
        except Exception:
            pass  # a bad poll / log write must never take down the thread


def start(out, on_change=None) -> "_FocusThread | None":
    """Start the focus-watch thread (idempotent). Returns the thread, or None if disabled /
    already running. ``on_change`` (optional) is called with the new app name on each switch — the
    command DB hooks its per-app load in here. Fully guarded — a failure to start never breaks the daemon."""
    global _THREAD
    if not getattr(CONFIG, "focus_watch_enabled", True):
        return None
    if _THREAD is not None and _THREAD.is_alive():
        return _THREAD
    try:
        _THREAD = _FocusThread(out, getattr(CONFIG, "focus_watch_poll_seconds", 1.5), on_change=on_change)
        _THREAD.start()
        return _THREAD
    except Exception:
        return None


def stop() -> None:
    """Signal the background thread to stop (best-effort; it's a daemon thread)."""
    global _THREAD
    if _THREAD is not None:
        try:
            _THREAD.stop()
        except Exception:
            pass
        _THREAD = None
