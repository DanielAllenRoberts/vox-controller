import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ScrollText,
  Plus,
  Trash2,
  Check,
  X,
  Pencil,
  Sparkles,
} from "lucide-react";
import { api, type Rule } from "@/lib/api";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

const RULES_KEY = ["rules"] as const;

// A negative temp id stands in for an optimistically-added rule until the
// server returns the real one. Keeps React keys stable and lets us detect
// the placeholder so we don't try to mutate a row that doesn't exist yet.
let _tempSeq = -1;
function tempId(): string {
  return `temp:${_tempSeq--}`;
}
function isTemp(id: string): boolean {
  return id.startsWith("temp:");
}

// ---------------------------------------------------------------------------
// Add a rule (optimistic — appears immediately, reconciled on success).
// ---------------------------------------------------------------------------

function useAddRule(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (text: string) => api.addRule(text),
    onMutate: async (text) => {
      await qc.cancelQueries({ queryKey: RULES_KEY });
      const prev = qc.getQueryData<Rule[]>(RULES_KEY);
      const optimistic: Rule = { id: tempId(), text, enabled: true };
      qc.setQueryData<Rule[]>(RULES_KEY, (old) => [...(old ?? []), optimistic]);
      return { prev, optimisticId: optimistic.id };
    },
    onError: (_err, _text, ctx) => {
      if (ctx?.prev) qc.setQueryData(RULES_KEY, ctx.prev);
      toast({
        variant: "error",
        title: "Couldn't add rule",
        description: "Reverted — is the bridge running?",
      });
    },
    onSuccess: (created, _text, ctx) => {
      // Swap the placeholder for the authoritative server rule.
      qc.setQueryData<Rule[]>(RULES_KEY, (old) =>
        (old ?? []).map((r) => (r.id === ctx?.optimisticId ? created : r)),
      );
      toast({ variant: "success", title: "Rule added" });
      onDone();
    },
  });
}

// ---------------------------------------------------------------------------
// Update a rule (toggle enabled / edit text) — optimistic.
// ---------------------------------------------------------------------------

interface UpdateVars {
  id: string;
  patch: { enabled?: boolean; text?: string };
}

function useUpdateRule() {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({ id, patch }: UpdateVars) => api.updateRule(id, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: RULES_KEY });
      const prev = qc.getQueryData<Rule[]>(RULES_KEY);
      qc.setQueryData<Rule[]>(RULES_KEY, (old) =>
        (old ?? []).map((r) => (r.id === id ? { ...r, ...patch } : r)),
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(RULES_KEY, ctx.prev);
      toast({
        variant: "error",
        title: "Couldn't save rule",
        description: "Reverted — is the bridge running?",
      });
    },
    onSuccess: (updated) => {
      qc.setQueryData<Rule[]>(RULES_KEY, (old) =>
        (old ?? []).map((r) => (r.id === updated.id ? updated : r)),
      );
    },
  });
}

// ---------------------------------------------------------------------------
// Remove a rule — optimistic.
// ---------------------------------------------------------------------------

function useRemoveRule(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (id: string) => api.removeRule(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: RULES_KEY });
      const prev = qc.getQueryData<Rule[]>(RULES_KEY);
      qc.setQueryData<Rule[]>(RULES_KEY, (old) =>
        (old ?? []).filter((r) => r.id !== id),
      );
      return { prev };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(RULES_KEY, ctx.prev);
      toast({
        variant: "error",
        title: "Couldn't delete rule",
        description: "Reverted — is the bridge running?",
      });
    },
    onSuccess: () => {
      toast({ variant: "info", title: "Rule deleted" });
      onDone();
    },
  });
}

// ---------------------------------------------------------------------------
// Add-rule composer (top of page).
// ---------------------------------------------------------------------------

