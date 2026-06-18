import { Command, HelpCircle } from "lucide-react";
import { ListeningPulse } from "@/components/animate/ListeningPulse";
import { ThemeToggle } from "./ThemeToggle";
import { Badge } from "@/components/ui/badge";
import type { Status } from "@/lib/api";

// 56px sticky glass top bar. Left: product mark + live listening status.
// Right: theme toggle + ? help + ⌘K palette trigger + brain/personality chips
// (ui.md §5). Help/palette are opened via callbacks owned by AppShell.
export function TopBar({
  status,
  onOpenPalette,
  onOpenHelp,
}: {
  status?: Status;
  onOpenPalette?: () => void;
  onOpenHelp?: () => void;
}) {
  const listening = !!status?.running;

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b border-border px-4 backdrop-blur-md md:px-6 glass">
      <div className="flex items-center gap-3">
        <span className="font-semibold tracking-tight md:hidden">Vox</span>
        <span className="flex items-center gap-2 text-sm text-foreground-secondary">
          <ListeningPulse active={listening} />
          {listening ? "Listening" : "Offline"}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <ThemeToggle />

        <button
          type="button"
          onClick={onOpenHelp}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-strong text-foreground-muted transition-colors hover:border-accent/40 hover:text-foreground"
          aria-label="Keyboard shortcuts"
          title="Keyboard shortcuts (?)"
        >
          <HelpCircle className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={onOpenPalette}
          className="hidden items-center gap-1.5 rounded-lg border border-border-strong px-2.5 py-1 text-xs text-foreground-muted transition-colors hover:border-accent/40 hover:text-foreground sm:flex"
          aria-label="Open command palette"
        >
          <Command className="h-3 w-3" />K
        </button>

        {status && (
          <>
            <Badge variant="accent" className="font-mono">
              {status.smallBrain.model || status.smallBrain.provider}
            </Badge>
            <Badge variant="outline">{status.personality}</Badge>
          </>
        )}
      </div>
    </header>
  );
}
