import {
  LayoutDashboard,
  Coins,
  Settings,
  Drama,
  Network,
  ScrollText,
  TerminalSquare,
  Brain,
  Plug,
  BookOpen,
  MessagesSquare,
  AlarmClock,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

// The 7 original pages + Integrations + Handbook (mirrors src/pages/* and
// CONTRACT.md routes; Integrations surfaces the vox-speak MCP setup per
// MEMORY_DESIGN.md; Handbook is the catalog of what Vox can do).
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/conversation", label: "Conversation", icon: MessagesSquare },
  { to: "/scheduler", label: "Scheduler", icon: AlarmClock },
  { to: "/usage", label: "Token Usage", icon: Coins },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/personalities", label: "Personalities", icon: Drama },
  { to: "/axtree", label: "AX Tree", icon: Network },
  { to: "/rules", label: "Rules", icon: ScrollText },
  { to: "/commands", label: "Commands", icon: TerminalSquare },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/handbook", label: "Handbook", icon: BookOpen },
];
