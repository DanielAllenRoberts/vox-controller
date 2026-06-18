import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import {
  Accessibility,
  ChevronRight,
  RefreshCw,
  Search,
  X,
  ScanEye,
  ShieldAlert,
  MonitorOff,
  Eye,
  ListTree,
} from "lucide-react";
import {
  api,
  type AxNode,
  type AxTree as AxTreeData,
  type AxTreeError,
} from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { cn } from "@/lib/utils";

const AXTREE_KEY = ["axtree"] as const;
const AUTO_REFRESH_MS = 3000;

// A snapshot can be a success ({app,tree,...}) or a graceful {error}.
function isError(d: AxTreeData | AxTreeError | undefined): d is AxTreeError {
  return !!d && "error" in d;
}

// ---------------------------------------------------------------------------
// Tree indexing: assign a stable path id per node and pre-compute, for a given
// query, which nodes match and which must stay open to reveal a match.
// ---------------------------------------------------------------------------

// Does this node's own role/title/value contain the (lowercased) query?
function nodeMatches(node: AxNode, q: string): boolean {
  if (!q) return false;
  return (
    node.role.toLowerCase().includes(q) ||
    (node.title?.toLowerCase().includes(q) ?? false) ||
    (node.value?.toLowerCase().includes(q) ?? false)
  );
}

interface SearchInfo {
  matched: Set<string>; // node ids whose own text matches
  reveal: Set<string>; // ancestor ids that must be expanded to show a match
  total: number; // count of matched nodes
}

// Walk once to compute match + ancestors-to-reveal sets for the query.
function computeSearch(root: AxNode, q: string): SearchInfo {
  const matched = new Set<string>();
  const reveal = new Set<string>();

  function visit(node: AxNode, id: string): boolean {
    const self = nodeMatches(node, q);
    if (self) matched.add(id);
    let childHit = false;
    node.children.forEach((child, i) => {
      if (visit(child, `${id}.${i}`)) childHit = true;
    });
    // If any descendant matched, this node must be expanded to reveal it.
    if (childHit) reveal.add(id);
    return self || childHit;
  }

  visit(root, "0");
  return { matched, reveal, total: matched.size };
}

// Count nodes for the header summary.
function countNodes(node: AxNode): number {
  return 1 + node.children.reduce((sum, c) => sum + countNodes(c), 0);
}

// ---------------------------------------------------------------------------
// Highlighter — wraps query hits in an accent-tinted mark.
// ---------------------------------------------------------------------------

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const parts: React.ReactNode[] = [];
  let from = 0;
  let hit = lower.indexOf(q, from);
  let key = 0;
  while (hit !== -1) {
    if (hit > from) parts.push(text.slice(from, hit));
    parts.push(
      <mark
        key={key++}
        className="rounded-[3px] bg-accent/25 px-0.5 text-accent-foreground ring-1 ring-accent/30"
      >
        {text.slice(hit, hit + q.length)}
      </mark>,
    );
    from = hit + q.length;
    hit = lower.indexOf(q, from);
  }
  if (from < text.length) parts.push(text.slice(from));
  return <>{parts}</>;
}

// ---------------------------------------------------------------------------
// Recursive tree row. Indentation guides are absolutely-positioned hairlines.
// ---------------------------------------------------------------------------

