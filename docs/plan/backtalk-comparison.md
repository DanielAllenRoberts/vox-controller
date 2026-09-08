# backtalk vs Vox — how he made the Claude Agent SDK fast, and why ours is slow

> **Date:** 2026-09-01 · **Subject:** [jaredrhod/fullstack-agent](https://github.com/jaredrhod/fullstack-agent)
> and the piece that actually matters, [jaredrhod/backtalk](https://github.com/jaredrhod/backtalk) (both AGPL-3.0).
> **Question asked:** he gets the Claude SDK to respond quickly — ours takes forever. What's the trick?
> **Answer:** he never lets the session go cold, and he starts speaking before the reply is finished.
> Our `_claude_sdk` does the opposite of both, in four lines we can point at.

## First, what the repo actually is

`fullstack-agent` is **12 files** — an installer wizard, not an agent. It assembles four separate
repos: `ai-memory-vault` (memory), **`backtalk` (voice)**, `ai-visualizer` (a face), `barehands`
(webcam gesture control). The voice loop is the only one that overlaps Vox, and it's where the
latency work lives.

Its own claim: *"first audio in about 1 to 2 seconds on warm turns"* — with the full Claude Code
harness, tools, and project context in play.

## The trick, in his own words

`backtalk/brain.py`, module docstring:

> **"The warm brain — a persistent Claude session via the Agent SDK, streaming. One
> ClaudeSDKClient lives for the whole voice session: no per-turn process spawn, no per-turn context
> reload. Partial-message streaming means sentences are yielded the moment they're complete, so the
> mouth starts speaking while the rest of the thought is still forming."**

Two independent wins, and they multiply:

**1. A warm client.** `query()` spawns a fresh Claude Code session per call — process start, tool
discovery, system prompt, project context, every time. `ClaudeSDKClient` connects once and stays
connected. Anthropic's own docs are explicit: *"`query()` creates a new connection per call…
`ClaudeSDKClient` reuses a single connection across multiple `query()` calls… For low-latency
interactive apps: use `ClaudeSDKClient` with a persistent connection."*

**2. Sentence-level streaming.** `include_partial_messages=True` gives `StreamEvent` deltas. He
buffers text, regex-splits on `(?<=[.!?])\s`, and **yields each complete sentence as it forms** —
so TTS starts on sentence one while sentence four is still generating. Time-to-first-audio stops
being a function of reply length.

## Why ours is slow — `src/vox/assistant.py:508`

```python
opts = ClaudeAgentOptions(system_prompt=system, allowed_tools=[], max_turns=6, model=model)
...
async for msg in query(prompt=prompt, options=opts):     # ← new session EVERY utterance
    ...
return "".join(parts).strip()                            # ← nothing leaves until it's all done
```

Four separate problems, in order of cost:

| | Ours | Theirs |
|---|---|---|
| Session | `query()` — cold start per utterance | one `ClaudeSDKClient`, connected once |
| Output | `"".join(parts)` — wait for the whole reply | yield each sentence as it completes |
| History | re-serialised into the prompt as `"You: …\nVox: …"` every turn | the session remembers; nothing to resend |
| System prompt | `system_prompt=system` — **replaces** Claude Code's preset | `{"type": "preset", "preset": "claude_code", "append": …}` |

The third is worse than it looks: we pay the cold start *and* re-send a growing transcript that a
warm session would already hold — so the input grows while the cache stays cold.

**And this is the big brain.** `big_brain_provider = "claude_sdk"` on `claude-opus-4-8`, which is
what serves vision, `_click_fuzzy`, and every chat escalation. The slow path is the one that runs
when Vox is doing something hard, which is exactly when waiting feels worst.

**One thing we should NOT conclude:** that the Agent SDK is the wrong surface because we pass
`allowed_tools=[]` (full harness, zero harness benefit). It looks like the wrong surface, but the
Agent SDK is *the only way to bill against a Claude subscription* — the Messages API needs an API
key. The harness cost is the price of "no per-token cost", and the fix is to pay it **once per
session** instead of once per utterance.

## The traps he already hit — and one we will hit harder

**The drain-after-interrupt bug.** `reset_turn()` in `brain.py` documents it at length, and
Anthropic's docs now confirm it: *"After interrupting, you must drain all messages from
`receive_response()` before sending a new query — otherwise you'll receive the interrupted task's
leftover messages."*

His description of the failure:

> "The SDK client has ONE shared message stream and `receive_response()` stops at the FIRST
> ResultMessage it sees — there is no pairing between a query and its response. A cancelled turn
> stops consuming mid-stream, leaving the dead turn's remaining messages buffered. The next query
> then pairs with those leftovers: the first ask lands on the stale ResultMessage and yields
> nothing, and **every ask after that answers the PREVIOUS question — for the rest of the session.**"

**This is not a footnote for us — it's the main risk.** Vox has barge-in as a headline feature: say
"stop" and the reply is cut mid-sentence. That is *precisely* the condition that desyncs the pipe.
A warm client without a drain path would give us an assistant that answers one question late, all
day, and looks like a mishearing bug rather than a plumbing one. His containment is worth copying
wholesale: a `_dirty` flag set on query and cleared only on `ResultMessage`, a bounded drain, and a
session rebuild if the drain fails — losing that session's memory rather than running desynced.

**Model aliases.** His comment: *"Full model id ON PURPOSE — never a bare alias. The SDK resolves
aliases through its own bundled CLI and can silently land on an older model."* We pass
`big_brain_model` straight through, so we're fine today — worth not regressing.

**Bounded everything.** Every await in his brain has a timeout, and every failure is swallowed
rather than allowed to wedge the voice loop. Same discipline as our Kokoro deadlock fix.

## What to take

**1. A warm `ClaudeSDKClient` for the big brain.** The single biggest latency win available to us,
and it needs no new dependency — we already use the Agent SDK.

**2. Sentence streaming into the TTS we already have.** This is the part that's cheaper for us than
it was for him: `tts._speak_kokoro_streaming` + `_split_chunks` already speaks incrementally, and
`_StreamingPlayer` is already killable for barge-in. The missing link is upstream —
`assistant.respond()` / `complete()` return `str`, so the brain has no way to hand TTS anything but
a finished reply. A generator variant alongside them (not replacing them) is the whole job.

**3. The desync guard, ported before the warm client ships**, not after. With barge-in, this is the
difference between a speedup and a haunting.

**4. `exclude_dynamic_sections: True`** — from Anthropic's docs, not from backtalk. It moves cwd and
git-repo details out of the system prompt into the first user message, so the cached prefix stops
changing per machine and per directory. Free cache-hit improvement on top of the warm session.

## What to decline

- **The rest of the stack.** `ai-visualizer`, `barehands`, `ai-memory-vault` — a face, webcam
  gesture control, and a Markdown memory vault. We have our own memory design (#28) and the other
  two aren't what Vox is for.
- **His session-control-by-voice console** ("clear the session", "switch to the deep model", "set
  effort to low"). Genuinely nice, and it maps onto our command DB — but it's a feature, not the
  latency fix we came for. Note it, don't chase it.
- **Reaching past the SDK's public surface.** He calls `client._query._send_control_request({"subtype":
  "get_usage"})` for plan-usage readouts, and says outright it can break with nobody doing anything
  wrong. We already have `_record_usage` and a dashboard for cost. Not worth the private API.

## ⚠️ Licensing — read before copying a line

**backtalk is AGPL-3.0-or-later.** Vox is a public repo heading for open distribution. Copying his
code makes Vox AGPL. We already declined `kan` for exactly this reason when building the board.

The good news is that we don't need his code. Everything in "What to take" is **documented public
API** — `ClaudeSDKClient`, `include_partial_messages`, `StreamEvent` deltas, the drain-after-
interrupt requirement, `exclude_dynamic_sections` are all in Anthropic's Agent SDK docs, which is
where our implementation should come from. The technique is not the expression.

**So: read `brain.py` for what to watch out for, write ours from Anthropic's docs.** Don't paste.

## Sources

- <https://github.com/jaredrhod/fullstack-agent>
- <https://github.com/jaredrhod/backtalk> — `backtalk/brain.py`
- <https://code.claude.com/docs/en/agent-sdk/python>
