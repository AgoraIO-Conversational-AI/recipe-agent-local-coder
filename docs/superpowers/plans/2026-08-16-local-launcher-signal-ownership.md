# Local Launcher Signal Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `bun run dev:codex` own terminal signals once, shut down every local descendant, and exit without Uvicorn or ACP tracebacks.

**Architecture:** Keep the public Bash launcher and `concurrently`, but replace the shell trap with `exec python3 scripts/supervise-local.py`. The Python supervisor remains in the terminal process group, starts `concurrently` in a new session, signals only its root during graceful shutdown, and uses the isolated group only for bounded escalation and residual cleanup.

**Tech Stack:** Bash, Python 3.10+ standard library, Bun/TypeScript integration harness, `concurrently@8.2.2`.

## Global Constraints

- Preserve `bun run dev:codex`, `--workspace`, `--acp-command-json`, `LOCAL_BACKEND_COMMAND`, and `LOCAL_FRONTEND_COMMAND` contracts.
- Keep `concurrently` responsible for labeled output, fail-fast behavior, and sibling shutdown.
- The first SIGINT or SIGTERM is delivered only to the `concurrently` root; SIGHUP maps to root SIGTERM.
- Duplicate SIGINT delivery within 0.5 seconds is coalesced; a later second
  SIGINT or a 10-second deadline sends SIGKILL to the isolated group.
- Return `130` for SIGINT, `143` for SIGTERM, `129` for SIGHUP, and `137` for forced cleanup.
- Remove residual descendants after the root exits, including an open native picker, without picker-specific logic.
- Use no new runtime dependency and do not start Agora, RTC/RTM, ngrok, or a conversation during verification.

---

## File Structure

- Create `scripts/supervise-local.py`: one standard-library lifecycle boundary for terminal signals, root forwarding, escalation, residual group cleanup, and exit-code mapping.
- Modify `scripts/run-local-codex.sh`: keep argument/env parsing, then `exec` the supervisor with opaque backend/frontend command arguments.
- Modify `scripts/verify-local-launcher.ts`: drive the public launcher from a detached test process group and assert signals, exit codes, child cleanup, and clean output.
- Modify `README.md`, `AGENTS.md`, `docs/ai/L0_repo_card.md`, `docs/ai/L1/01_setup.md`, and `docs/ai/L1/L2/verification_scripts.md`: document signal ownership and verification scope.

### Task 1: Supervisor and public launcher contract

**Files:**
- Create: `scripts/supervise-local.py`
- Modify: `scripts/run-local-codex.sh`
- Modify: `scripts/verify-local-launcher.ts`

**Interfaces:**
- Consumes: `LOCAL_BACKEND_COMMAND: string`, `LOCAL_FRONTEND_COMMAND: string`, and test-only `LOCAL_LAUNCHER_GRACE_SECONDS: positive number` from the shell launcher.
- Produces: `supervise-local.py BACKEND_COMMAND FRONTEND_COMMAND --grace-seconds SECONDS -> process exit status`.
- Preserves: `bun run dev:codex -- [--workspace PATH] [--acp-command-json JSON_ARRAY]`.

- [ ] **Step 1: Extend the launcher harness with a red process-group Ctrl-C test**

Import Node's `spawn` and add a detached public-launcher helper whose PID is the terminal process-group ID:

```ts
import { spawn } from 'node:child_process'

function startDetachedLauncher(backend: string, frontend: string) {
  return spawn('bash', ['scripts/run-local-codex.sh'], {
    cwd: root,
    detached: true,
    env: {
      ...process.env,
      LOCAL_BACKEND_COMMAND: backend,
      LOCAL_FRONTEND_COMMAND: frontend,
      LOCAL_LAUNCHER_GRACE_SECONDS: '0.25',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

function interruptTerminalGroup(pid: number, signal: NodeJS.Signals) {
  process.kill(-pid, signal)
}
```

Use two shell stubs that write their PID and received signal name into separate temporary files. Send SIGINT to `-launcher.pid`, wait for exit, and assert:

```ts
assert(result.code === 130, 'terminal SIGINT should return 130')
assert(!result.output.includes('Traceback'), 'terminal SIGINT should not print a traceback')
assert(readSignals(backendSignals).join(',') === 'SIGINT', 'backend should receive one SIGINT')
assert(readSignals(frontendSignals).join(',') === 'SIGINT', 'frontend should receive one SIGINT')
await Promise.all([waitForExit(backendPid), waitForExit(frontendPid)])
```

Retain the existing direct launcher tests so this new seam supplements rather than replaces the child-failure and override coverage.

- [ ] **Step 2: Run the focused harness and capture the current failure**

Run: `bun run verify:launcher`

Expected: FAIL because the current shell trap leaves the launcher and descendants in one terminal group, so Uvicorn-style children can receive terminal and supervisor shutdown signals rather than exactly one signal.

- [ ] **Step 3: Implement the standard-library supervisor**

Create `scripts/supervise-local.py` with this public shape:

```python
GRACE_SECONDS = 10.0
RESIDUAL_GRACE_SECONDS = 0.5
SIGNAL_EXIT_CODES = {
    signal.SIGHUP: 129,
    signal.SIGINT: 130,
    signal.SIGTERM: 143,
}


def supervise(
    backend_command: str,
    frontend_command: str,
    grace_seconds: float = GRACE_SECONDS,
) -> int:
    """Run concurrently in an isolated session and own terminal shutdown."""


def main(argv: list[str] | None = None) -> int:
    """Validate CLI input, run the supervisor, and return its stable status."""
```

