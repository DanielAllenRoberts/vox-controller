import { cn } from "@/lib/utils";

interface ListeningPulseProps {
  /** When true, the violet ring pulses ("listening"); otherwise a static dot. */
  active?: boolean;
  className?: string;
  /** Tailwind size of the core dot, e.g. "h-2 w-2". */
  size?: string;
}

// The dashboard's signature "alive" element: a soft pulsing violet ring around
// a core dot, animated only while the daemon is listening (ui.md §6/§7). The
// CSS keyframe (listening-pulse) is gated by prefers-reduced-motion globally.
export function ListeningPulse({
  active = false,
  className,
  size = "h-2 w-2",
}: ListeningPulseProps) {
  return (
    <span
      className={cn("relative inline-flex items-center justify-center", className)}
    >
      {active && (
        <span
          className={cn(
            "absolute rounded-full bg-accent/70 animate-listening-pulse",
            size,
          )}
        />
      )}
      <span
        className={cn(
          "relative rounded-full",
          size,
          active ? "bg-accent shadow-[0_0_8px_hsl(var(--accent))]" : "bg-foreground-muted",
        )}
      />
    </span>
  );
}
