import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  SlidersHorizontal,
  AudioLines,
  Bug,
  RotateCcw,
  Zap,
  ShieldCheck,
  MessageCircle,
} from "lucide-react";
import { api, type Setting } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

const SETTINGS_KEY = ["settings"] as const;

// Radix's <SelectItem> throws on an empty-string value — it reserves "" for
// "nothing selected". The API legitimately ships one (input_device's "System
// default"), so stand in for it in the DOM and swap it back on change.
const EMPTY_OPTION = "__empty__";

// Display order + icon per group. Unknown groups fall after these, ungrouped.
const GROUP_META: Record<string, { icon: typeof Brain; blurb: string }> = {
  Brains: {
    icon: Brain,
    blurb: "Which models answer, and when Vox escalates to the big brain.",
  },
  Behavior: {
    icon: SlidersHorizontal,
    blurb: "What Vox is allowed to do on its own while running.",
  },
  Voice: {
    icon: AudioLines,
    blurb: "Speech output and interruption during a call.",
  },
  "MCP voice": {
    icon: MessageCircle,
    blurb:
      "The vox-speak MCP's heads-up voice — kept separate from the system voice so the IDE assistant sounds different from Vox. Reload the MCP server to apply.",
  },
  Debug: {
    icon: Bug,
    blurb: "Diagnostics. Verbose — leave off unless you're tracing an issue.",
  },
};
const GROUP_ORDER = ["Brains", "Behavior", "Voice", "MCP voice", "Debug"];

// A setting "needs a restart" when its help says so (settings_store encodes this
// in the help text); otherwise the override takes effect on the next call.
function needsRestart(s: Setting): boolean {
  return /restart/i.test(s.help);
}

function groupRank(group: string): number {
  const i = GROUP_ORDER.indexOf(group);
  return i === -1 ? GROUP_ORDER.length : i;
}

interface MutationVars {
  key: string;
  value: string | boolean;
}

function useSetSetting() {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({ key, value }: MutationVars) => api.setSetting(key, value),
    // Optimistic: write the new value into the cached Setting[] immediately.
    onMutate: async ({ key, value }) => {
      await qc.cancelQueries({ queryKey: SETTINGS_KEY });
      const prev = qc.getQueryData<Setting[]>(SETTINGS_KEY);
      qc.setQueryData<Setting[]>(SETTINGS_KEY, (old) =>
        old?.map((s) => (s.key === key ? { ...s, value } : s)),
      );
      return { prev };
    },
    onError: (_err, vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(SETTINGS_KEY, ctx.prev);
      toast({
        variant: "error",
        title: "Couldn't save",
        description: `${vars.key} reverted — is the bridge running?`,
      });
    },
    // Reflect the server's returned value (authoritative) over the optimistic one.
    onSuccess: (res, vars) => {
      if (res?.ok) {
        qc.setQueryData<Setting[]>(SETTINGS_KEY, (old) =>
          old?.map((s) => (s.key === vars.key ? { ...s, value: res.value } : s)),
        );
        toast({ variant: "success", title: "Saved", description: vars.key });
      } else {
        toast({
          variant: "error",
          title: "Rejected",
          description: `${vars.key} is not a known setting.`,
        });
      }
    },
  });
}

function HintBadge({ setting }: { setting: Setting }) {
  if (needsRestart(setting)) {
    return (
      <Badge variant="warning" className="font-normal">
        <RotateCcw className="h-3 w-3" />
        needs restart
      </Badge>
    );
  }
  return (
    <Badge variant="default" className="font-normal text-foreground-muted">
      <Zap className="h-3 w-3" />
      applies on next call
    </Badge>
  );
}

function SettingRow({
  setting,
  onChange,
  pending,
}: {
  setting: Setting;
  onChange: (value: string | boolean) => void;
  pending: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6",
        pending && "opacity-70",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-foreground">
            {setting.label}
          </span>
          <span className="font-mono text-[11px] text-foreground-muted">
            {setting.key}
          </span>
          <HintBadge setting={setting} />
        </div>
        <p className="mt-1 max-w-prose text-xs leading-relaxed text-foreground-secondary">
          {setting.help}
        </p>
      </div>
      <div className="shrink-0 sm:w-64 sm:pt-0.5">
        <SettingControl
          setting={setting}
          onChange={onChange}
          disabled={pending}
        />
      </div>
    </div>
  );
}

