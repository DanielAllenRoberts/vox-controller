import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { GO_SHORTCUTS } from "./shortcuts";

// --- Global keyboard shortcuts ----------------------------------------------
// Vim/Linear-style `g` then <key> navigation, plus `?` to open the help
// overlay. Never fires while the user is typing in a field (input, textarea,
// select, or contenteditable). The g-chord has a short timeout so a stray `g`
// doesn't arm navigation forever. ⌘K is handled separately in AppShell.

const CHORD_TIMEOUT_MS = 1200;

function isEditable(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable
  );
}

export function useKeyboardShortcuts({
  onHelp,
  enabled = true,
}: {
  onHelp: () => void;
  enabled?: boolean;
}) {
  const navigate = useNavigate();
  // Latest callbacks in a ref so the listener stays mounted once.
  const onHelpRef = useRef(onHelp);
  onHelpRef.current = onHelp;
  const navRef = useRef(navigate);
  navRef.current = navigate;

  useEffect(() => {
    if (!enabled) return;

    let gArmed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const disarm = () => {
      gArmed = false;
      if (timer) clearTimeout(timer);
    };

    const onKey = (e: KeyboardEvent) => {
      // Never hijack typing or modified chords (⌘K etc. handled elsewhere).
      if (isEditable(e.target) || e.metaKey || e.ctrlKey || e.altKey) {
        disarm();
        return;
      }

      const key = e.key.toLowerCase();

      // `?` opens help (Shift+/ on most layouts; match the literal char).
      if (e.key === "?") {
        e.preventDefault();
        disarm();
        onHelpRef.current();
        return;
      }

      if (gArmed) {
        const match = GO_SHORTCUTS.find((s) => s.key === key);
        disarm();
        if (match) {
          e.preventDefault();
          navRef.current(match.to);
        }
        return;
      }

      if (key === "g") {
        gArmed = true;
        timer = setTimeout(disarm, CHORD_TIMEOUT_MS);
      }
    };

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      disarm();
    };
  }, [enabled]);
}
