import { AnimatePresence, motion } from "motion/react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "./theme";
import { useReducedMotion } from "@/hooks/useReducedMotion";

// Small TopBar control that flips between dark and light. Icon cross-fades /
// rotates with the existing motion dep; respects reduced-motion. Reads/writes
// the persisted theme via useTheme.
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const reduced = useReducedMotion();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Light theme" : "Dark theme"}
      className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg border border-border-strong text-foreground-muted transition-colors hover:border-accent/40 hover:text-foreground"
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={theme}
          initial={reduced ? { opacity: 0 } : { opacity: 0, rotate: -90, scale: 0.6 }}
          animate={reduced ? { opacity: 1 } : { opacity: 1, rotate: 0, scale: 1 }}
          exit={reduced ? { opacity: 0 } : { opacity: 0, rotate: 90, scale: 0.6 }}
          transition={{ duration: reduced ? 0 : 0.18 }}
          className="absolute inset-0 flex items-center justify-center"
        >
          {isDark ? (
            <Moon className="h-4 w-4" />
          ) : (
            <Sun className="h-4 w-4" />
          )}
        </motion.span>
      </AnimatePresence>
    </button>
  );
}
