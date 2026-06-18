# LangChain & LangGraph — research for Vox

> Research notes for deciding whether Vox should adopt LangGraph/LangChain, or borrow their
> patterns without the dependency. Grounded in the v1.0 docs (Oct 2025 release line).
> Vox's relevant code: `src/vox/core/loop.py` (state machine), `src/vox/actions.py` (intent
> parse), `src/vox/assistant.py` (provider-agnostic LLM).

## The landscape after v1.0

As of LangChain/LangGraph **1.0**, the two are layered:

- **LangGraph** — the *low-level* runtime: a stateful graph engine (nodes, edges, shared
  state, checkpointing). "Useful for highly custom and controllable agents… production-grade,
  long-running agents."
- **LangChain** — the *high-level* agent framework, **built on the LangGraph runtime**. Its
  headline API is `create_agent(model, tools, system_prompt)` plus a **middleware** system.

The older agent surface is **deprecated**: `AgentExecutor`, the classic `create_react_agent`
(in both `langchain.agents` and `langgraph.prebuilt`), and the legacy memory classes
(`ConversationBufferMemory`, `ConversationChain`) are slated for removal in 2.0. So any
adoption today means buying into the LangGraph-based stack, not the 2023-era chains.

## LangGraph — the state-machine model

This is the part most relevant to Vox, because Vox *already is* a hand-written state machine.

**State** is a `TypedDict` (or Pydantic model) threaded through every node. Fields can declare
**reducers** via `Annotated` — controlling how updates merge instead of overwriting:

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    mode: str                                  # default reducer: overwrite
    messages: Annotated[list, add_messages]    # reducer: append + dedupe by id
```

**Nodes** are plain functions `state -> partial_state`. **Edges** wire them up; conditional
edges do the routing:

```python
from langgraph.graph import StateGraph, START, END

builder = StateGraph(State)
builder.add_node("control", control_node)
builder.add_node("assistant", assistant_node)

def route(state: State) -> str:               # returns the next node name
    return state["mode"]

builder.add_conditional_edges(START, route, {"control": "control", "assistant": "assistant"})
builder.add_edge("control", END)
graph = builder.compile()                       # MUST compile before use
```

That `route` function is exactly Vox's `_is_control` / `_is_assistant` dispatch, expressed
as a graph edge. The model maps cleanly onto Vox's IDLE → mode → back loop.

### Persistence / checkpointing

Pass a **checkpointer** at compile; state is then saved automatically **after every super-step**,
keyed by a **`thread_id`**:

```python
from langgraph.checkpoint.memory import InMemorySaver
graph = builder.compile(checkpointer=InMemorySaver())

config = {"configurable": {"thread_id": "session-1"}}
graph.invoke({"messages": [{"role": "user", "content": "hi"}]}, config)
graph.invoke({"messages": [{"role": "user", "content": "and again"}]}, config)  # remembers turn 1
```

Checkpointer backends: `InMemorySaver` (lost on restart), `SqliteSaver`, `PostgresSaver`.
You get `graph.get_state(config)` and `graph.get_state_history(config)` for free, plus
"time travel" (resume from an older checkpoint). For Vox, a `SqliteSaver` would line up with
the planned SQLite runtime store in `overview.md`.

### Human-in-the-loop

`interrupt()` pauses a node, persists state (requires a checkpointer + `thread_id`), and waits;
you resume with `Command(resume=value)`, which becomes the return value of `interrupt()`:

```python
from langgraph.types import interrupt, Command

def confirm_node(state):
    ok = interrupt("Run this dangerous command?")   # pauses here
    return {"approved": ok}

graph.invoke(Command(resume=True), config)          # resumes, ok == True
```

This is directly applicable to Vox's "control mode is a hot mic" risk (`modes.md`):
a confidence-gated confirm step before executing a risky action.

### When LangGraph is genuinely worth it

- Long-running / resumable agents that must survive process restarts.
- Multi-step agentic flows with branching, retries, parallel fan-out, cycles.
- Human approval gates mid-execution.
- Multiple concurrent sessions/threads needing isolated, durable state.

### When it's overkill

For a **single-user, single-session** voice loop whose "graph" is 3 modes and whose mode
transitions are a handful of `if` checks, the graph engine adds indirection without buying
much. Vox's `loop.py` is ~200 lines and already does idle→mode→back, mode chaining, and
sleep/quit/restart. LangGraph would not make that shorter; it would make it heavier and
add a stack to learn and debug.

## LangChain agents — tool calling & ReAct

`create_agent` runs a standard **tool-calling loop** (the modern ReAct shape): send messages
to the model → if it emits tool calls, execute them, append results as tool messages, loop →
if no tool calls, return the answer.

```python
from langchain.agents import create_agent

def open_app(name: str) -> str:
    """Open a macOS app by name."""
    ...

agent = create_agent(model="anthropic:claude-haiku-4-5", tools=[open_app],
                     system_prompt="You control a Mac by voice.")
