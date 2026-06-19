import * as React from "react";
import { conversationStreamUrl, type Turn } from "@/lib/api";

export type StreamStatus = "connecting" | "live" | "offline";

interface UseConversationStreamResult {
  /** Chronological (oldest→newest) buffer of turns this session — chat order. */
  turns: Turn[];
  status: StreamStatus;
}

/**
 * Subscribes to WS /api/conversation/stream and appends each incoming Turn.
 *
 * Mirrors useUsageStream, but keeps turns in CHAT order (oldest first, newest at
 * the bottom) since the page renders a standard conversation. The backend pushes
 * one raw Turn JSON per utterance/reply (server.py ws.send_json). Optional `seed`
 * (the REST `conversation/recent` snapshot, which arrives newest-first) primes
 * the buffer before the first push; we reverse it into chat order. Auto-reconnects
 * with a small backoff so the feed survives daemon restarts.
 */
export function useConversationStream(
  seed: Turn[] = [],
  max = 300,
): UseConversationStreamResult {
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [status, setStatus] = React.useState<StreamStatus>("connecting");

  // Prime the buffer from the seed snapshot once it arrives (and only while we
  // haven't yet received any live turns, so streamed rows are never clobbered).
  // The REST snapshot is newest-first; reverse it into chat order.
  const seeded = React.useRef(false);
  React.useEffect(() => {
    if (seeded.current || seed.length === 0) return;
    seeded.current = true;
    const chrono = [...seed].reverse().slice(-max);
    setTurns((prev) => (prev.length ? prev : chrono));
  }, [seed, max]);

  React.useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      if (closed) return;
      setStatus((s) => (s === "live" ? s : "connecting"));
      try {
        ws = new WebSocket(conversationStreamUrl());
      } catch {
        scheduleRetry();
        return;
      }

      ws.onopen = () => setStatus("live");
      ws.onmessage = (msg) => {
        try {
          const turn = JSON.parse(msg.data) as Turn;
          if (!turn?.id) return;
          setTurns((prev) => {
            if (prev.some((t) => t.id === turn.id)) return prev;
            return [...prev, turn].slice(-max);
          });
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onerror = () => ws?.close();
      ws.onclose = () => {
        setStatus("offline");
        scheduleRetry();
      };
    };

    const scheduleRetry = () => {
      if (closed) return;
      clearTimeout(retry);
      retry = setTimeout(connect, 2000);
    };

    connect();

    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [max]);

  return { turns, status };
}
