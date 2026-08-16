# Local Launcher Signal Ownership Design

**Date:** 2026-08-15

## Goal

Make `bun run dev:codex` stop cleanly from one terminal interrupt without an
Uvicorn `KeyboardInterrupt` or `CancelledError` traceback, while preserving
sibling cleanup and all existing local runtime behavior.

## Confirmed Failure

The complete launcher reproduces the traceback when Ctrl-C reaches its terminal
process group. The frontend exits from SIGINT, `concurrently` then sends SIGTERM
to the backend, and Uvicorn receives more than one shutdown signal. A control
run that starts only the backend and sends one SIGINT shuts down cleanly. The
ACP transport-close traceback fixed separately does not recur, and all local
children and ports are removed in both cases.

## Decision

Use one thin Local Launcher Supervisor as the sole owner of terminal signals.
The supervisor starts the existing `concurrently` command in a separate process
group and waits for it. On normal shutdown, it forwards exactly one signal to
the `concurrently` root process only. Backend and frontend descendants do not
receive the terminal signal directly; `concurrently` remains responsible for
stopping its siblings once.

The shell launcher remains responsible for argument parsing and the existing
environment contract. It delegates only process-group lifecycle to the
supervisor. Backend and frontend commands, ports, Workspace persistence, ACP
configuration, and Agora behavior do not change.

After parsing arguments, the shell uses `exec` to replace itself with the
supervisor. This leaves exactly one process in the terminal's foreground group
to receive terminal signals.

`concurrently` remains in the process tree. It continues to own labeled output,
child fail-fast behavior, and sibling shutdown. Replacing it would require the
supervisor to duplicate log multiplexing and child race handling. The two
layers have non-overlapping responsibilities:

```text
Terminal -> Local Launcher Supervisor -> concurrently -> backend + frontend
```

## Signal and Exit Contract

- Normal child completion preserves the existing `concurrently --success first`
  result.
- The first SIGINT or SIGTERM starts shutdown and is forwarded once to the
  `concurrently` root process, not broadcast to its process group.
- SIGHUP, including terminal-window closure, follows the same graceful-first
  path so isolated descendants cannot remain after their terminal disappears.
  The supervisor maps HUP to SIGTERM at the `concurrently` root because
  `concurrently` forwards its received root signal to both children, while the
  supervisor still reports the conventional HUP exit status `129`.
- Duplicate SIGINT delivery within one 0.5-second terminal burst is coalesced
  because `bun run` can forward the same user gesture after direct process-group
  delivery. A deliberate second SIGINT after that window skips the remaining
  wait and sends SIGKILL to the isolated process group.
- The supervisor waits for the group to exit and does not leave backend,
  frontend, or ACP descendants running.
- If graceful cleanup exceeds 10 seconds, the supervisor sends SIGKILL to the
  isolated process group so unresponsive descendants cannot remain. SIGTERM
  uses the same graceful-first, deadline-bounded path.
- User interruption may return a conventional non-zero interrupted exit status;
  clean logs and complete cleanup are the required behavior.

The supervisor preserves `concurrently`'s exit status for normal completion or
a child failure. A completed SIGINT shutdown returns `130`, a completed SIGTERM
shutdown returns `143`, and a completed SIGHUP shutdown returns `129`. Forced
cleanup after a second Ctrl-C or the 10-second deadline returns `137`.

## Implementation Boundary

Add one small Local Launcher Supervisor under `scripts/` using the repository's
existing Python runtime. Keep `scripts/run-local-codex.sh` as the public
launcher and replace its background `concurrently` plus trap logic with one
foreground supervisor call.

The supervisor accepts the backend and frontend commands as opaque argument
values. It does not parse shell command content, credentials, Workspace paths,
or ACP configuration.

It uses only the system Python standard library guaranteed by local preflight,
starts `concurrently` in a new session, and inherits the terminal's standard
input and output so existing colors and interactive behavior remain intact.
The launcher pins `concurrently` sibling cleanup to SIGTERM rather than relying
on its implicit default. A spawn failure returns one bounded diagnostic and the
conventional command-not-found status instead of a Python traceback.

## Project Folder Selection Boundary

The native macOS picker remains part of the local backend. A browser directory
picker returns a browser-owned directory handle or relative file paths, not the
absolute native path required for the ACP session `cwd`. The Web app therefore
continues to trigger and poll the backend picker without receiving file access.

Manual absolute-path entry and `--workspace` remain advanced fallbacks. A
desktop application shell and a browser-owned filesystem architecture are out
of scope. The supervisor treats the picker process like any other descendant;
it contains no picker-specific cleanup branch.

## Verification

Extend `scripts/verify-local-launcher.ts` with a process-group interrupt test
that:

1. launches the real shell launcher with deterministic fake siblings;
2. sends SIGINT as a terminal process-group event to the supervisor;
3. asserts both fake siblings exit;
4. asserts the supervisor signals only the `concurrently` root during graceful
   shutdown and sibling shutdown delivery is not duplicated; and
5. asserts a duplicate SIGINT burst stays graceful, while a deliberate second
   SIGINT and the 10-second deadline can each force cleanup; and
6. asserts SIGHUP also removes both siblings; and
7. asserts launcher output contains no traceback.

Retain the existing tests for opaque advanced overrides, invalid arguments,
one-child failure, SIGINT cleanup, and SIGTERM cleanup. Then rerun the real
`bun run dev:codex` Ctrl-C path and the full offline local verification suite.

## Out of Scope

- Agora conversation start, RTC/RTM, ngrok, or minute-consuming validation
- Changes to FastAPI or Uvicorn application lifecycle
- Changes to ACP session semantics
- Production deployment supervision
- Log filtering or suppression as a substitute for correct signal ownership
- A pure Web directory picker or Electron/Tauri application shell
