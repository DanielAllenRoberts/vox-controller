import * as React from "react";
import { motion, type HTMLMotionProps } from "motion/react";
import { useReducedMotion } from "@/hooks/useReducedMotion";

// Staggered list/grid entrance. Wrap items in <StaggerItem> (ui.md §7:
// staggerChildren 0.04, each child fade + 6px rise).
export function Stagger({
  children,
  stagger = 0.04,
  ...props
}: HTMLMotionProps<"div"> & { stagger?: number }) {
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: stagger } },
      }}
      {...props}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, ...props }: HTMLMotionProps<"div">) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={{
        hidden: reduced ? { opacity: 0 } : { opacity: 0, y: 6 },
        show: reduced
          ? { opacity: 1 }
          : {
              opacity: 1,
              y: 0,
              transition: { type: "spring", stiffness: 300, damping: 30 },
            },
      }}
      {...props}
    >
      {children}
    </motion.div>
  );
}