agent.invoke({"messages": [{"role": "user", "content": "open Safari"}]})
```

**Middleware** (v1) wraps that loop with hooks — built-ins include human-in-the-loop approval,
**message-history summarization**, and PII redaction; you can write custom hooks for
pre-processing/post-validation.

**Routing / intent classification** in this world is usually one of:
- A conditional edge that branches on a classifier node's output (graph routing), or
- Letting the tool-calling model itself pick the tool (model-as-router).

Vox's design is deliberately the opposite of model-as-router for the common case: a **fast
deterministic regex parse** (`actions.parse`) first, **escalate to the LLM only on miss**
(`loop.py` line 95). That tiered cascade (overview.md) is cheaper and lower-latency than
asking an LLM to classify every utterance — and it's a pattern LangChain doesn't give you;
you'd be bypassing the agent loop to keep it.

## Memory

Legacy `ConversationBufferMemory` / `ConversationChain` are **deprecated**. The recommended
approach is **LangGraph checkpointing for short-term memory** (the message list in state) and
a **LangGraph Store for long-term memory**. Two reusable strategies stand out:

**Trimming** — `trim_messages` keeps a window under a token budget before each model call:

```python
from langchain_core.messages import trim_messages

trimmed = trim_messages(
    messages, max_tokens=1000, strategy="last",
    token_counter=count_tokens, include_system=True, start_on="human",
)
```

**Summarization** — a summary node (or v1 `SummarizationMiddleware`) condenses old turns into
a running summary once history grows past a threshold, so context stays bounded without
losing the gist.

Vox today keeps memory as a plain `history` list of `(role, text)` tuples
(`loop.py:_assistant_mode`, passed into `assistant.respond_turn`). That's fine for short
sessions; the *patterns* worth importing are trimming and summarization, not the classes.

## Tradeoffs — adopt vs. borrow

| Concern | Adopt LangGraph/LangChain | Borrow the patterns |
|---|---|---|
| **Dependency weight** | Pulls `langgraph` + `langgraph-checkpoint`, `-sdk`, `-prebuilt`, `langchain-core`, `pydantic`, `xxhash`; LangChain adds more. Many MB across many packages. | Zero new deps. |
| **Disk budget** | Disk space can be a real constraint — favour lightweight deps. | None. |
| **Lock-in** | v1 just deprecated the v0 agent/memory APIs; churn is real. Vox's provider-agnostic layer (`assistant.py`) would partly invert to LangChain's model abstraction. | Patterns are timeless; no API to track. |
| **Complexity** | A graph engine + middleware to learn for a 3-mode loop. Conflicts with CLAUDE.md "minimum code… no speculative abstractions." | Stays in plain Python you already own. |
| **What you gain** | Free checkpointing, time-travel, HITL, multi-thread, a maintained tool loop. | You reimplement only the slivers you need. |

The honest read: most of LangGraph's payoff (durable multi-thread state, time travel,
resumable long-running agents) targets problems **a single-user local voice loop doesn't have**.
The genuinely nice bit — SQLite-backed conversation persistence — is ~30 lines against the
SQLite store Vox is already planning.

## How this applies to Vox

**Verdict: BORROW, don't adopt.** Do not add `langgraph`/`langchain` to `pyproject.toml`.
The framework's strengths (durable multi-thread checkpointing, time travel, resumable
long-running agents, a maintained tool loop) solve problems Vox doesn't have as a single-user,
single-session local assistant — and its weight (many MB, multiple transitive packages,
ongoing v1→v2 API churn) directly fights Vox's CLAUDE.md ("minimum code… no speculative
abstractions") and the tight disk budget. Reconsider **only** if Vox later grows true
multi-session, resumable, approval-gated agentic execution (the OpenCode/Tier-3 path).

Patterns worth stealing (cheap, framework-free):

1. **Explicit state + reducers, not ad-hoc returns.** Vox already models modes as strings
   returned up the call stack (`loop.py`). Borrow LangGraph's idea of a single typed `State`
   object (mode, history, flags) passed through, rather than threading separate args — clearer
   as modes grow, without a graph engine.

2. **Intent routing as a named dispatch table** (LangGraph's conditional-edge idea). Vox's
   `actions._run` dispatch dict and the `_is_*` predicates already are this; keep the
   **deterministic-first, escalate-on-miss** cascade and resist the model-as-router default.

3. **Message trimming before the LLM call.** Port the `trim_messages(strategy="last",
   max_tokens=…)` idea into `assistant.respond_turn` so long ASSISTANT sessions stay bounded
   in tokens/cost — a few lines, no dependency.

4. **Running summarization of old turns.** When `history` grows, fold older turns into a short
   summary string prepended to the system prompt (the `SummarizationMiddleware` idea, done by
   hand). Keeps multi-turn context cheap.

5. **SQLite-backed session persistence** (the checkpointer idea). Persist `(thread_id, mode,
   history)` to the planned SQLite store so a session survives a restart — mirroring
   `SqliteSaver` without importing it.

6. **A confirm/interrupt step for risky control actions** (the `interrupt()` HITL idea).
   For "hot mic" control mode (`modes.md`), gate high-risk actions behind a spoken
   confirmation before `actions.handle` executes — a plain conditional, not the graph runtime.

## Sources

- LangGraph persistence/checkpointing: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph graph API (State, reducers, nodes, edges): https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph human-in-the-loop / interrupt: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangChain 1.0 / LangGraph 1.0 announcement (create_agent, middleware, deprecations): https://www.langchain.com/blog/langchain-langgraph-1dot0
- `create_react_agent` reference (tool-calling loop): https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent
- LangGraph v1 migration guide: https://docs.langchain.com/oss/python/migrate/langgraph-v1
- `trim_messages` / memory how-to: https://docs.langchain.com/oss/python/langchain/overview
- LangGraph package structure & deps: https://deepwiki.com/langchain-ai/langgraph/2-core-architecture
- langchain-core on PyPI: https://pypi.org/project/langchain-core/
