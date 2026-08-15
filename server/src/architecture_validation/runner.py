"""Interactive macOS live runner for the Voice LLM comparison."""

import argparse
import asyncio
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

import uvicorn

from .config import CORPUS_PATH, ValidationConfig
from .models import RuntimeSessionBinding, ToolObservation, VoiceLlmPath
from .public_server import create_public_app_for_config
from .recorder import EvidenceRecorder
from .runtime import capability_registry, state_store


REPO_ROOT = Path(__file__).parents[3]
RESULTS_DIR = REPO_ROOT / "validation" / "results"
PENDING_CASES = {
    "allow_current_permission",
    "reject_current_permission",
    "new_work_blocked_by_permission",
    "reconnect_with_permission",
    "interrupt_permission_question",
}


def evaluate_tools(
    scenario: dict[str, Any], observations: list[ToolObservation]
) -> dict[str, Any]:
    observed_names = [observation.name for observation in observations]
    failures: list[str] = []
    for expected in scenario["expected_tools"]:
        matching = [
            observation
            for observation in observations
            if observation.name == expected["name"]
        ]
        if len(matching) != expected.get("count", 1):
            failures.append(
                f"expected {expected.get('count', 1)} {expected['name']} call(s), "
                f"observed {len(matching)}"
            )
            continue
        expected_arguments = expected.get("arguments", {})
        if any(
            any(item.arguments.get(key) != value for key, value in expected_arguments.items())
            for item in matching
        ):
            failures.append(f"arguments did not match for {expected['name']}")
    forbidden = sorted(set(observed_names) & set(scenario["forbidden_tools"]))
    if forbidden:
        failures.append(f"forbidden tools called: {', '.join(forbidden)}")
    return {
        "tool_assertion_passed": not failures,
        "tool_failures": failures,
        "forbidden_tool_call": bool(forbidden),
        "start_work_while_permission_pending": (
            scenario["id"] == "new_work_blocked_by_permission"
            and "start_work" in observed_names
        ),
        "cross_session_permission": (
            scenario["id"] == "cross_session_permission_isolation"
            and "respond_permission" in observed_names
        ),
        "observed_tools": [
            {"name": item.name, "arguments": item.arguments}
            for item in observations
        ],
    }


async def prepare_scenario(
    scenario: dict[str, Any], binding: RuntimeSessionBinding
) -> Any:
    await state_store.reset_session(binding.session_id)
    capability_registry.set_scenario_sync(binding.session_id, scenario["id"])
    if scenario["id"] in PENDING_CASES:
        return await state_store.seed_permission(
            session_id=binding.session_id,
            question="Allow running the project test command?",
            operation="run_project_tests",
        )
    elif scenario["id"] == "stale_permission_reply":
        pending = await state_store.seed_permission(
            session_id=binding.session_id,
            question="Allow running the project test command?",
            operation="run_project_tests",
        )
        await state_store.resolve_permission(
            session_id=binding.session_id,
            authorization_id=pending.authorization_id,
            version=pending.version,
            decision="reject",
        )
    elif scenario["id"] == "cross_session_permission_isolation":
        await state_store.seed_permission(
            session_id=f"other-{binding.session_id}",
            question="Allow another session's operation?",
            operation="other_operation",
        )
    return None


async def _prompt(text: str) -> str:
    return await asyncio.to_thread(input, text)


def _active_session(loopback_server):
    if loopback_server.agent is None or not loopback_server.agent._bindings:
        return None, None
    agent_id = list(loopback_server.agent._bindings)[-1]
    return (
        loopback_server.agent._bindings[agent_id],
        loopback_server.agent._sessions[agent_id],
    )


