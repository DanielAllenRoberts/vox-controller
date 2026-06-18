import { type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import {
  Activity,
  Cpu,
  Sparkles,
  Clock,
  Radio,
  Coins,
  Drama,
  Settings as SettingsIcon,
  Network,
  TrendingUp,
  HeartPulse,
  MemoryStick,
  AudioWaveform,
  BrainCircuit,
  Gauge,
  type LucideIcon,
} from "lucide-react";
import {
  api,
  type Status,
  type UsageSummary,
  type UsageEvent,
  type Diagnostics,
  type DiagnosticsBrain,
} from "@/lib/api";
import { formatCost, todayKey } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { SlidingNumber } from "@/components/animate/SlidingNumber";
import { ListeningPulse } from "@/components/animate/ListeningPulse";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { FadeIn } from "@/components/animate/FadeIn";
import { StatusDot, type StatusKind } from "@/components/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { LiveFeed } from "@/components/usage/LiveFeed";
import { useUsageStream } from "@/hooks/useUsageStream";

function formatUptime(seconds: number): { value: number; unit: string } {
  if (seconds < 60) return { value: Math.floor(seconds), unit: "sec" };
  if (seconds < 3600) return { value: Math.floor(seconds / 60), unit: "min" };
  if (seconds < 86400)
    return { value: Math.round((seconds / 3600) * 10) / 10, unit: "hrs" };
  return { value: Math.round((seconds / 86400) * 10) / 10, unit: "days" };
}

// ---------------------------------------------------------------------------
// Diagnostics (GET /api/diagnostics) via the typed `api.diagnostics()` client.
//
// The route returns the nested health snapshot, or an { error } envelope at
// HTTP 200 when its bridge module is absent. Every field is read defensively so
// the card degrades gracefully if the backend hands back its "unknown" sentinel
// (off-mac, missing psutil, etc).
// ---------------------------------------------------------------------------

// A single labelled stat row inside the System health card. Optional accent
// colour for the value (used to flag CPU/memory pressure).
function HealthRow({
  icon: Icon,
  label,
  loading,
  children,
}: {
  icon: LucideIcon;
  label: string;
  loading?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <span className="flex items-center gap-2 text-sm text-foreground-muted">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </span>
      {loading ? (
        <Skeleton className="h-4 w-20" />
      ) : (
        <span className="min-w-0 text-right text-sm font-medium text-foreground-secondary">
          {children}
        </span>
      )}
    </div>
  );
}

function pressureClass(pct?: number): string {
  if (pct == null || !Number.isFinite(pct)) return "text-foreground-secondary";
  if (pct >= 85) return "text-danger";
  if (pct >= 60) return "text-warning";
  return "text-success";
}

function brainLabel(b?: DiagnosticsBrain): string {
  if (!b) return "—";
  // The backend's "unknown" sentinel reads as a real value; treat it as empty.
  const model = b.model && b.model !== "unknown" ? b.model : "";
  const provider = b.provider && b.provider !== "unknown" ? b.provider : "";
  return model || provider || "—";
}

// Compact "System health" card — live process/runtime telemetry from
// GET /api/diagnostics, in the established glass style (small stat rows + a
// subtle live pulse). Premium loading / empty / error states.
function SystemHealthCard({ running }: { running: boolean }) {
  const { data, isLoading, isError, error } = useQuery<Diagnostics>({
    queryKey: ["diagnostics"],
    queryFn: api.diagnostics,
    refetchInterval: 4000,
    retry: 1,
  });

  // The endpoint never 500s — it returns {error} when the module is missing —
  // so treat both a thrown fetch error and an {error} envelope as the failure.
  const failure = isError
    ? error instanceof Error
      ? error.message
      : "unreachable"
    : data?.error;
  const live = running && !failure && !isLoading;

  const cpu = data?.process?.cpuPercent;
  const mem = data?.process?.memMb;
  const uptime = data?.process?.uptimeSeconds;
  const sttModel =
    data?.stt?.model && data.stt.model !== "unknown" ? data.stt.model : "";
  const sttCompute =
    data?.stt?.computeType && data.stt.computeType !== "unknown"
      ? data.stt.computeType
      : "";

  return (
    <Card glass className="relative flex h-full flex-col overflow-hidden p-5">
      <div className="pointer-events-none absolute -left-10 -bottom-12 h-32 w-32 rounded-full bg-accent-2/15 opacity-50 blur-2xl" />
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
          <HeartPulse className="h-3.5 w-3.5" />
          System health
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-foreground-muted">
          <ListeningPulse active={live} size="h-1.5 w-1.5" />
          {failure ? "offline" : live ? "live" : "idle"}
        </span>
      </div>

      {failure ? (
        <div className="mt-4 flex flex-1 flex-col items-center justify-center gap-2 py-4 text-center">
          <Gauge className="h-6 w-6 text-foreground-muted/60" />
          <p className="text-sm text-foreground-secondary">
            Diagnostics unavailable
          </p>
          <p className="max-w-[18rem] text-xs text-foreground-muted">{failure}</p>
        </div>
      ) : (
        <div className="mt-3 flex-1 divide-y divide-border/60">
          <HealthRow icon={Cpu} label="CPU" loading={isLoading}>
            {cpu == null ? (
              "—"
            ) : (
              <SlidingNumber
                value={cpu}
                decimals={cpu < 10 ? 1 : 0}
                suffix="%"
                className={pressureClass(cpu)}
              />
            )}
          </HealthRow>

          <HealthRow icon={MemoryStick} label="Memory" loading={isLoading}>
            {mem == null ? (
              "—"
            ) : (
              <span className="flex items-baseline justify-end gap-1">
                <SlidingNumber value={mem} decimals={mem < 100 ? 1 : 0} />
                <span className="text-xs text-foreground-muted">MB</span>
              </span>
            )}
          </HealthRow>

          <HealthRow icon={Clock} label="Uptime" loading={isLoading}>
            {uptime == null ? (
              "—"
            ) : (
              (() => {
                const u = formatUptime(uptime);
                return (
                  <span className="flex items-baseline justify-end gap-1">
                    <SlidingNumber
                      value={u.value}
                      decimals={u.unit === "sec" || u.unit === "min" ? 0 : 1}
                    />
                    <span className="text-xs text-foreground-muted">{u.unit}</span>
                  </span>
                );
              })()
            )}
          </HealthRow>

          <HealthRow icon={AudioWaveform} label="Whisper" loading={isLoading}>
            <span className="flex items-center justify-end gap-1.5">
              <span className="truncate font-mono text-xs">
                {sttModel || "—"}
              </span>
              {sttCompute && (
                <Badge variant="outline" className="font-mono text-[10px]">
                  {sttCompute}
                </Badge>
              )}
            </span>
          </HealthRow>

          <HealthRow icon={BrainCircuit} label="Brains" loading={isLoading}>
            <span className="flex items-center justify-end gap-1.5 font-mono text-xs">
              <span className="truncate">{brainLabel(data?.smallBrain)}</span>
              <span className="text-foreground-muted">·</span>
              <span className="truncate">{brainLabel(data?.bigBrain)}</span>
            </span>
          </HealthRow>
        </div>
      )}
    </Card>
  );
}

const QUICK_ACTIONS: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/usage", label: "Token Usage", icon: Coins },
  { to: "/personalities", label: "Personalities", icon: Drama },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
  { to: "/axtree", label: "AX Tree", icon: Network },
];

