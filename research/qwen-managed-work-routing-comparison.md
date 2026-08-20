# Qwen Audio Agent vs. Managed Work Routing

**Reviewed:** 2026-08-20  
**Qwen upstream:** [`QwenAudio/qwen-audio-agent@774aaf4f820e3ac19938587b8511ac74a30b5d73`](https://github.com/QwenAudio/qwen-audio-agent/tree/774aaf4f820e3ac19938587b8511ac74a30b5d73)  
**Local comparison point:** [`recipe-agent-acp-local@22770cd0e4b3c0f013bb717136876e40a371d5d2`](https://github.com/AgoraIO-Conversational-AI/recipe-agent-acp-local/tree/22770cd0e4b3c0f013bb717136876e40a371d5d2)

## Question

What can the Managed Voice LLM → MCP → local ACP route learn from Qwen Audio
Agent after a live turn completed MCP discovery but answered that it could not
inspect the Project Folder and asked the user to provide a command instead of
calling `start_work`?

## Conclusion

Qwen does **not** solve this with deterministic backend routing. In its main
voice path, the Realtime model receives instructions and function tools and is
left to choose a tool. There is no `tool_choice` override for ordinary user
turns, no code-level intent classifier that directly dispatches work, and no
retry that converts an ordinary model answer into a backend task.

Its useful advantage is a clearer capability contract:

1. the voice assistant is told that registered tools are its own capabilities;
2. it must call them directly instead of saying that it cannot access something
   or needs to hand the request off;
3. the current working directory is supplied as runtime context; and
4. the background-work tool says that a clear objective should be called
   directly and accepts a natural-language objective.

The local recipe should adopt those principles without copying Qwen's category
lists. This is a prompt-and-tool-contract repair, not a reason to add an intent
classifier or Custom LLM.

## How Qwen routes a voice request

### 1. The Realtime model owns the routing decision

For an ordinary voice session, Qwen builds a session with the assembled
instructions and registers the frontend tools when the selected model supports
function calling. It does not set `tool_choice`, so normal tool selection stays
model-driven ([session construction](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/voice/providers/dashscope.mjs#L70-L91)).

Qwen only sets `tool_choice: "none"` for synthetic turns that speak an already
available backend result or ask a permission question; that prevents those
injected turns from starting new work ([result and permission injection](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/voice/providers/dashscope.mjs#L100-L123)). It does not force
`spawn_thinking` for an ordinary request.

### 2. The main prompt is mostly principle-based, but not enumeration-free

Qwen's top-level routing rule distinguishes direct conversational answers,
specialized tools, and background work. It does enumerate broad triggers such
as current information, investigation, files, code, and application operations
([routing rule](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/config/frontend-agent/PROMPT.md#L24-L29)). Therefore Qwen is not evidence that scenario enumeration is necessary; it is only evidence that their current prompt contains some.

The stronger and more transferable rule follows immediately after it: tool
descriptions and schemas are capability contracts; anything available through
a registered tool is the assistant's own capability; and the assistant must not
first say that it cannot access the resource or that the task must be handed
off ([capability ownership rule](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/config/frontend-agent/PROMPT.md#L31-L34)). That directly addresses the observed local failure.

### 3. Workspace state is explicit runtime context

Qwen normalizes the client working directory and adds it to a bounded
`runtime_context` block when one is available
([context construction](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/conversation/frontend-agent-context.mjs#L15-L41), [runtime injection](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/conversation/frontend-agent-context.mjs#L133-L152)). Its prompt then defines “current directory” references against that runtime field rather than asking the user to provide a command or repeat the location ([directory-reference rule](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/config/frontend-agent/PROMPT.md#L36-L38)).

The local recipe should expose the **fact** that one Project Folder is already
selected, but it does not need to expose the path. Its capability binding
already resolves the Workspace server-side.

### 4. The tool description carries substantial routing policy

Qwen's `spawn_thinking` description says that it is the assistant's execution
capability, that a clear request should be called directly, and that the model
must not deny the capability or announce a handoff first. Its `objective`
parameter is explicitly the executable natural-language goal, preserving the
user's requested result and constraints
([tool contract](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/voice/frontend-tools.mjs#L15-L38)).

By comparison, the local `start_work` description only says “Accept one complete
executable coding objective without waiting,” which does not tell the Managed
LLM that natural language is sufficient or that the selected Project Folder is
available through the tool
([current local tool description](https://github.com/AgoraIO-Conversational-AI/recipe-agent-acp-local/blob/22770cd0e4b3c0f013bb717136876e40a371d5d2/server/src/managed_ingress/mcp_app.py#L40-L50)).

### 5. Code handles a tool call; it does not infer one

After the model emits a function call, Qwen parses and dispatches the named
tool, rejects unknown names, and applies stale-turn and duplicate-call guards
([tool-call dispatch](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/voice/tools/tool-call-handler.mjs#L324-L403)). If the model calls `spawn_thinking` without an objective, Qwen may recover the objective from the
turn transcript; that recovery happens only **after** a tool call exists
([objective fallback](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/voice/tools/tool-call-handler.mjs#L487-L508)). Work is then created from the accepted objective and a server-derived submission key
([work submission](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/server/src/voice/tools/tool-call-handler.mjs#L534-L619)).

Nothing in this path detects “the model answered without calling a tool” and
retries the turn. Qwen could still have a model-selection miss; its prompt and
tool contract make that miss less likely.

## Routing comparison

| Concern | Qwen main voice path | Local Managed LLM path | Implication |
|---|---|---|---|
| Routing owner | Qwen Realtime model | Agora Managed Voice LLM | Both depend on model tool selection. |
| Ordinary-turn `tool_choice` | Not set | Not set | Qwen does not justify forcing all turns through a tool. |
| Code intent classifier | None in the main voice path | None | Do not add one for this failure. |
| Direct backend dispatch | Only after a model tool call | Only after an MCP `tools/call` | MCP discovery alone proves availability, not selection. |
| Semantic retry after no call | None found | None | Improve the contract, then verify live. |
| Workspace context | Working directory is injected and reference semantics are defined | Workspace is bound server-side but the model is not clearly told it is selected | State capability availability without exposing the path. |
| Execution tool contract | “This is your capability”; call directly; natural-language objective | Generic “complete executable coding objective” | Make ownership and input form explicit. |
| Scenario enumeration | Broad categories exist in prompt/tool text | Current prompt lists project files, commands, code changes, verification | Neither list is required; use a boundary rule instead. |

## Patterns worth learning

### Treat delegated execution as the assistant's capability

The voice model should not conceptualize `start_work` as asking another party
to do something the assistant cannot do. The tool is how the assistant acts on
the selected Workspace. This changes the relevant decision from “Can I inspect
the folder?” to “Does this answer depend on the selected Workspace or its local
environment?”

### Put routing semantics in both instruction and tool contract

The system prompt defines the boundary; the tool description defines the call.
Using both is not redundant: the Managed LLM sees the MCP tool contract during
tool discovery, and the live failure occurred despite discovery succeeding.

### Provide state, not scenario examples

Qwen's useful runtime fact is that a working directory exists. For this recipe,
the equivalent is simply: one Project Folder is already selected and is the
Workspace used by `start_work`. The model does not need the path or a list of
things people might do in it.

### Clarify only for an undefined outcome

Qwen asks for one necessary clarification only when core information cannot be
reasonably inferred ([clarification boundary](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/config/frontend-agent/PROMPT.md#L31-L38)). A user-supplied shell command is not a prerequisite when the requested outcome is already clear.

## Patterns not portable or not desirable

### Do not copy Qwen's category lists

The broad lists in Qwen's prompt and tool description are examples of their
current product surface, not a required routing mechanism. Copying or expanding
them would create an incomplete taxonomy, drift as capabilities grow, and
conflict with the approved requirement not to preset scenarios.

### Do not copy the car example's forced skill router

The repository's separate car example contains a code-level matcher for custom
skill names/descriptions and forces the matching function on the first round
([matcher](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/examples/car/server/agent.mjs#L59-L80), [forced first-round choice](https://github.com/QwenAudio/qwen-audio-agent/blob/774aaf4f820e3ac19938587b8511ac74a30b5d73/examples/car/server/agent.mjs#L223-L236)). This is not Qwen's main full-duplex voice-to-backend route. It requires owning the LLM loop, introduces matching heuristics, and would push this recipe toward Custom LLM. It is also exactly the sort of scenario preset the local design rejects.

### Do not force `tool_choice=required`

Ordinary conversation must remain possible. Qwen's main route leaves tool choice
to the model and only disables tools on controlled result/permission turns. A
global required setting would solve one missed call by breaking the direct-chat
half of the assistant.

### Do not assume Qwen's post-call recovery solves a no-call failure

Transcript fallback, idempotency, stale-turn checks, and tool-output instructions
make an accepted call robust. They cannot repair a turn in which the Realtime
model never emitted the call.

## Concrete recommendation

Keep Managed LLM + MCP and retain the four-tool surface. Replace the task-type
enumeration in the Managed Work prompt with one capability boundary:

> One Project Folder is already selected. You act on that Workspace through
> `start_work`. If answering or acting depends on the selected Workspace or its
> local environment, call `start_work` with the user's objective in natural
> language. Do not ask the user to provide a command or say that you cannot
> access the Project Folder unless the tool reports that it is unavailable.
> Ask one question only when the requested outcome cannot be determined from
> the conversation.

Change the MCP description to the same abstraction, for example:

> Delegate one complete natural-language objective to the local coding Agent in
> the already-selected Project Folder and return immediately after acceptance.

Keep the existing state-specific rules for status, cancellation, and permission
decisions. Do not add examples, task categories, keyword matching, a second
classifier, forced tool choice, or a Custom LLM. Add offline contract tests for
the prompt and MCP description, but treat them as configuration checks rather
than proof of model behavior. The decisive verification remains one short live
turn that produces a `start_work` `tools/call` and a new Work receipt.

