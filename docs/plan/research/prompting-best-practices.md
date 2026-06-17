# Prompting & Agent Best Practices (research for Vox)

Field notes pulled from primary vendor guides (Anthropic, OpenAI), leaked/published agent
prompts (Claude Code), and voice-agent platforms (Vapi, ElevenLabs, Amazon Nova). Goal: harden
Vox's system prompt and decide whether the `[OPEN]`/`[DONE]` turn-taking tags are the right
mechanism. The Vox-specific takeaways are in the final section.

Vox's current prompt lives in `src/vox/assistant.py` (`_SYSTEM`), and the tag is parsed by
`_split_signal()` in the same file.

---

## 1. System-prompt structure for agents

The convergent structure across vendors is a small set of labelled sections, most-important-first,
each stating one kind of thing. ElevenLabs codifies a **six-block structure**: Personality,
Environment, Tone, Goal, Guardrails, Tools. Anthropic's guide maps the same idea onto **role,
task, context, examples, output format, constraints**. OpenAI: "The model reads your prompt top to
bottom, so put the most important information first... specify the full execution order when tool
use or side effects matter."

Concrete rules that show up everywhere:

- **Give it a role, explicitly.** Anthropic: "Setting a role in the system prompt focuses Claude's
  behavior and tone... Even a single sentence makes a difference." Vox already does this well
  ("You are Vox, a hands-free voice assistant and Mac controller the user built themselves").
- **Use XML/section tags to separate kinds of content.** Anthropic: "Wrapping each type of content
  in its own tag (e.g. `<instructions>`, `<context>`, `<input>`) reduces misinterpretation."
  Useful even in a short prompt because it lets you grow it without sections bleeding into each
  other. (Note: Claude is specifically tuned for XML tags; the OpenAI-compatible providers Vox
  supports do fine with Markdown headers too — both are just delimiters.)
- **Be explicit, with motivation.** Anthropic's single best illustration, directly relevant to
  voice:
  > Less effective: `NEVER use ellipses`
  > More effective: `Your response will be read aloud by a text-to-speech engine, so never use ellipses since the text-to-speech engine will not know how to pronounce them.`
  The model generalizes from the *reason*, so it handles cases you didn't enumerate.
- **Examples beat description for format/tone.** Anthropic: few-shot is "one of the most reliable
  ways to steer Claude's output format, tone, and structure"; recommends 3–5, wrapped in
  `<example>` tags. Vox currently has zero examples — the biggest cheap win available.
- **Define "done."** OpenAI's GPT-5 guide: the biggest agentic gains come from "giving the model a
  precise definition of what 'done' looks like." This is exactly the turn-taking problem.

## 2. Guardrails & rules that recur across good agent prompts

Patterns that appear in nearly every strong agent prompt:

- **Conciseness, stated as a hard target.** Claude Code's prompt is blunt: "Be extra concise", "Go
  straight to the point", "keep text between tool calls to ≤25 words. Keep final responses to ≤100
  words", "you're writing for a person, not logging to a console." Numeric targets work better than
  "be brief."
- **Don't hallucinate / stay grounded.** ElevenLabs: "Never guess or make up information",
  "Acknowledge when you don't know an answer instead of guessing." Anthropic's agentic variant:
  "Never speculate about code you have not opened... Never make any claims about code before
  investigating."
- **Don't claim tools/capabilities you don't have.** For Vox this maps to: don't pretend you can
  *run* Mac commands — you can only tell the user the voice phrase. The current prompt handles this
  ("You don't run these yourself" / "briefly say how they'd do it by voice"), which is the right
  instinct.
- **Stay in scope; hand off cleanly.** ElevenLabs: "If the customer's issue is not billing-related,
  transfer back to the orchestrator agent." Vox's analogue is steering control-style requests back
  to the voice command path.
- **Ask when unsure (one question at a time).** Vapi: "Ask only one question at a time" — critical
  for voice, where multi-part questions are unanswerable in one breath.