function AddRule() {
  const [text, setText] = React.useState("");
  const add = useAddRule(() => setText(""));

  const canSubmit = text.trim().length > 0 && !add.isPending;

  const submit = () => {
    if (!canSubmit) return;
    add.mutate(text.trim());
  };

  return (
    <FadeIn className="mb-6">
      <Card glass className="relative overflow-hidden p-1.5">
        <span className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
        <div className="flex items-center gap-2">
          <span className="ml-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <Plus className="h-4 w-4" />
          </span>
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Add a rule — e.g. “Always keep replies under two sentences.”"
            aria-label="New rule"
            className="h-10 border-0 bg-transparent text-sm shadow-none focus-visible:ring-0"
          />
          <Button
            variant="gradient"
            onClick={submit}
            disabled={!canSubmit}
            className="shrink-0"
          >
            <Sparkles className="h-4 w-4" />
            {add.isPending ? "Adding…" : "Add rule"}
          </Button>
        </div>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// A single rule row: animated switch, inline-editable text, delete.
// ---------------------------------------------------------------------------

function RuleRow({
  rule,
  onToggle,
  onSaveText,
  onDelete,
}: {
  rule: Rule;
  onToggle: (enabled: boolean) => void;
  onSaveText: (text: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(rule.text);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  // Don't let inline editing fight an authoritative update from elsewhere.
  React.useEffect(() => {
    if (!editing) setDraft(rule.text);
  }, [rule.text, editing]);

  const startEdit = () => {
    setDraft(rule.text);
    setEditing(true);
  };

  const cancelEdit = () => {
    setDraft(rule.text);
    setEditing(false);
  };

  const commitEdit = () => {
    const next = draft.trim();
    if (next && next !== rule.text) onSaveText(next);
    setEditing(false);
  };

  // Focus + place caret at end when entering edit mode.
  React.useEffect(() => {
    if (editing && textareaRef.current) {
      const el = textareaRef.current;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
  }, [editing]);

  const pending = isTemp(rule.id);

  return (
    <Card
      glass
      className={cn(
        "group relative overflow-hidden p-4 transition-all duration-200",
        rule.enabled
          ? "ring-1 ring-transparent hover:ring-border-strong"
          : "opacity-65 hover:opacity-90",
        pending && "opacity-70",
      )}
    >
      {/* Accent hairline on the left edge for active rules. */}
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-y-0 left-0 w-0.5 transition-opacity",
          rule.enabled ? "bg-brand-gradient opacity-80" : "opacity-0",
        )}
      />

      <div className="flex items-start gap-4">
        <div className="flex shrink-0 flex-col items-center gap-1.5 pt-0.5">
          <Switch
            checked={rule.enabled}
            disabled={pending}
            onCheckedChange={onToggle}
            aria-label={rule.enabled ? "Disable rule" : "Enable rule"}
          />
          <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-muted">
            {rule.enabled ? "On" : "Off"}
          </span>
        </div>

        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="space-y-2">
              <Textarea
                ref={textareaRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    commitEdit();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    cancelEdit();
                  }
                }}
                className="min-h-[72px] resize-y leading-relaxed"
                aria-label="Edit rule text"
              />
              <div className="flex items-center justify-end gap-2">
                <span className="mr-auto text-[11px] text-foreground-muted">
                  ⌘↵ to save · Esc to cancel
                </span>
                <Button variant="ghost" size="sm" onClick={cancelEdit}>
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </Button>
                <Button
                  variant="gradient"
                  size="sm"
                  onClick={commitEdit}
                  disabled={draft.trim().length === 0}
                >
                  <Check className="h-3.5 w-3.5" />
                  Save
                </Button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={startEdit}
              disabled={pending}
              className="block w-full rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              aria-label="Edit rule"
            >
              <p
                className={cn(
                  "whitespace-pre-wrap text-sm leading-relaxed",
                  rule.enabled
                    ? "text-foreground"
                    : "text-foreground-secondary line-through decoration-foreground-muted/40",
                )}
              >
                {rule.text}
              </p>
            </button>
          )}
        </div>

        {!editing && (
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={startEdit}
              disabled={pending}
              aria-label="Edit rule"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-muted hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onDelete}
              disabled={pending}
              aria-label="Delete rule"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-danger/15 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Delete confirm dialog.
// ---------------------------------------------------------------------------

function DeleteDialog({
  rule,
  onConfirm,
  onOpenChange,
  pending,
}: {
  rule: Rule | null;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
  pending: boolean;
}) {
  return (
    <Dialog open={rule !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete this rule?</DialogTitle>
          <DialogDescription>
            {rule && (
              <>
                <span className="text-foreground">
                  “{rule.text.length > 120 ? `${rule.text.slice(0, 120)}…` : rule.text}”
                </span>{" "}
                will be permanently removed. This can&apos;t be undone.
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
            {pending ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Premium empty state.
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
          <ScrollText className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          No rules yet
        </h3>
        <p className="mt-1 max-w-sm text-sm text-foreground-secondary">
          Rules are standing instructions Vox follows on every turn — tone,
          formatting, things to always (or never) do. Add your first above.
        </p>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Skeleton row.
// ---------------------------------------------------------------------------

function RowSkeleton() {
  return (
    <Card glass className="p-4">
      <div className="flex items-start gap-4">
        <Skeleton className="h-5 w-9 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
        <Skeleton className="h-8 w-8 rounded-lg" />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Rules() {
  const { data, isLoading, isError } = useQuery<Rule[]>({
    queryKey: RULES_KEY,
    queryFn: api.rules,
  });

  const update = useUpdateRule();
  const [toDelete, setToDelete] = React.useState<Rule | null>(null);
  const remove = useRemoveRule(() => setToDelete(null));

  const rules = data ?? [];
  const enabledCount = rules.filter((r) => r.enabled).length;

  return (
    <div>
      <PageHeader
        title="Rules"
        description="Standing instructions injected into Vox's behavior on every turn."
        actions={
          data && rules.length > 0 ? (
            <Badge variant="accent" className="font-normal">
              <Check className="h-3 w-3" />
              {enabledCount} active
            </Badge>
          ) : null
        }
      />

      {/* Explainer: how rules feed into the assistant. */}
      <FadeIn className="mb-6">
        <Card
          glass
          className="relative overflow-hidden border-accent/20 px-5 py-4"
        >
          <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
          <p className="max-w-3xl text-sm leading-relaxed text-foreground-secondary">
            Enabled rules are{" "}
            <span className="text-foreground">added to Vox&apos;s system prompt</span>{" "}
            before every reply, on top of the active personality. Keep them short
            and specific — toggle a rule{" "}
            <span className="text-accent">off</span> to pause it without losing
            the text.
          </p>
        </Card>
      </FadeIn>

      <AddRule />

      {isError && (
        <Card
          glass
          className="mb-6 border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
        >
          Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
          <span className="font-mono">127.0.0.1:8765</span>? Rules will load once
          it&apos;s back.
        </Card>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <RowSkeleton key={i} />
          ))}
        </div>
      ) : rules.length === 0 && !isError ? (
        <EmptyState />
      ) : (
        <Stagger className="space-y-3">
          {rules.map((rule) => (
            <StaggerItem key={rule.id}>
              <RuleRow
                rule={rule}
                onToggle={(enabled) =>
                  update.mutate({ id: rule.id, patch: { enabled } })
                }
                onSaveText={(text) =>
                  update.mutate({ id: rule.id, patch: { text } })
                }
                onDelete={() => setToDelete(rule)}
              />
            </StaggerItem>
          ))}
        </Stagger>
      )}

      <DeleteDialog
        rule={toDelete}
        pending={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
        onOpenChange={(o) => {
          if (!o && !remove.isPending) setToDelete(null);
        }}
      />
    </div>
  );
}