function SettingControl({
  setting,
  onChange,
  disabled,
}: {
  setting: Setting;
  onChange: (value: string | boolean) => void;
  disabled: boolean;
}) {
  if (setting.type === "toggle") {
    return (
      <div className="flex items-center justify-start gap-3 sm:justify-end">
        <span className="text-xs text-foreground-muted">
          {setting.value ? "On" : "Off"}
        </span>
        <Switch
          checked={Boolean(setting.value)}
          disabled={disabled}
          onCheckedChange={(checked) => onChange(checked)}
          aria-label={setting.label}
        />
      </div>
    );
  }

  if (setting.type === "select") {
    const options = setting.options ?? [];
    // Only stand in for "" when it's a real option — otherwise a null value
    // should stay "" so the placeholder shows.
    const hasEmptyOption = options.some((opt) => opt.value === "");
    const current = String(setting.value ?? "");
    return (
      <Select
        value={current === "" && hasEmptyOption ? EMPTY_OPTION : current}
        disabled={disabled}
        onValueChange={(v) => onChange(v === EMPTY_OPTION ? "" : v)}
      >
        <SelectTrigger aria-label={setting.label}>
          <SelectValue placeholder="Select…" />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem
              key={opt.value}
              value={opt.value === "" ? EMPTY_OPTION : opt.value}
            >
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  // text
  return (
    <TextSetting setting={setting} onChange={onChange} disabled={disabled} />
  );
}

// Text fields commit on blur / Enter (not per keystroke) so we don't POST on
// every character; local state mirrors the input until then.
function TextSetting({
  setting,
  onChange,
  disabled,
}: {
  setting: Setting;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const [draft, setDraft] = React.useState(String(setting.value ?? ""));

  // Keep the draft in sync when the authoritative value changes elsewhere.
  React.useEffect(() => {
    setDraft(String(setting.value ?? ""));
  }, [setting.value]);

  const commit = () => {
    const next = draft.trim();
    if (next !== String(setting.value ?? "")) onChange(next);
  };

  return (
    <Input
      value={draft}
      disabled={disabled}
      spellCheck={false}
      autoCapitalize="off"
      autoCorrect="off"
      className="font-mono text-xs"
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          setDraft(String(setting.value ?? ""));
          e.currentTarget.blur();
        }
      }}
    />
  );
}

function GroupCard({
  group,
  settings,
  onChange,
  pendingKey,
}: {
  group: string;
  settings: Setting[];
  onChange: (key: string, value: string | boolean) => void;
  pendingKey: string | null;
}) {
  const meta = GROUP_META[group];
  const Icon = meta?.icon ?? SlidersHorizontal;
  return (
    <Card glass className="overflow-hidden p-0">
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent/15 text-accent">
          <Icon className="h-4 w-4" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">{group}</h2>
          {meta?.blurb && (
            <p className="text-xs text-foreground-muted">{meta.blurb}</p>
          )}
        </div>
      </div>
      <div className="divide-y divide-border/50 px-5">
        {settings.map((s) => (
          <SettingRow
            key={s.key}
            setting={s}
            pending={pendingKey === s.key}
            onChange={(value) => onChange(s.key, value)}
          />
        ))}
      </div>
    </Card>
  );
}

function GroupSkeleton() {
  return (
    <Card glass className="p-5">
      <div className="mb-4 flex items-center gap-3">
        <Skeleton className="h-9 w-9 rounded-xl" />
        <div className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-3 w-56" />
        </div>
      </div>
      <div className="space-y-5">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center justify-between gap-6">
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64" />
            </div>
            <Skeleton className="h-9 w-40 rounded-lg" />
          </div>
        ))}
      </div>
    </Card>
  );
}

export function Settings() {
  const { data, isLoading, isError } = useQuery<Setting[]>({
    queryKey: SETTINGS_KEY,
    queryFn: api.settings,
  });

  const mutation = useSetSetting();
  const pendingKey = mutation.isPending
    ? (mutation.variables?.key ?? null)
    : null;

  const handleChange = (key: string, value: string | boolean) => {
    mutation.mutate({ key, value });
  };

  // Group + order. Within a group, preserve the schema's order from the API.
  const grouped = React.useMemo(() => {
    const map = new Map<string, Setting[]>();
    for (const s of data ?? []) {
      if (!map.has(s.group)) map.set(s.group, []);
      map.get(s.group)!.push(s);
    }
    return [...map.entries()].sort(
      (a, b) => groupRank(a[0]) - groupRank(b[0]),
    );
  }, [data]);

  // `/settings#voice` (the daemon opens this when it can't find a microphone) scrolls to that
  // group once the cards exist. BrowserRouter doesn't honour hashes on its own.
  React.useEffect(() => {
    const id = window.location.hash.slice(1);
    if (!data || !id) return;
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [data]);

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Runtime overrides for the Vox voice assistant."
        actions={
          data ? (
            <Badge variant="accent" className="font-normal">
              <ShieldCheck className="h-3 w-3" />
              {data.length} settings
            </Badge>
          ) : null
        }
      />

      {/* Tasteful explainer: these override Config at runtime. */}
      <FadeIn className="mb-6">
        <Card
          glass
          className="relative overflow-hidden border-accent/20 px-5 py-4"
        >
          <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-brand-gradient opacity-15 blur-3xl" />
          <p className="max-w-3xl text-sm leading-relaxed text-foreground-secondary">
            Changes here are saved as{" "}
            <span className="text-foreground">runtime overrides</span> layered on
            top of the daemon&apos;s <span className="font-mono">Config</span> —
            no code edit, no config file. Toggles and most behavior flags{" "}
            <span className="text-accent">apply on the next call</span>; brain
            provider/model changes{" "}
            <span className="text-warning">need a restart</span> to take effect.
            The voice assistant keeps running while you tune it.
          </p>
        </Card>
      </FadeIn>

      {isError && (
        <Card
          glass
          className="mb-6 border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
        >
          Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
          <span className="font-mono">127.0.0.1:8765</span>? Settings fall back to
          the daemon&apos;s own Config until it&apos;s back.
        </Card>
      )}

      {isLoading ? (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <GroupSkeleton />
          <GroupSkeleton />
        </div>
      ) : (
        <Stagger className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
          {grouped.map(([group, settings]) => (
            <StaggerItem key={group}>
              <div id={group.toLowerCase().replace(/\s+/g, "-")}>
                <GroupCard
                  group={group}
                  settings={settings}
                  pendingKey={pendingKey}
                  onChange={handleChange}
                />
              </div>
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  );
}
