import { NavLink } from "react-router-dom";
import { motion } from "motion/react";
import { NAV_ITEMS } from "./nav";
import { StatusDot, type StatusKind } from "@/components/StatusDot";
import { cn } from "@/lib/utils";

// 240px persistent left nav. Active item: violet text + gradient left
// indicator + subtle surface fill (ui.md §5). Daemon status pinned bottom.
export function SideNav({ status }: { status: StatusKind }) {
  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-bg-elevated md:flex">
      <div className="flex h-14 items-center gap-2 px-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-gradient text-sm font-bold text-white">
          V
        </div>
        <span className="text-sm font-semibold tracking-tight">
          Vox Control
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3 py-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-card text-foreground"
                  : "text-foreground-secondary hover:bg-muted hover:text-foreground",
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="sidenav-indicator"
                    className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-brand-gradient"
                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                  />
                )}
                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    isActive ? "text-accent" : "",
                  )}
                />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-border px-5 py-4">
        <StatusDot status={status} />
      </div>
    </aside>
  );
}
