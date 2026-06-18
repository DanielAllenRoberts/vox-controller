// --- Keyboard shortcut registry ---------------------------------------------
// Single source of truth for the dashboard's keyboard map, consumed by the
// global handler (useKeyboardShortcuts) and the help overlay so they never
// drift. The g-then-key set mirrors the SideNav / CONTRACT.md routes.

export interface GoShortcut {
  /** Second key pressed after `g`. */
  key: string;
  /** Destination route. */
  to: string;
  /** Human label for the help overlay. */
  label: string;
}

// `g` then <key> → navigate. Order matches the SideNav.
export const GO_SHORTCUTS: GoShortcut[] = [
  { key: "o", to: "/", label: "Overview" },
  { key: "u", to: "/usage", label: "Token Usage" },
  { key: "s", to: "/settings", label: "Settings" },
  { key: "p", to: "/personalities", label: "Personalities" },
  { key: "a", to: "/axtree", label: "AX Tree" },
  { key: "r", to: "/rules", label: "Rules" },
  { key: "m", to: "/memory", label: "Memory" },
];

export interface ShortcutDoc {
  /** Key tokens rendered as <kbd> chips, in order. */
  keys: string[];
  description: string;
}

// Non-navigation global shortcuts, for the help overlay.
export const GLOBAL_SHORTCUTS: ShortcutDoc[] = [
  { keys: ["⌘", "K"], description: "Open command palette (Ctrl K on Windows/Linux)" },
  { keys: ["?"], description: "Open this shortcuts help" },
  { keys: ["Esc"], description: "Close any overlay" },
];
