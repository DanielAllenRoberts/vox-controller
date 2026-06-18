import * as React from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import {
  Search,
  Copy,
  Check,
  BookOpen,
  Mic,
  Keyboard,
  Power,
  Sparkles,
  Command,
  Layers,
  Boxes,
  KeyRound,
  ChevronDown,
  ChevronRight,
  X,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/useToast";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { cn } from "@/lib/utils";
import { api, type HandbookGroup, type HandbookItem } from "@/lib/api";

// ---------------------------------------------------------------------------
// Handbook client.
//
// The catalog comes from GET /api/handbook (see src/vox/web/server.py
// _handbook), via the shared typed client (api.handbook). Live phrase groups
// (pulled from CONFIG) come first, then curated static groups (commands /
// modes / features). We normalise the response defensively here so a partial
// or malformed payload can't crash the render — fields may be absent if the
// bridge changes. A network error surfaces as the error state and never throws
// past the query boundary.
// ---------------------------------------------------------------------------

async function fetchHandbook(): Promise<HandbookGroup[]> {
  const data = await api.handbook();
  if (!Array.isArray(data)) return [];
  return data
    .filter(
      (g): g is HandbookGroup =>
        !!g && typeof g.title === "string" && Array.isArray(g.items),
    )
    .map((g) => ({
      title: g.title,
      blurb: typeof g.blurb === "string" ? g.blurb : undefined,
      items: g.items
        .filter(
          (it): it is HandbookItem =>
            !!it &&
            typeof it.phrase === "string" &&
            typeof it.description === "string",
        )
        // Preserve curated alternative phrasings when present, keeping only
        // the well-formed string entries so a malformed variant can't break
        // the popover render.
        .map((it) => ({
          phrase: it.phrase,
          description: it.description,
          variants: Array.isArray(it.variants)
            ? it.variants.filter((v): v is string => typeof v === "string")
            : undefined,
        })),
    }))
    .filter((g) => g.items.length > 0);
}

const HANDBOOK_KEY = ["handbook"] as const;

// ---------------------------------------------------------------------------
// Per-group icon. Matched on the title the bridge sends (case-insensitive
// substring) so new groups still get a sensible default rather than nothing.
// ---------------------------------------------------------------------------

function iconForGroup(title: string): LucideIcon {
  const t = title.toLowerCase();
  if (t.includes("wake") || t.includes("activation")) return Mic;
  if (t.includes("dictation")) return Keyboard;
  if (t.includes("sleep") || t.includes("stop") || t.includes("quit"))
    return Power;
  if (t.includes("escalation") || t.includes("keyword")) return KeyRound;
  if (t.includes("command")) return Command;
  if (t.includes("mode")) return Layers;
  if (t.includes("feature")) return Boxes;
  return Sparkles;
}

// ---------------------------------------------------------------------------
// Search: case-insensitive substring across phrase + description + variants +
// group title. Returns the groups with only their matching items; groups that
// end up empty are dropped by the caller. Matching on variants means searching
// e.g. "go to sleep" surfaces the item whose canonical phrase is "stand down".
// ---------------------------------------------------------------------------

function filterGroups(
  groups: HandbookGroup[],
  query: string,
): HandbookGroup[] {
  const q = query.trim().toLowerCase();
  if (!q) return groups;
  const out: HandbookGroup[] = [];
  for (const g of groups) {
    const titleHit = g.title.toLowerCase().includes(q);
    const items = titleHit
      ? g.items
      : g.items.filter(
          (it) =>
            it.phrase.toLowerCase().includes(q) ||
            it.description.toLowerCase().includes(q) ||
            (it.variants ?? []).some((v) => v.toLowerCase().includes(q)),
        );
    if (items.length > 0) out.push({ ...g, items });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Copy helper — shared by the plain phrase row and every variant in the
// popover. Returns the toast-firing copy fn plus a transient "copied" flag so
// each call site can show its own check-mark affordance.
// ---------------------------------------------------------------------------

function useCopy() {
  const { toast } = useToast();
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const copy = React.useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 1400);
        toast({ variant: "success", title: "Copied", description: text });
      } catch {
        toast({
          variant: "error",
          title: "Couldn't copy",
          description: "Clipboard access was blocked.",
        });
      }
    },
    [toast],
  );

  return { copy, copied };
}

