import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CornerDownLeft,
  Drama,
  ExternalLink,
  Search,
  type LucideIcon,
} from "lucide-react";
import { NAV_ITEMS } from "@/components/layout/nav";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { cn } from "@/lib/utils";

// --- Command palette ---------------------------------------------------------
// Glassy ⌘K modal: fuzzy search over actions — navigate to any page, activate a
// personality, and quick links. Fully keyboard-driven (↑↓ + Enter + Esc),
// animated, theme-matched. Mounted once in AppShell. (CONTRACT.md §Theme/craft)

type CommandGroup = "Navigate" | "Personalities" | "Links";

interface Command {
  id: string;
  label: string;
  hint?: string;
  group: CommandGroup;
  icon: LucideIcon;
  keywords?: string;
  run: () => void | Promise<void>;
}

/**
 * Subsequence fuzzy match: every char of `query` appears in `text` in order.
 * Returns a score (lower = better; contiguous/early matches win) or null on miss.
 * Scoped to the palette — small, single-use, no dependency added.
 */
function fuzzyScore(query: string, text: string): number | null {
  if (!query) return 0;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  let score = 0;
  let ti = 0;
  let prevMatch = -2;
  for (let qi = 0; qi < q.length; qi++) {
    const ch = q[qi];
    const found = t.indexOf(ch, ti);
    if (found === -1) return null;
    // Penalise gaps between consecutive matched chars; reward adjacency.
    score += found - ti;
    if (found !== prevMatch + 1) score += 1;
    prevMatch = found;
    ti = found + 1;
  }
  // Prefer shorter targets when scores tie.
  return score + text.length * 0.01;
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const reduced = useReducedMotion();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);

  const close = useCallback(() => onOpenChange(false), [onOpenChange]);

  // Activate a personality, then refresh status so the TopBar chip updates.
  const activatePersonality = useCallback(
    async (id: string, name: string) => {
      setBusy(true);
      try {
        await api.setActivePersonality(id);
        await queryClient.invalidateQueries({ queryKey: ["status"] });
        await queryClient.invalidateQueries({ queryKey: ["personalities"] });
        toast({ title: `Personality → ${name}` });
        close();
      } catch (err) {
        toast({
          title: "Couldn't switch personality",
          description: err instanceof Error ? err.message : "Request failed",
          variant: "error",
        });
      } finally {
        setBusy(false);
      }
    },
    [queryClient, toast, close],
  );

  // Personalities are fetched lazily the first time the palette opens, then
  // cached by react-query; failure degrades gracefully (just no entries).
  const [personalities, setPersonalities] = useState<
    { id: string; name: string; emoji: string }[]
  >([]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    queryClient
      .fetchQuery({ queryKey: ["personalities"], queryFn: api.personalities })
      .then((data) => {
        if (cancelled) return;
        setPersonalities(
          [...data.presets, ...data.custom].map((p) => ({
            id: p.id,
            name: p.name,
            emoji: p.emoji,
          })),
        );
      })
      .catch(() => {
        /* offline / bridge down — palette still navigates */
      });
    return () => {
      cancelled = true;
    };
  }, [open, queryClient]);

  const commands = useMemo<Command[]>(() => {
    const navCmds: Command[] = NAV_ITEMS.map((item) => ({
      id: `nav:${item.to}`,
      label: item.label,
      hint: "Go to page",
      group: "Navigate",
      icon: item.icon,
      keywords: `open ${item.label} page route`,
      run: () => {
        navigate(item.to);
        close();
      },
    }));

    const personalityCmds: Command[] = personalities.map((p) => ({
      id: `personality:${p.id}`,
      label: `Activate ${p.name}`,
      hint: p.emoji,
      group: "Personalities",
      icon: Drama,
      keywords: `personality voice persona tone ${p.name}`,
      run: () => activatePersonality(p.id, p.name),
    }));

    const linkCmds: Command[] = [
      {
        id: "link:repo",
        label: "Open GitHub repo",
        hint: "github.com",
        group: "Links",
        icon: ExternalLink,
        keywords: "source code git repository",
        run: () => {
          window.open(
            "https://github.com/DanielAllenRoberts/vox-controller",
            "_blank",
            "noopener,noreferrer",
          );
          close();
        },
      },
    ];

    return [...navCmds, ...personalityCmds, ...linkCmds];
  }, [personalities, navigate, close, activatePersonality]);

  // Rank by fuzzy score across label + keywords; stable for empty query.
  const results = useMemo(() => {
    const q = query.trim();
    if (!q) return commands;
    return commands
      .map((cmd) => {
        const s = fuzzyScore(q, `${cmd.label} ${cmd.keywords ?? ""}`);
        return s === null ? null : { cmd, s };
      })
      .filter((x): x is { cmd: Command; s: number } => x !== null)
      .sort((a, b) => a.s - b.s)
      .map((x) => x.cmd);
  }, [commands, query]);

  // Group results for section headers while preserving the flat ranked order.
  const groups = useMemo(() => {
    const order: CommandGroup[] = ["Navigate", "Personalities", "Links"];
    const flat: Command[] = [];
    const sections = order
      .map((name) => {
        const items = results.filter((c) => c.group === name);
        items.forEach((c) => flat.push(c));
        return { name, items };
      })
      .filter((s) => s.items.length > 0);
    return { sections, flat };
  }, [results]);

  // Reset query/selection each time the palette opens; focus the input.
  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // focus after the open animation frame
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Clamp active index when the result set shrinks.
  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, groups.flat.length - 1)));
  }, [groups.flat.length]);

  // Keep the active row scrolled into view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-index="${active}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const n = groups.flat.length;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (n ? (a + 1) % n : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (n ? (a - 1 + n) % n : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      groups.flat[active]?.run();
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-start justify-center px-4 pt-[12vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.12 }}
        >
          {/* Scrim */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={close}
            aria-hidden
          />

          {/* Palette */}
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            className="glass relative w-full max-w-xl overflow-hidden rounded-2xl"
            initial={
              reduced ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.98 }
            }
            animate={
              reduced ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }
            }
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
            onKeyDown={onKeyDown}
          >
            {/* Accent hairline at the top edge */}
            <div className="h-px w-full bg-brand-gradient opacity-70" />

            {/* Search input */}
            <div className="flex items-center gap-3 border-b border-border px-4">
              <Search className="h-4 w-4 shrink-0 text-foreground-muted" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                placeholder="Search actions, pages, personalities…"
                className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-foreground-muted"
                spellCheck={false}
                autoComplete="off"
              />
              <kbd className="hidden rounded border border-border-strong px-1.5 py-0.5 text-[10px] text-foreground-muted sm:block">
                ESC
              </kbd>
            </div>

            {/* Results */}
            <div
              ref={listRef}
              className="max-h-[50vh] overflow-y-auto overflow-x-hidden p-2"
            >
              {groups.flat.length === 0 ? (
                <div className="px-3 py-10 text-center">
                  <p className="text-sm text-foreground-secondary">
                    No matching actions
                  </p>
                  <p className="mt-1 text-xs text-foreground-muted">
                    Try a page name or a personality.
                  </p>
                </div>
              ) : (
                groups.sections.map((section) => (
                  <div key={section.name} className="mb-1 last:mb-0">
                    <div className="px-3 pb-1 pt-2 text-overline uppercase text-foreground-muted">
                      {section.name}
                    </div>
                    {section.items.map((cmd) => {
                      const idx = groups.flat.indexOf(cmd);
                      const isActive = idx === active;
                      const Icon = cmd.icon;
                      return (
                        <button
                          key={cmd.id}
                          type="button"
                          data-index={idx}
                          onMouseMove={() => setActive(idx)}
                          onClick={() => cmd.run()}
                          disabled={busy}
                          className={cn(
                            "group flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors disabled:opacity-50",
                            isActive
                              ? "bg-muted text-foreground"
                              : "text-foreground-secondary hover:bg-muted/60",
                          )}
                        >
                          <span
                            className={cn(
                              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border text-[13px]",
                              isActive
                                ? "border-accent/40 bg-accent/10 text-accent"
                                : "border-border text-foreground-muted",
                            )}
                          >
                            {cmd.group === "Personalities" && cmd.hint ? (
                              <span aria-hidden>{cmd.hint}</span>
                            ) : (
                              <Icon className="h-4 w-4" />
                            )}
                          </span>
                          <span className="min-w-0 flex-1 truncate">
                            {cmd.label}
                          </span>
                          {cmd.group !== "Personalities" && cmd.hint && (
                            <span className="hidden truncate text-xs text-foreground-muted sm:block">
                              {cmd.hint}
                            </span>
                          )}
                          {isActive ? (
                            <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-accent" />
                          ) : (
                            <ArrowRight className="h-3.5 w-3.5 shrink-0 text-transparent group-hover:text-foreground-muted" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            {/* Footer hint bar */}
            <div className="flex items-center justify-between border-t border-border px-4 py-2 text-[11px] text-foreground-muted">
              <span className="flex items-center gap-1.5">
                <kbd className="rounded border border-border-strong px-1 py-0.5">
                  ↑
                </kbd>
                <kbd className="rounded border border-border-strong px-1 py-0.5">
                  ↓
                </kbd>
                to navigate
              </span>
              <span className="flex items-center gap-1.5">
                <kbd className="rounded border border-border-strong px-1 py-0.5">
                  ↵
                </kbd>
                to select
              </span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
