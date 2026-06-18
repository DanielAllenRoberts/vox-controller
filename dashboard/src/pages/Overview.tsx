import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, Sparkles, Clock, Radio } from "lucide-react";
import { api, type Status } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { SlidingNumber } from "@/components/animate/SlidingNumber";
import { ListeningPulse } from "@/components/animate/ListeningPulse";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { StatusDot, type StatusKind } from "@/components/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

function formatUptime(seconds: number): { value: number; unit: string } {
  if (seconds < 60) return { value: Math.floor(seconds), unit: "sec" };
  if (seconds < 3600) return { value: Math.floor(seconds / 60), unit: "min" };
  if (seconds < 86400)
    return { value: Math.round((seconds / 3600) * 10) / 10, unit: "hrs" };
  return { value: Math.round((seconds / 86400) * 10) / 10, unit: "days" };
}

export function Overview() {
  const { data, isLoading, isError, error } = useQuery<Status>({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 5000,
  });

  const running = !!data?.running;
  const status: StatusKind = isLoading
    ? "connecting"
    : isError || !running
      ? "offline"
      : "online";

  const uptime = formatUptime(data?.uptimeSeconds ?? 0);

  return (
    <div>
      <PageHeader
        title="Overview"
        description="Live status of your Vox voice assistant."
        actions={<StatusDot status={status} />}
      />

      {isError && (
        <Card
          glass
          className="mb-6 flex items-center gap-3 border-danger/30 px-5 py-4 text-sm"
        >
          <Radio className="h-4 w-4 text-danger" />
          <span className="text-foreground-secondary">
            Can&apos;t reach the Vox bridge
            {error instanceof Error ? ` — ${error.message}` : ""}. Is the daemon
            running on{" "}
            <span className="font-mono">127.0.0.1:8765</span>?
          </span>
        </Card>
      )}

      <Stagger className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
        <StaggerItem>
          <MetricCard
            label="Status"
            icon={Activity}
            loading={isLoading}
            adornment={<ListeningPulse active={running} />}
            value={
              <span className={running ? "text-success" : "text-foreground-muted"}>
                {running ? "Listening" : "Offline"}
              </span>
            }
            sub={`Mode · ${data?.mode ?? "—"}`}
          />
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Uptime"
            icon={Clock}
            loading={isLoading}
            value={
              <span className="flex items-baseline gap-1.5">
                <SlidingNumber
                  value={uptime.value}
                  decimals={uptime.unit === "sec" || uptime.unit === "min" ? 0 : 1}
                />
                <span className="text-base text-foreground-muted">
                  {uptime.unit}
                </span>
              </span>
            }
            sub="Since daemon start"
          />
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Personality"
            icon={Sparkles}
            loading={isLoading}
            value={
              <span className="text-2xl">{data?.personality ?? "—"}</span>
            }
            sub="Active persona"
          />
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Small Brain"
            icon={Cpu}
            loading={isLoading}
            mono
            value={
              <span className="text-xl">
                {data?.smallBrain.model || data?.smallBrain.provider || "—"}
              </span>
            }
            sub={
              <Badge variant="outline" className="font-mono">
                {data?.smallBrain.provider ?? "—"}
              </Badge>
            }
          />
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Big Brain"
            icon={Cpu}
            loading={isLoading}
            mono
            value={
              <span className="text-xl">
                {data?.bigBrain.model || data?.bigBrain.provider || "—"}
              </span>
            }
            sub={
              <Badge variant="outline" className="font-mono">
                {data?.bigBrain.provider ?? "—"}
              </Badge>
            }
          />
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Bridge"
            icon={Radio}
            loading={isLoading}
            value={
              <span className={isError ? "text-danger" : "text-success"}>
                {isError ? "Down" : "Connected"}
              </span>
            }
            sub={<span className="font-mono text-xs">127.0.0.1:8765</span>}
          />
        </StaggerItem>
      </Stagger>
    </div>
  );
}
