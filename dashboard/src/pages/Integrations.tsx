import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Volume2,
  Terminal,
  Copy,
  Check,
  FolderOpen,
  Package,
  Plug,
  ArrowRight,
  ShieldCheck,
  RefreshCw,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// vox-speak MCP integration (idea #34).
//
// This page is intentionally self-contained: per the build contract it OWNS
// only this file and must NOT touch lib/api.ts. So it talks to the bridge with
// a direct same-origin fetch (mirroring lib/api.ts's API_BASE convention) and
// degrades gracefully when the endpoint is missing — the voice daemon and the
// rest of the dashboard never depend on it.
//
// Source of truth for the config content lives in mcp/README.md +
// mcp/vox_speak_server.py. The ONLY machine-specific value is the repo path:
// GET /api/mcp/config fills it in at runtime. Everything else (the mcpServers
// block, the `claude mcp add` command) is derived from that path here, so the
// page works even if the endpoint only returns { repoPath }.
// ---------------------------------------------------------------------------

// Committed docs never carry a personal path; this placeholder is what the UI
// shows when the bridge can't tell us the real one (CONTRACT: never commit
// personal paths — the real one is only ever computed locally).
const PLACEHOLDER_PATH = "/ABSOLUTE/PATH/TO/vox-controller";
const SERVER_SCRIPT = "mcp/vox_speak_server.py";
const INSTALL_HINT = "uv add mcp";

// Same-origin /api in production (served by the FastAPI bridge); in dev Vite
// proxies /api to the bridge. Mirrors lib/api.ts without importing it.
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

// The bridge (`GET /api/mcp/config`, see server.py `_mcp_config`) returns
// `{ cursor, claudeAdd, repoRoot }`. We only require `repoRoot` — this machine's
// real absolute path; the rest is re-derived locally so a minimal backend
// response still renders correctly.
interface McpConfigResponse {
  repoRoot?: string;
  serverScript?: string;
  configPath?: string;
  installHint?: string;
  error?: string;
}

interface McpConfig {
  repoPath: string;
  serverScript: string;
  configPath?: string;
  installHint: string;
  /** True when the bridge gave us this machine's real, absolute path. */
  resolved: boolean;
}

async function fetchMcpConfig(): Promise<McpConfig> {
  const res = await fetch(`${API_BASE}/api/mcp/config`, {
    headers: { "Content-Type": "application/json" },
  });
  // Endpoint not built yet / not found → fall back to the documented
  // placeholder so the page is still useful and copy-pastable.
  if (res.status === 404) return fallbackConfig();

  let body: McpConfigResponse = {};
  try {
    body = (await res.json()) as McpConfigResponse;
  } catch {
    return fallbackConfig();
  }
  // Bridge returns HTTP 200 with { error } when the module is absent.
  if (!res.ok || body.error || !body.repoRoot) return fallbackConfig();

  return {
    repoPath: body.repoRoot,
    serverScript: body.serverScript ?? SERVER_SCRIPT,
    configPath: body.configPath,
    installHint: body.installHint ?? INSTALL_HINT,
    resolved: true,
  };
}

function fallbackConfig(): McpConfig {
  return {
    repoPath: PLACEHOLDER_PATH,
    serverScript: SERVER_SCRIPT,
    installHint: INSTALL_HINT,
    resolved: false,
  };
}

// --- Snippet builders (single source of truth = repoPath) ------------------

function buildCursorJson(cfg: McpConfig): string {
  const block = {
    mcpServers: {
      "vox-speak": {
        command: "uv",
        args: ["run", "python", cfg.serverScript],
        cwd: cfg.repoPath,
      },
    },
  };
  return JSON.stringify(block, null, 2);
}

function buildClaudeCommand(cfg: McpConfig): string {
  // `claude mcp add` runs from the repo root, so the relative script path is
  // correct without the absolute cwd (matches mcp/README.md).
  return `claude mcp add vox-speak -- uv run python ${cfg.serverScript}`;
}

// ---------------------------------------------------------------------------
// Clipboard helper + copyable code box.
// ---------------------------------------------------------------------------

function useCopy() {
  const { toast } = useToast();
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout>>();

  React.useEffect(() => () => clearTimeout(timer.current), []);

  const copy = React.useCallback(
    async (text: string, label: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 1600);
        toast({
          variant: "success",
          title: `${label} copied`,
          description: "Paste it into your editor to wire up vox-speak.",
        });
      } catch {
        toast({
          variant: "error",
          title: "Couldn't copy",
          description:
            "Your browser blocked clipboard access — select and copy manually.",
        });
      }
    },
    [toast],
  );

  return { copied, copy };
}

