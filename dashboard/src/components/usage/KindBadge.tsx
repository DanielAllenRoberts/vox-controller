import { MessageSquare, Terminal, Eye, PenLine } from "lucide-react";
import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { UsageKind } from "@/lib/api";

const META: Record<UsageKind, { icon: LucideIcon; label: string; tint: string }> = {
  chat: { icon: MessageSquare, label: "Chat", tint: "text-accent-2" },
  command: { icon: Terminal, label: "Command", tint: "text-accent" },
  vision: { icon: Eye, label: "Vision", tint: "text-info" },
  rewrite: { icon: PenLine, label: "Rewrite", tint: "text-warning" },
};

// Tiny kind glyph + label for usage rows. Falls back gracefully on unknowns.
export function KindBadge({
  kind,
  showLabel = true,
  className,
}: {
  kind: UsageKind | string;
  showLabel?: boolean;
  className?: string;
}) {
  const meta = META[kind as UsageKind] ?? {
    icon: Terminal,
    label: kind,
    tint: "text-foreground-muted",
  };
  const Icon = meta.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <Icon className={cn("h-3.5 w-3.5", meta.tint)} />
      {showLabel && (
        <span className="text-xs text-foreground-secondary">{meta.label}</span>
      )}
    </span>
  );
}
