/*
 * Typed fetch client + ALL data shapes for the Vox dashboard.
 * Types MUST mirror the Python bridge responses (CONTRACT.md §"Data shapes").
 * camelCase fields, JSON over REST under /api.
 */

// ---------------------------------------------------------------------------
// Data shapes (mirror CONTRACT.md exactly)
// ---------------------------------------------------------------------------

export interface BrainRef {
  provider: string;
  model: string;
}

export interface Status {
  running: boolean;
  mode: string;
  smallBrain: BrainRef;
  bigBrain: BrainRef;
  personality: string;
  uptimeSeconds: number;
}

export type Brain = "small" | "big";
export type UsageKind = "chat" | "command" | "vision" | "rewrite";

export interface UsageEvent {
  id: string;
  ts: string;
  provider: string;
  model: string;
  brain: Brain;
  kind: UsageKind;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  latencyMs: number;
}

export interface UsageByModel {
  model: string;
  provider: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

export interface UsageByDay {
  date: string;
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
}

export interface UsageSummary {
  totals: {
    calls: number;
    inputTokens: number;
    outputTokens: number;
    costUsd: number;
  };
  byModel: UsageByModel[];
  byDay: UsageByDay[];
}

// Conversation turn — mirrors a turn from the live, EPHEMERAL feed
// (src/vox/web/conversation.py `record_turn`). `role`: "user" (you) or
// "assistant" (Vox). `brain` is the replying brain on assistant turns (else
// null); `kind` tags it ("chat"|"command"|"reply") so a command can render
// inline. `session` distinguishes concurrent sessions. Nothing is persisted —
// this is the running session in RAM, gone on daemon restart.
export type TurnRole = "user" | "assistant";

export interface Turn {
  id: string;
  session: string;
  ts: string;
  role: TurnRole;
  text: string;
  brain: Brain | null;
  kind: string | null;
}

export type SettingType = "toggle" | "select" | "text";

export interface SettingOption {
  value: string;
  label: string;
}

export interface Setting {
  key: string;
  label: string;
  group: string;
  type: SettingType;
  value: string | boolean;
  options?: SettingOption[];
  help: string;
}

export interface Personality {
  id: string;
  name: string;
  emoji: string;
  tagline: string;
  persona: string;
  suggestedVoice?: string;
  preset: boolean;
}

export interface Personalities {
  active: string;
  presets: Personality[];
  custom: Personality[];
}

export interface Rule {
  id: string;
  text: string;
  enabled: boolean;
}

// Scheduled job (timer / alarm / reminder) — mirrors a Job from the Vox-owned
// scheduler (src/vox/scheduler.py), serialised camelCase by the bridge. `fireAt`
// is an ISO LOCAL datetime (naive). `recurrence` is null for a one-shot.
export type ReminderKind = "timer" | "alarm" | "reminder";
export type Recurrence = "daily" | "weekdays" | "weekly" | null;

export interface Reminder {
  id: string;
  kind: ReminderKind;
  text: string;
  fireAt: string;
  recurrence: Recurrence;
  createdAt: string;
  enabled: boolean;
}

// Memory tier (MEMORY_DESIGN.md v1). "core" = durable, always-injected facts;
// "daily" = dated, contextual notes recalled by relevance.
export type MemoryTier = "core" | "daily";

export interface Memory {
  id: string;
  ts: string;
  text: string;
  tags: string[];
  score?: number;
  // Present on the tiered store; older /api/memory responses may omit it, so
  // pages should default to "daily" when absent.
  tier?: MemoryTier;
}

// vox-speak MCP setup block for THIS machine — mirrors GET /api/mcp/config.
// `repoPath` is computed locally by the bridge and is never committed (docs use
// the /ABSOLUTE/PATH/TO/vox-controller placeholder). Fields are read
// defensively: the whole envelope may instead be { error } when the bridge
// module is missing or a read fails (HTTP 200 either way).
export interface McpConfig {
  // Server id to register the MCP under (e.g. "vox-speak").
  name: string;
  // Absolute path to this repo on this machine (local-only, do not commit).
  repoPath: string;
  // Command + args the MCP host should launch (e.g. uv run ...).
  command: string;
  args: string[];
  // Ready-to-paste `.cursor/mcp.json` block (the mcpServers entry).
  cursorBlock: string;
  // Ready-to-run `claude mcp add ...` shell command.
  claudeAddCommand: string;
  // On-disk path to the editor config we'd reveal (for "open config location").
  configPath?: string;
  error?: string;
}

// Handbook catalog — the human-readable reference of what Vox can do, mirrors
// GET /api/handbook (src/vox/web/server.py `_handbook`). The bridge returns a
// bare ARRAY of groups (no envelope), in display order: live phrase groups
// (pulled from CONFIG: wake/control, dictation, sleep/stop, escalation) first,
// then curated static groups (commands / modes / features). Each item is a
// spoken `phrase` + a `description`. This route is additive (not in the
// original CONTRACT.md data shapes). The route degrades to the static groups
// even when CONFIG can't be read, so it does not use the { error } envelope.
export interface HandbookItem {
  // The exact phrase to say (or an example phrasing the parser understands).
  phrase: string;
  // One-line description of what it does.
  description: string;
  // Curated legitimate alternative phrasings (NOT misrecognition spellings),
  // shown when the phrase is clicked. Absent when there are no other ways to say it.
  variants?: string[];
}

export interface HandbookGroup {
  // Display name for the group (e.g. "Wake & activation", "Dictation").
  title: string;
  // Optional one-line summary shown under the group title.
  blurb?: string;
  items: HandbookItem[];
}

// The catalog is the array of groups itself (GET /api/handbook → HandbookGroup[]).
export type Handbook = HandbookGroup[];

export interface AxNode {
  role: string;
  title?: string;
  value?: string;
  enabled?: boolean;
  children: AxNode[];
}

export interface AxTree {
  app: string;
  capturedAt: string;
  tree: AxNode;
}

export interface AxTreeError {
  error: string;
}

// Monthly cost budget meter — mirrors usage.budget_status() (backend.md §it.7).
// `state`: none (no budget set) · ok · warn (>=80%) · over (>=100%).
// remainingUsd may go negative when over budget (the meter shows the overspend).
export type BudgetState = "none" | "ok" | "warn" | "over";

export interface BudgetStatus {
  budgetUsd: number;
  spentUsd: number;
  remainingUsd: number;
  percent: number;
  state: BudgetState;
}

// Either route may return a plain { error } when its bridge module is absent
// or a read fails (the FastAPI bridge returns HTTP 200 with this body).
export interface ApiErrorBody {
  error: string;
}

// Diagnostics snapshot — mirrors diagnostics.snapshot() (backend diagnostics.py).
// All nested fields are read defensively by the page: brain/stt strings can be
// the backend "unknown" sentinel, and the whole envelope may instead be { error }
// when the bridge module is missing or a read fails (HTTP 200 either way).
export interface DiagnosticsBrain {
  provider: string;
  model: string;
}

export interface Diagnostics {
  capturedAt?: string;
  platform?: string;
  process?: { cpuPercent: number; memMb: number; uptimeSeconds: number };
  stt?: { model: string; computeType: string; sampleRate: number };
  smallBrain?: DiagnosticsBrain;
  bigBrain?: DiagnosticsBrain;
  tts?: { enabled: boolean; voice: string };
  error?: string;
}

export function isApiError(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as { error: unknown }).error === "string"
  );
}

