import { AnimatePresence, motion } from "motion/react";
import { Radio, Inbox } from "lucide-react";
import { cn, formatCost, formatLatency, formatTokens, relativeTime } from "@/lib/utils";
import { useNow } from "@/hooks/useNow";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { KindBadge } from "./KindBadge";
import { Badge } from "@/components/ui/badge";
import type { StreamStatus } from "@/hooks/useUsageStream";
import type { UsageEvent } from "@/lib/api";

const SUBSCRIPTION_PROVIDERS = new Set(["claude_sdk", "claude_cli"]);

function shortModel(model: string): string {
  if (!model) return "—";
  // Trim trailing date snapshots (claude-haiku-4-5-20251001 → claude-haiku-4-5).
  return model.replace(/-\d{6,8}$/, "");
}

function FeedRow({ e, now }: { e: UsageEvent; now: number }) {
  const isSub = SUBSCRIPTION_PROVIDERS.has(e.provider);
  return (
    <div className="flex items-center gap-3 px-1 py-2.5">
      <KindBadge kind={e.kind} showLabel={false} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-xs text-foreground">
            {shortModel(e.model)}
          </span>
          <Badge
            variant={e.brain === "big" ? "accent" : "outline"}
            className="shrink-0 px-1.5 py-0 text-[10px] uppercase"
          >
            {e.brain}
          </Badge>
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-foreground-muted">
          <span className="tnum">
            {formatTokens(e.inputTokens)}→{formatTokens(e.outputTokens)} tok
          </span>
          <span aria-hidden>·</span>
          <span className="tnum">{formatLatency(e.latencyMs)}</span>
        </div>
      </div>
      <div className="shrink-0 text-right">
        {isSub ? (
          <Badge
            variant="info"
            className="px-1.5 py-0 text-[10px]"
            title="Flat-rate subscription call (no per-token cost)"
          >
            subscription
          </Badge>
        ) : (
          <span className="tnum text-xs font-medium text-foreground">
            {formatCost(e.costUsd)}
          </span>
        )}
        <div className="mt-0.5 tnum text-[10px] text-foreground-muted">
          {relativeTime(e.ts, now)}
        </div>
      </div>
    </div>
  );
}

interface LiveFeedProps {
  events: UsageEvent[];
  status: StreamStatus;
  /** Cap rows rendered (the hook keeps a larger buffer). */
  limit?: number;
  className?: string;
}

// Shared live recent-calls feed: streamed UsageEvents, newest first, with a
// spring slide-in on each new row. Used by Overview (compact) + Token Usage.
export function LiveFeed({ events, status, limit = 12, className }: LiveFeedProps) {
  const now = useNow(1000);
  const reduced = useReducedMotion();
  const rows = events.slice(0, limit);

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className="mb-1 flex items-center justify-between px-1">
        <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
          <Radio className="h-3.5 w-3.5" />
          Live activity
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              status === "live"
                ? "bg-success shadow-[0_0_6px_hsl(var(--success))]"
                : status === "connecting"
                  ? "bg-warning"
                  : "bg-foreground-muted",
            )}
          />
          <span className="text-[10px] uppercase tracking-wide text-foreground-muted">
            {status}
          </span>
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
          <Inbox className="h-6 w-6 text-foreground-muted" />
          <p className="text-sm text-foreground-secondary">No calls yet</p>
          <p className="max-w-[18rem] text-xs text-foreground-muted">
            Talk to Vox — chats, commands, and rewrites stream in here the moment
            they happen.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-border/60">
          <AnimatePresence initial={false}>
            {rows.map((e) => (
              <motion.div
                key={e.id}
                layout={!reduced}
                initial={reduced ? { opacity: 0 } : { opacity: 0, y: -6, height: 0 }}
                animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0, height: "auto" }}
                exit={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
                transition={{ type: "spring", stiffness: 400, damping: 36 }}
              >
                <FeedRow e={e} now={now} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
