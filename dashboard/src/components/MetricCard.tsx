import * as React from "react";
import { type LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  icon?: LucideIcon;
  /** Main value — pass a SlidingNumber or any node. */
  value?: React.ReactNode;
  /** Secondary line under the value (e.g. provider·model). */
  sub?: React.ReactNode;
  /** Top-right adornment (status dot, badge). */
  adornment?: React.ReactNode;
  loading?: boolean;
  mono?: boolean;
  className?: string;
}

// Glass metric card — overline label + big value + sub + optional adornment.
// The Overview & Token Usage workhorse (ui.md §6).
export function MetricCard({
  label,
  icon: Icon,
  value,
  sub,
  adornment,
  loading = false,
  mono = false,
  className,
}: MetricCardProps) {
  return (
    <Card
      glass
      className={cn(
        "group p-5 transition-all duration-150 hover:-translate-y-px hover:border-white/15 hover:shadow-accent-glow",
        className,
      )}
    >
      <div className="flex items-start justify-between">
        <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
          {Icon && <Icon className="h-3.5 w-3.5" />}
          {label}
        </span>
        {adornment}
      </div>
      <div className="mt-3">
        {loading ? (
          <Skeleton className="h-9 w-28" />
        ) : (
          <div
            className={cn(
              "text-display leading-none text-foreground",
              mono && "font-mono",
            )}
          >
            {value}
          </div>
        )}
      </div>
      {sub && (
        <div className="mt-2 text-sm text-foreground-secondary">
          {loading ? <Skeleton className="h-4 w-24" /> : sub}
        </div>
      )}
    </Card>
  );
}
