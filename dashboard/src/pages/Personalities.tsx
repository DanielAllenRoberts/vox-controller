import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  Plus,
  Check,
  Trash2,
  AudioLines,
  Wand2,
  UserPlus,
  Mic,
  Pencil,
  Eye,
} from "lucide-react";
import {
  api,
  type Personalities as PersonalitiesData,
  type Personality,
} from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

const PERSONALITIES_KEY = ["personalities"] as const;

// macOS `say` voices offered in the custom editor (CONTRACT.md §Personalities).
const SAY_VOICES = [
  "Daniel",
  "Karen",
  "Moira",
  "Rishi",
  "Samantha",
  "Tessa",
] as const;

// Sentinel for "no suggested voice" — Radix Select can't hold an empty value.
const NO_VOICE = "__none__";

// Kokoro TTS voices, grouped by language/accent for the custom-persona picker.
// The selected id is sent as `kokoroVoice`; an empty value falls back to the
// dashboard's global `kokoro_voice` setting. Only used when the TTS engine is
// Kokoro. This is a plain <select> (not the Radix Select) so it can hold an
// empty value and use native <optgroup> grouping.
const KOKORO_VOICE_GROUPS: { label: string; voices: string[] }[] = [
  {
    label: "US English — Female",
    voices: [
      "af_alloy",
      "af_aoede",
      "af_bella",
      "af_heart",
      "af_jessica",
      "af_kore",
      "af_nicole",
      "af_nova",
      "af_river",
      "af_sarah",
      "af_sky",
    ],
  },
  {
    label: "US English — Male",
    voices: [
      "am_adam",
      "am_echo",
      "am_eric",
      "am_fenrir",
      "am_liam",
      "am_michael",
      "am_onyx",
      "am_puck",
      "am_santa",
    ],
  },
  {
    label: "British English — Female",
    voices: ["bf_alice", "bf_emma", "bf_isabella", "bf_lily"],
  },
  {
    label: "British English — Male",
    voices: ["bm_daniel", "bm_fable", "bm_george", "bm_lewis"],
  },
  {
    label: "Other languages (reads English with an accent)",
    voices: [
      "ef_dora",
      "em_alex",
      "em_santa",
      "ff_siwis",
      "hf_alpha",
      "hf_beta",
      "hm_omega",
      "hm_psi",
      "if_sara",
      "im_nicola",
      "jf_alpha",
      "jf_gongitsune",
      "jf_nezumi",
      "jf_tebukuro",
      "jm_kumo",
      "pf_dora",
      "pm_alex",
      "pm_santa",
      "zf_xiaobei",
      "zf_xiaoni",
      "zf_xiaoxiao",
      "zf_xiaoyi",
      "zm_yunjian",
      "zm_yunxi",
      "zm_yunxia",
      "zm_yunyang",
    ],
  },
];

// The synthetic "Default" persona the bridge prepends to `presets` (id "default",
// empty persona) — represents base Vox with no special character. Selecting it
// DESELECTS any active persona. The bridge's set_active only accepts "" or a real
// preset/custom id, so we send "" (not "default") to clear it; "default" is
// reported as active whenever nothing is set.
const DEFAULT_ID = "default";
const isDefault = (p: Personality) => p.id === DEFAULT_ID;

