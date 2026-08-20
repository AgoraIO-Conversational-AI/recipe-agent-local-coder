# Repository Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the repository and local checkout from `recipe-agent-acp-local` to `recipe-agent-local-coder` without changing runtime behavior.

**Architecture:** Update only current machine-readable and maintained-document identifiers before changing repository infrastructure. Rename GitHub first, then repoint `origin`, stop the running checkout, move the local directory, and verify all identities from the new path.

**Tech Stack:** Git, GitHub CLI, Bun workspace metadata, Python FastMCP identifiers, Markdown documentation, macOS filesystem.

## Global Constraints

- Preserve runtime behavior, routes, ports, environment variables, and commands.
- Keep the `acp-local` recipe role and ACP implementation terminology.
- Do not rewrite historical design documents, plans, research reports, commits, or evidence.
- Keep the `upstream` remote unchanged.
- Do not start an Agora conversation during verification.

---

### Task 1: Rename current repository identifiers

**Files:**
- Modify: `package.json`
- Modify: `AGENTS.md`
- Modify: `docs/ai/L0_repo_card.md`
- Modify: `server/src/managed_ingress/mcp_app.py`
- Modify: `server/src/architecture_validation/mcp_app.py`

**Interfaces:**
- Consumes: the approved repository name `recipe-agent-local-coder`.
- Produces: current package, contributor, repo-card, and MCP service identifiers using the new name.

- [ ] **Step 1: Record the existing current-name surface**

Run:

```bash
rg -n "recipe-agent-acp-local" package.json AGENTS.md docs/ai/L0_repo_card.md server/src
```

Expected: matches only in the five files listed above.

- [ ] **Step 2: Replace current identifiers**

Apply these exact replacements:

```text
package.json name:
  recipe-agent-acp-local -> recipe-agent-local-coder

AGENTS.md repository identifier:
  recipe-agent-acp-local -> recipe-agent-local-coder

docs/ai/L0_repo_card.md title and Repo value:
  recipe-agent-acp-local -> recipe-agent-local-coder

server/src/managed_ingress/mcp_app.py FastMCP name:
  recipe-agent-acp-local -> recipe-agent-local-coder

server/src/architecture_validation/mcp_app.py FastMCP name:
  recipe-agent-acp-local-validation -> recipe-agent-local-coder-validation
```

- [ ] **Step 3: Verify identifier boundaries**

Run:

```bash
rg -n "recipe-agent-acp-local" . --hidden --glob '!.git/**' --glob '!research/**' --glob '!docs/superpowers/specs/**' --glob '!docs/superpowers/plans/**' --glob '!server/.env.local'
```

Expected: no matches. Matches in excluded historical material remain unchanged.

- [ ] **Step 4: Run offline verification**

Run:

```bash
bun run verify:backend
bun run verify:web:build
git diff --check
```

Expected: backend tests and web production build pass; `git diff --check` prints nothing.

- [ ] **Step 5: Commit current identifier changes**

```bash
git add package.json AGENTS.md docs/ai/L0_repo_card.md server/src/managed_ingress/mcp_app.py server/src/architecture_validation/mcp_app.py
git commit -m "chore: rename local coder recipe"
```

Expected: one commit containing only current-identifier updates.

### Task 2: Rename GitHub repository and local checkout

**Files:**
- Rename directory: `/Users/zhangqianze/Documents/recipe-agent-acp-local` to `/Users/zhangqianze/Documents/recipe-agent-local-coder`
- Modify repository-local Git configuration: `origin` URL only

**Interfaces:**
- Consumes: committed Task 1 identifiers and authenticated GitHub CLI access.
- Produces: renamed GitHub repository, synchronized feature branch, new local checkout path, and updated `origin`.

- [ ] **Step 1: Verify preconditions**

Run:

```bash
git status --short
gh auth status -h github.com
test ! -e /Users/zhangqianze/Documents/recipe-agent-local-coder
```

Expected: clean worktree, authenticated GitHub CLI, and no conflicting destination path.

- [ ] **Step 2: Rename the GitHub repository**

Run:

```bash
gh api --method PATCH repos/AgoraIO-Conversational-AI/recipe-agent-acp-local -f name=recipe-agent-local-coder
```

Expected: response `full_name` is `AgoraIO-Conversational-AI/recipe-agent-local-coder`.

- [ ] **Step 3: Repoint origin and push**

Run:

```bash
git remote set-url origin git@github.com:AgoraIO-Conversational-AI/recipe-agent-local-coder.git
git push origin feat/voice-llm-architecture-validation
```

Expected: push succeeds and the branch is synchronized with the renamed repository.

- [ ] **Step 4: Stop the exact running checkout process group**

Resolve listeners on ports `3000`, `8000`, and `8001`, verify they belong to this checkout's `bun run dev:codex` supervisor, and send `SIGTERM` to only that verified process group.

Expected: all three listeners stop without affecting unrelated processes.

- [ ] **Step 5: Rename the local checkout**

Run from `/Users/zhangqianze/Documents`:

```bash
mv recipe-agent-acp-local recipe-agent-local-coder
```

Expected: only the new directory exists.

- [ ] **Step 6: Verify final identity from the new path**

Run from `/Users/zhangqianze/Documents/recipe-agent-local-coder`:

```bash
git status -sb
git remote -v
git rev-parse HEAD
git rev-parse origin/feat/voice-llm-architecture-validation
gh repo view AgoraIO-Conversational-AI/recipe-agent-local-coder --json nameWithOwner,url
```

Expected: clean synchronized branch, new `origin`, unchanged `upstream`, matching local and remote commit IDs, and the new GitHub repository URL.

- [ ] **Step 7: Restart without live Agora usage**

Run:

```bash
bun run dev:codex
```

Expected: `http://127.0.0.1:8000/local/runtime` returns state `ready` and the frontend responds on `http://127.0.0.1:3000`; do not click **Start conversation**.
