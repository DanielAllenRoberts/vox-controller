import {
  LayoutDashboard,
  Coins,
  Settings,
  Drama,
  Network,
  ScrollText,
  Brain,
  Plug,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

// The 7 original pages + Integrations (mirrors src/pages/* and CONTRACT.md
// routes; Integrations surfaces the vox-speak MCP setup per MEMORY_DESIGN.md).
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/usage", label: "Token Usage", icon: Coins },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/personalities", label: "Personalities", icon: Drama },
  { to: "/axtree", label: "AX Tree", icon: Network },
  { to: "/rules", label: "Rules", icon: ScrollText },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/integrations", label: "Integrations", icon: Plug },
];
