# Managed Work Routing Prompt Design

**Date:** 2026-08-20  
**Status:** Revised for approval

## Problem

Live acceptance proved that Agora completed MCP initialization and returned all
four production tools, but the Managed Voice LLM did not call `start_work` for
this request:

> Inspect the current project folder and tell me the names of its top-level
> files. Do not modify anything.

Instead, it said it could not inspect the Project Folder and asked the user to
provide a command. ngrok recorded no `tools/call`, and the Work database stayed
empty.

The current system prompt says to use `start_work` for a complete request, but
does not state that the Project Folder is already selected or that natural
language is sufficient. The current tool description also says only that it
accepts a complete executable objective.

## Decision

Strengthen only the Managed Work prompt and the public `start_work` tool
description.

The system prompt will use one capability-based routing rule rather than an
enumeration of task types or examples:

- the Project Folder is already selected and available to the local coding
  Agent;
- when a response or action depends on Workspace contents or local tooling, the
  voice model delegates the user's objective through `start_work` instead of
  attempting the task itself;
- `start_work` accepts a complete natural-language objective and does not
  require a shell command from the user;
- the voice model must not claim that it cannot inspect the Project Folder or
  ask the user to translate a clear objective into a command;
- it asks one clarification only when the objective lacks information required
  to define the requested outcome.

The `start_work` description will say that it delegates a natural-language
objective to the local coding Agent in the already-selected Project Folder.

## Non-Goals

- Do not set `tool_choice=required`; ordinary conversation must remain possible.
- Do not change the Managed model, temperature, STT, TTS, or VAD.
- Do not introduce Custom LLM routing or a second intent classifier.
- Do not execute commands in the voice process or expose the Workspace path.
- Do not enumerate, classify, or provide examples of anticipated Work scenarios
  in the prompt or tool description.
- Do not claim deterministic tool choice; Managed LLM selection remains model
  behavior and requires one live acceptance after offline contract checks.

## Verification

Offline tests will verify two stable configuration contracts:

1. `build_work_voice_llm()` serializes a system message containing the
   selected-Workspace, capability-based routing, natural-language delegation,
   and no-command-required rules, without a task-type list.
2. `create_mcp_server(...).list_tools()` exposes `start_work` with a description
   that identifies natural-language delegation and the selected Project Folder.

The existing MCP handshake, tool schema, capability, and Task Runtime tests
must remain green. Automated verification does not call Agora or ngrok.

One separately authorized live conversation will repeat the same read-only
request. Acceptance requires a recorded `tools/call` for `start_work` and one
new Work receipt. Completion still requires a later `get_work_status` request;
proactive result speech remains out of scope.
