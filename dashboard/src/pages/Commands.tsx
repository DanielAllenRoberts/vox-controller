import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  TerminalSquare,
  Globe,
  AppWindow,
  PanelsTopLeft,
  Plus,
  X,
} from "lucide-react";
import {
  api,
  type CommandDb,
  type Command,
  type CommandContext,
  type IntentCategory,
  type PhraseMatchType,
} from "@/lib/api";
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

const COMMANDS_KEY = ["commands"] as const;

// intent category → badge tone. `system` (sleep/quit/restart/…) and `mode`
// (enter control/assistant/dictation) are shown for transparency, but the DB
// resolver only RUNS `action` intents — the control plane stays hardcoded.
const CATEGORY_VARIANT: Record<IntentCategory, "accent" | "info" | "warning"> = {
  action: "accent",
  mode: "info",
  system: "warning",
};

const SOURCE_VARIANT = {
  builtin: "outline",
  user: "success",
  learned: "info",
} as const;

// ---------------------------------------------------------------------------
// Immutable helpers to patch one command / context inside the CommandDb tree.
// ---------------------------------------------------------------------------

function patchCommand(
  db: CommandDb,
  id: number,
  fn: (c: Command) => Command,
): CommandDb {
  return {
    ...db,
    contexts: db.contexts.map((ctx) => ({
      ...ctx,
      commands: ctx.commands.map((c) => (c.id === id ? fn(c) : c)),
    })),
  };
}

function patchContext(
  db: CommandDb,
  id: number,
  fn: (c: CommandContext) => CommandContext,
): CommandDb {
  return {
    ...db,
    contexts: db.contexts.map((ctx) => (ctx.id === id ? fn(ctx) : ctx)),
  };
}

// ---------------------------------------------------------------------------
// Mutations.
// ---------------------------------------------------------------------------

function useToggleCommand() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.setCommandEnabled(id, enabled),
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: COMMANDS_KEY });
      const prev = qc.getQueryData<CommandDb>(COMMANDS_KEY);
      if (prev)
        qc.setQueryData<CommandDb>(
          COMMANDS_KEY,
          patchCommand(prev, id, (c) => ({ ...c, enabled })),
        );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(COMMANDS_KEY, ctx.prev);
      toast({ variant: "error", title: "Couldn't update command", description: "Reverted — is the bridge running?" });
    },
  });
}

function useToggleContext() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.setCommandContextEnabled(id, enabled),
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: COMMANDS_KEY });
      const prev = qc.getQueryData<CommandDb>(COMMANDS_KEY);
      if (prev)
        qc.setQueryData<CommandDb>(
          COMMANDS_KEY,
          patchContext(prev, id, (c) => ({ ...c, enabled })),
        );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(COMMANDS_KEY, ctx.prev);
      toast({ variant: "error", title: "Couldn't update context", description: "Reverted." });
    },
  });
}

function useAddPhrase() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ commandId, text, matchType }: { commandId: number; text: string; matchType?: PhraseMatchType }) =>
      api.addCommandPhrase(commandId, text, matchType),
    onSuccess: (created, { commandId }) => {
      const prev = qc.getQueryData<CommandDb>(COMMANDS_KEY);
      if (prev)
        qc.setQueryData<CommandDb>(
          COMMANDS_KEY,
          patchCommand(prev, commandId, (c) =>
            c.phrases.some((p) => p.id === created.id)
              ? c
              : { ...c, phrases: [...c.phrases, created] },
          ),
        );
    },
    onError: () => toast({ variant: "error", title: "Couldn't add phrase" }),
  });
}

function useRemovePhrase() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ phraseId }: { phraseId: number; commandId: number }) =>
      api.removeCommandPhrase(phraseId),
    onMutate: async ({ phraseId, commandId }) => {
      await qc.cancelQueries({ queryKey: COMMANDS_KEY });
      const prev = qc.getQueryData<CommandDb>(COMMANDS_KEY);
      if (prev)
        qc.setQueryData<CommandDb>(
          COMMANDS_KEY,
          patchCommand(prev, commandId, (c) => ({
            ...c,
            phrases: c.phrases.filter((p) => p.id !== phraseId),
          })),
        );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(COMMANDS_KEY, ctx.prev);
      toast({ variant: "error", title: "Couldn't remove phrase" });
    },
  });
}

// ---------------------------------------------------------------------------
// Inline "add phrase" composer (one per command).
// ---------------------------------------------------------------------------