function TreeNode({
  node,
  id,
  depth,
  query,
  search,
  open,
  toggle,
}: {
  node: AxNode;
  id: string;
  depth: number;
  query: string;
  search: SearchInfo;
  open: Set<string>;
  toggle: (id: string, next?: boolean) => void;
}) {
  const reduced = useReducedMotion();
  const hasChildren = node.children.length > 0;
  // While searching, honour the reveal set so matches are always visible.
  const isOpen = query
    ? search.reveal.has(id) || open.has(id)
    : open.has(id);
  const selfMatch = search.matched.has(id);
  const dimmed = query.length > 0 && !selfMatch && !search.reveal.has(id);

  return (
    <div>
      <div
        className={cn(
          "group/row relative flex items-start gap-2 rounded-lg py-1.5 pr-2 transition-colors",
          "hover:bg-muted/50",
          selfMatch && "bg-accent/10",
          dimmed && "opacity-40",
        )}
        style={{ paddingLeft: depth * 18 + 8 }}
      >
        {/* Indentation guides: one hairline per ancestor level. */}
        {Array.from({ length: depth }).map((_, i) => (
          <span
            key={i}
            aria-hidden
            className="pointer-events-none absolute top-0 bottom-0 w-px bg-border/50"
            style={{ left: i * 18 + 15 }}
          />
        ))}

        {/* Disclosure toggle (or a leaf dot). */}
        {hasChildren ? (
          <button
            type="button"
            onClick={() => toggle(id)}
            aria-expanded={isOpen}
            aria-label={isOpen ? "Collapse" : "Expand"}
            className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded text-foreground-muted transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            <motion.span
              animate={{ rotate: isOpen ? 90 : 0 }}
              transition={reduced ? { duration: 0 } : { duration: 0.15 }}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </motion.span>
          </button>
        ) : (
          <span
            aria-hidden
            className="mt-[9px] ml-[5px] mr-[6px] h-1 w-1 shrink-0 rounded-full bg-border-strong"
          />
        )}

        {/* Node content: role + title + value. */}
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span
            className={cn(
              "font-mono text-[11px] font-medium tracking-tight",
              selfMatch ? "text-accent" : "text-foreground-secondary",
            )}
          >
            <Highlight text={node.role} query={query} />
          </span>
          {node.title && (
            <span className="truncate text-sm text-foreground">
              <Highlight text={node.title} query={query} />
            </span>
          )}
          {node.value && (
            <span className="min-w-0 truncate font-mono text-xs text-foreground-muted">
              <Highlight text={node.value} query={query} />
            </span>
          )}
          {hasChildren && (
            <span className="text-[10px] tabular-nums text-foreground-muted/70">
              {node.children.length}
            </span>
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {hasChildren && isOpen && (
          <motion.div
            initial={reduced ? false : { height: 0, opacity: 0 }}
            animate={reduced ? {} : { height: "auto", opacity: 1 }}
            exit={reduced ? {} : { height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="overflow-hidden"
          >
            {node.children.map((child, i) => (
              <TreeNode
                key={`${id}.${i}`}
                node={child}
                id={`${id}.${i}`}
                depth={depth + 1}
                query={query}
                search={search}
                open={open}
                toggle={toggle}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error / off-mac state. The bridge returns {error} for off-mac, missing
// Accessibility permission, no front window, or a timeout — we shape the copy.
// ---------------------------------------------------------------------------

function classifyError(msg: string): {
  icon: typeof ShieldAlert;
  title: string;
  hint: React.ReactNode;
} {
  const m = msg.toLowerCase();
  if (m.includes("only available on macos")) {
    return {
      icon: MonitorOff,
      title: "Only available on macOS",
      hint: "The accessibility tree is read from macOS System Events. Open the dashboard on your Mac to inspect the focused app.",
    };
  }
  if (
    m.includes("not allowed") ||
    m.includes("permission") ||
    m.includes("assistive") ||
    m.includes("-1719") ||
    m.includes("accessibility read failed")
  ) {
    return {
      icon: ShieldAlert,
      title: "Accessibility permission needed",
      hint: (
        <>
          Grant Vox access under{" "}
          <span className="font-medium text-foreground-secondary">
            System Settings → Privacy &amp; Security → Accessibility
          </span>
          , then refresh.
        </>
      ),
    };
  }
  if (m.includes("no front window")) {
    return {
      icon: ScanEye,
      title: "No window to inspect",
      hint: "The focused app has no front window right now. Click into an app with a visible window, then refresh.",
    };
  }
  return {
    icon: ShieldAlert,
    title: "Couldn't read the AX tree",
    hint: "The snapshot failed. Is the Vox daemon running on 127.0.0.1:8765?",
  };
}

function ErrorState({ message }: { message: string }) {
  const { icon: Icon, title, hint } = classifyError(message);
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-16 text-center"
      >
        <span className="pointer-events-none absolute -top-10 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-warning/15 text-warning">
          <Icon className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          {title}
        </h3>
        <p className="mt-1.5 max-w-md text-sm text-foreground-secondary">
          {hint}
        </p>
        <p className="mt-4 max-w-md font-mono text-[11px] text-foreground-muted/70">
          {message}
        </p>
      </Card>
    </FadeIn>
  );
}

function NoMatchesState({ query }: { query: string }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted text-foreground-muted">
        <Search className="h-5 w-5" />
      </span>
      <p className="mt-3 text-sm text-foreground-secondary">
        No nodes match{" "}
        <span className="font-mono text-foreground">&ldquo;{query}&rdquo;</span>
      </p>
    </div>
  );
}

function TreeSkeleton() {
  return (
    <div className="space-y-2.5 p-4">
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
        <div key={i} className="flex items-center gap-2" style={{ paddingLeft: (i % 4) * 18 }}>
          <Skeleton className="h-4 w-4 rounded" />
          <Skeleton className="h-4 rounded" style={{ width: `${40 + ((i * 13) % 40)}%` }} />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function AxTree() {
  const [auto, setAuto] = React.useState(false);
  const [query, setQuery] = React.useState("");
  // Manual expand/collapse overrides keyed by node id. Searching layers the
  // reveal set on top of this so matches stay visible without mutating it.
  const [open, setOpen] = React.useState<Set<string>>(() => new Set(["0"]));

  const { data, isLoading, isFetching, isError, error, refetch, dataUpdatedAt } =
    useQuery<AxTreeData | AxTreeError>({
      queryKey: AXTREE_KEY,
      queryFn: api.axtree,
      refetchInterval: auto ? AUTO_REFRESH_MS : false,
      refetchOnWindowFocus: false,
    });

  const toggle = React.useCallback((id: string, next?: boolean) => {
    setOpen((prev) => {
      const set = new Set(prev);
      const willOpen = next ?? !set.has(id);
      if (willOpen) set.add(id);
      else set.delete(id);
      return set;
    });
  }, []);

  const q = query.trim().toLowerCase();
  const payloadError = isErrorPayload(data) ? (data as AxTreeError).error : null;
  const tree = !isErrorPayload(data)
    ? (data as AxTreeData | undefined)
    : undefined;

  const search = React.useMemo<SearchInfo>(
    () =>
      tree?.tree && q
        ? computeSearch(tree.tree, q)
        : { matched: new Set(), reveal: new Set(), total: 0 },
    [tree, q],
  );

  const nodeCount = React.useMemo(
    () => (tree?.tree ? countNodes(tree.tree) : 0),
    [tree],
  );

  // Expand/collapse all — collect every node id with children.
  const allParentIds = React.useMemo(() => {
    const ids: string[] = [];
    if (!tree?.tree) return ids;
    const walk = (n: AxNode, id: string) => {
      if (n.children.length) ids.push(id);
      n.children.forEach((c, i) => walk(c, `${id}.${i}`));
    };
    walk(tree.tree, "0");
    return ids;
  }, [tree]);

  const expandAll = () => setOpen(new Set(allParentIds));
  const collapseAll = () => setOpen(new Set());

  const noMatches = q.length > 0 && tree?.tree && search.total === 0;

  return (
    <div>
      <PageHeader
        title="AX Tree"
        description="Read-only accessibility tree of the focused app. Visualises roles, titles, and values — it never touches the UI."
        actions={
          <div className="flex items-center gap-3">
            <label className="flex select-none items-center gap-2 text-sm text-foreground-secondary">
              <span className="hidden sm:inline">Auto-refresh</span>
              <Switch
                checked={auto}
                onCheckedChange={setAuto}
                aria-label="Auto-refresh every few seconds"
              />
            </label>
            <Button
              variant="outline"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw
                className={cn("h-4 w-4", isFetching && "animate-spin")}
              />
              Refresh
            </Button>
          </div>
        }
      />

      {/* Toolbar: app badge, node count, capture time, search. */}
      <FadeIn className="mb-4">
        <Card glass className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
              <Accessibility className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              {tree ? (
                <>
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-foreground">
                      {tree.app || "Focused app"}
                    </span>
                    <Badge variant="outline" className="font-normal">
                      <ListTree className="h-3 w-3" />
                      {nodeCount} nodes
                    </Badge>
                    {auto && (
                      <Badge variant="accent" className="font-normal">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent" />
                        </span>
                        Live
                      </Badge>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-xs text-foreground-muted">
                    {dataUpdatedAt
                      ? `Captured ${new Date(dataUpdatedAt).toLocaleTimeString()}`
                      : "—"}
                  </p>
                </>
              ) : (
                <div className="space-y-1">
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-3 w-20" />
                </div>
              )}
            </div>
          </div>

          {/* Search */}
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by role, title, or value…"
              className="pl-9 pr-9"
              aria-label="Filter the accessibility tree"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear filter"
                className="absolute right-2.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-foreground-muted transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </Card>
      </FadeIn>

      {/* Expand controls + match count (only when there's a tree). */}
      {tree?.tree && (
        <div className="mb-3 flex items-center justify-between gap-3 px-1">
          <div className="flex items-center gap-1.5">
            <Button variant="ghost" size="sm" onClick={expandAll}>
              <Eye className="h-3.5 w-3.5" />
              Expand all
            </Button>
            <Button variant="ghost" size="sm" onClick={collapseAll}>
              Collapse all
            </Button>
          </div>
          {q.length > 0 && search.total > 0 && (
            <Badge variant="accent" className="font-normal">
              {search.total} match{search.total === 1 ? "" : "es"}
            </Badge>
          )}
        </div>
      )}

      {/* Body */}
      {payloadError ? (
        <ErrorState message={payloadError} />
      ) : isError ? (
        <ErrorState
          message={
            (error as Error)?.message ??
            "Couldn't reach the Vox bridge on 127.0.0.1:8765"
          }
        />
      ) : isLoading ? (
        <Card glass className="overflow-hidden">
          <TreeSkeleton />
        </Card>
      ) : tree?.tree ? (
        <FadeIn>
          <Card glass className="overflow-hidden">
            <ScrollArea className="h-[calc(100vh-22rem)] min-h-[20rem]">
              <div className="p-2">
                {noMatches ? (
                  <NoMatchesState query={query.trim()} />
                ) : (
                  <TreeNode
                    node={tree.tree}
                    id="0"
                    depth={0}
                    query={q}
                    search={search}
                    open={open}
                    toggle={toggle}
                  />
                )}
              </div>
            </ScrollArea>
          </Card>
        </FadeIn>
      ) : (
        <ErrorState message="empty result" />
      )}
    </div>
  );
}

// Type guard kept outside the component to avoid re-creation per render.
function isErrorPayload(
  d: AxTreeData | AxTreeError | undefined,
): d is AxTreeError {
  return isError(d);
}
