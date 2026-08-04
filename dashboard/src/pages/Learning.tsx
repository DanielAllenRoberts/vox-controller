import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Check,
  Clock,
  Ban,
  Trash2,
  Sparkles,
  Hourglass,
  ShieldAlert,
} from "lucide-react";
import {
  api,
  type LearningView,
  type LearnedCommand,
  type LearningCandidate,
  type LearningThresholds,
} from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/useToast";

const LEARNING_KEY = ["commands", "learning"] as const;

// ---------------------------------------------------------------------------
// The four states a self-taught command moves through. Keeping them as one
// ordered list (rather than scattered conditionals) is what lets the page group
// by app and still show the states in a consistent order inside each group.
// ---------------------------------------------------------------------------

type Stage = "saved" | "probation" | "learning" | "blocked";

const STAGE_META: Record<
  Stage,
  { label: string; blurb: string; icon: typeof Brain; variant: "success" | "warning" | "info" | "danger" }
> = {
  saved: {
    label: "Cemented",
    blurb: "Used enough to be permanent. Run without asking the AI.",
    icon: Check,
    variant: "success",
  },
  probation: {
    label: "Working, not yet permanent",
    blurb: "These RUN already — no AI. Used enough in time, they stay; otherwise they expire.",
    icon: Hourglass,
    variant: "warning",
  },
  learning: {
    label: "Learning",
    blurb: "Evidence only. These never fire — Vox is still counting.",
    icon: Clock,
    variant: "info",
  },
  blocked: {
    label: "Blocked",
    blurb: "Rejected. Won't be learned again.",
    icon: Ban,
    variant: "danger",
  },
};

// ---------------------------------------------------------------------------

// The bridge is a long-running daemon and can be older than the bundle it's serving (it only picks
// up Python changes on restart). `thresholds`, `bar` and the probation fields were added later, so
// fill them in rather than letting a stale backend blank the page.
const DEFAULT_THRESHOLDS: LearningThresholds = {
  min_hits: 3,
  window_days: 2,
  probation_days: 14,
  probation_uses: 2,
  max_negatives: 3,
};

function normalize(raw: LearningView): LearningView {
  const thresholds = { ...DEFAULT_THRESHOLDS, ...(raw.thresholds ?? {}) };
  return {
    ...raw,
    thresholds,
    aliases: raw.aliases ?? [],
    learned: (raw.learned ?? []).map((c) => ({
      ...c,
      probation:
        c.probation ?? (c.hits ?? 0) < thresholds.probation_uses,
      probation_uses_left:
        c.probation_uses_left ??
        Math.max(0, thresholds.probation_uses - (c.hits ?? 0)),
      probation_days_left: c.probation_days_left ?? null,
    })),
    candidates: (raw.candidates ?? []).map((c) => ({
      ...c,
      bar: c.bar || `${c.hits}/${thresholds.min_hits} hits in ${thresholds.window_days}d`,
    })),
  };
}

function useLearningMutation<TArgs>(
  fn: (a: TArgs) => Promise<unknown>,
  messages: { error: string; success: string },
) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LEARNING_KEY });
      toast({ variant: "success", title: messages.success });
    },
    onError: () =>
      toast({
        variant: "error",
        title: messages.error,
        description: "Is the bridge running?",
      }),
  });
}