`supervise()` must:

1. start this exact root command with inherited stdio and `start_new_session=True`:

```python
[
    "concurrently",
    "-k",
    "--kill-signal",
    "SIGTERM",
    "--success",
    "first",
    "-n",
    "backend,frontend",
    "-c",
    "blue,green",
    backend_command,
    frontend_command,
]
```

2. install SIGHUP, SIGINT, and SIGTERM handlers on the supervisor;
3. on the first signal, call `root.send_signal(signal.SIGTERM if received == signal.SIGHUP else received)` exactly once and start the deadline;
4. coalesce SIGINT signals received within 0.5 seconds, then on a later second SIGINT or expired deadline call `os.killpg(root.pid, signal.SIGKILL)` and remember forced cleanup;
5. after `root.wait()`, probe `os.killpg(root.pid, 0)` and, if descendants remain, send group SIGTERM, wait up to `RESIDUAL_GRACE_SECONDS`, then send group SIGKILL;
6. return the accepted signal exit code, `137` for forced cleanup, or the root status when no terminal signal was received; and
7. catch a missing `concurrently` executable, print `Could not start the local process supervisor: concurrently was not found` to stderr, and return `127` without a traceback.

Signal handlers should mutate state only; process signalling and waiting stay in the main polling loop so races are testable and exceptions are bounded.

- [ ] **Step 4: Replace the Bash trap with one `exec` boundary**

Keep all current argument parsing, then replace `runner`, `cleanup()`, `trap`, background execution, and `wait` with:

```bash
grace_seconds="${LOCAL_LAUNCHER_GRACE_SECONDS:-10}"

exec python3 scripts/supervise-local.py \
  --grace-seconds "$grace_seconds" \
  "$backend_command" \
  "$frontend_command"
```

Do not evaluate or split either command string in Bash or Python.

- [ ] **Step 5: Complete the signal-state regression matrix**

Extend `scripts/verify-local-launcher.ts` to cover:

- SIGINT returns `130` and each child records one SIGINT;
- SIGTERM returns `143` and each child records one SIGTERM;
- SIGHUP returns `129` while each child records one SIGTERM;
- duplicate SIGINT delivery 50 milliseconds apart stays graceful and returns
  `130`;
- a second SIGINT forces the isolated group and returns `137`;
- a `0.25` second deadline forces signal-ignoring stubs and returns `137`;
- an orphan descendant in the isolated group is gone after root completion;
- a normal first-child failure still terminates its sibling and remains non-zero;
- no case includes `Traceback` in captured stdout/stderr.

Use temporary files for PID/signal evidence and always clean test process groups in `finally`, including `process.kill(-pid, 'SIGKILL')` guarded for `ESRCH`.

- [ ] **Step 6: Run focused verification**

Run:

```bash
bun run verify:launcher
git diff --check
```

Expected: launcher cleanup integration checks pass; no whitespace errors.

- [ ] **Step 7: Commit the working launcher slice**

```bash
git add scripts/supervise-local.py scripts/run-local-codex.sh scripts/verify-local-launcher.ts
git commit -m "fix: centralize local launcher signals"
```

### Task 2: Maintained documentation and real shutdown acceptance

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/ai/L0_repo_card.md`
- Modify: `docs/ai/L1/01_setup.md`
- Modify: `docs/ai/L1/L2/verification_scripts.md`

**Interfaces:**
- Consumes: the Task 1 exit-code and signal-delivery contract.
- Produces: current developer guidance for starting, interrupting, and verifying the local launcher.

- [ ] **Step 1: Update maintained documentation**

Document these exact facts:

- `bun run dev:codex` uses a Local Launcher Supervisor to isolate terminal signals from backend/frontend descendants;
- the first Ctrl-C is graceful, a second Ctrl-C forces cleanup, and the automatic grace deadline is 10 seconds;
- closing the terminal also cleans local descendants;
- interrupted exit statuses are `130`, `143`, `129`, and forced cleanup is `137`;
- `LOCAL_LAUNCHER_GRACE_SECONDS` is a verification-only seam, not an end-user setting;
- `verify:launcher` uses harmless local stubs and consumes no Agora minutes;
- `Last Reviewed` becomes `2026-08-16`.

- [ ] **Step 2: Run the real no-Agora Ctrl-C acceptance path**

Start `bun run dev:codex` in a PTY, wait for both services to report ready, and send one Ctrl-C without opening the Web page or calling `/startAgent`.

Expected:

- backend logs normal application shutdown;
- output contains neither `Traceback`, `KeyboardInterrupt`, `CancelledError`, nor `ConnectionError`;
- launcher exits `130`;
- no process whose command contains `recipe-agent-acp-local`, `codex-acp`, or `agentclientprotocol` remains;
- ports `127.0.0.1:8000` and `127.0.0.1:3000` have no listener from this repository.

- [ ] **Step 3: Run the full offline release suite**

Run:

```bash
cd server && source venv/bin/activate && PYTHONPATH=src pytest -q
cd ../web && bun test
cd .. && bun run verify:launcher
bun run verify:local
git diff --check
```

Expected: all test suites, proxy smoke checks, launcher checks, and the production Web build pass without starting a real Agora conversation.

- [ ] **Step 4: Commit docs and verification evidence**

```bash
git add README.md AGENTS.md docs/ai/L0_repo_card.md docs/ai/L1/01_setup.md docs/ai/L1/L2/verification_scripts.md
git commit -m "docs: document local launcher shutdown"
```
