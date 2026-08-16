"""Interactive macOS evidence runner for the selected Managed Voice LLM path."""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from dotenv import load_dotenv

from .config import CORPUS_PATH, ValidationConfig
from .models import (
    PendingPermission,
    RuntimeSessionBinding,
    ToolObservation,
)
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


def _alias(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def evaluate_tools(
    scenario: dict[str, Any],
    observations: list[ToolObservation],
    expected_permission: PendingPermission | None = None,
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
    permission_observations = [
        item for item in observations if item.name == "respond_permission"
    ]
    permission_correlation_mismatch = False
    if expected_permission is not None and permission_observations:
        permission_correlation_mismatch = any(
            item.result.get("code") != "permission_resolved"
            or item.result.get("authorization_id")
            != expected_permission.authorization_id
            or item.result.get("version") != expected_permission.version
            for item in permission_observations
        )
        if permission_correlation_mismatch:
            failures.append("permission result did not match the seeded authorization")

    def safe_result(result: dict[str, object]) -> dict[str, object]:
        safe = {key: value for key, value in result.items() if key != "authorization_id"}
        if isinstance(result.get("authorization_id"), str):
            safe["permission_alias"] = _alias(str(result["authorization_id"]))
        return safe

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
        "permission_correlation_mismatch": permission_correlation_mismatch,
        "observed_tools": [
            {
                "name": item.name,
                "arguments": item.arguments,
                "result": safe_result(item.result),
            }
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
    if loopback_server.agent is None:
        return None
    return loopback_server.agent.active_validation_session()


async def wait_for_active_session(loopback_server):
    active = _active_session(loopback_server)
    while active is None:
        await _prompt(
            "Start or re-enter the browser voice conversation, then press Enter. "
        )
        active = _active_session(loopback_server)
    return active


async def stop_current_active_session(loopback_server) -> str | None:
    active = _active_session(loopback_server)
    if active is None or loopback_server.agent is None:
        return None
    agent_id = active[0]
    await loopback_server.agent.stop(agent_id)
    return agent_id


def scenario_repetitions(scenario: dict[str, Any], *, smoke: bool) -> int:
    if smoke:
        return 1
    return 10 if scenario["safety_critical"] else 3


async def _wait_for_servers(servers: list[uvicorn.Server]) -> None:
    for _ in range(100):
        if all(server.started for server in servers):
            return
        await asyncio.sleep(0.05)
    raise RuntimeError("validation listeners did not start")


async def verify_public_route_isolation(
    config: ValidationConfig,
) -> list[dict[str, object]]:
    checks = [
        ("GET", "/get_config", 404),
        ("POST", "/startAgent", 404),
        ("POST", "/stopAgent", 404),
        ("POST", "/validation/admin/permissions", 404),
        ("GET", "/validation/results", 404),
        ("GET", "/mcp/", 401),
        ("POST", "/llm/chat/completions", 404),
    ]
    observations = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        for method, route, expected_status in checks:
            response = await client.request(
                method, f"{config.public_base_url}{route}", json={}
            )
            observations.append(
                {
                    "method": method,
                    "route": route,
                    "status": response.status_code,
                    "expected_status": expected_status,
                    "passed": response.status_code == expected_status,
                }
            )
        probe_binding = capability_registry.issue_sync(
            session_id="route-isolation-probe",
            scenario_id="route-isolation-probe",
            ttl_seconds=60,
        )
        try:
            response = await client.post(
                f"{config.public_base_url}/mcp/",
                headers={
                    "Authorization": f"Bearer {probe_binding.mcp_bearer}"
                },
                json={},
            )
            observations.append(
                {
                    "method": "POST",
                    "route": "/mcp/",
                    "status": response.status_code,
                    "expected_status": "authenticated request is not 401 or 421",
                    "passed": response.status_code not in {401, 421},
                }
            )
        finally:
            capability_registry.expire_session_sync(probe_binding.session_id)
    failed = [item for item in observations if not item["passed"]]
    if failed:
        raise RuntimeError(f"public route isolation failed: {failed}")
    return observations


async def run_live(*, smoke: bool = False) -> int:
    load_dotenv(Path(__file__).parents[2] / ".env.local", override=False)
    config = ValidationConfig.from_env()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Architecture validation is certified only on Apple Silicon macOS")

    import server as loopback_server
    from agent import Agent

    loopback_server.agent = Agent(evidence_config=config)

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
    active_agent_id = None
    recorder = None
    try:
        await _wait_for_servers(servers)
        print("Loopback agent backend: http://127.0.0.1:8000")
        print("Public tunnel target: http://127.0.0.1:8001")
        route_observations = await verify_public_route_isolation(config)
        print("Public route isolation: passed")
        print("Start the web client with: bun run dev:frontend")
        active = await wait_for_active_session(loopback_server)
        active_agent_id, binding, managed_session = active

        from agent import VOICE_SYSTEM_MESSAGES
        from architecture_validation.managed import ManagedContextSynchronizer

        managed_synchronizer = ManagedContextSynchronizer(
            state_store, VOICE_SYSTEM_MESSAGES
        )

        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        recorder = EvidenceRecorder(RESULTS_DIR / "managed.jsonl")
        completed = recorder.completed_trial_ids()
        for scenario in corpus["scenarios"]:
            repetitions = scenario_repetitions(scenario, smoke=smoke)
            for repetition in range(1, repetitions + 1):
                # Preserve the namespace used by existing paid live evidence so
                # resumed runs never repeat an already completed conversation.
                trial_id = f"managed:{scenario['id']}:{repetition}"
                if trial_id in completed:
                    continue
                while True:
                    active = await wait_for_active_session(loopback_server)
                    active_agent_id, binding, managed_session = active
                    pending = await prepare_scenario(scenario, binding)
                    await managed_synchronizer.on_permission_changed(
                        session_id=binding.session_id, session=managed_session
                    )
                    if pending is not None:
                        await managed_synchronizer.announce_permission(
                            session=managed_session, pending=pending
                        )
                    print(f"\n[{trial_id}]")
                    operator_actions = scenario.get("operator_actions", [])
                    operator_confirmed = True
                    for action in operator_actions:
                        print(f"Action: {action['instruction']}")
                        if action["timing"] == "before_turns":
                            await _prompt("Perform this action, then press Enter. ")
                            refreshed = _active_session(loopback_server)
                            if scenario["id"] == "reconnect_with_permission":
                                if refreshed is None or refreshed[0] == active_agent_id:
                                    raise RuntimeError(
                                        "reconnect trial requires a new Agora agent session"
                                    )
                                old_binding = binding
                                active_agent_id, binding, managed_session = refreshed
                                await state_store.rebind_session(
                                    old_binding.session_id, binding.session_id
                                )
                                capability_registry.set_scenario_sync(
                                    binding.session_id, scenario["id"]
                                )
                                pending = await state_store.current_permission(
                                    binding.session_id
                                )
                                await managed_synchronizer.on_permission_changed(
                                    session_id=binding.session_id,
                                    session=managed_session,
                                )
                                if pending is not None:
                                    await managed_synchronizer.announce_permission(
                                        session=managed_session, pending=pending
                                    )
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
                    error_category = (
                        await _prompt(
                            "Observed error category "
                            "[blank/disconnect/interruption/rest/sse/model]: "
                        )
                    ).strip().lower()
                    errors = {
                        "disconnect": [],
                        "interruption": [],
                        "rest": [],
                        "sse": [],
                        "model": [],
                    }
                    if error_category:
                        if error_category not in errors:
                            raise ValueError("unknown error category")
                        error_detail = (
                            await _prompt("Bounded error description: ")
                        ).strip()[:512]
                        errors[error_category].append(error_detail or "observed")
                    for action in operator_actions:
                        if action["timing"] == "during_turns":
                            confirmed = (
                                await _prompt("Did you perform the printed action? [y/N] ")
                            ).strip().lower() == "y"
                            operator_confirmed = operator_confirmed and confirmed
                    observations = await state_store.list_observations(binding.session_id)
                    automatic = evaluate_tools(scenario, observations, pending)
                    passed = (
                        behavior
                        and operator_confirmed
                        and automatic["tool_assertion_passed"]
                    )
                    invalidation_reason = None
                    if invalidated:
                        invalidation_reason = (
                            await _prompt("Reason for invalidation (required): ")
                        ).strip()
                        if not invalidation_reason:
                            raise ValueError("invalidation reason is required")
                    recorded_trial_id = (
                        f"{trial_id}:invalidated:{time.time_ns()}"
                        if invalidated
                        else trial_id
                    )
                    recorder.append(
                        {
                            "trial_id": recorded_trial_id,
                            "scenario_id": scenario["id"],
                            "corpus_version": corpus["schema_version"],
                            "model_control": corpus["model_control"],
                            "environment": {
                                "platform": platform.platform(),
                                "machine": platform.machine(),
                                "python": platform.python_version(),
                            },
                            "configuration_hash": hashlib.sha256(
                                json.dumps(
                                    {
                                        "model_control": corpus["model_control"],
                                        "public_base_url_host": httpx.URL(
                                            config.public_base_url
                                        ).host,
                                    },
                                    sort_keys=True,
                                ).encode("utf-8")
                            ).hexdigest(),
                            "session_alias": _alias(binding.session_id),
                            "permission_seed": (
                                {
                                    "permission_alias": _alias(
                                        pending.authorization_id
                                    ),
                                    "version": pending.version,
                                    "operation": pending.operation,
                                }
                                if pending is not None
                                else None
                            ),
                            "route_isolation": route_observations,
                            "upstream_quickstart_commit": "2c95b9f5cf1e2b369f6ffe64a111ce8c31ef34e0",
                            "safety_critical": scenario["safety_critical"],
                            "passed": passed,
                            "manual_behavior_passed": behavior,
                            "first_response_ms": first_response_ms,
                            "terminal_latency_ms": terminal_latency_ms,
                            "invalidated": invalidated,
                            "invalidation_reason": invalidation_reason,
                            "operator_actions": operator_actions,
                            "operator_actions_confirmed": operator_confirmed,
                            "errors": errors,
                            "failing_assertions": automatic["tool_failures"],
                            **automatic,
                        }
                    )
                    if not invalidated:
                        break
        print(f"Evidence written to {recorder.path}")
        return 0
    finally:
        stop_error = None
        try:
            await stop_current_active_session(loopback_server)
        except Exception as exc:
            stop_error = exc
            if recorder is not None:
                recorder.append(
                    {
                        "trial_id": f"managed:cleanup:{time.time_ns()}",
                        "scenario_id": "cleanup",
                        "invalidated": True,
                        "invalidation_reason": "agent stop failed",
                        "errors": {
                            "rest": [type(exc).__name__],
                        },
                    }
                )
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
        if stop_error is not None:
            raise RuntimeError("failed to stop the active Agora agent") from stop_error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run_live(smoke=args.smoke))


if __name__ == "__main__":
    raise SystemExit(main())