function CodeBox({
  code,
  label,
  language,
}: {
  code: string;
  label: string;
  language: "json" | "bash";
}) {
  const { copied, copy } = useCopy();

  return (
    <div className="group relative overflow-hidden rounded-xl border border-border bg-zinc-950/60 ring-1 ring-transparent transition-colors focus-within:ring-accent/30 dark:bg-black/40">
      <div className="flex items-center justify-between gap-2 border-b border-border/70 px-3 py-1.5">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-foreground-muted">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              language === "json" ? "bg-accent" : "bg-accent-2",
            )}
          />
          {language === "json" ? ".cursor/mcp.json" : "terminal"}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => copy(code, label)}
          aria-label={`Copy ${label}`}
          className="h-7 gap-1.5 px-2 text-xs text-foreground-secondary hover:text-foreground"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-success" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="overflow-x-auto px-4 py-3.5 text-[12.5px] leading-relaxed">
        <code className="font-mono text-foreground/90">{code}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step list (numbered wiring instructions) + inline mono helper.
// ---------------------------------------------------------------------------

function Steps({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="mt-1 space-y-2.5">
      {items.map((node, i) => (
        <li key={i} className="flex gap-3 text-sm text-foreground-secondary">
          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[11px] font-semibold text-accent">
            {i + 1}
          </span>
          <span className="leading-relaxed">{node}</span>
        </li>
      ))}
    </ol>
  );
}

function Mono({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[12px] text-foreground">
      {children}
    </code>
  );
}

// ---------------------------------------------------------------------------
// Header / hero — what vox-speak does + the install hint.
// ---------------------------------------------------------------------------