function ago(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (!Number.isFinite(mins)) return "—";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/** "click 'refresh'" — what the command actually DOES, in the same shape everywhere. */
function actionOf(x: { intent: string; arg: string | null }): string {
  return x.arg ? `${x.intent} · ${x.arg}` : x.intent;
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

function Phrases({ phrases }: { phrases: string[] }) {
  if (!phrases.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {phrases.map((p) => (
        <span
          key={p}
          className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground-secondary"
        >
          “{p}”
        </span>
      ))}
    </div>
  );
}

function SavedRow({
  cmd,
  onForget,
  busy,
}: {
  cmd: LearnedCommand;
  onForget: (id: number) => void;
  busy: boolean;
}) {
  return (
    <Card className="p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm">{actionOf(cmd)}</span>
            {cmd.probation ? (
              <Badge variant="warning">
                <Hourglass className="size-3" />
                {cmd.hits}/{cmd.hits + cmd.probation_uses_left} uses
                {cmd.probation_days_left !== null &&
                  ` · ${cmd.probation_days_left}d to cement`}
              </Badge>
            ) : (
              <Badge variant="success">
                <Check className="size-3" />
                proven
              </Badge>
            )}
            {!cmd.enabled && <Badge variant="danger">disabled</Badge>}
          </div>
          <Phrases phrases={cmd.phrases} />
          <p className="mt-1.5 text-[11px] text-foreground-muted">
            {cmd.hits} use{cmd.hits === 1 ? "" : "s"} · saved {ago(cmd.learned_at)}
            {cmd.last_used_at && ` · last used ${ago(cmd.last_used_at)}`}
            {cmd.reason && ` · ${cmd.reason}`}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => onForget(cmd.id)}
          aria-label={`Forget ${actionOf(cmd)}`}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
    </Card>
  );
}

function CandidateRow({
  cand,
  onPromote,
  onReject,
  busy,
}: {
  cand: LearningCandidate;
  onPromote: (id: number) => void;
  onReject: (id: number) => void;
  busy: boolean;
}) {
  return (
    <Card className="p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm">{actionOf(cand)}</span>
            {cand.blocked ? (
              <Badge variant="danger">
                <Ban className="size-3" />
                blocked
              </Badge>
            ) : (
              <Badge variant="info">{cand.bar}</Badge>
            )}
            {cand.negatives > 0 && (
              <Badge variant="warning">
                <ShieldAlert className="size-3" />
                {cand.negatives} correction
                {cand.negatives === 1 ? "" : "s"}
              </Badge>
            )}
          </div>
          <Phrases phrases={cand.phrases} />
          <p className="mt-1.5 text-[11px] text-foreground-muted">
            first heard {ago(cand.first_seen)} · last {ago(cand.last_seen)}
          </p>
        </div>
        {!cand.blocked && (
          <div className="flex shrink-0 gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => onPromote(cand.id)}
            >
              <Check className="size-3.5" />
              Save
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onReject(cand.id)}
              aria-label="Never learn this"
            >
              <Ban className="size-4" />
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Grouping — by app first (that's how you think about them), stage second.
// ---------------------------------------------------------------------------

interface AppGroup {
  app: string;
  saved: LearnedCommand[];
  probation: LearnedCommand[];
  learning: LearningCandidate[];
  blocked: LearningCandidate[];
}

function groupByApp(data: LearningView): AppGroup[] {
  const map = new Map<string, AppGroup>();
  const get = (app: string) => {
    let g = map.get(app);
    if (!g) {
      g = { app, saved: [], probation: [], learning: [], blocked: [] };
      map.set(app, g);
    }
    return g;
  };
  for (const c of data.learned) {
    const g = get(c.context);
    (c.probation ? g.probation : g.saved).push(c);
  }
  for (const c of data.candidates) {
    const g = get(c.context);
    (c.blocked ? g.blocked : g.learning).push(c);
  }
  // "global" (applies everywhere) first, then apps alphabetically.
  return [...map.values()].sort((a, b) =>
    a.app === "global" ? -1 : b.app === "global" ? 1 : a.app.localeCompare(b.app),
  );
}

function StageBlock({
  stage,
  children,
  count,
}: {
  stage: Stage;
  count: number;
  children: React.ReactNode;
}) {
  if (!count) return null;
  const meta = STAGE_META[stage];
  const Icon = meta.icon;
  return (
    <div className="mt-3 first:mt-0">
      <div className="mb-1.5 flex items-center gap-2">
        <Icon className="size-3.5 text-foreground-muted" />
        <span className="text-[11px] font-medium uppercase tracking-wide text-foreground-muted">
          {meta.label}
        </span>
        <span className="text-[11px] text-foreground-muted">· {count}</span>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Summary({
  groups,
  thresholds,
  mode,
}: {
  groups: AppGroup[];
  thresholds: LearningThresholds;
  mode: string;
}) {
  const totals = groups.reduce(
    (acc, g) => ({
      saved: acc.saved + g.saved.length,
      probation: acc.probation + g.probation.length,
      learning: acc.learning + g.learning.length,
      blocked: acc.blocked + g.blocked.length,
    }),
    { saved: 0, probation: 0, learning: 0, blocked: 0 },
  );
  const tiles: { stage: Stage; n: number }[] = [
    { stage: "saved", n: totals.saved },
    { stage: "probation", n: totals.probation },
    { stage: "learning", n: totals.learning },
    { stage: "blocked", n: totals.blocked },
  ];
  return (
    <FadeIn className="mb-6">
      <Card glass className="relative overflow-hidden p-4">
        <span className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
        <div className="grid gap-4 sm:grid-cols-4">
          {tiles.map(({ stage, n }) => {
            const meta = STAGE_META[stage];
            const Icon = meta.icon;
            return (
              <div key={stage}>
                <div className="flex items-center gap-1.5">
                  <Icon className="size-3.5 text-foreground-muted" />
                  <span className="text-[11px] uppercase tracking-wide text-foreground-muted">
                    {meta.label}
                  </span>
                </div>
                <p className="mt-0.5 text-2xl font-semibold tabular-nums">{n}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-foreground-muted">
                  {meta.blurb}
                </p>
              </div>
            );
          })}
        </div>
        <p className="mt-4 border-t border-border pt-3 text-[11px] text-foreground-muted">
          Mode <span className="font-medium text-foreground-secondary">{mode}</span> · the AI works
          something out once, it's{" "}
          <span className="font-medium text-foreground-secondary">saved and usable immediately</span>{" "}
          — every use after that skips the AI. Use it{" "}
          {thresholds.probation_uses}× within {thresholds.probation_days} days and it becomes
          permanent; otherwise it expires. {thresholds.max_negatives} corrections block it.
        </p>
      </Card>
    </FadeIn>
  );
}

export function Learning() {
  const { data: raw, isLoading } = useQuery({
    queryKey: LEARNING_KEY,
    queryFn: api.learning,
    refetchInterval: 15_000,
  });
  const data = React.useMemo(() => (raw ? normalize(raw) : undefined), [raw]);

  const promote = useLearningMutation((id: number) => api.promoteCandidate(id), {
    error: "Couldn't save that command",
    success: "Saved — it'll run without the AI now",
  });
  const reject = useLearningMutation((id: number) => api.rejectCandidate(id), {
    error: "Couldn't reject that",
    success: "Rejected — it won't be learned",
  });
  const forget = useLearningMutation((id: number) => api.forgetLearned(id), {
    error: "Couldn't forget that command",
    success: "Forgotten",
  });
  const busy = promote.isPending || reject.isPending || forget.isPending;

  const groups = React.useMemo(() => (data ? groupByApp(data) : []), [data]);

  return (
    <div>
      <PageHeader
        title="Learned Commands"
        description="Commands Vox worked out for itself — what it's saved, what's still on trial, and what it's only considering."
      />

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}

      {data && (
        <>
          <Summary groups={groups} thresholds={data.thresholds} mode={data.mode} />

          {data.aliases.length > 0 && (
            <FadeIn className="mb-6">
              <Card className="p-3">
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles className="size-3.5 text-foreground-muted" />
                  <span className="text-[11px] font-medium uppercase tracking-wide text-foreground-muted">
                    New ways of saying existing commands · {data.aliases.length}
                  </span>
                </div>
                <p className="mb-2 text-[11px] text-foreground-muted">
                  Vox already knew how to do these, so it added your wording to the command it
                  had rather than making a duplicate. These work now.
                </p>
                <div className="space-y-1.5">
                  {data.aliases.map((a) => (
                    <div key={a.id} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground-secondary">
                        “{a.text}”
                      </span>
                      <span className="text-foreground-muted">→</span>
                      <span className="font-mono text-[13px]">{a.label}</span>
                      <Badge variant="success">
                        <Check className="size-3" />
                        live
                      </Badge>
                    </div>
                  ))}
                </div>
              </Card>
            </FadeIn>
          )}

          {groups.length === 0 && data.aliases.length === 0 && (
            <Card className="p-8 text-center">
              <Brain className="mx-auto size-8 text-foreground-muted" />
              <p className="mt-3 text-sm text-foreground-secondary">
                Nothing learned yet.
              </p>
              <p className="mx-auto mt-1 max-w-md text-xs text-foreground-muted">
                When the AI works out a command for you, it lands here as evidence
                first. Repeat it {data.thresholds.min_hits} times within{" "}
                {data.thresholds.window_days} days and Vox saves it — or say “remember
                that” straight after to keep it right away.
              </p>
            </Card>
          )}

          <Stagger className="space-y-5">
            {groups.map((g) => (
              <StaggerItem key={g.app}>
                <section>
                  <div className="mb-2 flex items-center gap-2">
                    <h2 className="text-sm font-semibold">
                      {g.app === "global" ? "Everywhere" : g.app}
                    </h2>
                    {g.app === "global" && (
                      <Badge variant="outline">
                        <Sparkles className="size-3" />
                        any app
                      </Badge>
                    )}
                  </div>

                  <StageBlock stage="saved" count={g.saved.length}>
                    {g.saved.map((c) => (
                      <SavedRow
                        key={c.id}
                        cmd={c}
                        busy={busy}
                        onForget={(id) => forget.mutate(id)}
                      />
                    ))}
                  </StageBlock>

                  <StageBlock stage="probation" count={g.probation.length}>
                    {g.probation.map((c) => (
                      <SavedRow
                        key={c.id}
                        cmd={c}
                        busy={busy}
                        onForget={(id) => forget.mutate(id)}
                      />
                    ))}
                  </StageBlock>

                  <StageBlock stage="learning" count={g.learning.length}>
                    {g.learning.length > 0 && (
                      <p className="-mt-0.5 mb-1 text-[11px] text-foreground-muted">
                        Not commands yet — saying these does nothing until they're saved.
                      </p>
                    )}
                    {g.learning.map((c) => (
                      <CandidateRow
                        key={c.id}
                        cand={c}
                        busy={busy}
                        onPromote={(id) => promote.mutate(id)}
                        onReject={(id) => reject.mutate(id)}
                      />
                    ))}
                  </StageBlock>

                  <StageBlock stage="blocked" count={g.blocked.length}>
                    {g.blocked.map((c) => (
                      <CandidateRow
                        key={c.id}
                        cand={c}
                        busy={busy}
                        onPromote={(id) => promote.mutate(id)}
                        onReject={(id) => reject.mutate(id)}
                      />
                    ))}
                  </StageBlock>
                </section>
              </StaggerItem>
            ))}
          </Stagger>
        </>
      )}
    </div>
  );
}
