import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Plus,
  Trash2,
  Tag,
  Sparkles,
  X,
  Check,
  Pencil,
  Star,
  CalendarDays,
  FolderOpen,
  Wand2,
  ChevronLeft,
  ChevronRight,
  Info,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/useToast";
import { useNow } from "@/hooks/useNow";
import { relativeTime, cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Local tiered-memory client.
//
// The v1 tiered endpoints (/api/memory/core, /daily, /dates, /reveal) and the
// memory_autocapture setting are added by parallel backend/shell agents; this
// page is NOT allowed to edit lib/api.ts, so it talks to them with a thin
// fetch helper here. Everything degrades gracefully: a missing route (404 /
// network error) surfaces as an error/empty state and never throws past the
// query boundary, so the page stays usable as the backend lands.
// ---------------------------------------------------------------------------

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

type Tier = "core" | "daily";

// Mirrors the contract Memory shape, plus the new `tier` field (MEMORY_DESIGN).
interface MemoryEntry {
  id: string;
  ts: string;
  text: string;
  tags: string[];
  tier?: Tier;
  score?: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.error ?? detail;
    } catch {
      /* non-JSON body */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const memoryApi = {
  // Tiered reads. core() returns the always-injected curated list; daily(date)
  // returns one day's log (omit date → today, resolved server-side).
  core: () => req<MemoryEntry[]>("/memory/core"),
  daily: (date?: string) =>
    req<MemoryEntry[]>(
      `/memory/daily${date ? `?date=${encodeURIComponent(date)}` : ""}`,
    ),
  dates: () => req<string[]>("/memory/dates"),

  // Writes carry the tier so the backend files it in core.md vs daily/<date>.md.
  add: (text: string, tier: Tier, tags?: string[], date?: string) =>
    req<MemoryEntry>("/memory", {
      method: "POST",
      body: JSON.stringify({ text, tier, tags, date }),
    }),
  update: (id: string, patch: { text?: string; tags?: string[] }) =>
    req<MemoryEntry>(`/memory/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  remove: (id: string) =>
    req<{ ok: boolean }>(`/memory/${id}`, { method: "DELETE" }),

  // Opens data/memory/ in Finder; the response carries the on-disk path so we
  // can show it for transparency even before the reveal runs.
  reveal: () => req<{ ok?: boolean; path?: string }>("/memory/reveal", {
    method: "POST",
  }),

  // memory_autocapture lives in the generic settings store.
  getSetting: async (key: string): Promise<boolean | null> => {
    const all = await req<
      { key: string; value: string | boolean }[]
    >("/settings");
    const s = all.find((x) => x.key === key);
    if (!s) return null;
    return typeof s.value === "boolean" ? s.value : s.value === "true";
  },
  setSetting: (key: string, value: boolean) =>
    req<{ ok: boolean; value: string | boolean }>("/settings", {
      method: "POST",
      body: JSON.stringify({ key, value }),
    }),
};

const CORE_KEY = ["memory", "core"] as const;
const DATES_KEY = ["memory", "dates"] as const;
const dailyKey = (date: string) => ["memory", "daily", date] as const;
const AUTOCAPTURE_KEY = ["memory", "autocapture"] as const;
const PATH_KEY = ["memory", "path"] as const;

const AUTOCAPTURE_SETTING = "memory_autocapture";

// Parse the composer's free-text tag field ("work, ideas , vox") into a clean,
// de-duped list. Empty fragments and pure whitespace are dropped.
function parseTags(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(",")) {
    const t = part.trim();
    if (t && !seen.has(t.toLowerCase())) {
      seen.add(t.toLowerCase());
      out.push(t);
    }
  }
  return out;
}

// Human label for a daily-log date key ("2026-06-18" → "Wed, Jun 18").
function formatDateLabel(key: string, todayKeyStr: string): string {
  if (key === todayKeyStr) return "Today";
  const d = new Date(`${key}T00:00:00`);
  if (Number.isNaN(d.getTime())) return key;
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function localDateKey(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Mutations (shared by both tiers; invalidate the right cache key on success).
// ---------------------------------------------------------------------------

function useAddEntry(
  tier: Tier,
  invalidate: readonly unknown[],
  onDone: () => void,
  date?: string,
) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ text, tags }: { text: string; tags: string[] }) =>
      memoryApi.add(text, tier, tags.length ? tags : undefined, date),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: invalidate });
      if (tier === "daily") qc.invalidateQueries({ queryKey: DATES_KEY });
      toast({
        variant: "success",
        title: tier === "core" ? "Core memory saved" : "Logged for the day",
        description:
          tier === "core"
            ? "Vox always keeps this in mind."
            : "Recalled when it's relevant.",
      });
      onDone();
    },
    onError: () =>
      toast({
        variant: "error",
        title: "Couldn't save",
        description: "Is the bridge running?",
      }),
  });
}

function useUpdateEntry(invalidate: readonly unknown[]) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      memoryApi.update(id, { text }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: invalidate });
    },
    onError: () =>
      toast({
        variant: "error",
        title: "Couldn't save edit",
        description: "Is the bridge running?",
      }),
  });
}

function useRemoveEntry(
  invalidate: readonly unknown[],
  fromDaily: boolean,
  onDone: () => void,
) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => memoryApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: invalidate });
      if (fromDaily) qc.invalidateQueries({ queryKey: DATES_KEY });
      toast({ variant: "info", title: "Memory forgotten" });
      onDone();
    },
    onError: () =>
      toast({
        variant: "error",
        title: "Couldn't delete",
        description: "Is the bridge running?",
      }),
  });
}

// ---------------------------------------------------------------------------
// Entry card — inline-editable text, tags, timestamp, delete.
// ---------------------------------------------------------------------------

function EntryCard({
  entry,
  now,
  accent,
  onSaveText,
  onDelete,
}: {
  entry: MemoryEntry;
  now: number;
  accent: boolean;
  onSaveText: (text: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(entry.text);
  const ref = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (!editing) setDraft(entry.text);
  }, [entry.text, editing]);

  React.useEffect(() => {
    if (editing && ref.current) {
      const el = ref.current;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
  }, [editing]);

  const commit = () => {
    const next = draft.trim();
    if (next && next !== entry.text) onSaveText(next);
    setEditing(false);
  };
  const cancel = () => {
    setDraft(entry.text);
    setEditing(false);
  };

  return (
    <Card
      glass
      className="group relative flex h-full flex-col overflow-hidden p-5 ring-1 ring-transparent transition-all duration-200 hover:-translate-y-0.5 hover:ring-border-strong"
    >
      {/* Accent hairline on core entries to signal "always injected". */}
      {accent && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-brand-gradient opacity-80"
        />
      )}

      {editing ? (
        <div className="space-y-2">
          <Textarea
            ref={ref}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                commit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancel();
              }
            }}
            className="min-h-[72px] resize-y leading-relaxed"
            aria-label="Edit memory text"
          />
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-[11px] text-foreground-muted">
              ⌘↵ to save · Esc to cancel
            </span>
            <Button variant="ghost" size="sm" onClick={cancel}>
              <X className="h-3.5 w-3.5" />
              Cancel
            </Button>
            <Button
              variant="gradient"
              size="sm"
              onClick={commit}
              disabled={draft.trim().length === 0}
            >
              <Check className="h-3.5 w-3.5" />
              Save
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-start justify-between gap-3">
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="min-w-0 flex-1 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              aria-label="Edit memory"
            >
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {entry.text}
              </p>
            </button>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                aria-label="Edit memory"
                onClick={() => setEditing(true)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-muted hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label="Delete memory"
                onClick={onDelete}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-danger/15 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {entry.tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {entry.tags.map((t) => (
                <Badge key={t} variant="outline" className="font-normal">
                  <Tag className="h-3 w-3 text-accent" />
                  {t}
                </Badge>
              ))}
            </div>
          )}

          <div className="mt-4 flex items-center justify-between gap-2 text-[11px] text-foreground-muted">
            <span title={new Date(entry.ts).toLocaleString()}>
              {relativeTime(entry.ts, now)}
            </span>
          </div>
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Composer — add an entry to the active tier.
// ---------------------------------------------------------------------------

function Composer({
  tier,
  invalidate,
  date,
}: {
  tier: Tier;
  invalidate: readonly unknown[];
  date?: string;
}) {
  const [text, setText] = React.useState("");
  const [tagsRaw, setTagsRaw] = React.useState("");
  const add = useAddEntry(
    tier,
    invalidate,
    () => {
      setText("");
      setTagsRaw("");
    },
    date,
  );

  const tags = parseTags(tagsRaw);
  const canSubmit = text.trim().length > 0 && !add.isPending;
  const submit = () => {
    if (!canSubmit) return;
    add.mutate({ text: text.trim(), tags });
  };

  const isCore = tier === "core";

  return (
    <FadeIn>
      <Card glass className="relative overflow-hidden p-5">
        <span className="pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full bg-brand-gradient opacity-10 blur-3xl" />

        <div className="mb-3 flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent/15 text-accent">
            {isCore ? <Star className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          </span>
          <h2 className="text-sm font-semibold text-foreground">
            {isCore ? "Add a core memory" : "Add to today's log"}
          </h2>
        </div>

        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={
            isCore
              ? "Durable facts — e.g. Call me Dan. I prefer concise answers. I'm building Vox."
              : "Something from today — e.g. Switched to the Batman persona for a demo."
          }
          className="min-h-[88px] resize-y leading-relaxed"
          aria-label="Memory text"
        />

        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Tag className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-foreground-muted" />
            <Input
              value={tagsRaw}
              onChange={(e) => setTagsRaw(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder="Optional tags, comma-separated"
              className="pl-9"
              aria-label="Tags"
            />
          </div>
          <Button
            variant="gradient"
            onClick={submit}
            disabled={!canSubmit}
            className="sm:w-auto"
          >
            <Sparkles className="h-4 w-4" />
            {add.isPending ? "Saving…" : isCore ? "Remember always" : "Log it"}
          </Button>
        </div>

        {tags.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-foreground-muted">Tags:</span>
            {tags.map((t) => (
              <Badge key={t} variant="accent" className="font-normal">
                {t}
              </Badge>
            ))}
          </div>
        )}
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Auto-capture toggle + transparency strip (folder path, open location).
// ---------------------------------------------------------------------------

function AutoCaptureCard() {
  const qc = useQueryClient();
  const { toast } = useToast();

  const setting = useQuery({
    queryKey: AUTOCAPTURE_KEY,
    queryFn: () => memoryApi.getSetting(AUTOCAPTURE_SETTING),
  });

  // The reveal response also carries the on-disk path; we fetch it once (without
  // opening Finder) by reading any cached path, and otherwise show a sensible
  // default until the first reveal populates it.
  const pathQ = useQuery({
    queryKey: PATH_KEY,
    queryFn: async () => {
      try {
        const r = await memoryApi.reveal();
        return r.path ?? null;
      } catch {
        return null;
      }
    },
    enabled: false, // only via the explicit "open location" action
  });

  const toggle = useMutation({
    mutationFn: (value: boolean) =>
      memoryApi.setSetting(AUTOCAPTURE_SETTING, value),
    onMutate: async (value) => {
      await qc.cancelQueries({ queryKey: AUTOCAPTURE_KEY });
      const prev = qc.getQueryData<boolean | null>(AUTOCAPTURE_KEY);
      qc.setQueryData(AUTOCAPTURE_KEY, value);
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx) qc.setQueryData(AUTOCAPTURE_KEY, ctx.prev);
      toast({
        variant: "error",
        title: "Couldn't change auto-capture",
        description: "Reverted — is the bridge running?",
      });
    },
    onSuccess: (res) => {
      const v =
        typeof res.value === "boolean" ? res.value : res.value === "true";
      qc.setQueryData(AUTOCAPTURE_KEY, v);
    },
  });

  const reveal = useMutation({
    mutationFn: () => memoryApi.reveal(),
    onSuccess: (r) => {
      if (r.path) qc.setQueryData(PATH_KEY, r.path);
      toast({ variant: "info", title: "Opened in Finder" });
    },
    onError: () =>
      toast({
        variant: "error",
        title: "Couldn't open the folder",
        description: "Is the bridge running on macOS?",
      }),
  });

  const enabled = setting.data === true;
  // Prefer a path discovered via reveal; fall back to the canonical layout.
  const folderPath =
    (pathQ.data ?? (qc.getQueryData<string | null>(PATH_KEY) as string | null)) ||
    "data/memory/";

  return (
    <FadeIn className="mb-6">
      <Card glass className="relative overflow-hidden p-5">
        <span className="pointer-events-none absolute -right-12 -top-12 h-36 w-36 rounded-full bg-brand-gradient opacity-15 blur-3xl" />

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
              <Wand2 className="h-5 w-5" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground">
                  Auto-capture
                </h2>
                {setting.data === null && (
                  <Badge variant="outline" className="font-normal">
                    unavailable
                  </Badge>
                )}
              </div>
              <p className="mt-1 max-w-xl text-sm leading-relaxed text-foreground-secondary">
                Let Vox quietly remember important facts and daily context as you
                talk — sorting durable facts into{" "}
                <span className="text-foreground">Core</span> and one-off notes
                into <span className="text-foreground">Daily</span>. Turn it off
                to capture only what you add by hand.
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2 sm:flex-col sm:items-end">
            <Switch
              checked={enabled}
              disabled={setting.isLoading || setting.data === null || toggle.isPending}
              onCheckedChange={(v) => toggle.mutate(v)}
              aria-label="Toggle auto-capture"
            />
            <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-muted">
              {setting.isLoading ? "…" : enabled ? "On" : "Off"}
            </span>
          </div>
        </div>

        {/* Transparency strip: exactly where memories live on disk. */}
        <div className="mt-4 flex flex-col gap-3 border-t border-border/60 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-2 text-[11px] text-foreground-muted">
            <Info className="h-3.5 w-3.5 shrink-0" />
            <span className="shrink-0">Stored as plain Markdown in</span>
            <code className="truncate rounded-md bg-muted px-1.5 py-0.5 font-mono text-foreground-secondary">
              {folderPath}
            </code>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => reveal.mutate()}
            disabled={reveal.isPending}
            className="shrink-0"
          >
            <FolderOpen className="h-4 w-4" />
            {reveal.isPending ? "Opening…" : "Open file location"}
          </Button>
        </div>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Date picker for the Daily tab.
// ---------------------------------------------------------------------------

function DatePicker({
  dates,
  selected,
  onSelect,
  todayKeyStr,
}: {
  dates: string[];
  selected: string;
  onSelect: (d: string) => void;
  todayKeyStr: string;
}) {
  // dates come newest-first from the backend; guard anyway.
  const sorted = React.useMemo(
    () => [...dates].sort((a, b) => (a < b ? 1 : -1)),
    [dates],
  );
  const idx = sorted.indexOf(selected);

  const go = (delta: number) => {
    const next = idx + delta;
    if (next >= 0 && next < sorted.length) onSelect(sorted[next]);
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          aria-label="Newer day"
          disabled={idx <= 0}
          onClick={() => go(-1)}
          className="h-9 w-9"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Older day"
          disabled={idx < 0 || idx >= sorted.length - 1}
          onClick={() => go(1)}
          className="h-9 w-9"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {sorted.slice(0, 14).map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => onSelect(d)}
            className={cn(
              "rounded-lg px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
              d === selected
                ? "bg-accent/15 text-accent ring-1 ring-accent/30"
                : "text-foreground-secondary hover:bg-muted hover:text-foreground",
            )}
          >
            {formatDateLabel(d, todayKeyStr)}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared states.
// ---------------------------------------------------------------------------

const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3";

function CardSkeleton() {
  return (
    <Card glass className="p-5">
      <Skeleton className="h-4 w-full" />
      <Skeleton className="mt-2 h-4 w-4/5" />
      <div className="mt-4 flex gap-1.5">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-5 w-12 rounded-full" />
      </div>
      <Skeleton className="mt-4 h-3 w-20" />
    </Card>
  );
}

function GridSkeleton() {
  return (
    <div className={GRID}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  );
}

function ErrorState({ what }: { what: string }) {
  return (
    <Card
      glass
      className="border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
    >
      Can&apos;t reach the Vox bridge to load {what}. Is the daemon running on{" "}
      <span className="font-mono">127.0.0.1:8765</span>? It&apos;ll appear once
      the bridge is back.
    </Card>
  );
}

function EmptyState({
  icon: Icon,
  title,
  body,
}: {
  icon: typeof Brain;
  title: string;
  body: string;
}) {
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-14 text-center"
      >
        <span className="pointer-events-none absolute -top-10 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <Icon className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">{title}</h3>
        <p className="mt-1 max-w-md text-sm text-foreground-secondary">{body}</p>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Delete confirm.
// ---------------------------------------------------------------------------

function DeleteDialog({
  entry,
  onConfirm,
  onOpenChange,
  pending,
}: {
  entry: MemoryEntry | null;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
  pending: boolean;
}) {
  return (
    <Dialog open={entry !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Forget this memory?</DialogTitle>
          <DialogDescription>
            {entry && (
              <>
                <span className="text-foreground">
                  “{entry.text.length > 80
                    ? `${entry.text.slice(0, 80).trimEnd()}…`
                    : entry.text}
                  ”
                </span>{" "}
                will be permanently removed from disk. Vox won&apos;t recall it
                again.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={pending}>
            <Trash2 className="h-4 w-4" />
            {pending ? "Forgetting…" : "Forget it"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Core tab.
// ---------------------------------------------------------------------------

function CoreSection({
  now,
  onDelete,
}: {
  now: number;
  onDelete: (e: MemoryEntry) => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: CORE_KEY,
    queryFn: memoryApi.core,
  });
  const update = useUpdateEntry(CORE_KEY);
  const items = data ?? [];

  return (
    <div className="space-y-6">
      <Composer tier="core" invalidate={CORE_KEY} />

      {isError && <ErrorState what="core memories" />}

      {isLoading ? (
        <GridSkeleton />
      ) : items.length > 0 ? (
        <Stagger className={GRID}>
          {items.map((m) => (
            <StaggerItem key={m.id} className="h-full">
              <EntryCard
                entry={m}
                now={now}
                accent
                onSaveText={(text) => update.mutate({ id: m.id, text })}
                onDelete={() => onDelete(m)}
              />
            </StaggerItem>
          ))}
        </Stagger>
      ) : isError ? null : (
        <EmptyState
          icon={Star}
          title="No core memories yet"
          body="Core memories are the durable facts Vox always keeps in mind — your name, standing preferences, the projects you're working on. Add a few above, or let auto-capture build them."
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Daily tab.
// ---------------------------------------------------------------------------

function DailySection({
  now,
  todayKeyStr,
  onDelete,
}: {
  now: number;
  todayKeyStr: string;
  onDelete: (e: MemoryEntry) => void;
}) {
  const [selected, setSelected] = React.useState(todayKeyStr);

  const datesQ = useQuery({ queryKey: DATES_KEY, queryFn: memoryApi.dates });

  // Always offer "today" even if the backend hasn't created the file yet.
  const dates = React.useMemo(() => {
    const set = new Set(datesQ.data ?? []);
    set.add(todayKeyStr);
    return [...set];
  }, [datesQ.data, todayKeyStr]);

  const dayKey = dailyKey(selected);
  const dayQ = useQuery({
    queryKey: dayKey,
    queryFn: () => memoryApi.daily(selected),
  });
  const update = useUpdateEntry(dayKey);
  const items = dayQ.data ?? [];

  return (
    <div className="space-y-6">
      <Composer tier="daily" invalidate={dayKey} date={selected} />

      <Card glass className="p-4">
        <DatePicker
          dates={dates}
          selected={selected}
          onSelect={setSelected}
          todayKeyStr={todayKeyStr}
        />
      </Card>

      {(datesQ.isError || dayQ.isError) && <ErrorState what="daily logs" />}

      {dayQ.isLoading ? (
        <GridSkeleton />
      ) : items.length > 0 ? (
        <Stagger className={GRID}>
          {items.map((m) => (
            <StaggerItem key={m.id} className="h-full">
              <EntryCard
                entry={m}
                now={now}
                accent={false}
                onSaveText={(text) => update.mutate({ id: m.id, text })}
                onDelete={() => onDelete(m)}
              />
            </StaggerItem>
          ))}
        </Stagger>
      ) : dayQ.isError ? null : (
        <EmptyState
          icon={CalendarDays}
          title={
            selected === todayKeyStr
              ? "Nothing logged today yet"
              : `Nothing logged on ${formatDateLabel(selected, todayKeyStr)}`
          }
          body="Daily logs capture the transient stuff — what you did, one-off requests, notes from a session. Vox recalls the relevant ones by keyword. Add one above or let auto-capture fill the day in."
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Memory() {
  const now = useNow(15_000);
  const todayKeyStr = React.useMemo(() => localDateKey(), []);
  const [toDelete, setToDelete] = React.useState<MemoryEntry | null>(null);

  // The delete mutation needs to invalidate the tier the entry came from.
  const removeCore = useRemoveEntry(CORE_KEY, false, () => setToDelete(null));
  const removeDaily = useRemoveEntry(
    toDelete ? dailyKey(toDelete.ts.slice(0, 10)) : DATES_KEY,
    true,
    () => setToDelete(null),
  );

  const coreCount = useQuery({
    queryKey: CORE_KEY,
    queryFn: memoryApi.core,
  }).data?.length;

  const confirmDelete = () => {
    if (!toDelete) return;
    if (toDelete.tier === "core") removeCore.mutate(toDelete.id);
    else removeDaily.mutate(toDelete.id);
  };
  const deletePending = removeCore.isPending || removeDaily.isPending;

  return (
    <div>
      <PageHeader
        title="Memory"
        description="Transparent, human-readable memory Vox recalls mid-conversation. Curate the always-on Core facts, browse Daily logs by date, and decide how much Vox captures on its own."
        actions={
          typeof coreCount === "number" ? (
            <Badge variant="accent" className="font-normal">
              <Star className="h-3 w-3" />
              {coreCount} core
            </Badge>
          ) : undefined
        }
      />

      <AutoCaptureCard />

      <Tabs defaultValue="core">
        <TabsList>
          <TabsTrigger value="core">
            <Star className="mr-1.5 h-3.5 w-3.5" />
            Core
          </TabsTrigger>
          <TabsTrigger value="daily">
            <CalendarDays className="mr-1.5 h-3.5 w-3.5" />
            Daily logs
          </TabsTrigger>
        </TabsList>

        <TabsContent value="core">
          <CoreSection
            now={now}
            onDelete={(e) => setToDelete({ ...e, tier: "core" })}
          />
        </TabsContent>

        <TabsContent value="daily">
          <DailySection
            now={now}
            todayKeyStr={todayKeyStr}
            onDelete={(e) => setToDelete({ ...e, tier: "daily" })}
          />
        </TabsContent>
      </Tabs>

      <DeleteDialog
        entry={toDelete}
        pending={deletePending}
        onConfirm={confirmDelete}
        onOpenChange={(o) => {
          if (!o && !deletePending) setToDelete(null);
        }}
      />
    </div>
  );
}
