# Vox — Modes & Activation Design

> How Vox switches between doing-what-you-say and talking-to-an-LLM, and which wake/sleep phrases we need to train to make that happen.
>
> **Status:** implemented in v1 with **placeholder** built-in wake words (`hey_jarvis` = control, `hey_mycroft` = assistant) and text-matched sleep ("stand down"). Custom "Vox" phrases swap in after training. Assistant mode's LLM call is stubbed until M4.

## The key insight

A "mode" is **not a separate model** — it's a *behaviour* in the dispatch layer. What we actually **train** are the **activation/sleep phrases** (small openWakeWord models). openWakeWord can load several phrase-models at once and score them all in parallel every frame, so the daemon can listen for every trigger simultaneously while idle.

## States

| State | What it does | Compute |
|---|---|---|
| **IDLE** | Listens only for activation phrases. Nothing else runs. | Cheap (wake detection only) |
| **CONTROL MODE** (Dragon-style) | Continuously transcribes + **executes commands** — no wake word per command. Deterministic actions / rules. Exits on the sleep phrase. | STT + action dispatch while active |
| **ASSISTANT MODE** (Siri/Alexa-style) | Routes your speech to the **LLM** for a conversational request/answer. The "built-in ecosystem". Exits on completion, timeout, or sleep phrase. | STT + LLM call |

## Flow

```
IDLE
 ├─ "control phrase"    → CONTROL MODE ─(transcribe + execute each utterance)…─┐
 │                                                                             │
 │                          "sleep phrase"  ───────────────────────────────────┤→ back to IDLE
 │                                                                             │
 └─ "assistant phrase"  → ASSISTANT MODE ─(LLM handles request)─ done/timeout ─┘
```

## The phrases to train (this is "what we need to train")

Each is one custom openWakeWord model, trained via the runbook in `wake-word-training.md` (synthetic TTS + frozen feature extractors — **not** from scratch).

| Purpose | Example phrase (TBD) | Notes |
|---|---|---|
| Enter **control mode** | e.g. "Vox, take control" | begins continuous command-following |
| **Sleep / deactivate** | e.g. "go to sleep" | exits any active mode → IDLE; should be reliable and ideally global |
| Enter **assistant (LLM) mode** | e.g. "Hey Vox" | Siri-style; one request or a short conversation |

## Design considerations / decisions to make

- **Phrase distinctiveness.** Triggers should be acoustically distinct from each other *and* from everyday speech, to avoid false fires and cross-triggering. ⚠️ "go to sleep" is a common phrase — it could false-trigger mid-conversation. Options: pick a more distinctive kill phrase (e.g. "Vox, stand down"), and/or only listen for sleep *while a mode is active*.
- **Control mode is a "hot mic."** It executes whatever it hears as a command — powerful but risky. Needs: a clear mode indicator (visual/audio), confidence gating before acting, and a rock-solid sleep phrase. Decide: execute *every* utterance, or require a command grammar/verb?
- **Assistant mode shape.** One-shot ("Hey Vox, what's the weather" → answer → idle) or multi-turn (stays in a short conversation until a pause/timeout)?
- **Sleep should probably be global** — a dependable "stop everything" phrase that works in any state. Recommended.
- **Alternative we're *not* taking (noted for the record):** a single wake word that routes by intent (command vs question). We're choosing **explicit per-mode triggers** for instant, unambiguous mode entry — more deliberate, fewer surprises.

## Open questions (let's lock these)

1. Exact phrase for each of the 3 triggers (control / sleep / assistant).
2. Control mode: execute every utterance, or require a verb/grammar?
3. Assistant mode: one-shot or multi-turn?
4. Sleep phrase: global (any state) — yes?

## Relationship to the rest of the plan

- **Control mode** ≈ the deterministic / rules + fast-action side of the tiered cascade (`overview.md`).
- **Assistant mode** ≈ the LLM side (fast → deep model escalation).
- Personalised STT and the learned-rules DB are *separate* training efforts (see `overview.md`/`roadmap.md`) — distinct from these wake-phrase models.
