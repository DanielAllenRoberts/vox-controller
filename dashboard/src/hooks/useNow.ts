import * as React from "react";

/**
 * Returns Date.now(), re-rendering every `intervalMs`. Used to keep relative
 * timestamps ("just now" / "12s") ticking without each row owning a timer.
 */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
