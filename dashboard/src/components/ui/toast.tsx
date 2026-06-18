import { AnimatePresence, motion } from "motion/react";
import { Check, Info, X, AlertTriangle } from "lucide-react";
import { useToast, type ToastVariant } from "@/hooks/useToast";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { cn } from "@/lib/utils";

const VARIANT: Record<
  ToastVariant,
  { icon: typeof Check; ring: string; tint: string }
> = {
  success: {
    icon: Check,
    ring: "border-success/40",
    tint: "text-success bg-success/15",
  },
  error: {
    icon: AlertTriangle,
    ring: "border-danger/40",
    tint: "text-danger bg-danger/15",
  },
  info: {
    icon: Info,
    ring: "border-accent/40",
    tint: "text-accent bg-accent/15",
  },
};

// Mount once near the app root. Reads the toast queue from context and renders a
// bottom-right stack of glass cards with spring slide-in / fade-out.
export function Toaster() {
  const { toasts, dismiss } = useToast();
  const reduced = useReducedMotion();

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const v = VARIANT[t.variant];
          const Icon = v.icon;
          return (
            <motion.div
              key={t.id}
              layout={!reduced}
              initial={reduced ? { opacity: 0 } : { opacity: 0, x: 24, scale: 0.96 }}
              animate={reduced ? { opacity: 1 } : { opacity: 1, x: 0, scale: 1 }}
              exit={reduced ? { opacity: 0 } : { opacity: 0, x: 24, scale: 0.96 }}
              transition={{ type: "spring", stiffness: 380, damping: 32 }}
              className={cn(
                "glass pointer-events-auto flex items-start gap-3 rounded-xl border px-3.5 py-3 shadow-glass",
                v.ring,
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                  v.tint,
                )}
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-foreground">{t.title}</div>
                {t.description && (
                  <div className="mt-0.5 text-xs text-foreground-secondary">
                    {t.description}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
                className="shrink-0 rounded-md p-1 text-foreground-muted transition-colors hover:bg-muted hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