- **Prefer positive instructions over long banlists.** Anthropic: "Tell Claude what to do instead
  of what not to do" — `Do not use markdown` → `compose your response of smoothly flowing prose`.
  Long "never say X" lists can actually prime the banned tokens.
- **Don't over-prompt modern models.** Anthropic (4.6/4.8): "Where you might have said 'CRITICAL:
  You MUST...', you can use more normal prompting like 'Use this tool when...'." All-caps coercion
  now causes *over*-triggering.

## 3. Structured / controllable output: tags vs JSON vs tool calls

This is the crux for Vox's `[OPEN]`/`[DONE]`. Three mechanisms for getting a machine-readable
signal out of a model:

| Mechanism | How you get the signal | Reliability | Cost/latency | Fits Vox? |
|---|---|---|---|---|
| **Sentinel tag** in the text (`[OPEN]`/`[DONE]`) | regex-strip a token from the reply | Medium — model can omit, mis-place, or *speak* it | 1 call, no overhead | Yes, with a fallback |
| **Structured Outputs** (schema-constrained JSON) | parse a guaranteed-valid object | High — "the LLM will generate structured data that follows the desired schema 100% of the time" | 1 call | Partly — not portable across all of Vox's providers |
| **Tool call** | model emits a function call | High, but "always produces" risk; needs iteration caps | ≥2 calls (decide→execute) | Poor — overkill for a boolean |

Key guidance:

- Anthropic now explicitly recommends **Structured Outputs over prefill/tags** for forcing a
  format: "The Structured Outputs feature is designed specifically to constrain Claude's responses
  to follow a given schema... For classification tasks, use either tools with an enum field... or
  structured outputs."
- But forcing a schema for an *agentic decision* is called out as an anti-pattern: "Using a fixed
  schema with a `next_action` field instead of native tool calling is fragile workaround
  architecture." And structured outputs "always produce output" — fine for a boolean, bad when the
  model should sometimes decline.
- Tool calling earns its 2-call cost only for "multi-step workflows requiring conditional
  decision-making" and external side effects — not for a single boolean. "A tool-calling loop
  without a max iteration count is a production incident waiting to happen."

**Verdict for a single boolean like "expects a reply":** a sentinel tag is a *reasonable* choice
because it's free (no extra call) and provider-portable (Vox spans Claude SDK, Claude CLI, OpenAI,
DeepSeek — and structured-output APIs differ across them). The tag's weakness is reliability: the
model may forget it, or — worst case for voice — *speak it aloud*. Vox already mitigates both
(strips-anywhere regex + `?`-heuristic fallback). See recommendations for hardening.

## 4. Voice-specific prompting (spoken, not read)

Every voice platform converges on the same handful of rules:

- **Length: 1–2 sentences.** Vapi: "Keep responses to one or two sentences maximum... every token
  adds latency — dead air the caller experiences as the agent 'thinking'." Vox says "1–3
  sentences" — fine, lean toward 1–2.
- **No markdown / no lists.** Vapi: "Avoid formatting (bold, italics, markdown) and enumerated
  lists. Instead, use natural connectors like 'first... then... finally'." Phrase it positively
  (Anthropic) and with the TTS reason attached.