// ---------------------------------------------------------------------------
// Variant popover — a small panel anchored to a phrase row. Lists the canonical
// phrase plus each curated alternative, each individually click-to-copy. Closes
// on outside-click and Esc; arrow keys move between rows and focus returns to
// the trigger on close. Rendered only for items that actually have variants.
//
// Rendered through a portal to document.body so it escapes the accordion body's
// `overflow-hidden` (used for the height animation), which would otherwise clip
// it. It's anchored with `position: fixed` coordinates computed from the
// trigger's bounding box, repositioned on scroll/resize while open. The panel
// is `width: max-content` so every variant name fits without truncation.
// ---------------------------------------------------------------------------

// Gap between the trigger row and the popover, and the minimum margin we keep
// from the viewport edges when clamping the panel's left coordinate.
const POPOVER_GAP = 6;
const VIEWPORT_MARGIN = 12;

function VariantPopover({
  item,
  onClose,
  triggerRef,
}: {
  item: HandbookItem;
  onClose: () => void;
  triggerRef: React.RefObject<HTMLButtonElement>;
}) {
  const reduced = useReducedMotion();
  const panelRef = React.useRef<HTMLDivElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const { copy, copied } = useCopy();
  const [justCopied, setJustCopied] = React.useState<number | null>(null);
  const [pos, setPos] = React.useState<{
    top: number;
    left: number;
    maxHeight: number;
  } | null>(null);

  // Canonical phrase first, then the curated alternatives.
  const phrases = React.useMemo(
    () => [item.phrase, ...(item.variants ?? [])],
    [item],
  );

  // Compute fixed coordinates from the trigger's box. Horizontally: left-aligned
  // to the trigger, clamped within the viewport. Vertically: open below the
  // trigger by default, but FLIP above it when there isn't enough room below.
  // Whichever side has more room wins if neither fully fits, and the panel's
  // height is capped to the available space (so a long variant list scrolls
  // internally rather than spilling off-screen). Every coordinate is clamped so
  // the panel always stays fully on-screen.
  const reposition = React.useCallback(() => {
    const trigger = triggerRef.current;
    const panel = panelRef.current;
    if (!trigger || !panel) return;
    const rect = trigger.getBoundingClientRect();

    // Horizontal: left-align to the trigger, clamp to the viewport.
    const panelWidth = panel.offsetWidth;
    const maxLeft = Math.max(
      VIEWPORT_MARGIN,
      window.innerWidth - panelWidth - VIEWPORT_MARGIN,
    );
    const left = Math.min(Math.max(rect.left, VIEWPORT_MARGIN), maxLeft);

    // Vertical: measure the panel's NATURAL height, then decide below vs. above
    // based on the room available on each side of the trigger row. We derive the
    // natural height from the fixed chrome (panel minus the scrollable list) plus
    // the list's `scrollHeight` — not the panel's own `offsetHeight`, which is
    // already capped by `maxHeight` once set and so couldn't recover space on a
    // later scroll/resize.
    const scrollEl = scrollRef.current;
    const chrome = scrollEl
      ? panel.offsetHeight - scrollEl.offsetHeight
      : panel.offsetHeight;
    const panelHeight = scrollEl
      ? chrome + scrollEl.scrollHeight
      : panel.offsetHeight;
    const spaceBelow = window.innerHeight - rect.bottom - POPOVER_GAP;
    const spaceAbove = rect.top - POPOVER_GAP;

    let top: number;
    let maxHeight: number;
    if (panelHeight <= spaceBelow - VIEWPORT_MARGIN) {
      // Fits below as-is.
      top = rect.bottom + POPOVER_GAP;
      maxHeight = spaceBelow - VIEWPORT_MARGIN;
    } else if (panelHeight <= spaceAbove - VIEWPORT_MARGIN) {
      // Doesn't fit below but fits above — flip up.
      top = rect.top - POPOVER_GAP - panelHeight;
      maxHeight = spaceAbove - VIEWPORT_MARGIN;
    } else if (spaceBelow >= spaceAbove) {
      // Fits neither side; open on whichever has more room and cap the height.
      maxHeight = Math.max(0, spaceBelow - VIEWPORT_MARGIN);
      top = rect.bottom + POPOVER_GAP;
    } else {
      maxHeight = Math.max(0, spaceAbove - VIEWPORT_MARGIN);
      top = rect.top - POPOVER_GAP - maxHeight;
    }

    // Final vertical clamp so the panel never bleeds past either edge even if
    // its measured height and the chosen space disagree by a pixel.
    top = Math.min(
      Math.max(top, VIEWPORT_MARGIN),
      Math.max(VIEWPORT_MARGIN, window.innerHeight - VIEWPORT_MARGIN - maxHeight),
    );

    setPos({ top, left, maxHeight });
  }, [triggerRef]);

  // Position before paint to avoid a flash at the wrong spot, then keep it
  // pinned to the trigger on scroll/resize while open.
  React.useLayoutEffect(() => {
    reposition();
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [reposition]);

  // Move focus into the panel on open so keyboard users land on the first
  // option; restore focus to the trigger on unmount (close).
  React.useEffect(() => {
    const first = panelRef.current?.querySelector<HTMLButtonElement>(
      "[data-variant-option]",
    );
    first?.focus();
    return () => triggerRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Outside-click + Esc close. Pointerdown (not click) so the close fires
  // before the trigger's own click handler can re-toggle it open.
  React.useEffect(() => {
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t)) return;
      if (triggerRef.current?.contains(t)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose, triggerRef]);

  // Roving arrow-key navigation between the option buttons.
  const onListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const opts = Array.from(
      panelRef.current?.querySelectorAll<HTMLButtonElement>(
        "[data-variant-option]",
      ) ?? [],
    );
    if (opts.length === 0) return;
    e.preventDefault();
    const idx = opts.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      e.key === "ArrowDown"
        ? (idx + 1) % opts.length
        : (idx - 1 + opts.length) % opts.length;
    opts[next]?.focus();
  };

  const onCopy = (text: string, idx: number) => {
    void copy(text);
    setJustCopied(idx);
    window.setTimeout(() => setJustCopied(null), 1400);
  };

  return createPortal(
    <motion.div
      ref={panelRef}
      role="dialog"
      aria-label="Other ways to say it"
      onKeyDown={onListKeyDown}
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: -4, scale: 0.98 }}
      animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, y: -4, scale: 0.98 }}
      transition={{ duration: 0.14, ease: "easeOut" }}
      // Fixed-positioned and portalled to <body> so no `overflow-hidden`
      // ancestor can clip it. `width: max-content` (capped) lets every variant
      // name fit; the panel is hidden until its position is measured. `maxHeight`
      // caps it to the available vertical space (set once measured) so a long
      // variant list scrolls internally instead of spilling off-screen.
      style={{
        position: "fixed",
        top: pos?.top ?? 0,
        left: pos?.left ?? 0,
        width: "max-content",
        maxWidth: `calc(100vw - ${VIEWPORT_MARGIN * 2}px)`,
        maxHeight: pos ? pos.maxHeight : undefined,
        visibility: pos ? "visible" : "hidden",
      }}
      className="z-50 flex origin-top-left flex-col rounded-xl border border-border-strong bg-popover/95 p-1.5 shadow-lg backdrop-blur-md"
    >
      <p className="shrink-0 px-2.5 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-foreground-muted">
        Other ways to say it
      </p>
      <div ref={scrollRef} className="flex min-h-0 flex-col overflow-y-auto">
        {phrases.map((p, i) => {
          const isCopied = justCopied === i && copied;
          return (
            <button
              key={`${p}-${i}`}
              type="button"
              data-variant-option
              onClick={() => onCopy(p, i)}
              aria-label={`Copy “${p}”`}
              className="group/opt flex items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
            >
              <code className="flex-1 whitespace-normal break-words font-mono text-[13px] font-medium leading-snug text-foreground">
                {p}
              </code>
              {i === 0 && (
                <Badge
                  variant="outline"
                  className="shrink-0 px-1.5 py-0 text-[10px] font-normal"
                >
                  canonical
                </Badge>
              )}
              <span
                aria-hidden
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-all",
                  isCopied
                    ? "bg-success/15 text-success"
                    : "text-foreground-muted opacity-0 group-hover/opt:opacity-100 group-focus-visible/opt:opacity-100",
                )}
              >
                {isCopied ? (
                  <Check className="h-3.5 w-3.5" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </span>
            </button>
          );
        })}
      </div>
    </motion.div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Phrase row. An item with no variants behaves exactly as before — click copies