function QuickActions() {
  return (
    <div className="flex flex-wrap gap-2">
      {QUICK_ACTIONS.map(({ to, label, icon: Icon }) => (
        <Link
          key={to}
          to={to}
          className="group inline-flex items-center gap-2 rounded-full border border-border-strong bg-muted/40 px-3.5 py-1.5 text-sm text-foreground-secondary transition-all hover:-translate-y-px hover:border-accent/40 hover:text-foreground hover:shadow-accent-glow"
        >
          <Icon className="h-3.5 w-3.5 text-foreground-muted transition-colors group-hover:text-accent" />
          {label}
        </Link>
      ))}
    </div>
  );
}

export function Overview() {
  const { data, isLoading, isError, error } = useQuery<Status>({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 5000,
  });

  const { data: summary } = useQuery<UsageSummary>({
    queryKey: ["usage", "summary"],
    queryFn: api.usageSummary,
    refetchInterval: 10_000,
  });

  const { data: recent } = useQuery<UsageEvent[]>({
    queryKey: ["usage", "recent"],
    queryFn: () => api.usageRecent(100),
    refetchInterval: false,
  });

  const { events, status: streamStatus } = useUsageStream(recent ?? [], 60);

  const running = !!data?.running;
  const status: StatusKind = isLoading
    ? "connecting"
    : isError || !running
      ? "offline"
      : "online";

  const uptime = formatUptime(data?.uptimeSeconds ?? 0);
  const personality = data?.personality?.trim() || "Default";

  const byDay = summary?.byDay ?? [];
  const today = todayKey();
  const todayCost = byDay.find((d) => d.date === today)?.costUsd ?? 0;
  // Sparkline of recent daily cost (last 14 days, ascending).
  const spark = byDay.slice(-14).map((d) => ({ v: d.costUsd }));
  const hasSpark = spark.length >= 2;

  return (
    <div className="relative">
      {/* Subtle background radial glow behind the grid (violet→cyan). */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      >
        <div className="absolute -top-32 left-1/3 h-[28rem] w-[28rem] -translate-x-1/2 rounded-full bg-accent/10 blur-[120px]" />
        <div className="absolute -top-20 right-1/4 h-[22rem] w-[22rem] rounded-full bg-accent-2/10 blur-[120px]" />
      </div>

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
            value={<span className="text-2xl">{personality}</span>}
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

      {/* Lower section: left column stacks hero today's-cost + System health;
          right column holds the live feed. Quick actions sit below. */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-1">
        <FadeIn delay={0.05}>
          <Card glass className="relative flex h-full flex-col overflow-hidden p-5">
            <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-brand-gradient opacity-25 blur-2xl" />
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
                <Coins className="h-3.5 w-3.5" />
                Today&apos;s cost
              </span>
              <Link
                to="/usage"
                className="text-xs text-foreground-muted transition-colors hover:text-accent"
              >
                Details →
              </Link>
            </div>
            <div className="mt-3 text-display leading-none">
              <SlidingNumber
                value={todayCost}
                decimals={todayCost < 1 ? 3 : 2}
                prefix="$"
                className="text-brand-gradient font-semibold"
              />
            </div>
            <div className="mt-1 flex items-center gap-1.5 text-sm text-foreground-secondary">
              <TrendingUp className="h-3.5 w-3.5 text-accent-2" />
              {summary
                ? `${formatCost(summary.totals.costUsd)} all-time`
                : "—"}
            </div>

            <div className="mt-4 flex-1">
              {hasSpark ? (
                <ResponsiveContainer width="100%" height={64}>
                  <AreaChart data={spark} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="ovSpark" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="hsl(258 90% 66%)" stopOpacity={0.45} />
                        <stop offset="100%" stopColor="hsl(187 85% 53%)" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <Area
                      type="monotone"
                      dataKey="v"
                      stroke="hsl(258 90% 66%)"
                      strokeWidth={1.75}
                      fill="url(#ovSpark)"
                      dot={false}
                      isAnimationActive
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-16 items-end gap-1">
                  {/* Flat baseline placeholder until we have ≥2 days of data. */}
                  <div className="h-px w-full bg-border" />
                </div>
              )}
              <p className="mt-1 text-[11px] text-foreground-muted">
                Daily spend, last {Math.max(spark.length, 0) || 14} days
              </p>
            </div>
          </Card>
        </FadeIn>

        <FadeIn delay={0.1}>
          <SystemHealthCard running={running} />
        </FadeIn>
        </div>

        <FadeIn delay={0.15} className="lg:col-span-2">
          <Card glass className="h-full p-5">
            <LiveFeed events={events} status={streamStatus} limit={8} />
          </Card>
        </FadeIn>
      </div>

      <FadeIn delay={0.15} className="mt-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-overline uppercase text-foreground-muted">
            Quick actions
          </span>
          <QuickActions />
        </div>
      </FadeIn>
    </div>
  );
}
