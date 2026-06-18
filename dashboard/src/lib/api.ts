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

export interface Memory {
  id: string;
  ts: string;
  text: string;
  tags: string[];
  score?: number;
}

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

// Diagnostics snapshot — shape is owned by the diagnostics agent (a flat record
// of health probes). Typed openly so the page can render whatever lands; the
// `error` field is present when the bridge module is missing or the read fails.
export interface Diagnostics {
  error?: string;
  [key: string]: unknown;
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

  settings: () => request<Setting[]>("/settings"),
  setSetting: (key: string, value: string | boolean) =>
    request<{ ok: boolean; value: string | boolean }>("/settings", {
      method: "POST",
      body: JSON.stringify({ key, value }),
    }),

  personalities: () => request<Personalities>("/personalities"),
  setActivePersonality: (id: string) =>
    request<{ ok: boolean }>("/personalities/active", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
  addCustomPersonality: (body: {
    name: string;
    persona: string;
    emoji?: string;
    suggestedVoice?: string;
  }) =>
    request<Personality>("/personalities/custom", {
      method: "POST",
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

  memory: (query = "", limit = 50) =>
    request<Memory[]>(
      `/memory?query=${encodeURIComponent(query)}&limit=${limit}`,
    ),
  addMemory: (text: string, tags?: string[]) =>
    request<Memory>("/memory", {
      method: "POST",
      body: JSON.stringify({ text, tags }),
    }),
  removeMemory: (id: string) =>
    request<{ ok: boolean }>(`/memory/${id}`, { method: "DELETE" }),

  axtree: () => request<AxTree | AxTreeError>("/axtree"),

  // Iteration 7 — cost budget meter + runtime diagnostics. Both routes return
  // HTTP 200 even when their bridge module is absent, with an { error } body;
  // callers should narrow with isApiError() before reading the typed fields.
  budget: () => request<BudgetStatus | ApiErrorBody>("/budget"),
  diagnostics: () => request<Diagnostics>("/diagnostics"),
};

// WebSocket URL for the live usage stream (CONTRACT.md WS /api/usage/stream).
export function usageStreamUrl(): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, "ws") + "/api/usage/stream";
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/usage/stream`;
}
