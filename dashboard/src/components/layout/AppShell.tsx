import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Outlet } from "react-router-dom";
import { SideNav } from "./SideNav";
import { TopBar } from "./TopBar";
import { HelpOverlay } from "./HelpOverlay";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import { CommandPalette } from "@/components/CommandPalette";
import { api, type Status } from "@/lib/api";
import type { StatusKind } from "@/components/StatusDot";

// App shell = persistent SideNav + sticky TopBar + scrollable content.
// Status is fetched here once and shared with the nav/topbar; pages fetch
// their own data. The command palette is mounted once here and toggled by
// Cmd/Ctrl+K (or the TopBar hint). (ui.md §5, CONTRACT.md §Theme/craft)
export function AppShell() {
  const { data, isError, isLoading } = useQuery<Status>({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 5000,
  });

  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // Global ⌘K / Ctrl+K toggle (ignored inside text fields except to open).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // g-then-key navigation + `?` opens the shortcuts help (ignores typing).
  useKeyboardShortcuts({ onHelp: () => setHelpOpen(true) });

  const status: StatusKind = isLoading
    ? "connecting"
    : isError || !data?.running
      ? "offline"
      : "online";

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <SideNav status={status} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          status={data}
          onOpenPalette={() => setPaletteOpen(true)}
          onOpenHelp={() => setHelpOpen(true)}
        />
        <main className="flex-1">
          <div className="mx-auto w-full max-w-[1200px] px-6 py-6 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <HelpOverlay open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  );
}
