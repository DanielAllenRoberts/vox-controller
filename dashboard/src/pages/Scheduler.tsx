import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlarmClock,
  Timer,
  Bell,
  Plus,
  Trash2,
  Repeat,
} from "lucide-react";
import {
  api,
  type Reminder,
  type ReminderKind,
  type Recurrence,
} from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/useToast";
import { useNow } from "@/hooks/useNow";
import { cn } from "@/lib/utils";

const REMINDERS_KEY = ["reminders"] as const;

// Per-kind presentation: icon, label, accent.
const KIND_META: Record<
  ReminderKind,
  { icon: typeof Timer; label: string; plural: string }
> = {
  timer: { icon: Timer, label: "Timer", plural: "Timers" },
  alarm: { icon: AlarmClock, label: "Alarm", plural: "Alarms" },
  reminder: { icon: Bell, label: "Reminder", plural: "Reminders" },
};

const RECURRENCE_LABEL: Record<string, string> = {
  daily: "every day",
  weekdays: "every weekday",
  weekly: "every week",
};

// --- fireAt is a NAIVE local ISO ("2026-06-19T21:30:00"); parse it as local time. ---
function fireMs(iso: string): number {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
}

// Countdown text: a timer/short window shows mm:ss; longer shows the wall-clock.
function countdown(iso: string, now: number): string {
  const ms = fireMs(iso) - now;
  if (ms <= 0) return "now";
  const s = Math.floor(ms / 1000);
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${String(sec).padStart(2, "0")}`;
  }
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

function clockOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Mutations (optimistic refetch on success).
// ---------------------------------------------------------------------------

function useAddReminder(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (body: {
      kind: ReminderKind;
      text?: string;
      fireAt: string;
      recurrence?: Recurrence;
    }) => api.addReminder(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: REMINDERS_KEY });
      toast({ variant: "success", title: "Scheduled" });
      onDone();
    },
    onError: () =>
      toast({
        variant: "error",
        title: "Couldn't schedule",
        description: "Is the bridge running?",
      }),
  });
}

function useRemoveReminder() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.removeReminder(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: REMINDERS_KEY });
      const prev = qc.getQueryData<Reminder[]>(REMINDERS_KEY);
      qc.setQueryData<Reminder[]>(REMINDERS_KEY, (old) =>
        (old ?? []).filter((r) => r.id !== id),
      );
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(REMINDERS_KEY, ctx.prev);
      toast({ variant: "error", title: "Couldn't cancel" });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: REMINDERS_KEY });
      toast({ variant: "info", title: "Cancelled" });
    },
  });
}

// ---------------------------------------------------------------------------
// Build a NAIVE-local ISO string (no timezone) for the bridge.
// ---------------------------------------------------------------------------

function naiveIso(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

// Next occurrence of a wall-clock HH:MM today, rolling to tomorrow if it passed.
function nextClock(hhmm: string): Date {
  const [h, m] = hhmm.split(":").map((x) => parseInt(x, 10));
  const d = new Date();
  d.setHours(h || 0, m || 0, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  return d;
}

// ---------------------------------------------------------------------------
// Create form — kind, text, time/duration, recurrence.
// ---------------------------------------------------------------------------

function CreateForm() {
  const [kind, setKind] = React.useState<ReminderKind>("reminder");
  const [text, setText] = React.useState("");
  const [duration, setDuration] = React.useState("10"); // minutes, for timers
  const [time, setTime] = React.useState("09:00"); // HH:MM, for alarms/reminders
  const [recurrence, setRecurrence] = React.useState<Recurrence>(null);

  const add = useAddReminder(() => {
    setText("");
  });

  const isTimer = kind === "timer";
  const canSubmit =
    !add.isPending &&
    (isTimer
      ? parseInt(duration, 10) > 0
      : /^\d{1,2}:\d{2}$/.test(time));

  const submit = () => {
    if (!canSubmit) return;
    let fireAt: string;
    if (isTimer) {
      const mins = Math.max(1, parseInt(duration, 10) || 1);
      fireAt = naiveIso(new Date(Date.now() + mins * 60_000));
    } else {
      fireAt = naiveIso(nextClock(time));
    }
    add.mutate({
      kind,
      text: text.trim(),
      fireAt,
      // Timers don't recur; only alarms/reminders carry a recurrence.
      recurrence: isTimer ? null : recurrence,
    });
  };

  return (
    <FadeIn className="mb-6">
      <Card glass className="relative overflow-hidden p-4">
        <span className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
        <div className="flex flex-wrap items-end gap-3">
          {/* Kind */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] uppercase tracking-wide text-foreground-muted">
              Kind
            </label>
            <Select
              value={kind}
              onValueChange={(v) => setKind(v as ReminderKind)}
            >
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="reminder">Reminder</SelectItem>
                <SelectItem value="alarm">Alarm</SelectItem>
                <SelectItem value="timer">Timer</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Time or duration */}
          {isTimer ? (
            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] uppercase tracking-wide text-foreground-muted">
                Minutes
              </label>
              <Input
                type="number"
                min={1}
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                className="w-24"
                aria-label="Timer minutes"
              />
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] uppercase tracking-wide text-foreground-muted">
                Time
              </label>
              <Input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="w-32"
                aria-label="Fire time"
              />
            </div>
          )}

          {/* Recurrence (not for timers) */}
          {!isTimer && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] uppercase tracking-wide text-foreground-muted">
                Repeat
              </label>
              <Select
                value={recurrence ?? "once"}
                onValueChange={(v) =>
                  setRecurrence(v === "once" ? null : (v as Recurrence))
                }
              >
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="once">Once</SelectItem>
                  <SelectItem value="daily">Every day</SelectItem>
                  <SelectItem value="weekdays">Every weekday</SelectItem>
                  <SelectItem value="weekly">Every week</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Text (the label / what to remind) */}
          <div className="flex min-w-[12rem] flex-1 flex-col gap-1.5">
            <label className="text-[10px] uppercase tracking-wide text-foreground-muted">
              {isTimer ? "Label (optional)" : "What"}
            </label>
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={
                isTimer ? "e.g. tea" : "e.g. go fetch the kids"
              }
              aria-label="Reminder text"
            />
          </div>

          <Button
            variant="gradient"
            onClick={submit}
            disabled={!canSubmit}
            className="shrink-0"
          >
            <Plus className="h-4 w-4" />
            {add.isPending ? "Adding…" : "Schedule"}
          </Button>
        </div>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// A single job row with a live countdown.
// ---------------------------------------------------------------------------

function JobRow({
  job,
  now,
  onCancel,
}: {
  job: Reminder;
  now: number;
  onCancel: () => void;
}) {
  const meta = KIND_META[job.kind];
  const Icon = meta.icon;
  const due = fireMs(job.fireAt) - now <= 0;

  return (
    <Card
      glass
      className="group relative flex items-center gap-4 overflow-hidden p-4"
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-brand-gradient opacity-80"
      />
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
        <Icon className="h-4 w-4" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-foreground">
            {job.text || meta.label}
          </p>
          {job.recurrence && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              <Repeat className="h-3 w-3" />
              {RECURRENCE_LABEL[job.recurrence] ?? job.recurrence}
            </Badge>
          )}
        </div>
        <p className="mt-0.5 text-xs text-foreground-muted">
          {job.kind === "timer"
            ? "Timer"
            : `at ${clockOf(job.fireAt)}`}
        </p>
      </div>

      <div
        className={cn(
          "tnum shrink-0 text-right font-mono text-sm",
          due ? "text-warning" : "text-foreground-secondary",
        )}
      >
        {countdown(job.fireAt, now)}
      </div>

      <button
        type="button"
        onClick={onCancel}
        aria-label="Cancel"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-danger/15 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Empty state.
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-14 text-center"
      >
        <span className="pointer-events-none absolute -top-12 left-1/2 h-44 w-44 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <AlarmClock className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          Nothing scheduled
        </h3>
        <p className="mt-1 max-w-sm text-sm text-foreground-secondary">
          Set a timer, alarm, or reminder above — or just say it:{" "}
          <span className="text-foreground">“set a timer for 10 minutes”</span>,{" "}
          <span className="text-foreground">“remind me at 9 to stretch”</span>.
        </p>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Scheduler() {
  const now = useNow(1000);
  const { data, isLoading, isError } = useQuery<Reminder[]>({
    queryKey: REMINDERS_KEY,
    queryFn: api.reminders,
    refetchInterval: 1000, // live: reflect voice-created jobs + firing
  });
  const remove = useRemoveReminder();

  const jobs = data ?? [];
  const order: ReminderKind[] = ["timer", "alarm", "reminder"];
  const byKind = order
    .map((k) => ({ kind: k, items: jobs.filter((j) => j.kind === k) }))
    .filter((g) => g.items.length > 0);

  return (
    <div>
      <PageHeader
        title="Scheduler"
        description="Timers, alarms, and reminders — all in one place, with live countdowns."
        actions={
          jobs.length > 0 ? (
            <Badge variant="accent" className="font-normal">
              {jobs.length} active
            </Badge>
          ) : null
        }
      />

      <CreateForm />

      {isError && (
        <Card
          glass
          className="mb-6 border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
        >
          Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
          <span className="font-mono">127.0.0.1:8765</span>?
        </Card>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1].map((i) => (
            <Card key={i} glass className="p-4">
              <div className="flex items-center gap-4">
                <Skeleton className="h-9 w-9 rounded-xl" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-3 w-1/4" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : jobs.length === 0 && !isError ? (
        <EmptyState />
      ) : (
        <div className="space-y-6">
          {byKind.map((group) => (
            <section key={group.kind}>
              <h2 className="mb-2 px-1 text-overline uppercase text-foreground-muted">
                {KIND_META[group.kind].plural}
              </h2>
              <Stagger className="space-y-3">
                {group.items.map((job) => (
                  <StaggerItem key={job.id}>
                    <JobRow
                      job={job}
                      now={now}
                      onCancel={() => remove.mutate(job.id)}
                    />
                  </StaggerItem>
                ))}
              </Stagger>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