- **Spell out numbers, dates, symbols** (they're the #1 cause of TTS mispronunciation). Vapi:
  `$42.50` → "forty-two dollars and fifty cents"; `03/04/2025` → "March fourth, twenty
  twenty-five"; phone numbers as individual digits. Vox sends text straight to macOS `say`, so this
  has to happen in the prompt.
- **Handle ASR errors by asking, not guessing.** Vapi: on a bad transcript, "I'm sorry, I didn't
  quite catch that. Could you please repeat that?" — don't silently act on a mis-hear. This is
  highly relevant: Vox runs Whisper `base.en` and the config already shows phonetic confusion
  ("hey vox/vaux/vocks/fox/box", "switch" → "search"). The LLM should treat a garbled or
  nonsensical transcript as a mis-hear and ask for a repeat rather than confabulate an answer.
- **One question at a time** (Vapi), and **define personality/tone explicitly** rather than "a
  helpful assistant" (ElevenLabs). Vox's "helpful, warm, and direct" is good; keep it tight.
- **No ellipses / no emoji** — they have no spoken form.

## 5. Evals — lightweight regression testing for a solo dev

You don't need a platform; you need a small frozen test set and an assertion runner.

- **Golden set, kept tiny.** "Start small with 10–20 high-priority examples that cover your most
  critical use cases and common edge cases." For Vox: a dozen `(user_utterance → expected
  behaviour)` rows covering each mode-explanation, a refusal/handoff case, a mis-hear case, and —
  critically — several `[OPEN]` vs `[DONE]` cases (question vs statement vs "thanks, bye").
- **Assert on cheap structural properties, not exact wording.** For Vox the high-value automatable
  assertions are: reply contains exactly one valid tag; tag never survives into spoken text
  (`_split_signal` strips it); reply ≤ N sentences; no markdown characters (`* # _ \`` ); no bare
  digits in number-heavy replies. These are plain `assert`s over `respond_turn()` output — no
  framework needed.
- **Use an LLM-judge only for the fuzzy bits** (tone, "did it ask one question"), and keep it
  separate from the deterministic gate.
- **`promptfoo`** is the standard off-the-shelf option if you want config-over-code: "simple,
  declarative test cases that don't require writing code", runs as a CLI in CI, caches results.
  Worth it once the golden set grows; overkill at 12 rows.
- **Run it as a gate before changing the prompt**, and diff old-vs-new on the same set so you can
  see exactly what a wording change moved.

---

## How this applies to Vox

1. **Keep the `[OPEN]`/`[DONE]` tag — but harden it.** It's the right call: a single boolean,
   zero extra latency, and portable across all four providers (structured-output APIs aren't
   uniform across Claude SDK / CLI / OpenAI / DeepSeek, and a tool call's 2× round-trip is
   unjustified for one bit). The keep-it case rests on the fallbacks already in `_split_signal`.
   Hardening: (a) give 2–3 few-shot examples of tagged replies — the single biggest reliability
   lever; (b) explicitly warn it the tag is *spoken* if leaked, so suppression matters; (c) keep
   the strip-anywhere regex and `?`-fallback; (d) add an eval asserting the tag never reaches TTS.

2. **Add a TTS-formatting block with the *reason* attached.** Tell it numbers/dates/symbols are
   read by macOS `say`, so spell them out ("twenty twenty-six", not "2026"; "eight thirty a.m.").
   Per Anthropic, the reason makes it generalize. This is currently missing and is a common live
   failure mode.