function AddPhrase({ commandId }: { commandId: number }) {
  const [text, setText] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const add = useAddPhrase();

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    add.mutate({ commandId, text: t });
    setText("");
    setOpen(false);
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded-full border border-dashed border-border-strong px-2.5 py-0.5 text-xs font-medium text-foreground-muted transition-colors hover:border-accent/50 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      >
        <Plus className="h-3 w-3" />
        Add phrase
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-1">
      <Input
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            submit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setText("");
            setOpen(false);
          }
        }}
        onBlur={() => !text.trim() && setOpen(false)}
        placeholder="say…"
        aria-label="New phrase"
        className="h-7 w-40 text-xs"
      />
      <Button variant="gradient" size="sm" className="h-7 px-2" onClick={submit} disabled={!text.trim()}>
        Add
      </Button>
    </span>
  );
}

// ---------------------------------------------------------------------------
// One command row.
// ---------------------------------------------------------------------------

function CommandRow({
  command,
  category,
  onToggle,
  onRemovePhrase,
}: {
  command: Command;
  category: IntentCategory;
  onToggle: (enabled: boolean) => void;
  onRemovePhrase: (phraseId: number) => void;
}) {
  return (
    <Card
      glass
      className={cn(
        "group/cmd p-3.5 transition-all duration-200",
        command.enabled ? "hover:ring-1 hover:ring-border-strong" : "opacity-60 hover:opacity-90",
      )}
    >
      <div className="flex items-start gap-3.5">
        <div className="flex shrink-0 flex-col items-center gap-1 pt-0.5">
          <Switch
            checked={command.enabled}
            onCheckedChange={onToggle}
            aria-label={command.enabled ? `Disable ${command.label}` : `Enable ${command.label}`}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-foreground">{command.label}</span>
            <Badge variant={CATEGORY_VARIANT[category]} className="font-mono text-[10px]">
              {command.intent}
              {command.arg ? <span className="opacity-70"> · {command.arg}</span> : null}
              {command.param ? <span className="opacity-70"> · ${command.param}</span> : null}
            </Badge>
            {command.source !== "builtin" && (
              <Badge variant={SOURCE_VARIANT[command.source]} className="text-[10px]">
                {command.source}
              </Badge>
            )}
          </div>

          {/* Phrases as chips + inline add. */}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {command.phrases.length === 0 && (
              <span className="text-xs italic text-foreground-muted">no phrases — add one to make it triggerable</span>
            )}
            {command.phrases.map((p) => (
              <span
                key={p.id}
                className="group/chip inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs text-foreground-secondary"
                title={p.matchType !== "contains" ? `match: ${p.matchType}` : undefined}
              >
                <span className={cn(p.isPrimary && "font-medium text-foreground")}>{p.text}</span>
                {p.matchType !== "contains" && (
                  <span className="text-[9px] uppercase tracking-wide text-foreground-muted">{p.matchType}</span>
                )}
                <button
                  type="button"
                  onClick={() => onRemovePhrase(p.id)}
                  aria-label={`Remove phrase "${p.text}"`}
                  className="ml-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full text-foreground-muted opacity-0 transition-opacity hover:bg-danger/20 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none group-hover/chip:opacity-100"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
            <AddPhrase commandId={command.id} />
          </div>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// A context section (Everywhere / Arc / …).
// ---------------------------------------------------------------------------

function ContextIcon({ kind }: { kind: CommandContext["kind"] }) {
  const Icon = kind === "global" ? Globe : kind === "site" ? PanelsTopLeft : AppWindow;
  return <Icon className="h-4 w-4" />;
}

function ContextSection({
  ctx,
  categoryOf,
  onToggleContext,
  onToggleCommand,
  onRemovePhrase,
}: {
  ctx: CommandContext;
  categoryOf: (intent: string) => IntentCategory;
  onToggleContext: (enabled: boolean) => void;
  onToggleCommand: (id: number, enabled: boolean) => void;
  onRemovePhrase: (commandId: number, phraseId: number) => void;
}) {
  return (
    <FadeIn>
      <section className="mb-7">
        <div className="mb-3 flex items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <ContextIcon kind={ctx.kind} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">{ctx.displayName}</h2>
              <Badge variant="outline" className="text-[10px]">
                {ctx.kind === "global" ? "everywhere" : ctx.kind}
                {ctx.matchValue ? ` · ${ctx.matchValue}` : ""}
              </Badge>
            </div>
            <p className="text-xs text-foreground-muted">
              {ctx.commands.length} command{ctx.commands.length === 1 ? "" : "s"}
              {ctx.kind !== "global" && " · overrides the Everywhere set when this app is focused"}
            </p>
          </div>
          {ctx.kind !== "global" && (
            <div className="flex shrink-0 items-center gap-2">
              <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-muted">
                {ctx.enabled ? "On" : "Off"}
              </span>
              <Switch
                checked={ctx.enabled}
                onCheckedChange={onToggleContext}
                aria-label={ctx.enabled ? `Disable ${ctx.displayName} context` : `Enable ${ctx.displayName} context`}
              />
            </div>
          )}
        </div>

        <Stagger className="space-y-2">
          {ctx.commands.map((c) => (
            <StaggerItem key={c.id}>
              <CommandRow
                command={c}
                category={categoryOf(c.intent)}
                onToggle={(enabled) => onToggleCommand(c.id, enabled)}
                onRemovePhrase={(phraseId) => onRemovePhrase(c.id, phraseId)}
              />
            </StaggerItem>
          ))}
        </Stagger>
      </section>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// States.
// ---------------------------------------------------------------------------

function LoadingState() {
  return (
    <div className="space-y-3">
      {[0, 1, 2, 3].map((i) => (
        <Card key={i} glass className="p-3.5">
          <div className="flex items-start gap-3.5">
            <Skeleton className="h-5 w-9 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <FadeIn>
      <Card glass className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-14 text-center">
        <span className="pointer-events-none absolute -top-12 left-1/2 h-44 w-44 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <TerminalSquare className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">No commands in the database</h3>
        <p className="mt-1 max-w-sm text-sm text-foreground-secondary">
          The command database is empty or hasn&apos;t been seeded yet. Start Vox once to seed it
          from the built-in commands.
        </p>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Commands() {
  const { data, isLoading, isError } = useQuery<CommandDb>({
    queryKey: COMMANDS_KEY,
    queryFn: api.commands,
  });

  const toggleCommand = useToggleCommand();
  const toggleContext = useToggleContext();
  const removePhrase = useRemovePhrase();

  const categoryOf = React.useCallback(
    (intent: string): IntentCategory => {
      const found = data?.intents.find((i) => i.name === intent);
      return found?.category ?? "action";
    },
    [data?.intents],
  );

  const contexts = data?.contexts ?? [];
  const totalCommands = contexts.reduce((n, c) => n + c.commands.length, 0);

  return (
    <div>
      <PageHeader
        title="Commands"
        description="The app-scoped voice command database — every phrase Vox can match, and what it does."
        actions={
          data && totalCommands > 0 ? (
            <div className="flex items-center gap-2">
              <Badge variant="accent" className="font-normal">
                {totalCommands} commands
              </Badge>
              <Badge variant="outline" className="font-normal">
                {contexts.length} contexts
              </Badge>
            </div>
          ) : null
        }
      />

      {/* Explainer. */}
      <FadeIn className="mb-6">
        <Card glass className="relative overflow-hidden border-accent/20 px-5 py-4">
          <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
          <p className="max-w-3xl text-sm leading-relaxed text-foreground-secondary">
            Commands are grouped by <span className="text-foreground">context</span>: the{" "}
            <span className="text-foreground">Everywhere</span> set always applies, and an app&apos;s
            set takes over when you&apos;re focused on it (so the same words can do different things
            per app). Toggle a command off to pause it, or add/remove the{" "}
            <span className="text-accent">phrases</span> that trigger it.{" "}
            <span className="text-foreground-muted">
              Resolution runs only when “App-scoped command DB” is on in Settings; the
              <span className="text-warning"> system</span>/<span className="text-info">mode</span>{" "}
              commands are shown for reference but stay handled by the built-in control plane.
            </span>
          </p>
        </Card>
      </FadeIn>

      {isError && (
        <Card glass className="mb-6 border-danger/30 px-5 py-4 text-sm text-foreground-secondary">
          Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
          <span className="font-mono">127.0.0.1:8765</span>? Commands will load once it&apos;s back.
        </Card>
      )}

      {isLoading ? (
        <LoadingState />
      ) : contexts.length === 0 && !isError ? (
        <EmptyState />
      ) : (
        contexts.map((ctx) => (
          <ContextSection
            key={ctx.id}
            ctx={ctx}
            categoryOf={categoryOf}
            onToggleContext={(enabled) => toggleContext.mutate({ id: ctx.id, enabled })}
            onToggleCommand={(id, enabled) => toggleCommand.mutate({ id, enabled })}
            onRemovePhrase={(commandId, phraseId) => removePhrase.mutate({ commandId, phraseId })}
          />
        ))
      )}
    </div>
  );
}