function truncate(text: string, max = 150): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max).trimEnd()}…` : clean;
}

// ---------------------------------------------------------------------------
// Activate (optimistic) — clicking any card sets it active.
// ---------------------------------------------------------------------------

function useSetActive() {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    // The Default card optimistically becomes active under id "default", but the
    // bridge clears the persona via "" (set_active rejects the synthetic id).
    mutationFn: (id: string) =>
      api.setActivePersonality(id === DEFAULT_ID ? "" : id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: PERSONALITIES_KEY });
      const prev = qc.getQueryData<PersonalitiesData>(PERSONALITIES_KEY);
      qc.setQueryData<PersonalitiesData>(PERSONALITIES_KEY, (old) =>
        old ? { ...old, active: id } : old,
      );
      return { prev };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(PERSONALITIES_KEY, ctx.prev);
      toast({
        variant: "error",
        title: "Couldn't switch persona",
        description: "Reverted — is the bridge running?",
      });
    },
    onSuccess: (_res, id) => {
      // The bridge returns "" when a persona is deselected (back to base Vox).
      if (id === "" || id === DEFAULT_ID) {
        toast({
          variant: "info",
          title: "Back to base Vox",
          description: "No special persona — Vox as itself.",
        });
        return;
      }
      const data = qc.getQueryData<PersonalitiesData>(PERSONALITIES_KEY);
      const found = [...(data?.presets ?? []), ...(data?.custom ?? [])].find(
        (p) => p.id === id,
      );
      toast({
        variant: "success",
        title: "Persona activated",
        description: found ? `${found.emoji} ${found.name}` : id,
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Create custom persona.
// ---------------------------------------------------------------------------

function useAddCustom(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (body: {
      name: string;
      persona: string;
      emoji?: string;
      suggestedVoice?: string;
      // Kokoro voice id for this persona; the backend forwards it to add_custom
      // and the running TTS reads it (falling back to the global voice).
      kokoroVoice?: string;
    }) =>
      // `api.addCustomPersonality` types its body without `kokoroVoice` (that
      // file isn't ours to edit); spread through a const so the extra field is
      // serialized into the POST without tripping TS's excess-property check.
      api.addCustomPersonality({ ...body }),
    onSuccess: (created) => {
      qc.setQueryData<PersonalitiesData>(PERSONALITIES_KEY, (old) =>
        old ? { ...old, custom: [...old.custom, created] } : old,
      );
      toast({
        variant: "success",
        title: "Persona created",
        description: `${created.emoji} ${created.name}`,
      });
      onDone();
    },
    onError: () => {
      toast({
        variant: "error",
        title: "Couldn't create persona",
        description: "Is the bridge running?",
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Edit custom persona (PATCH — only sent fields change; id stays stable).
// ---------------------------------------------------------------------------

function useUpdateCustom(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: {
        name?: string;
        persona?: string;
        emoji?: string;
        tagline?: string;
        suggestedVoice?: string;
        kokoroVoice?: string;
      };
    }) => api.updateCustomPersonality(id, body),
    onSuccess: (updated) => {
      // Re-fetch so the list reflects the persisted persona (the PATCH echoes
      // the full updated object, but invalidating keeps us in sync with the
      // bridge's canonical shape).
      qc.invalidateQueries({ queryKey: PERSONALITIES_KEY });
      toast({
        variant: "success",
        title: "Persona updated",
        description: `${updated.emoji} ${updated.name}`,
      });
      onDone();
    },
    onError: () => {
      toast({
        variant: "error",
        title: "Couldn't update persona",
        description: "Is the bridge running?",
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Set a persona's voice (works for presets — the bridge stores an override).
// ---------------------------------------------------------------------------

function useSetVoice() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, suggestedVoice }: { id: string; suggestedVoice: string }) =>
      api.setPersonalityVoice(id, { suggestedVoice }),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: PERSONALITIES_KEY });
      toast({
        variant: "success",
        title: "Voice updated",
        description: `${updated.name} → ${updated.suggestedVoice || "default"}`,
      });
    },
    onError: () =>
      toast({ variant: "error", title: "Couldn't update voice" }),
  });
}

// ---------------------------------------------------------------------------
// Delete custom persona.
// ---------------------------------------------------------------------------

function useRemoveCustom(onDone: () => void) {
  const qc = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (id: string) => api.removeCustomPersonality(id),
    onSuccess: (_res, id) => {
      qc.setQueryData<PersonalitiesData>(PERSONALITIES_KEY, (old) =>
        old ? { ...old, custom: old.custom.filter((p) => p.id !== id) } : old,
      );
      toast({ variant: "info", title: "Persona deleted" });
      onDone();
    },
    onError: () => {
      toast({
        variant: "error",
        title: "Couldn't delete persona",
        description: "Is the bridge running?",
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Default card — base Vox (no persona). Calm, neutral "base" look that reads as
// the absence of a character rather than a character. Clicking it deselects any
// active persona and returns to plain Vox.
// ---------------------------------------------------------------------------

function DefaultCard({
  active,
  pending,
  onActivate,
}: {
  active: boolean;
  pending: boolean;
  onActivate: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onActivate}
      aria-pressed={active}
      aria-label="Default — Vox as itself (no persona)"
      className={cn(
        "group relative flex h-full w-full flex-col rounded-2xl text-left transition-all duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
        pending && "opacity-70",
      )}
    >
      {/* Quieter halo than persona cards — base Vox is calm, not flashy. */}
      {active && (
        <span
          aria-hidden
          className="pointer-events-none absolute -inset-px rounded-2xl bg-accent/40 opacity-50 blur-md"
        />
      )}
      <Card
        glass
        className={cn(
          "relative flex h-full flex-col overflow-hidden p-5 transition-all duration-200",
          // Hairline dashed edge signals "no character" — a base slot, not a persona.
          active
            ? "ring-2 ring-accent shadow-[0_0_0_1px_hsl(var(--accent)/0.5)]"
            : "border border-dashed border-border-strong/70 ring-1 ring-transparent hover:-translate-y-0.5 hover:border-border-strong",
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <span
            className={cn(
              "flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl transition-colors",
              active
                ? "bg-accent/15 text-accent ring-1 ring-accent/30"
                : "bg-muted text-foreground-secondary ring-1 ring-border/60",
            )}
          >
            <Mic className="h-6 w-6" />
          </span>

          {active && (
            <Badge variant="accent" className="font-medium">
              <Check className="h-3 w-3" />
              Active
            </Badge>
          )}
        </div>

        <div className="mt-4 min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold text-foreground">
            Default
          </h3>
          <p className="mt-0.5 truncate text-sm text-foreground-secondary">
            Vox as itself
          </p>
          <p className="mt-3 line-clamp-3 text-xs leading-relaxed text-foreground-muted">
            No special character — Vox&apos;s plain, unstyled voice. Select this
            to clear any active persona and return to base.
          </p>
        </div>

        <div className="mt-4 flex items-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-muted/60 px-2.5 py-1 text-[11px] font-medium text-foreground-secondary">
            Base
          </span>
        </div>
      </Card>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Voice picker — the (now editable) pill on each card. Changes a persona's macOS
// `say` voice; works for presets too (the bridge stores an override). The current
// value is always offered even if it's not installed, so it can't be lost.
// ---------------------------------------------------------------------------

function VoicePicker({
  value,
  voices,
  onChange,
}: {
  value: string;
  voices: string[];
  onChange: (voice: string) => void;
}) {
  const options =
    value && !voices.includes(value) ? [value, ...voices] : voices;
  return (
    <Select
      value={value || NO_VOICE}
      onValueChange={(v) => onChange(v === NO_VOICE ? "" : v)}
    >
      <SelectTrigger
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        aria-label="Voice"
        className="h-7 w-auto gap-1.5 rounded-full border-border/70 bg-muted/60 px-2.5 text-[11px] font-medium text-foreground-secondary"
      >
        <AudioLines className="h-3 w-3 shrink-0 text-accent" />
        <SelectValue placeholder="Set voice" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_VOICE}>Default voice</SelectItem>
        {options.map((v) => (
          <SelectItem key={v} value={v}>
            {v}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// ---------------------------------------------------------------------------
// Persona card.
// ---------------------------------------------------------------------------

function PersonaCard({
  persona,
  active,
  pending,
  onActivate,
  onView,
  onEdit,
  onDelete,
  voices,
  onSetVoice,
}: {
  persona: Personality;
  active: boolean;
  pending: boolean;
  onActivate: () => void;
  onView?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  voices: string[];
  onSetVoice?: (voice: string) => void;
}) {
  return (
    // A div (not a <button>) so the voice <Select> can live inside it without nested-button issues;
    // click / Enter / Space still activate the persona.
    <div
      role="button"
      tabIndex={0}
      onClick={onActivate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onActivate();
        }
      }}
      aria-pressed={active}
      className={cn(
        "group relative flex h-full w-full cursor-pointer flex-col rounded-2xl text-left transition-all duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
        pending && "opacity-70",
      )}
    >
      {/* Accent glow halo behind the card when active. */}
      {active && (
        <span
          aria-hidden
          className="pointer-events-none absolute -inset-px rounded-2xl bg-brand-gradient opacity-60 blur-md"
        />
      )}
      <Card
        glass
        className={cn(
          "relative flex h-full flex-col overflow-hidden p-5 transition-all duration-200",
          active
            ? "ring-2 ring-accent shadow-[0_0_0_1px_hsl(var(--accent)/0.5)]"
            : "ring-1 ring-transparent hover:ring-border-strong hover:-translate-y-0.5",
        )}
      >
        {/* Subtle gradient wash in the corner for active cards. */}
        {active && (
          <span
            aria-hidden
            className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-brand-gradient opacity-20 blur-2xl"
          />
        )}

        <div className="flex items-start justify-between gap-3">
          <span
            className={cn(
              "flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl text-3xl transition-colors",
              active
                ? "bg-accent/15 ring-1 ring-accent/30"
                : "bg-muted ring-1 ring-border/60",
            )}
          >
            {persona.emoji || "✨"}
          </span>

          <div className="flex items-center gap-2">
            {active && (
              <Badge variant="accent" className="font-medium">
                <Check className="h-3 w-3" />
                Active
              </Badge>
            )}
            {!persona.preset && (
              <Badge variant="outline" className="font-normal">
                Custom
              </Badge>
            )}
          </div>
        </div>

        <div className="mt-4 min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold text-foreground">
            {persona.name}
          </h3>
          {persona.tagline && (
            <p className="mt-0.5 truncate text-sm text-foreground-secondary">
              {persona.tagline}
            </p>
          )}
          <p className="mt-3 line-clamp-3 text-xs leading-relaxed text-foreground-muted">
            {truncate(persona.persona)}
          </p>
        </div>

        <div className="mt-4 flex items-center justify-between gap-2">
          {persona.id !== "default" && onSetVoice ? (
            <VoicePicker
              value={persona.suggestedVoice || ""}
              voices={voices}
              onChange={onSetVoice}
            />
          ) : (
            <span />
          )}

          {/* Nested interactive controls — each stops propagation so it doesn't
              also activate the card. */}
          <div className="flex items-center gap-1">
            {onView && (
              <span
                role="button"
                tabIndex={0}
                aria-label={`View full persona text for ${persona.name}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onView();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    onView();
                  }
                }}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-accent/15 hover:text-accent focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
              >
                <Eye className="h-3.5 w-3.5" />
              </span>
            )}
            {onEdit && (
              <span
                role="button"
                tabIndex={0}
                aria-label={`Edit ${persona.name}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    onEdit();
                  }
                }}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-accent/15 hover:text-accent focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
              >
                <Pencil className="h-3.5 w-3.5" />
              </span>
            )}
            {onDelete && (
              <span
                role="button"
                tabIndex={0}
                aria-label={`Delete ${persona.name}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    onDelete();
                  }
                }}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-foreground-muted opacity-0 transition-all hover:bg-danger/15 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 group-hover:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </span>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create-or-edit custom persona dialog.
