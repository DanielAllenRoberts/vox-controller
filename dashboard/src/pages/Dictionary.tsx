import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SpellCheck, Plus, Trash2, ArrowRight, Check } from "lucide-react";
import { api, type VocabEntry } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

const VOCAB_KEY = ["vocab"] as const;

// ---------------------------------------------------------------------------
// Mutations (simple — refetch on success; the list is small).
// ---------------------------------------------------------------------------

function useVocabMutation<TArgs>(
  fn: (a: TArgs) => Promise<unknown>,
  messages: { error: string; success?: string },
) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: VOCAB_KEY });
      if (messages.success) toast({ variant: "success", title: messages.success });
    },
    onError: () =>
      toast({
        variant: "error",
        title: messages.error,
        description: "Is the bridge running?",
      }),
  });
}

// ---------------------------------------------------------------------------
// Add form — "when you hear X, write Y". Adding the same X again updates Y.
// ---------------------------------------------------------------------------

function AddCorrection() {
  const [heard, setHeard] = React.useState("");
  const [write, setWrite] = React.useState("");
  const add = useVocabMutation(
    ({ heard, write }: { heard: string; write: string }) =>
      api.addVocab(heard, write),
    { error: "Couldn't add correction", success: "Correction saved" },
  );

  const canSubmit = heard.trim().length > 0 && !add.isPending;
  const submit = () => {
    if (!canSubmit) return;
    add.mutate({ heard: heard.trim(), write: write.trim() });
    setHeard("");
    setWrite("");
  };

  return (
    <FadeIn className="mb-6">
      <Card glass className="relative overflow-hidden p-3">
        <span className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex min-w-[10rem] flex-1 flex-col gap-1.5">
            <label className="text-[10px] uppercase tracking-wide text-foreground-muted">
              When you hear
            </label>
            <Input
              value={heard}
              onChange={(e) => setHeard(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="clawed"
              aria-label="Heard phrase"
            />
          </div>
          <ArrowRight className="mb-2.5 h-4 w-4 shrink-0 text-foreground-muted" />
          <div className="flex min-w-[10rem] flex-1 flex-col gap-1.5">
            <label className="text-[10px] uppercase tracking-wide text-foreground-muted">
              Write instead
            </label>
            <Input
              value={write}
              onChange={(e) => setWrite(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="Claude"
              aria-label="Replacement"
            />
          </div>
          <Button
            variant="gradient"
            onClick={submit}
            disabled={!canSubmit}
            className="shrink-0"
          >
            <Plus className="h-4 w-4" />
            {add.isPending ? "Saving…" : "Add"}
          </Button>
        </div>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// A single correction row.
// ---------------------------------------------------------------------------

function CorrectionRow({
  entry,
  onToggle,
  onDelete,
}: {
  entry: VocabEntry;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <Card
      glass
      className={cn(
        "group relative overflow-hidden p-4 transition-all duration-200",
        entry.enabled
          ? "ring-1 ring-transparent hover:ring-border-strong"
          : "opacity-65 hover:opacity-90",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-y-0 left-0 w-0.5 transition-opacity",
          entry.enabled ? "bg-brand-gradient opacity-80" : "opacity-0",
        )}
      />
      <div className="flex items-center gap-4">
        <div className="flex shrink-0 flex-col items-center gap-1.5">
          <Switch
            checked={entry.enabled}
            onCheckedChange={onToggle}
            aria-label={entry.enabled ? "Disable correction" : "Enable correction"}
          />
          <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-muted">
            {entry.enabled ? "On" : "Off"}
          </span>
        </div>

        <div className="flex min-w-0 flex-1 items-center gap-3 text-sm">
          <span className="truncate rounded-md bg-muted/60 px-2 py-1 font-mono text-foreground-secondary">
            {entry.heard}
          </span>
          <ArrowRight className="h-4 w-4 shrink-0 text-accent" />
          <span className="truncate rounded-md bg-accent/10 px-2 py-1 font-mono font-medium text-foreground">
            {entry.write || <span className="italic text-foreground-muted">(deleted)</span>}
          </span>
        </div>

        <button
          type="button"
          onClick={onDelete}
          aria-label="Delete correction"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-danger/15 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </Card>
  );
}

function EmptyState() {
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-14 text-center"
      >
        <span className="pointer-events-none absolute -top-12 left-1/2 h-44 w-44 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <SpellCheck className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          No corrections yet
        </h3>
        <p className="mt-1 max-w-md text-sm text-foreground-secondary">
          Teach Vox a word: when it keeps mishearing something — a name, jargon, a
          homophone like <span className="text-foreground">clawed → Claude</span> —
          add it above. It&apos;s applied to everything Vox transcribes.
        </p>
      </Card>
    </FadeIn>
  );
}

export function Dictionary() {
  const { data, isLoading, isError } = useQuery<VocabEntry[]>({
    queryKey: VOCAB_KEY,
    queryFn: api.vocab,
  });

  const toggle = useVocabMutation(
    ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.updateVocab(id, { enabled }),
    { error: "Couldn't update correction" },
  );
  const remove = useVocabMutation((id: string) => api.removeVocab(id), {
    error: "Couldn't delete correction",
    success: "Correction removed",
  });

  const entries = data ?? [];
  const enabledCount = entries.filter((e) => e.enabled).length;

  return (
    <div>
      <PageHeader
        title="Dictionary"
        description="Teach Vox words it keeps mishearing — corrections applied to every transcript."
        actions={
          entries.length > 0 ? (
            <Badge variant="accent" className="font-normal">
              <Check className="h-3 w-3" />
              {enabledCount} active
            </Badge>
          ) : null
        }
      />

      <FadeIn className="mb-6">
        <Card glass className="relative overflow-hidden border-accent/20 px-5 py-4">
          <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
          <p className="max-w-3xl text-sm leading-relaxed text-foreground-secondary">
            Whisper can&apos;t be taught new words, so these are{" "}
            <span className="text-foreground">text replacements</span> applied
            right after it transcribes — whole-word and case-insensitive. Great for
            proper nouns and homophones. Add the same word again to change its
            replacement; toggle one <span className="text-accent">off</span> to
            pause it.
          </p>
        </Card>
      </FadeIn>

      <AddCorrection />

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
                <Skeleton className="h-5 w-9 rounded-full" />
                <Skeleton className="h-8 flex-1" />
              </div>
            </Card>
          ))}
        </div>
      ) : entries.length === 0 && !isError ? (
        <EmptyState />
      ) : (
        <Stagger className="space-y-3">
          {entries.map((entry) => (
            <StaggerItem key={entry.id}>
              <CorrectionRow
                entry={entry}
                onToggle={(enabled) => toggle.mutate({ id: entry.id, enabled })}
                onDelete={() => remove.mutate(entry.id)}
              />
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  );
}
