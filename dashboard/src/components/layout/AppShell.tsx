import { useQuery } from "@tanstack/react-query";
import { Outlet } from "react-router-dom";
import { SideNav } from "./SideNav";
import { TopBar } from "./TopBar";
import { api, type Status } from "@/lib/api";
import type { StatusKind } from "@/components/StatusDot";

// App shell = persistent SideNav + sticky TopBar + scrollable content.
// Status is fetched here once and shared with the nav/topbar; pages fetch
// their own data. (ui.md §5)
export function AppShell() {
  const { data, isError, isLoading } = useQuery<Status>({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 5000,
  });

  const status: StatusKind = isLoading
    ? "connecting"
    : isError || !data?.running
      ? "offline"
      : "online";

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <SideNav status={status} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar status={data} />
        <main className="flex-1">
          <div className="mx-auto w-full max-w-[1200px] px-6 py-6 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
