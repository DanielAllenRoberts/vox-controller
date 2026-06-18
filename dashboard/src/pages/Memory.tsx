import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Plus,
  Search,
  Trash2,
  Tag,
  Sparkles,
  X,
  Target,
} from "lucide-react";
import { api, type Memory as MemoryItem } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
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
import { relativeTime } from "@/lib/utils";

// Base list (no query) is cached under this key; scored search results live
// under a per-term key so typing doesn't blow away the recall list.
const MEMORY_KEY = ["memory"] as const;
const memorySearchKey = (q: string) => ["memory", "search", q] as const;

const LIST_LIMIT = 100;

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

// ---------------------------------------------------------------------------
// Mutations.
// ---------------------------------------------------------------------------

function useAddMemory(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({ text, tags }: { text: string; tags: string[] }) =>
      api.addMemory(text, tags.length ? tags : undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MEMORY_KEY });
      toast({
        variant: "success",
        title: "Memory saved",
        description: "Vox can recall this in future conversations.",
      });
      onDone();
    },
    onError: () => {
      toast({
        variant: "error",
        title: "Couldn't save memory",
        description: "Is the bridge running?",
      });
    },
  });
}

function useRemoveMemory(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (id: string) => api.removeMemory(id),
    onSuccess: () => {
      // Both the recall list and any open search results may hold this id.
      qc.invalidateQueries({ queryKey: MEMORY_KEY });
      toast({ variant: "info", title: "Memory forgotten" });
      onDone();
    },
    onError: () => {
      toast({
        variant: "error",
        title: "Couldn't delete memory",
        description: "Is the bridge running?",
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Memory card.
// ---------------------------------------------------------------------------

function MemoryCard({
  memory,
  now,
  onDelete,
}: {
  memory: MemoryItem;
  now: number;
  onDelete: () => void;
}) {
  // score is only present on search results; surface it as a relevance chip.
  const score = memory.score;
  const hasScore = typeof score === "number";

  return (
    <Card
      glass
      className="group relative flex h-full flex-col overflow-hidden p-5 ring-1 ring-transparent transition-all duration-200 hover:-translate-y-0.5 hover:ring-border-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 flex-1 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
          {memory.text}
        </p>
        <button
          type="button"
          aria-label="Delete memory"
          onClick={onDelete}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-danger/15 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {memory.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {memory.tags.map((t) => (
            <Badge key={t} variant="outline" className="font-normal">
              <Tag className="h-3 w-3 text-accent" />
              {t}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-4 flex items-center justify-between gap-2 text-[11px] text-foreground-muted">
        <span title={new Date(memory.ts).toLocaleString()}>
          {relativeTime(memory.ts, now)}
        </span>
        {hasScore && (
          <span className="inline-flex items-center gap-1 rounded-full bg-accent/15 px-2 py-0.5 font-medium text-accent">
            <Target className="h-3 w-3" />
            {Math.round(score * 100)}% match
          </span>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Composer — add a new memory (text + optional tags).
// ---------------------------------------------------------------------------

function Composer() {
  const [text, setText] = React.useState("");
  const [tagsRaw, setTagsRaw] = React.useState("");

  const add = useAddMemory(() => {
    setText("");
    setTagsRaw("");
  });

  const canSubmit = text.trim().length > 0 && !add.isPending;
  const tags = parseTags(tagsRaw);

  const submit = () => {
    if (!canSubmit) return;
    add.mutate({ text: text.trim(), tags });
  };

  return (
    <FadeIn>
      <Card glass className="relative overflow-hidden p-5">
        <span className="pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full bg-brand-gradient opacity-10 blur-3xl" />

        <div className="mb-3 flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <Plus className="h-4 w-4" />
          </span>
          <h2 className="text-sm font-semibold text-foreground">
            Teach Vox something
          </h2>
        </div>

        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // Cmd/Ctrl+Enter saves without reaching for the mouse.
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="e.g. I prefer concise answers. My standup is at 9:30am. Call me Dan."
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
            {add.isPending ? "Saving…" : "Remember this"}
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
// Search bar.
// ---------------------------------------------------------------------------

function SearchBar({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search memories — Vox scores them by relevance…"
        className="h-11 rounded-xl pl-10 pr-10 text-sm"
        aria-label="Search memories"
      />
      {value && (
        <button
          type="button"
          aria-label="Clear search"
          onClick={() => onChange("")}
          className="absolute right-3 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-foreground-muted transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Delete confirm.
// ---------------------------------------------------------------------------

function DeleteDialog({
  memory,
  onOpenChange,
}: {
  memory: MemoryItem | null;
  onOpenChange: (open: boolean) => void;
}) {
  const remove = useRemoveMemory(() => onOpenChange(false));

  return (
    <Dialog open={memory !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Forget this memory?</DialogTitle>
          <DialogDescription>
            {memory && (
              <>
                <span className="text-foreground">
                  “{memory.text.length > 80
                    ? `${memory.text.slice(0, 80).trimEnd()}…`
                    : memory.text}
                  ”
                </span>{" "}
                will be permanently removed. Vox won&apos;t recall it again.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={remove.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => memory && remove.mutate(memory.id)}
            disabled={remove.isPending}
          >
            <Trash2 className="h-4 w-4" />
            {remove.isPending ? "Forgetting…" : "Forget it"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Empty / error states.
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-14 text-center"
      >
        <span className="pointer-events-none absolute -top-10 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <Brain className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          Vox has nothing memorised yet
        </h3>
        <p className="mt-1 max-w-md text-sm text-foreground-secondary">
          Add facts, preferences, or context above — your name, how you like
          answers, recurring details. Vox pulls the most relevant ones into
          conversations automatically.
        </p>
      </Card>
    </FadeIn>
  );
}

function NoResults({ query }: { query: string }) {
  return (
    <FadeIn>
      <Card
        glass
        className="flex flex-col items-center justify-center px-6 py-12 text-center"
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted text-foreground-muted">
          <Search className="h-5 w-5" />
        </span>
        <h3 className="mt-4 text-sm font-semibold text-foreground">
          No memories match “{query}”
        </h3>
        <p className="mt-1 max-w-sm text-sm text-foreground-secondary">
          Try different words, or clear the search to see everything Vox knows.
        </p>
      </Card>
    </FadeIn>
  );
}

function ErrorState() {
  return (
    <Card
      glass
      className="border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
    >
      Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
      <span className="font-mono">127.0.0.1:8765</span>? Memories will load once
      it&apos;s back.
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Skeleton + grid.
// ---------------------------------------------------------------------------

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

const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3";

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Memory() {
  const [rawQuery, setRawQuery] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [toDelete, setToDelete] = React.useState<MemoryItem | null>(null);
  const now = useNow(15_000);

  // Debounce the search term so each keystroke doesn't hit the bridge.
  React.useEffect(() => {
    const id = setTimeout(() => setDebounced(rawQuery.trim()), 250);
    return () => clearTimeout(id);
  }, [rawQuery]);

  const searching = debounced.length > 0;

  // Full recall list (always loaded so empty-state + counts are accurate).
  const list = useQuery({
    queryKey: MEMORY_KEY,
    queryFn: () => api.memory("", LIST_LIMIT),
  });

  // Scored search results, only when a term is present.
  const results = useQuery({
    queryKey: memorySearchKey(debounced),
    queryFn: () => api.memory(debounced, LIST_LIMIT),
    enabled: searching,
  });

  const active = searching ? results : list;
  const items = active.data ?? [];
  const isLoading = active.isLoading;
  const isError = list.isError || (searching && results.isError);

  return (
    <div>
      <PageHeader
        title="Memory"
        description="Long-term memory Vox can recall mid-conversation. Add facts and preferences, search what it knows, and prune anything stale."
        actions={
          list.data ? (
            <Badge variant="accent" className="font-normal">
              <Brain className="h-3 w-3" />
              {list.data.length} {list.data.length === 1 ? "memory" : "memories"}
            </Badge>
          ) : undefined
        }
      />

      <div className="space-y-6">
        <Composer />

        <SearchBar value={rawQuery} onChange={setRawQuery} />

        {isError && <ErrorState />}

        {isLoading ? (
          <div className={GRID}>
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        ) : items.length > 0 ? (
          <>
            {searching && (
              <p className="text-xs text-foreground-muted">
                {items.length} {items.length === 1 ? "match" : "matches"} for “
                {debounced}”, ranked by relevance.
              </p>
            )}
            <Stagger className={GRID}>
              {items.map((m) => (
                <StaggerItem key={m.id} className="h-full">
                  <MemoryCard
                    memory={m}
                    now={now}
                    onDelete={() => setToDelete(m)}
                  />
                </StaggerItem>
              ))}
            </Stagger>
          </>
        ) : isError ? null : searching ? (
          <NoResults query={debounced} />
        ) : (
          <EmptyState />
        )}
      </div>

      <DeleteDialog
        memory={toDelete}
        onOpenChange={(o) => {
          if (!o) setToDelete(null);
        }}
      />
    </div>
  );
}
