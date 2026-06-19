import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { MessagesSquare, Radio, Terminal } from "lucide-react";
import { api, type Turn } from "@/lib/api";
import { cn, relativeTime } from "@/lib/utils";
import { useNow } from "@/hooks/useNow";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useConversationStream } from "@/hooks/useConversationStream";
import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// A short, stable label for a session id (first 6 chars) so concurrent sessions
// are visually distinguishable without dumping the full hash.
function shortSession(id: string): string {
  return id ? id.slice(0, 6) : "—";
}

function CommandBubble({ turn, now }: { turn: Turn; now: number }) {
  // A command that ran (control action / deterministic command mid-chat) renders
  // inline as a neutral system line rather than a chat bubble.
  return (
    <div className="flex justify-center px-2 py-1">
      <div className="flex max-w-[80%] items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-1.5 text-xs text-foreground-secondary">
        <Terminal className="h-3.5 w-3.5 shrink-0 text-foreground-muted" />
        <span className="truncate font-mono">{turn.text}</span>
        <span className="shrink-0 tnum text-[10px] text-foreground-muted">
          {relativeTime(turn.ts, now)}
        </span>
      </div>
    </div>
  );
}

function ChatBubble({ turn, now }: { turn: Turn; now: number }) {
  const isUser = turn.role === "user";
  return (
    <div className={cn("flex px-2 py-1.5", isUser ? "justify-end" : "justify-start")}>
      <div className={cn("flex max-w-[78%] flex-col gap-1", isUser ? "items-end" : "items-start")}>
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-foreground-muted">
            {isUser ? "You" : "Vox"}
          </span>
          {!isUser && turn.brain && (
            <Badge
              variant={turn.brain === "big" ? "accent" : "outline"}
              className="px-1.5 py-0 text-[10px] uppercase"
            >
              {turn.brain}
            </Badge>
          )}
          <span className="tnum text-[10px] text-foreground-muted">
            {relativeTime(turn.ts, now)}
          </span>
        </div>
        <div
          className={cn(
            "whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
            isUser
              ? "rounded-br-sm bg-accent/15 text-foreground"
              : "rounded-bl-sm border border-border bg-card text-foreground",
          )}
        >
          {turn.text}
        </div>
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: "connecting" | "live" | "offline" }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "live"
            ? "bg-success shadow-[0_0_6px_hsl(var(--success))]"
            : status === "connecting"
              ? "bg-warning"
              : "bg-foreground-muted",
        )}
      />
      <span className="text-[10px] uppercase tracking-wide text-foreground-muted">
        {status}
      </span>
    </span>
  );
}

export function Conversation() {
  const now = useNow(1000);
  const reduced = useReducedMotion();

  const { data: recent } = useQuery<Turn[]>({
    queryKey: ["conversation", "recent"],
    queryFn: () => api.conversationRecent(300),
    refetchInterval: false,
  });

  const { turns, status } = useConversationStream(recent ?? [], 300);

  // How many distinct sessions are in view — only surfaced when >1 (the common
  // case is a single running session; the label is noise otherwise).
  const sessions = React.useMemo(
    () => Array.from(new Set(turns.map((t) => t.session))),
    [turns],
  );
  const multiSession = sessions.length > 1;

  // Auto-scroll to the newest turn as it streams in.
  const endRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: reduced ? "auto" : "smooth" });
  }, [turns.length, reduced]);

  return (
    <div>
      <PageHeader
        title="Conversation"
        description="The running session, live. Ephemeral by design — nothing is written to disk."
        actions={<StatusDot status={status} />}
      />

      <Card glass className="flex h-[calc(100vh-13rem)] flex-col p-5">
        <div className="mb-2 flex items-center justify-between px-1">
          <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
            <Radio className="h-3.5 w-3.5" />
            Live chat
          </span>
          {multiSession && (
            <Badge variant="info" className="px-1.5 py-0 text-[10px]">
              {sessions.length} sessions
            </Badge>
          )}
        </div>

        {turns.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
            <MessagesSquare className="h-7 w-7 text-foreground-muted" />
            <p className="text-sm text-foreground-secondary">No conversation yet</p>
            <p className="max-w-[22rem] text-xs text-foreground-muted">
              Talk to Vox — your utterances, its replies, and any command that runs
              stream in here the moment they happen.
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto pr-1">
            <AnimatePresence initial={false}>
              {turns.map((t) => (
                <motion.div
                  key={t.id}
                  layout={!reduced}
                  initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
                  animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0 }}
                  transition={{ type: "spring", stiffness: 400, damping: 36 }}
                >
                  {multiSession && (
                    <div className="px-2 pt-1 text-[9px] uppercase tracking-wide text-foreground-muted">
                      session {shortSession(t.session)}
                    </div>
                  )}
                  {t.kind === "command" ? (
                    <CommandBubble turn={t} now={now} />
                  ) : (
                    <ChatBubble turn={t} now={now} />
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
            <div ref={endRef} />
          </div>
        )}
      </Card>
    </div>
  );
}