function Hero({ cfg }: { cfg: McpConfig }) {
  const { copy } = useCopy();

  return (
    <FadeIn>
      <Card glass className="relative overflow-hidden p-6">
        <span className="pointer-events-none absolute -right-20 -top-24 h-56 w-56 rounded-full bg-brand-gradient opacity-[0.12] blur-3xl" />
        <span className="pointer-events-none absolute -bottom-24 -left-16 h-48 w-48 rounded-full bg-accent/20 opacity-10 blur-3xl" />

        <div className="flex items-start gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-glass">
            <Volume2 className="h-6 w-6" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">
                vox-speak
              </h2>
              <Badge variant="accent" className="font-normal">
                MCP
              </Badge>
              <Badge variant="outline" className="font-normal">
                idea #34
              </Badge>
            </div>
            <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-foreground-secondary">
              A tiny Model Context Protocol server that gives your editor
              assistant a voice. Once wired in, Cursor or Claude Code can call a{" "}
              <Mono>speak</Mono> tool to talk to you through your Mac&apos;s
              text-to-speech — so you can say &ldquo;give me a shout when
              you&apos;re done&rdquo; and it will literally say it out loud,
              instead of you having to watch the screen.
            </p>
          </div>
        </div>

        {/* Install the dependency hint. */}
        <div className="mt-5 flex flex-col gap-3 rounded-xl border border-border bg-muted/40 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent">
              <Package className="h-4 w-4" />
            </span>
            <div>
              <p className="text-sm font-medium text-foreground">
                First, install the dependency
              </p>
              <p className="mt-0.5 text-xs text-foreground-muted">
                vox-speak needs the <Mono>mcp</Mono> package. Run this once in
                the repo.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <code className="rounded-lg border border-border bg-zinc-950/60 px-3 py-1.5 font-mono text-[12.5px] text-foreground/90 dark:bg-black/40">
              {cfg.installHint}
            </code>
            <Button
              variant="outline"
              size="icon"
              aria-label="Copy install command"
              onClick={() => copy(cfg.installHint, "Install command")}
              className="h-9 w-9 shrink-0"
            >
              <Copy className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// "Generated locally" / path resolution note.
// ---------------------------------------------------------------------------

function LocalNote({ cfg }: { cfg: McpConfig }) {
  const { toast } = useToast();

  const reveal = () => {
    // "Open config location" affordance. There's no dedicated MCP-reveal
    // endpoint on the bridge (the editor config isn't managed by Vox), so we
    // just tell the user exactly where to put / find the block.
    toast({
      variant: "info",
      title: "Config lives in the repo root",
      description: cfg.resolved
        ? `${cfg.repoPath}/.cursor/mcp.json`
        : "Generated locally — not committed.",
    });
  };

  return (
    <Card
      glass
      className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-success/15 text-success">
          <ShieldCheck className="h-4 w-4" />
        </span>
        <div>
          <p className="text-sm font-medium text-foreground">
            Generated locally for this machine
          </p>
          <p className="mt-0.5 max-w-xl text-xs leading-relaxed text-foreground-muted">
            {cfg.resolved ? (
              <>
                The path below is your real repo path, resolved by the bridge at
                runtime. It&apos;s never committed — the docs in the repo use a{" "}
                <Mono>{PLACEHOLDER_PATH}</Mono> placeholder.
              </>
            ) : (
              <>
                The bridge couldn&apos;t resolve this machine&apos;s repo path,
                so the snippets use the <Mono>{PLACEHOLDER_PATH}</Mono>{" "}
                placeholder. Replace it with your absolute path to the
                vox-controller repo. Nothing here is committed.
              </>
            )}
          </p>
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={reveal}
        className="shrink-0 self-start sm:self-center"
      >
        <FolderOpen className="h-4 w-4" />
        Open config location
      </Button>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// The two setup cards (Cursor / Claude Code).
// ---------------------------------------------------------------------------

function SetupCard({
  icon,
  title,
  tagline,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  tagline: string;
  children: React.ReactNode;
}) {
  return (
    <Card glass className="flex h-full flex-col p-5">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent/15 text-accent">
          {icon}
        </span>
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="text-xs text-foreground-muted">{tagline}</p>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-3">{children}</div>
    </Card>
  );
}

function CursorCard({ cfg }: { cfg: McpConfig }) {
  return (
    <SetupCard
      icon={<Plug className="h-4 w-4" />}
      title="Cursor"
      tagline="Project or global MCP settings"
    >
      <Steps
        items={[
          <>
            Add this block to <Mono>.cursor/mcp.json</Mono> (project-level) or
            your global Cursor MCP settings.
          </>,
          <>Reload MCP servers, or restart Cursor.</>,
          <>
            In chat, say: &ldquo;When you finish, use vox-speak to tell me out
            loud.&rdquo;
          </>,
        ]}
      />
      <CodeBox
        code={buildCursorJson(cfg)}
        label="Cursor config"
        language="json"
      />
    </SetupCard>
  );
}

function ClaudeCard({ cfg }: { cfg: McpConfig }) {
  return (
    <SetupCard
      icon={<Terminal className="h-4 w-4" />}
      title="Claude Code / CLI"
      tagline="One command from the repo root"
    >
      <Steps
        items={[
          <>
            From the repo root, run the command below (or add the same{" "}
            <Mono>mcpServers</Mono> block to a project <Mono>.mcp.json</Mono>).
          </>,
          <>
            Confirm it&apos;s registered with <Mono>claude mcp list</Mono>.
          </>,
          <>
            Ask Claude to <Mono>announce_done</Mono> when a long task finishes.
          </>,
        ]}
      />
      <CodeBox
        code={buildClaudeCommand(cfg)}
        label="Claude Code command"
        language="bash"
      />
    </SetupCard>
  );
}

// ---------------------------------------------------------------------------
// Loading + error states.
// ---------------------------------------------------------------------------

function LoadingState() {
  return (
    <div className="space-y-6">
      <Card glass className="p-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-12 w-12 rounded-2xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-full max-w-lg" />
          </div>
        </div>
        <Skeleton className="mt-5 h-16 w-full rounded-xl" />
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <Card key={i} glass className="p-5">
            <Skeleton className="h-9 w-32" />
            <Skeleton className="mt-4 h-24 w-full" />
            <Skeleton className="mt-3 h-28 w-full rounded-xl" />
          </Card>
        ))}
      </div>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <FadeIn>
      <Card
        glass
        className="flex flex-col items-center justify-center gap-3 border-danger/30 px-6 py-12 text-center"
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-danger/15 text-danger">
          <Plug className="h-5 w-5" />
        </span>
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Can&apos;t reach the Vox bridge
          </h3>
          <p className="mt-1 max-w-sm text-sm text-foreground-secondary">
            The MCP setup needs the daemon running on{" "}
            <span className="font-mono">127.0.0.1:8765</span> to resolve this
            machine&apos;s repo path. You can still wire up vox-speak with the{" "}
            <Mono>{PLACEHOLDER_PATH}</Mono> placeholder.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="h-4 w-4" />
          Try again
        </Button>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Integrations() {
  const query = useQuery({
    queryKey: ["mcp", "config"],
    queryFn: fetchMcpConfig,
    staleTime: 5 * 60_000,
  });

  return (
    <div>
      <PageHeader
        title="Integrations"
        description="Connect Vox to your editor. Wire the vox-speak MCP into Cursor or Claude Code so your assistant can talk to you out loud while you work."
        actions={
          query.data ? (
            <Badge
              variant={query.data.resolved ? "success" : "warning"}
              className="font-normal"
            >
              {query.data.resolved ? (
                <>
                  <Check className="h-3 w-3" />
                  Path resolved
                </>
              ) : (
                <>
                  <ArrowRight className="h-3 w-3" />
                  Using placeholder
                </>
              )}
            </Badge>
          ) : undefined
        }
      />

      {query.isLoading ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState onRetry={() => query.refetch()} />
      ) : (
        query.data && (
          <div className="space-y-6">
            <Hero cfg={query.data} />
            <LocalNote cfg={query.data} />
            <Stagger className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <StaggerItem className="h-full">
                <CursorCard cfg={query.data} />
              </StaggerItem>
              <StaggerItem className="h-full">
                <ClaudeCard cfg={query.data} />
              </StaggerItem>
            </Stagger>
          </div>
        )
      )}
    </div>
  );
}

export default Integrations;