// ---------------------------------------------------------------------------
// Fetch client
// ---------------------------------------------------------------------------

// Empty base => same-origin /api (production: served by the FastAPI bridge).
// In dev, Vite proxies /api to VITE_API_BASE (see vite.config.ts), so leaving
// this empty also works in dev; the env var documents the bridge address.
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.error ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  status: () => request<Status>("/status"),

  usageRecent: (limit = 100) =>
    request<UsageEvent[]>(`/usage/recent?limit=${limit}`),
  usageSummary: () => request<UsageSummary>("/usage/summary"),

  // Live, ephemeral conversation feed (the running session in RAM).
  conversationRecent: (limit = 100) =>
    request<Turn[]>(`/conversation/recent?limit=${limit}`),

  settings: () => request<Setting[]>("/settings"),
  setSetting: (key: string, value: string | boolean) =>
    request<{ ok: boolean; value: string | boolean }>("/settings", {
      method: "POST",
      body: JSON.stringify({ key, value }),
    }),

  personalities: () => request<Personalities>("/personalities"),
  setActivePersonality: (id: string) =>
    request<{ ok: boolean; active: string }>("/personalities/active", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
  addCustomPersonality: (body: {
    name: string;
    persona: string;
    emoji?: string;
    suggestedVoice?: string;
    kokoroVoice?: string;
  }) =>
    request<Personality>("/personalities/custom", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCustomPersonality: (
    id: string,
    body: {
      name?: string;
      persona?: string;
      emoji?: string;
      tagline?: string;
      suggestedVoice?: string;
      kokoroVoice?: string;
    },
  ) =>
    request<Personality>(`/personalities/custom/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  removeCustomPersonality: (id: string) =>
    request<{ ok: boolean }>(`/personalities/custom/${id}`, {
      method: "DELETE",
    }),

  rules: () => request<Rule[]>("/rules"),
  addRule: (text: string) =>
    request<Rule>("/rules", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  updateRule: (id: string, patch: { enabled?: boolean; text?: string }) =>
    request<Rule>(`/rules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  removeRule: (id: string) =>
    request<{ ok: boolean }>(`/rules/${id}`, { method: "DELETE" }),

  // --- Reminders / timers / alarms (Vox-owned scheduler, idea #16) ---------
  reminders: () => request<Reminder[]>("/reminders"),
  addReminder: (body: {
    kind: ReminderKind;
    text?: string;
    fireAt: string;
    recurrence?: Recurrence;
  }) =>
    request<Reminder>("/reminders", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  removeReminder: (id: string) =>
    request<{ ok: boolean }>(`/reminders/${id}`, { method: "DELETE" }),

  // --- Memory (back-compat flat search; recalls across tiers) --------------
  memory: (query = "", limit = 50) =>
    request<Memory[]>(
      `/memory?query=${encodeURIComponent(query)}&limit=${limit}`,
    ),
  // Extended add: optional tier (default "daily" server-side) + tags. Accepts
  // either an options object {tier?, tags?} (preferred) or a bare string[] of
  // tags (legacy positional form) so existing callers keep working.
  addMemory: (
    text: string,
    opts?: { tier?: MemoryTier; tags?: string[] } | string[],
  ) => {
    const o = Array.isArray(opts) ? { tags: opts } : opts;
    return request<Memory>("/memory", {
      method: "POST",
      body: JSON.stringify({ text, tier: o?.tier, tags: o?.tags }),
    });
  },
  removeMemory: (id: string) =>
    request<{ ok: boolean }>(`/memory/${id}`, { method: "DELETE" }),

  // --- Memory (tiered, MEMORY_DESIGN.md v1) --------------------------------
  // All curated core memories (always-injected facts).
  memoryCore: () => request<Memory[]>("/memory/core"),
  // Daily log for a date (YYYY-MM-DD); omit `date` for today.
  memoryDaily: (date?: string) =>
    request<Memory[]>(
      date ? `/memory/daily?date=${encodeURIComponent(date)}` : "/memory/daily",
    ),
  // Dates (YYYY-MM-DD) that have a daily log, newest-first per the bridge.
  memoryDates: () => request<string[]>("/memory/dates"),
  // Reveal data/memory/ in the OS file manager (bridge runs `open -R`).
  revealMemory: () =>
    request<{ ok: boolean }>("/memory/reveal", { method: "POST" }),

  axtree: () => request<AxTree | AxTreeError>("/axtree"),

  // Handbook catalog (the reference of what Vox can do, grouped by area).
  // Returns a bare array of groups (HandbookGroup[]); the bridge falls back to
  // the static groups if CONFIG can't be read, so callers always get an array.
  handbook: () => request<Handbook>("/handbook"),

  // Iteration 7 — cost budget meter + runtime diagnostics. Both routes return
  // HTTP 200 even when their bridge module is absent, with an { error } body;
  // callers should narrow with isApiError() before reading the typed fields.
  budget: () => request<BudgetStatus | ApiErrorBody>("/budget"),
  diagnostics: () => request<Diagnostics>("/diagnostics"),

  // vox-speak MCP setup for this machine. Returns HTTP 200 with an { error }
  // body when the bridge module is absent; narrow with isApiError() before
  // reading the typed fields (McpConfig.error is also set in that case).
  mcpConfig: () => request<McpConfig | ApiErrorBody>("/mcp/config"),
};

// WebSocket URL for the live usage stream (CONTRACT.md WS /api/usage/stream).
export function usageStreamUrl(): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, "ws") + "/api/usage/stream";
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/usage/stream`;
}

// WebSocket URL for the live conversation feed (WS /api/conversation/stream).
export function conversationStreamUrl(): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, "ws") + "/api/conversation/stream";
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/conversation/stream`;
}
