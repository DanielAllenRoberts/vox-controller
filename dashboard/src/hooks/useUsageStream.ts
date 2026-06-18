import * as React from "react";
import { usageStreamUrl, type UsageEvent } from "@/lib/api";

export type StreamStatus = "connecting" | "live" | "offline";

interface UseUsageStreamResult {
  /** Newest-first buffer of events received over the WS this session. */
  events: UsageEvent[];
  status: StreamStatus;
}

/**
 * Subscribes to WS /api/usage/stream and prepends each incoming UsageEvent.
 *
 * The backend pushes one raw UsageEvent JSON per LLM call (server.py
 * ws.send_json). We keep a bounded, newest-first buffer and auto-reconnect with
 * a small backoff so the live feed survives daemon restarts. Optional `seed`
 * (e.g. the REST `usage/recent` snapshot) primes the feed before the first push.
 */
export function useUsageStream(
  seed: UsageEvent[] = [],
  max = 100,
): UseUsageStreamResult {
  const [events, setEvents] = React.useState<UsageEvent[]>([]);
  const [status, setStatus] = React.useState<StreamStatus>("connecting");

  // Prime the feed from the seed snapshot once it arrives (and only while we
  // haven't yet received any live events, so streamed rows are never clobbered).
  const seeded = React.useRef(false);
  React.useEffect(() => {
    if (seeded.current || seed.length === 0) return;
    seeded.current = true;
    setEvents((prev) => (prev.length ? prev : seed.slice(0, max)));
  }, [seed, max]);

  React.useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      if (closed) return;
      setStatus((s) => (s === "live" ? s : "connecting"));
      try {
        ws = new WebSocket(usageStreamUrl());
      } catch {
        scheduleRetry();
        return;
      }

      ws.onopen = () => setStatus("live");
      ws.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data) as UsageEvent;
          if (!event?.id) return;
          setEvents((prev) => {
            if (prev.some((e) => e.id === event.id)) return prev;
            return [event, ...prev].slice(0, max);
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

  return { events, status };
}
