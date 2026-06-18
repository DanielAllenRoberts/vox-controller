import * as React from "react";
import {
  animate,
  useMotionValue,
  useTransform,
  motion,
} from "motion/react";
import { cn } from "@/lib/utils";
import { useReducedMotion } from "@/hooks/useReducedMotion";

interface SlidingNumberProps extends React.HTMLAttributes<HTMLSpanElement> {
  value: number;
  /** Decimal places to render. */
  decimals?: number;
  /** Prefix (e.g. "$") rendered before the number. */
  prefix?: string;
  /** Suffix rendered after the number. */
  suffix?: string;
  /** Spring duration in seconds. */
  duration?: number;
}

// Spring-animated number for token/cost counters. Tabular figures so digits
// don't jitter as they change (ui.md §6). Respects prefers-reduced-motion.
export function SlidingNumber({
  value,
  decimals = 0,
  prefix = "",
  suffix = "",
  duration = 0.6,
  className,
  ...props
}: SlidingNumberProps) {
  const reduced = useReducedMotion();
  const mv = useMotionValue(value);
  const display = useTransform(mv, (v) =>
    v.toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }),
  );

  React.useEffect(() => {
    if (reduced) {
      mv.set(value);
      return;
    }
    const controls = animate(mv, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
    });
    return controls.stop;
  }, [value, duration, reduced, mv]);

  return (
    <span className={cn("tnum tabular-nums", className)} {...props}>
      {prefix}
      <motion.span>{display}</motion.span>
      {suffix}
    </span>
  );
}
