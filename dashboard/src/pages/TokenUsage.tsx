import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  DollarSign,
  BarChart3,
  TrendingUp,
  Sparkles,
} from "lucide-react";
import { api, type UsageSummary, type UsageEvent } from "@/lib/api";
import { formatCost, formatTokens } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { SlidingNumber } from "@/components/animate/SlidingNumber";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { FadeIn } from "@/components/animate/FadeIn";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LiveFeed } from "@/components/usage/LiveFeed";
import { useUsageStream } from "@/hooks/useUsageStream";

// Accent palette for per-model bars (violet→cyan family + semantics).
const BAR_COLORS = [
  "hsl(258 90% 66%)", // violet
  "hsl(187 85% 53%)", // cyan
  "hsl(213 94% 68%)", // blue
  "hsl(160 64% 52%)", // emerald
  "hsl(43 96% 56%)", // amber
];

function shortModel(model: string): string {
  if (!model) return "—";
  return model.replace(/-\d{6,8}$/, "");
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function ChartTooltip({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean;
  payload?: { value: number; name?: string; payload?: unknown }[];
  label?: string;
  formatter: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-lg px-3 py-2 text-xs">
      {label && <div className="mb-1 font-medium text-foreground">{label}</div>}
      {payload.map((p, i) => (
        <div key={i} className="tnum text-foreground-secondary">
          {formatter(p.value)}
        </div>
      ))}
    </div>
  );
}

function EmptyChart({ icon: Icon, hint }: { icon: typeof Activity; hint: string }) {
  return (
    <div className="flex h-full min-h-[220px] flex-col items-center justify-center gap-2 text-center">
      <Icon className="h-7 w-7 text-foreground-muted" />
      <p className="text-sm text-foreground-secondary">Nothing to chart yet</p>
      <p className="max-w-[20rem] text-xs text-foreground-muted">{hint}</p>
    </div>
  );
}

export function TokenUsage() {
  const { data, isLoading, isError } = useQuery<UsageSummary>({
    queryKey: ["usage", "summary"],
    queryFn: api.usageSummary,
    refetchInterval: 10_000,
  });

  const { data: recent } = useQuery<UsageEvent[]>({
    queryKey: ["usage", "recent"],
    queryFn: () => api.usageRecent(100),
    refetchInterval: false,
  });

  const { events, status } = useUsageStream(recent ?? [], 100);

  const totals = data?.totals ?? {
    calls: 0,
    inputTokens: 0,
    outputTokens: 0,
    costUsd: 0,
  };
  const byDay = data?.byDay ?? [];
  const byModel = data?.byModel ?? [];
  const hasUsage = totals.calls > 0;

  const dayData = byDay.map((d) => ({
    date: shortDate(d.date),
    cost: d.costUsd,
    tokens: d.inputTokens + d.outputTokens,
  }));

  const modelData = [...byModel]
    .sort((a, b) => b.inputTokens + b.outputTokens - (a.inputTokens + a.outputTokens))
    .map((m) => ({
      model: shortModel(m.model),
      provider: m.provider,
      tokens: m.inputTokens + m.outputTokens,
      cost: m.costUsd,
      calls: m.calls,
    }));

  return (
    <div>
      <PageHeader
        title="Token Usage"
        description="Live token usage, cost, and per-model breakdown."
        actions={
          hasUsage ? (
            <Badge variant="accent" className="font-mono">
              <Activity className="h-3 w-3" />
              {totals.calls} calls
            </Badge>
          ) : null
        }
      />

      {isError && (
        <Card glass className="mb-6 border-danger/30 px-5 py-4 text-sm text-foreground-secondary">
          Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
          <span className="font-mono">127.0.0.1:8765</span>?
        </Card>
      )}

      {/* Summary cards — animated counters. The cost card is the violet→cyan hero. */}
      <Stagger className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <StaggerItem>
          <Card glass className="relative overflow-hidden p-5">
            <div className="pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full bg-brand-gradient opacity-20 blur-2xl" />
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
                <DollarSign className="h-3.5 w-3.5" />
                Total cost
              </span>
              <Sparkles className="h-4 w-4 text-accent-2" />
            </div>
            <div className="mt-3 text-display leading-none">
              {isLoading ? (
                <span className="text-foreground-muted">—</span>
              ) : (
                <SlidingNumber
                  value={totals.costUsd}
                  decimals={totals.costUsd < 1 ? 3 : 2}
                  prefix="$"
                  className="text-brand-gradient font-semibold"
                />
              )}
            </div>
            <div className="mt-2 text-sm text-foreground-secondary">
              Across {totals.calls} calls
            </div>
          </Card>
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Total calls"
            icon={Activity}
            loading={isLoading}
            value={<SlidingNumber value={totals.calls} />}
            sub="LLM invocations"
          />
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Input tokens"
            icon={ArrowDownToLine}
            loading={isLoading}
            value={<SlidingNumber value={totals.inputTokens} />}
            sub={<span className="font-mono">{formatTokens(totals.inputTokens)} total</span>}
          />
        </StaggerItem>

        <StaggerItem>
          <MetricCard
            label="Output tokens"
            icon={ArrowUpFromLine}
            loading={isLoading}
            value={<SlidingNumber value={totals.outputTokens} />}
            sub={<span className="font-mono">{formatTokens(totals.outputTokens)} total</span>}
          />
        </StaggerItem>
      </Stagger>

      {/* Charts + live feed */}
      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <FadeIn delay={0.05} className="lg:col-span-2">
          <Card glass className="flex h-full flex-col p-5">
            <div className="mb-4 flex items-center justify-between">
              <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
                <TrendingUp className="h-3.5 w-3.5" />
                Cost over time
              </span>
              <span className="text-xs text-foreground-muted">by day</span>
            </div>
            {hasUsage && dayData.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={dayData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <defs>
                    <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="hsl(258 90% 66%)" stopOpacity={0.5} />
                      <stop offset="100%" stopColor="hsl(187 85% 53%)" stopOpacity={0.04} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(240 4% 16%)" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fill: "hsl(240 4% 46%)", fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    tick={{ fill: "hsl(240 4% 46%)", fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                    tickFormatter={(v) => formatCost(Number(v))}
                  />
                  <Tooltip
                    cursor={{ stroke: "hsl(258 90% 66%)", strokeOpacity: 0.3 }}
                    content={<ChartTooltip formatter={(v) => formatCost(v)} />}
                  />
                  <Area
                    type="monotone"
                    dataKey="cost"
                    stroke="hsl(258 90% 66%)"
                    strokeWidth={2}
                    fill="url(#costFill)"
                    activeDot={{ r: 4, fill: "hsl(187 85% 53%)" }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart
                icon={TrendingUp}
                hint="Daily spend will plot here once Vox starts making metered calls."
              />
            )}
          </Card>
        </FadeIn>

        <FadeIn delay={0.1}>
          <Card glass className="h-full p-5">
            <LiveFeed events={events} status={status} limit={14} />
          </Card>
        </FadeIn>
      </div>

      {/* Tokens by model */}
      <FadeIn delay={0.12} className="mt-5">
        <Card glass className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="flex items-center gap-2 text-overline uppercase text-foreground-muted">
              <BarChart3 className="h-3.5 w-3.5" />
              Tokens by model
            </span>
            <span className="text-xs text-foreground-muted">input + output</span>
          </div>
          {hasUsage && modelData.length > 0 ? (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
              <div className="lg:col-span-3">
                <ResponsiveContainer width="100%" height={Math.max(180, modelData.length * 48)}>
                  <BarChart
                    layout="vertical"
                    data={modelData}
                    margin={{ top: 0, right: 16, left: 8, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(240 4% 16%)" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fill: "hsl(240 4% 46%)", fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(v) => formatTokens(Number(v))}
                    />
                    <YAxis
                      type="category"
                      dataKey="model"
                      tick={{ fill: "hsl(240 5% 65%)", fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                      width={130}
                    />
                    <Tooltip
                      cursor={{ fill: "hsl(258 90% 66%)", fillOpacity: 0.08 }}
                      content={<ChartTooltip formatter={(v) => `${formatTokens(v)} tokens`} />}
                    />
                    <Bar dataKey="tokens" radius={[0, 6, 6, 0]} barSize={20}>
                      {modelData.map((_, i) => (
                        <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="lg:col-span-2">
                <div className="divide-y divide-border/60">
                  {modelData.map((m, i) => (
                    <div key={m.model + i} className="flex items-center gap-3 py-2.5">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ background: BAR_COLORS[i % BAR_COLORS.length] }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-mono text-xs text-foreground">{m.model}</div>
                        <div className="text-[11px] text-foreground-muted">
                          {m.provider} · {m.calls} calls
                        </div>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="tnum text-xs text-foreground">{formatTokens(m.tokens)}</div>
                        <div className="tnum text-[11px] text-foreground-muted">
                          {formatCost(m.cost)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <EmptyChart
              icon={BarChart3}
              hint="Per-model token usage appears here after the first call to each brain."
            />
          )}
        </Card>
      </FadeIn>
    </div>
  );
}