// the phrase with a toast. An item WITH variants instead opens a popover (see
// VariantPopover) listing the canonical phrase plus every alternative, each
// individually copyable; a "+N" chip on the row signals it's expandable.
// ---------------------------------------------------------------------------

function PhraseRow({ item }: { item: HandbookItem }) {
  const { copy, copied } = useCopy();
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const [open, setOpen] = React.useState(false);

  const variants = item.variants ?? [];
  const hasVariants = variants.length > 0;

  const onClick = () => {
    if (hasVariants) {
      setOpen((v) => !v);
    } else {
      void copy(item.phrase);
    }
  };

  // One reference row. A 3-column grid keeps the page aligned like a document:
  //  [ phrase | description | copy/expand affordance ]
  // The phrase column is a fixed, consistent width (sm+) so every phrase across
  // every section lines up in one left rail. On narrow screens the grid
  // collapses to a single column and the description stacks under the phrase.
  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={onClick}
        aria-label={
          hasVariants
            ? `Other ways to say “${item.phrase}”`
            : `Copy “${item.phrase}”`
        }
        aria-haspopup={hasVariants ? "dialog" : undefined}
        aria-expanded={hasVariants ? open : undefined}
        className="group/row grid w-full grid-cols-1 items-start gap-x-6 gap-y-1 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 sm:grid-cols-[minmax(0,12rem)_1fr_auto]"
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <code className="break-words font-mono text-[13px] font-medium leading-relaxed text-foreground">
            {item.phrase}
          </code>
          {hasVariants && (
            <Badge
              variant="outline"
              className="shrink-0 gap-0.5 px-1.5 py-0 text-[10px] font-normal tabular-nums text-foreground-secondary"
            >
              +{variants.length}
            </Badge>
          )}
        </span>
        <p className="text-xs leading-relaxed text-foreground-secondary sm:pt-px sm:text-[13px]">
          {item.description}
        </p>
        <span
          aria-hidden
          className={cn(
            "hidden h-6 w-6 shrink-0 items-center justify-center rounded-md transition-all sm:flex",
            copied && !hasVariants
              ? "bg-success/15 text-success"
              : "text-foreground-muted opacity-0 group-hover/row:opacity-100 group-focus-visible/row:opacity-100",
            hasVariants && open && "opacity-100",
          )}
        >
          {hasVariants ? (
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 transition-transform duration-200",
                open && "rotate-180",
              )}
            />
          ) : copied ? (
            <Check className="h-3.5 w-3.5" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </span>
      </button>

      <AnimatePresence>
        {hasVariants && open && (
          <VariantPopover
            item={item}
            triggerRef={triggerRef}
            onClose={() => setOpen(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group section — a collapsible document section. The header (icon + title +
// count + chevron) is a button that toggles the body open/closed; the body
// expands/collapses with a height-auto animation. Sections default to collapsed
// so the page opens as a scannable index, and each expands independently.
// When a search is active the parent forces every matching section open.
// ---------------------------------------------------------------------------

function GroupSection({
  group,
  open,
  onToggle,
}: {
  group: HandbookGroup;
  open: boolean;
  onToggle: () => void;
}) {
  const Icon = iconForGroup(group.title);
  const reduced = useReducedMotion();
  const bodyId = `handbook-section-${group.title.replace(/\s+/g, "-")}`;

  return (
    <section className="py-8 first:pt-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className="group/header flex w-full items-center gap-3 rounded-lg text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent">
          <Icon className="h-4 w-4" />
        </span>
        <h2 className="text-base font-semibold tracking-tight text-foreground">
          {group.title}
        </h2>
        <Badge variant="outline" className="font-normal tabular-nums">
          {group.items.length}
        </Badge>
        <ChevronRight
          aria-hidden
          className={cn(
            "ml-auto h-4 w-4 text-foreground-muted transition-transform duration-200 group-hover/header:text-foreground-secondary",
            open && "rotate-90",
          )}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={bodyId}
            key="body"
            initial={reduced ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={
              reduced ? { opacity: 1 } : { height: "auto", opacity: 1 }
            }
            exit={reduced ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            {group.blurb && (
              <p className="mt-2 max-w-prose text-sm leading-relaxed text-foreground-secondary">
                {group.blurb}
              </p>
            )}

            {/* Aligned reference list — one row per phrase, divided by hairlines
                so the rows scan like rows of a table without the card chrome. */}
            <div className="mt-4 flex flex-col divide-y divide-border/60">
              {group.items.map((it, i) => (
                <PhraseRow key={`${it.phrase}-${i}`} item={it} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

// ---------------------------------------------------------------------------
// States.
// ---------------------------------------------------------------------------

// Single centered reading column shared by every state so the page always
// reads like one structured document.
const COLUMN = "mx-auto max-w-3xl";

function GroupSkeleton() {
  return (
    <div className="border-t border-border py-8 first:border-t-0 first:pt-0">
      <div className="flex items-center gap-3">
        <Skeleton className="h-8 w-8 rounded-lg" />
        <Skeleton className="h-4 w-40" />
      </div>
      <Skeleton className="mt-3 h-3 w-3/4" />
      <div className="mt-5 space-y-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-[minmax(0,12rem)_1fr]"
          >
            <Skeleton className="h-3.5 w-2/3" />
            <Skeleton className="h-3.5 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className={COLUMN}>
      {[0, 1, 2, 3, 4].map((i) => (
        <GroupSkeleton key={i} />
      ))}
    </div>
  );
}

function ErrorState() {
  return (
    <FadeIn>
      <Card
        glass
        className="border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
      >
        Can&apos;t reach the Vox bridge to load the handbook. Is the daemon
        running on <span className="font-mono">127.0.0.1:8765</span>? It&apos;ll
        appear once the bridge is back.
      </Card>
    </FadeIn>
  );
}

function NoResults({ query, onClear }: { query: string; onClear: () => void }) {
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-14 text-center"
      >
        <span className="pointer-events-none absolute -top-10 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <Search className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          Nothing matches “{query}”
        </h3>
        <p className="mt-1 max-w-md text-sm text-foreground-secondary">
          Try a different word — search runs across every phrase, command and
          feature.
        </p>
        <Button variant="outline" size="sm" onClick={onClear} className="mt-4">
          <X className="h-3.5 w-3.5" />
          Clear search
        </Button>
      </Card>
    </FadeIn>
  );
}

function EmptyState() {
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-14 text-center"
      >
        <span className="pointer-events-none absolute -top-10 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <BookOpen className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          The handbook is empty
        </h3>
        <p className="mt-1 max-w-md text-sm text-foreground-secondary">
          Vox didn&apos;t return any reference entries. This usually clears up
          once the daemon and its config are fully loaded.
        </p>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Search box.
// ---------------------------------------------------------------------------

function SearchBox({
  value,
  onChange,
  resultCount,
}: {
  value: string;
  onChange: (v: string) => void;
  resultCount: number;
}) {
  const ref = React.useRef<HTMLInputElement>(null);

  // "/" focuses the search box (a familiar reference-doc affordance), unless
  // the user is already typing in a field.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/") return;
      const el = document.activeElement;
      const typing =
        el instanceof HTMLInputElement ||
        el instanceof HTMLTextAreaElement ||
        (el instanceof HTMLElement && el.isContentEditable);
      if (typing) return;
      e.preventDefault();
      ref.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" />
      <Input
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            e.preventDefault();
            onChange("");
          }
        }}
        placeholder="Search everything you can say and do…"
        aria-label="Search the handbook"
        className="h-11 pl-10 pr-28 text-sm"
      />
      <div className="absolute right-2.5 top-1/2 flex -translate-y-1/2 items-center gap-2">
        {value ? (
          <>
            <span className="text-[11px] tabular-nums text-foreground-muted">
              {resultCount} match{resultCount === 1 ? "" : "es"}
            </span>
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => onChange("")}
              className="flex h-6 w-6 items-center justify-center rounded-md text-foreground-muted transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </>
        ) : (
          <kbd className="hidden items-center rounded-md border border-border-strong px-1.5 py-0.5 font-mono text-[10px] text-foreground-muted sm:inline-flex">
            /
          </kbd>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Handbook() {
  const [query, setQuery] = React.useState("");
  // Sections default to CLOSED, so we track the EXPANDED ones (by title). A
  // title in this set is open; everything else is collapsed. An empty set means
  // all sections start collapsed on load.
  const [expanded, setExpanded] = React.useState<Set<string>>(
    () => new Set(),
  );

  const { data, isLoading, isError } = useQuery({
    queryKey: HANDBOOK_KEY,
    queryFn: fetchHandbook,
    staleTime: 60_000,
  });

  const groups = data ?? [];
  const filtered = React.useMemo(
    () => filterGroups(groups, query),
    [groups, query],
  );

  // A live search forces every matching section open so results are always
  // visible regardless of the user's collapse state.
  const searching = query.trim().length > 0;

  // Total phrases across the (possibly filtered) catalog — drives the search
  // result count and the header badge.
  const totalItems = React.useMemo(
    () => groups.reduce((n, g) => n + g.items.length, 0),
    [groups],
  );
  const matchCount = React.useMemo(
    () => filtered.reduce((n, g) => n + g.items.length, 0),
    [filtered],
  );

  const toggleSection = React.useCallback((title: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(title)) next.delete(title);
      else next.add(title);
      return next;
    });
  }, []);

  // Expand-all bases its set on the currently loaded/filtered group titles so
  // it works even though groups load async (empty before the query resolves).
  const expandAll = React.useCallback(
    () => setExpanded(new Set(filtered.map((g) => g.title))),
    [filtered],
  );
  const collapseAll = React.useCallback(() => setExpanded(new Set()), []);

  // True when at least one visible section is currently open (ignoring the
  // search-forced-open override) — drives the expand/collapse toggle label.
  const anyOpen = filtered.some((g) => expanded.has(g.title));

  return (
    <div>
      <PageHeader
        title="Handbook"
        description="Everything you can say and do — wake phrases, control commands, modes and features, in one searchable reference."
        actions={
          !isLoading && !isError && totalItems > 0 ? (
            <Badge variant="accent" className="font-normal">
              <BookOpen className="h-3 w-3" />
              {totalItems} entries
            </Badge>
          ) : undefined
        }
      />

      <div className={COLUMN}>
        <FadeIn className="mb-6 flex flex-col gap-2.5 sm:flex-row sm:items-center">
          <div className="flex-1">
            <SearchBox
              value={query}
              onChange={setQuery}
              resultCount={matchCount}
            />
          </div>
          {!isLoading && !isError && filtered.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={anyOpen ? collapseAll : expandAll}
              disabled={searching}
              className="shrink-0 self-start sm:self-auto"
              aria-label={anyOpen ? "Collapse all sections" : "Expand all sections"}
            >
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition-transform",
                  !anyOpen && "-rotate-90",
                )}
              />
              {anyOpen ? "Collapse all" : "Expand all"}
            </Button>
          )}
        </FadeIn>
      </div>

      {isError ? (
        <div className={COLUMN}>
          <ErrorState />
        </div>
      ) : isLoading ? (
        <LoadingState />
      ) : groups.length === 0 ? (
        <div className={COLUMN}>
          <EmptyState />
        </div>
      ) : filtered.length === 0 ? (
        <div className={COLUMN}>
          <NoResults query={query.trim()} onClear={() => setQuery("")} />
        </div>
      ) : (
        <Stagger
          // Re-key on the query so a new filter re-runs the stagger entrance.
          key={query.trim()}
          className={cn(COLUMN, "divide-y divide-border")}
        >
          {filtered.map((g) => (
            <StaggerItem key={g.title}>
              <GroupSection
                group={g}
                // While searching, force every matching section open.
                open={searching || expanded.has(g.title)}
                onToggle={() => toggleSection(g.title)}
              />
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  );
}