//
// With no `editing` prop it POSTs a new custom persona (as before). With an
// `editing` persona it pre-fills every field and PATCHes that persona in place
// (its id stays stable). Presets are never passed here — they're read-only.
// ---------------------------------------------------------------------------

// `Personality` doesn't carry kokoroVoice in its type (the create flow only
// sends it), but the bridge persists and may echo it back. Read it defensively
// so editing pre-fills the saved voice when present.
function personaKokoroVoice(p: Personality): string {
  const v = (p as { kokoroVoice?: unknown }).kokoroVoice;
  return typeof v === "string" ? v : "";
}

function PersonaFormDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // When set, the dialog edits this custom persona instead of creating one.
  editing?: Personality | null;
}) {
  const [name, setName] = React.useState("");
  const [emoji, setEmoji] = React.useState("");
  const [tagline, setTagline] = React.useState("");
  const [persona, setPersona] = React.useState("");
  const [voice, setVoice] = React.useState<string>(NO_VOICE);
  // Kokoro voice id; "" means "use the dashboard's global kokoro_voice".
  const [kokoroVoice, setKokoroVoice] = React.useState<string>("");

  const isEdit = !!editing;

  // Pre-fill (edit) or clear (create) the form whenever the dialog opens or the
  // target persona changes. Keying off `open` + `editing?.id` keeps the fields
  // in sync without clobbering in-progress typing on unrelated re-renders.
  React.useEffect(() => {
    if (!open) return;
    if (editing) {
      setName(editing.name ?? "");
      setEmoji(editing.emoji ?? "");
      setTagline(editing.tagline ?? "");
      setPersona(editing.persona ?? "");
      setVoice(editing.suggestedVoice || NO_VOICE);
      setKokoroVoice(personaKokoroVoice(editing));
    } else {
      setName("");
      setEmoji("");
      setTagline("");
      setPersona("");
      setVoice(NO_VOICE);
      setKokoroVoice("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing?.id]);

  const addCustom = useAddCustom(() => onOpenChange(false));
  const updateCustom = useUpdateCustom(() => onOpenChange(false));
  const pending = addCustom.isPending || updateCustom.isPending;

  const canSubmit = name.trim().length > 0 && persona.trim().length > 0;

  const handleSubmit = () => {
    if (!canSubmit || pending) return;
    if (editing) {
      updateCustom.mutate({
        id: editing.id,
        body: {
          name: name.trim(),
          persona: persona.trim(),
          // Empty strings clear these fields server-side (PATCH only touches
          // sent keys); send "" rather than undefined so edits can remove them.
          emoji: emoji.trim(),
          tagline: tagline.trim(),
          suggestedVoice: voice === NO_VOICE ? "" : voice,
          kokoroVoice: kokoroVoice,
        },
      });
      return;
    }
    addCustom.mutate({
      name: name.trim(),
      persona: persona.trim(),
      emoji: emoji.trim() || undefined,
      suggestedVoice: voice === NO_VOICE ? undefined : voice,
      // "" → omit so the backend falls back to the global kokoro_voice.
      kokoroVoice: kokoroVoice || undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent">
              {isEdit ? (
                <Pencil className="h-4 w-4" />
              ) : (
                <Wand2 className="h-4 w-4" />
              )}
            </span>
            {isEdit ? "Edit persona" : "Craft a persona"}
          </DialogTitle>
          <DialogDescription>
            Give Vox a voice and a point of view. The persona text becomes its
            system prompt while active.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-1">
          <div className="grid grid-cols-[5rem_1fr] gap-3">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground-secondary">
                Emoji
              </label>
              <Input
                value={emoji}
                onChange={(e) => setEmoji(e.target.value)}
                placeholder="✨"
                maxLength={4}
                className="text-center text-lg"
                aria-label="Emoji"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground-secondary">
                Name
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Zen Master"
                aria-label="Name"
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground-secondary">
              Tagline
              <span className="ml-1 font-normal text-foreground-muted">
                (optional)
              </span>
            </label>
            <Input
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
              placeholder="e.g. Calm, grounded, unflappable"
              aria-label="Tagline"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground-secondary">
              Persona
            </label>
            <Textarea
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              placeholder="Describe how Vox should speak and behave. Stay helpful — e.g. 'You are a calm, unflappable guide who answers in short, grounded sentences…'"
              className="min-h-[120px] resize-y leading-relaxed"
              aria-label="Persona"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground-secondary">
              Suggested voice
              <span className="ml-1 font-normal text-foreground-muted">
                (optional · macOS say)
              </span>
            </label>
            <Select value={voice} onValueChange={setVoice}>
              <SelectTrigger aria-label="Suggested voice">
                <SelectValue placeholder="No suggested voice" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_VOICE}>No suggested voice</SelectItem>
                {SAY_VOICES.map((v) => (
                  <SelectItem key={v} value={v}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label
              htmlFor="kokoro-voice"
              className="mb-1.5 block text-xs font-medium text-foreground-secondary"
            >
              Voice
              <span className="ml-1 font-normal text-foreground-muted">
                (Kokoro)
              </span>
            </label>
            {/* Native <select> (not the Radix Select) so it can hold an empty
                value for the "Default" option and use <optgroup> grouping. */}
            <select
              id="kokoro-voice"
              aria-label="Voice"
              value={kokoroVoice}
              onChange={(e) => setKokoroVoice(e.target.value)}
              className="flex h-9 w-full items-center justify-between whitespace-nowrap rounded-lg border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <option value="">Default — use the global voice</option>
              {KOKORO_VOICE_GROUPS.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.voices.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <p className="mt-1.5 text-xs text-foreground-muted">
              Only used when the TTS engine is Kokoro.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button
            variant="gradient"
            onClick={handleSubmit}
            disabled={!canSubmit || pending}
          >
            <Sparkles className="h-4 w-4" />
            {isEdit
              ? pending
                ? "Saving…"
                : "Save changes"
              : pending
                ? "Creating…"
                : "Create persona"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// View full persona text (read-only) — works for presets and custom alike.
// Presets can't be edited, so this is the only way to read their full prompt.
// ---------------------------------------------------------------------------

function ViewDialog({
  persona,
  onOpenChange,
}: {
  persona: Personality | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={persona !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent text-lg">
              {persona?.emoji || "✨"}
            </span>
            {persona?.name}
          </DialogTitle>
          {persona?.tagline && (
            <DialogDescription>{persona.tagline}</DialogDescription>
          )}
        </DialogHeader>

        <div className="grid gap-3 py-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="font-normal">
              {persona?.preset ? "Preset · read-only" : "Custom"}
            </Badge>
            {persona?.suggestedVoice && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-muted/60 px-2.5 py-1 text-[11px] font-medium text-foreground-secondary">
                <AudioLines className="h-3 w-3 text-accent" />
                {persona.suggestedVoice}
              </span>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground-secondary">
              Persona (full system prompt)
            </label>
            <div className="max-h-[55vh] overflow-y-auto whitespace-pre-wrap rounded-lg border border-border/70 bg-muted/40 px-3.5 py-3 text-sm leading-relaxed text-foreground-secondary">
              {persona?.persona || "—"}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Delete confirm dialog.
// ---------------------------------------------------------------------------

function DeleteDialog({
  persona,
  onOpenChange,
}: {
  persona: Personality | null;
  onOpenChange: (open: boolean) => void;
}) {
  const remove = useRemoveCustom(() => onOpenChange(false));

  return (
    <Dialog open={persona !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete persona?</DialogTitle>
          <DialogDescription>
            {persona && (
              <>
                <span className="text-foreground">
                  {persona.emoji} {persona.name}
                </span>{" "}
                will be permanently removed. This can&apos;t be undone.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={remove.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => persona && remove.mutate(persona.id)}
            disabled={remove.isPending}
          >
            <Trash2 className="h-4 w-4" />
            {remove.isPending ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Empty state for custom personas.
// ---------------------------------------------------------------------------

function CustomEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <FadeIn>
      <Card
        glass
        className="relative flex flex-col items-center justify-center overflow-hidden px-6 py-12 text-center"
      >
        <span className="pointer-events-none absolute -top-10 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-brand-gradient opacity-10 blur-3xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <UserPlus className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          No custom personas yet
        </h3>
        <p className="mt-1 max-w-sm text-sm text-foreground-secondary">
          Craft your own voice for Vox — a tone, a character, a system prompt.
          It&apos;ll live here and activate with one click.
        </p>
        <Button variant="gradient" className="mt-5" onClick={onCreate}>
          <Plus className="h-4 w-4" />
          Create your first persona
        </Button>
      </Card>
    </FadeIn>
  );
}

// ---------------------------------------------------------------------------
// Skeleton + section heading.
// ---------------------------------------------------------------------------

function CardSkeleton() {
  return (
    <Card glass className="p-5">
      <div className="flex items-start justify-between">
        <Skeleton className="h-14 w-14 rounded-2xl" />
        <Skeleton className="h-5 w-16 rounded-full" />
      </div>
      <Skeleton className="mt-4 h-5 w-32" />
      <Skeleton className="mt-2 h-4 w-40" />
      <Skeleton className="mt-3 h-3 w-full" />
      <Skeleton className="mt-1.5 h-3 w-5/6" />
      <Skeleton className="mt-4 h-6 w-24 rounded-full" />
    </Card>
  );
}

function SectionHeading({
  icon: Icon,
  title,
  count,
}: {
  icon: typeof Sparkles;
  title: string;
  count?: number;
}) {
  return (
    <div className="mb-4 flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent/15 text-accent">
        <Icon className="h-4 w-4" />
      </span>
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      {typeof count === "number" && (
        <span className="text-xs text-foreground-muted">{count}</span>
      )}
    </div>
  );
}

const GALLERY_GRID =
  "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Personalities() {
  const { data, isLoading, isError } = useQuery<PersonalitiesData>({
    queryKey: PERSONALITIES_KEY,
    queryFn: api.personalities,
  });

  const setActive = useSetActive();
  const pendingId = setActive.isPending
    ? (setActive.variables ?? null)
    : null;

  const setVoice = useSetVoice();
  const { data: voicesData } = useQuery({
    queryKey: ["voices"],
    queryFn: api.voices,
    staleTime: 5 * 60_000, // installed voices rarely change
  });
  const voices = voicesData?.voices ?? [];

  const [createOpen, setCreateOpen] = React.useState(false);
  const [toEdit, setToEdit] = React.useState<Personality | null>(null);
  const [toView, setToView] = React.useState<Personality | null>(null);
  const [toDelete, setToDelete] = React.useState<Personality | null>(null);

  const activeId = data?.active ?? "";
  const onDefault = activeId === DEFAULT_ID || activeId === "";

  // The bridge prepends a synthetic "Default" entry to `presets`; pull it out so
  // it can be rendered as a distinct base card, separate from the characters.
  const { defaultEntry, characterPresets } = React.useMemo(() => {
    const presets = data?.presets ?? [];
    return {
      defaultEntry: presets.find(isDefault) ?? null,
      characterPresets: presets.filter((p) => !isDefault(p)),
    };
  }, [data]);

  const activePersona = React.useMemo(
    () =>
      [...characterPresets, ...(data?.custom ?? [])].find(
        (p) => p.id === activeId,
      ),
    [characterPresets, data, activeId],
  );

  return (
    <div>
      <PageHeader
        title="Personalities"
        description="Choose a preset persona or craft your own. Click any card to make it Vox's voice."
        actions={
          <div className="flex items-center gap-3">
            {activePersona ? (
              <Badge variant="accent" className="font-normal">
                <Check className="h-3 w-3" />
                {activePersona.emoji} {activePersona.name}
              </Badge>
            ) : (
              !isLoading &&
              data &&
              onDefault && (
                <Badge variant="outline" className="font-normal">
                  <Mic className="h-3 w-3" />
                  Default — Vox as itself
                </Badge>
              )
            )}
            <Button variant="gradient" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              Create custom
            </Button>
          </div>
        }
      />

      {isError && (
        <Card
          glass
          className="mb-6 border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
        >
          Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
          <span className="font-mono">127.0.0.1:8765</span>? Personas will load
          once it&apos;s back.
        </Card>
      )}

      {isLoading ? (
        <div className={GALLERY_GRID}>
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <div className="space-y-10">
          {/* Presets */}
          <section>
            <SectionHeading
              icon={Sparkles}
              title="Presets"
              count={characterPresets.length}
            />
            <Stagger className={GALLERY_GRID}>
              {/* Base Vox always leads the gallery, visually set apart. */}
              {defaultEntry && (
                <StaggerItem key={defaultEntry.id} className="h-full">
                  <DefaultCard
                    active={onDefault}
                    pending={pendingId === DEFAULT_ID || pendingId === ""}
                    onActivate={() => {
                      if (!onDefault) setActive.mutate(DEFAULT_ID);
                    }}
                  />
                </StaggerItem>
              )}
              {characterPresets.map((p) => (
                <StaggerItem key={p.id} className="h-full">
                  <PersonaCard
                    persona={p}
                    active={p.id === activeId}
                    pending={pendingId === p.id}
                    onActivate={() => {
                      if (p.id !== activeId) setActive.mutate(p.id);
                    }}
                    onView={() => setToView(p)}
                    voices={voices}
                    onSetVoice={(v) =>
                      setVoice.mutate({ id: p.id, suggestedVoice: v })
                    }
                  />
                </StaggerItem>
              ))}
            </Stagger>
          </section>

          {/* Custom */}
          <section>
            <SectionHeading
              icon={UserPlus}
              title="Your personas"
              count={data?.custom.length}
            />
            {data && data.custom.length > 0 ? (
              <Stagger className={GALLERY_GRID}>
                {data.custom.map((p) => (
                  <StaggerItem key={p.id} className="h-full">
                    <PersonaCard
                      persona={p}
                      active={p.id === activeId}
                      pending={pendingId === p.id}
                      onActivate={() => {
                        if (p.id !== activeId) setActive.mutate(p.id);
                      }}
                      onView={() => setToView(p)}
                      onEdit={() => setToEdit(p)}
                      onDelete={() => setToDelete(p)}
                      voices={voices}
                      onSetVoice={(v) =>
                        setVoice.mutate({ id: p.id, suggestedVoice: v })
                      }
                    />
                  </StaggerItem>
                ))}
              </Stagger>
            ) : (
              <CustomEmptyState onCreate={() => setCreateOpen(true)} />
            )}
          </section>
        </div>
      )}

      {/* Create */}
      <PersonaFormDialog open={createOpen} onOpenChange={setCreateOpen} />
      {/* Edit — driven by the selected custom persona. */}
      <PersonaFormDialog
        open={toEdit !== null}
        editing={toEdit}
        onOpenChange={(o) => {
          if (!o) setToEdit(null);
        }}
      />
      <ViewDialog
        persona={toView}
        onOpenChange={(o) => {
          if (!o) setToView(null);
        }}
      />
      <DeleteDialog
        persona={toDelete}
        onOpenChange={(o) => {
          if (!o) setToDelete(null);
        }}
      />
    </div>
  );
}
