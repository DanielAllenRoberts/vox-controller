import { useEffect } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { Keyboard, X } from "lucide-react";
import { GO_SHORTCUTS, GLOBAL_SHORTCUTS } from "./shortcuts";
import { useReducedMotion } from "@/hooks/useReducedMotion";

// --- Keyboard shortcuts help overlay ----------------------------------------
// Glassy modal listing every shortcut: the `g`-then-key navigation set, ⌘K for
// the palette, and `?` for this help. Opened by `?` (global handler) or the
// TopBar `?` button. Closes on Esc / scrim click. Mirrors the CommandPalette
// recipe (portal + AnimatePresence + reduced-motion fallback) for cohesion.

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-md border border-border-strong bg-muted/50 px-1.5 font-mono text-[11px] font-medium text-foreground-secondary">
      {children}
    </kbd>
  );
}

export function HelpOverlay({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const reduced = useReducedMotion();

  // Esc to close (the global g-chord handler ignores Esc, so own it here).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-start justify-center px-4 pt-[12vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.12 }}
        >
          {/* Scrim */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
            aria-hidden
          />

          {/* Panel */}
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Keyboard shortcuts"
            className="glass relative w-full max-w-lg overflow-hidden rounded-2xl"
            initial={
              reduced ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.98 }
            }
            animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
          >
            {/* Accent hairline */}
            <div className="h-px w-full bg-brand-gradient opacity-70" />

            {/* Header */}
            <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
              <div className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-md border border-accent/40 bg-accent/10 text-accent">
                  <Keyboard className="h-4 w-4" />
                </span>
                <h2 className="text-sm font-semibold tracking-tight">
                  Keyboard shortcuts
                </h2>
              </div>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className="rounded-md p-1 text-foreground-muted transition-colors hover:bg-muted hover:text-foreground"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Body */}
            <div className="max-h-[60vh] overflow-y-auto px-5 py-4">
              {/* Navigation (g then key) */}
              <div className="mb-2 flex items-center gap-2 text-overline uppercase text-foreground-muted">
                Navigate
                <span className="font-normal normal-case tracking-normal text-foreground-muted/80">
                  press <Kbd>g</Kbd> then…
                </span>
              </div>
              <ul className="mb-5 divide-y divide-border/60">
                {GO_SHORTCUTS.map((s) => (
                  <li
                    key={s.key}
                    className="flex items-center justify-between py-2"
                  >
                    <span className="text-sm text-foreground-secondary">
                      {s.label}
                    </span>
                    <span className="flex items-center gap-1">
                      <Kbd>g</Kbd>
                      <span className="text-foreground-muted">then</span>
                      <Kbd>{s.key}</Kbd>
                    </span>
                  </li>
                ))}
              </ul>

              {/* Global */}
              <div className="mb-2 text-overline uppercase text-foreground-muted">
                General
              </div>
              <ul className="divide-y divide-border/60">
                {GLOBAL_SHORTCUTS.map((s) => (
                  <li
                    key={s.description}
                    className="flex items-center justify-between gap-4 py-2"
                  >
                    <span className="text-sm text-foreground-secondary">
                      {s.description}
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      {s.keys.map((k, i) => (
                        <Kbd key={i}>{k}</Kbd>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Footer */}
            <div className="border-t border-border px-5 py-2.5 text-[11px] text-foreground-muted">
              Press <Kbd>?</Kbd> any time to reopen this panel.
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
