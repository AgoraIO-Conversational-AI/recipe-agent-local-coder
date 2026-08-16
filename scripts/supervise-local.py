#!/usr/bin/env python3
"""Own terminal signals for the local backend/frontend launcher."""

from __future__ import annotations

import argparse
import math
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence


GRACE_SECONDS = 10.0
RESIDUAL_GRACE_SECONDS = 0.5
FORCE_INTERRUPT_DELAY_SECONDS = 0.5
SIGNAL_EXIT_CODES = {
    signal.SIGHUP: 129,
    signal.SIGINT: 130,
    signal.SIGTERM: 143,
}
_POLL_SECONDS = 0.05
_MISSING_CONCURRENTLY = (
    "Could not start the local process supervisor: concurrently was not found"
)


def _signal_group(process_group_id: int, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(process_group_id, requested_signal)
    except ProcessLookupError:
        pass


def _group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clean_residual_group(process_group_id: int) -> None:
    if not _group_exists(process_group_id):
        return
    _signal_group(process_group_id, signal.SIGTERM)
    deadline = time.monotonic() + RESIDUAL_GRACE_SECONDS
    while _group_exists(process_group_id) and time.monotonic() < deadline:
        time.sleep(_POLL_SECONDS)
    if _group_exists(process_group_id):
        _signal_group(process_group_id, signal.SIGKILL)


def supervise(
    backend_command: str,
    frontend_command: str,
    grace_seconds: float = GRACE_SECONDS,
) -> int:
    """Run concurrently in an isolated session and own terminal shutdown."""
    received_signal: signal.Signals | None = None
    received_signal_at: float | None = None
    force_requested = False

    def receive_signal(signum: int, _frame: object) -> None:
        nonlocal received_signal, received_signal_at, force_requested
        current = signal.Signals(signum)
        if received_signal is None:
            received_signal = current
            received_signal_at = time.monotonic()
        elif (
            current == signal.SIGINT
            and received_signal_at is not None
            # bun run can forward one terminal gesture after direct delivery.
            and time.monotonic() - received_signal_at
            >= FORCE_INTERRUPT_DELAY_SECONDS
        ):
            force_requested = True

    handled_signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    previous_handlers = {
        current: signal.signal(current, receive_signal) for current in handled_signals
    }
    try:
        try:
            root = subprocess.Popen(
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
                ],
                start_new_session=True,
            )
        except FileNotFoundError:
            print(_MISSING_CONCURRENTLY, file=sys.stderr)
            return 127

        forwarded = False
        forced = False
        deadline: float | None = None
        while root.poll() is None:
            if received_signal is not None and not forwarded:
                forwarded_signal = (
                    signal.SIGTERM
                    if received_signal == signal.SIGHUP
                    else received_signal
                )
                try:
                    root.send_signal(forwarded_signal)
                except ProcessLookupError:
                    pass
                forwarded = True
                deadline = time.monotonic() + grace_seconds

            if not forced and (
                force_requested
                or (deadline is not None and time.monotonic() >= deadline)
            ):
                _signal_group(root.pid, signal.SIGKILL)
                forced = True

            time.sleep(_POLL_SECONDS)

        root_status = root.wait()
        _clean_residual_group(root.pid)
        if forced:
            return 137
        if received_signal is not None:
            return SIGNAL_EXIT_CODES[received_signal]
        return root_status if root_status >= 0 else 128 - root_status
    finally:
        for current, previous in previous_handlers.items():
            signal.signal(current, previous)


def _positive_seconds(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("grace seconds must be a positive number")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--grace-seconds", type=_positive_seconds, default=GRACE_SECONDS)
    parser.add_argument("backend_command")
    parser.add_argument("frontend_command")
    arguments = parser.parse_args(argv)
    return supervise(
        arguments.backend_command,
        arguments.frontend_command,
        arguments.grace_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
