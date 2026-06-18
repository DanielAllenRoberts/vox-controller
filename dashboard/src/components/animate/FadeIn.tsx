import * as React from "react";
import { motion, type HTMLMotionProps } from "motion/react";
import { useReducedMotion } from "@/hooks/useReducedMotion";

interface FadeInProps extends HTMLMotionProps<"div"> {
  /** Delay in seconds before the entrance starts. */
  delay?: number;
  /** Upward rise distance in px. */
  y?: number;
}

// Entrance wrapper: fade + small upward slide on mount (ui.md §7).
export function FadeIn({
  delay = 0,
  y = 8,
  children,
  ...props
}: FadeInProps) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      initial={reduced ? { opacity: 0 } : { opacity: 0, y }}
      animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0 }}
      transition={{
        delay,
        type: "spring",
        stiffness: 260,
        damping: 30,
      }}
      {...props}
    >
      {children}
    </motion.div>
  );
}