3. **Tighten length to 1–2 sentences with a numeric ceiling**, phrased positively ("answer in one
   or two short spoken sentences"), and forbid markdown by describing prose, not banning syntax.

4. **Add explicit mis-hear handling.** One line: if a transcript is garbled, empty, or
   nonsensical, ask the user to repeat instead of guessing — Vox's Whisper `base.en` + phonetic
   confusion list makes this a real, frequent case, not a hypothetical.

5. **Convert the prompt to labelled sections.** Even short, sectioning (`<role>`, `<voice>`,
   `<modes>`, `<turn_taking>`, `<guardrails>`) makes it editable without cross-contamination and
   plays to Claude's XML tuning, while staying Markdown-readable for the OpenAI-compatible path.

6. **Soften any coercive phrasing.** "append exactly one control tag" is fine; avoid drifting into
   ALL-CAPS "MUST" stacking, which over-triggers on 4.x models (Anthropic).

7. **Stand up a 12-row golden set + plain `assert` runner** over `respond_turn()`: one-tag-only,
   tag-stripped-from-text, ≤2 sentences, no markdown, correct `expects_reply` on a handful of
   question-vs-statement cases. Run it before/after every prompt edit.

8. **Add 2–3 few-shot examples** to the prompt itself (a question → `[OPEN]`, a closed answer →
   `[DONE]`, a "thanks/bye" → `[DONE]`). Examples are the most reliable steering tool and directly
   improve tag accuracy.

### Suggested improved skeleton (`_SYSTEM`)

```text
<role>
You are Vox, a hands-free macOS voice assistant the user built. You run locally
(Whisper speech-to-text + a wake word). The user is SPEAKING to you and your reply is
read aloud.
</role>

<voice>
Reply in one or two short spoken sentences of plain, flowing speech — no markdown,
lists, emoji, or ellipses. Your text goes straight to a text-to-speech engine, so spell
out numbers, dates, times and symbols as words ("twenty twenty-six", "eight thirty
a.m.", "fifty dollars"). Tone: warm, direct, helpful. Ask at most one question per turn.
</voice>

<modes>
• CONTROL ("take control"): deterministic Mac commands (open apps, switch tabs/windows,
  web search, dictation). You do NOT run these — if asked, say the voice phrase the user
  would use.
• ASSISTANT ("Hey Vox"): this is you — conversation and questions.
• DICTATION ("start typing"): the user's speech is typed at the cursor.
Unrecognised control commands hand off to you. "Vox, <command>" runs a one-shot from idle.
</modes>

<guardrails>
If a transcript is garbled, empty, or makes no sense, assume you mis-heard and ask the
user to repeat — never guess or make up an answer. Don't claim to do things you can't do
from here.
</guardrails>

<turn_taking>
End every reply with exactly one tag: [OPEN] if you expect the user to respond (you asked
something or invited them to continue), else [DONE]. The tag is stripped before your
reply is spoken — never say it aloud or mention it. When unsure, use [OPEN].
</turn_taking>

<examples>
User: what's the weather like
You: I can't check live weather from here, but you can say "take control, search weather"
to look it up. [DONE]

User: remind me what dictation does
You: Say "start typing" and I'll type whatever you speak at the cursor. Want to try it? [OPEN]

User: thanks, that's all
You: Anytime. [DONE]
</examples>
```

(For the OpenAI/DeepSeek path the same content works with `##` Markdown headers instead of
XML tags — both are just delimiters; keep one source string and it reads fine either way.)

## Sources

- Anthropic — Prompting best practices: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Anthropic — Structured Outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- OpenAI — Prompt engineering guide: https://platform.openai.com/docs/guides/prompt-engineering
- OpenAI — GPT-5 prompting guide (completion criteria, eagerness, contradictory instructions): https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
- Vapi — Voice AI prompting guide: https://docs.vapi.ai/prompting-guide
- ElevenLabs — Agent prompting guide (six-block structure): https://elevenlabs.io/docs/eleven-agents/best-practices/prompting-guide
- Amazon Nova — Speech-to-speech system prompt guidelines: https://docs.aws.amazon.com/nova/latest/userguide/prompting-speech-speech.html
- Structured Outputs vs Tool Calling (decision guide): https://dev.to/thedailyagent/structured-outputs-vs-tool-calling-when-your-agent-actually-needs-which-kgk
- How Claude Code builds a system prompt (conciseness/structure, verbatim): https://www.dbreunig.com/2026/04/04/how-claude-code-builds-a-system-prompt.html
- Leaked system prompts collection: https://github.com/asgeirtj/system_prompts_leaks
- Claude Code system prompts (versioned): https://github.com/Piebald-AI/claude-code-system-prompts
- Promptfoo (lightweight evals): https://www.promptfoo.dev/docs/intro/
- Golden dataset vs random sampling for LLM regression tests: https://dev.to/practicaldeveloper/random-prompt-sampling-vs-golden-dataset-which-works-better-for-llm-regression-tests-1ln7