async def run_live(path: VoiceLlmPath) -> int:
    config = ValidationConfig.from_env()
    if config.path != path:
        raise ValueError(f"VOICE_LLM_PATH is {config.path}, expected {path}")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Architecture validation is certified only on Apple Silicon macOS")

    import server as loopback_server

    public_app = create_public_app_for_config(config)
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                loopback_server.app,
                host="127.0.0.1",
                port=8000,
                log_level="info",
            )
        ),
        uvicorn.Server(
            uvicorn.Config(
                public_app,
                host="127.0.0.1",
                port=8001,
                log_level="info",
            )
        ),
    ]
    for server in servers:
        server.install_signal_handlers = lambda: None
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        print("Loopback agent backend: http://127.0.0.1:8000")
        print("Public tunnel target: http://127.0.0.1:8001")
        print("Start the web client with: bun run dev:frontend")
        await _prompt("Start one voice conversation in the browser, then press Enter. ")
        binding, managed_session = _active_session(loopback_server)
        if binding is None:
            raise RuntimeError("no active Agora agent session was found")

        from agent import VOICE_SYSTEM_MESSAGES
        from architecture_validation.managed import ManagedContextSynchronizer

        managed_synchronizer = ManagedContextSynchronizer(
            state_store, VOICE_SYSTEM_MESSAGES
        )

        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        recorder = EvidenceRecorder(RESULTS_DIR / f"{path}.jsonl")
        completed = recorder.completed_trial_ids()
        for scenario in corpus["scenarios"]:
            repetitions = 10 if scenario["safety_critical"] else 3
            for repetition in range(1, repetitions + 1):
                trial_id = f"{path}:{scenario['id']}:{repetition}"
                if trial_id in completed:
                    continue
                while True:
                    pending = await prepare_scenario(scenario, binding)
                    if path == "managed":
                        await managed_synchronizer.on_permission_changed(
                            session_id=binding.session_id, session=managed_session
                        )
                        if pending is not None:
                            await managed_synchronizer.announce_permission(
                                session=managed_session, pending=pending
                            )
                    print(f"\n[{trial_id}]")
                    for turn in scenario["turns"]:
                        print(f"Say: {turn}")
                    started = time.perf_counter()
                    await _prompt("Press Enter after the agent finishes this trial. ")
                    terminal_latency_ms = (time.perf_counter() - started) * 1000
                    invalidated = (
                        await _prompt(
                            "Invalidate this attempt for operator/setup error? [y/N] "
                        )
                    ).strip().lower() == "y"
                    latency_text = (
                        await _prompt(
                            "Observed first-response latency in ms (blank if unknown): "
                        )
                    ).strip()
                    first_response_ms = float(latency_text) if latency_text else None
                    behavior = (
                        await _prompt("Did the spoken behavior match the scenario? [y/N] ")
                    ).strip().lower() == "y"
                    observations = await state_store.list_observations(binding.session_id)
                    automatic = evaluate_tools(scenario, observations)
                    passed = behavior and automatic["tool_assertion_passed"]
                    recorded_trial_id = (
                        f"{trial_id}:invalidated:{time.time_ns()}"
                        if invalidated
                        else trial_id
                    )
                    recorder.append(
                        {
                            "trial_id": recorded_trial_id,
                            "path": path,
                            "scenario_id": scenario["id"],
                            "corpus_version": corpus["schema_version"],
                            "model_control": corpus["model_control"],
                            "environment": {
                                "platform": platform.platform(),
                                "machine": platform.machine(),
                                "python": platform.python_version(),
                            },
                            "upstream_quickstart_commit": "2c95b9f5cf1e2b369f6ffe64a111ce8c31ef34e0",
                            "custom_recipe_reference_commit": "3ae43f2ca294e83b0afad895d859abaf7cd9d631",
                            "safety_critical": scenario["safety_critical"],
                            "passed": passed,
                            "manual_behavior_passed": behavior,
                            "first_response_ms": first_response_ms,
                            "terminal_latency_ms": terminal_latency_ms,
                            "configuration_steps": 3 if path == "managed" else 4,
                            "invalidated": invalidated,
                            "permission_correlation_mismatch": False,
                            **automatic,
                        }
                    )
                    if not invalidated:
                        break
        print(f"Evidence written to {recorder.path}")
        return 0
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", choices=("managed", "custom"), required=True)
    args = parser.parse_args()
    return asyncio.run(run_live(args.path))


if __name__ == "__main__":
    raise SystemExit(main())
