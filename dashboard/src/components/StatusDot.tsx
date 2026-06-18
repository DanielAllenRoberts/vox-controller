import { cn } from "@/lib/utils";

export type StatusKind = "online" | "offline" | "connecting";

const COLORS: Record<StatusKind, string> = {
  online: "bg-success shadow-[0_0_8px_hsl(var(--success))]",
  offline: "bg-danger shadow-[0_0_8px_hsl(var(--danger))]",
  connecting: "bg-warning shadow-[0_0_8px_hsl(var(--warning))]",
};

const LABELS: Record<StatusKind, string> = {
  online: "Online",
  offline: "Offline",
  connecting: "Connecting",
};

export function StatusDot({
  status,
  label,
  className,
}: {
  status: StatusKind;
  label?: string;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className={cn("h-2 w-2 rounded-full", COLORS[status])} />
      <span className="text-xs text-foreground-secondary">
        {label ?? LABELS[status]}
      </span>
    </span>
  );
}
