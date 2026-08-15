"""Deterministic report generation from local JSONL evidence."""

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .config import CORPUS_PATH
from .scoring import (
    CandidateScore,
    InconclusiveValidation,
    TrialSafetyObservation,
    collect_disqualifiers,
    select_winner,
)


REPO_ROOT = Path(__file__).parents[3]
RESULTS_DIR = REPO_ROOT / "validation" / "results"


def required_sample_counts() -> dict[str, int]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return {
        scenario["id"]: 10 if scenario["safety_critical"] else 3
        for scenario in corpus["scenarios"]
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _candidate_summary(path: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [record for record in records if not record.get("invalidated", False)]
    observations = [
        TrialSafetyObservation(
            scenario_id=record["scenario_id"],
            safety_critical=bool(record.get("safety_critical")),
            passed=bool(record.get("passed")),
            cross_session_permission=bool(record.get("cross_session_permission")),
            permission_correlation_mismatch=bool(
                record.get("permission_correlation_mismatch")
            ),
            start_work_while_permission_pending=bool(
                record.get("start_work_while_permission_pending")
            ),
            forbidden_tool_call=bool(record.get("forbidden_tool_call")),
        )
        for record in scored
    ]
    tool_accuracy = (
        sum(bool(record.get("tool_assertion_passed")) for record in scored)
        / len(scored)
        if scored
        else 0.0
    )
    failure_rate = (
        sum(not bool(record.get("passed")) for record in scored) / len(scored)
        if scored
        else 1.0
    )
    latencies = [
        float(record["first_response_ms"])
        for record in scored
        if record.get("first_response_ms") is not None
    ]
    route_checks = [
        check
        for record in scored
        for check in record.get("route_isolation", [])
    ]
    return {
        "path": path,
        "recorded_trials": len(records),
        "scored_trials": len(scored),
        "disqualifiers": list(collect_disqualifiers(observations)),
        "tool_accuracy": tool_accuracy,
        "configuration_steps": min(
            (int(record.get("configuration_steps", 999)) for record in scored),
            default=999,
        ),
        "p50_first_response_ms": (
            sorted(latencies)[len(latencies) // 2] if latencies else 0.0
        ),
        "p95_first_response_ms": _p95(latencies),
        "failure_rate": failure_rate,
        "required_secrets": (
            ["AGORA_APP_ID", "AGORA_APP_CERTIFICATE"]
            if path == "managed"
            else [
                "AGORA_APP_ID",
                "AGORA_APP_CERTIFICATE",
                "MODEL_PROVIDER_API_KEY",
            ]
        ),
        "route_isolation_passed": bool(route_checks) and all(
            check.get("passed") for check in route_checks
        ),
        "scenario_results": {
            scenario_id: {
                "passed": sum(
                    bool(item.get("passed"))
                    for item in scored
                    if item["scenario_id"] == scenario_id
                ),
                "total": sum(
                    1 for item in scored if item["scenario_id"] == scenario_id
                ),
            }
            for scenario_id in sorted(
                {item["scenario_id"] for item in scored}
            )
        },
    }


def build_report(
    records: Iterable[dict[str, Any]],
    required_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    records = list(records)
    required_counts = required_counts or required_sample_counts()
    candidates = {
        path: _candidate_summary(
            path, [record for record in records if record.get("path") == path]
        )
        for path in ("managed", "custom")
    }
    scores = [
        CandidateScore(
            path=summary["path"],
            disqualifiers=tuple(summary["disqualifiers"]),
            tool_accuracy=summary["tool_accuracy"],
            configuration_steps=summary["configuration_steps"],
            p95_first_response_ms=summary["p95_first_response_ms"],
            failure_rate=summary["failure_rate"],
        )
        for summary in candidates.values()
    ]
    incomplete = []
    for path, summary in candidates.items():
        for scenario_id, required in required_counts.items():
            observed = summary["scenario_results"].get(
                scenario_id, {"total": 0}
            )["total"]
            if observed < required:
                incomplete.append(
                    f"{path}:{scenario_id} has {observed}/{required} scored trials"
                )
    if incomplete:
        winner = None
        inconclusive_reason = "incomplete live matrix: " + "; ".join(incomplete)
    else:
        try:
            winner = select_winner(scores)
            inconclusive_reason = None
        except InconclusiveValidation as exc:
            winner = None
            inconclusive_reason = str(exc)
    return {
        "schema_version": "1.0",
        "corpus_version": records[0].get("corpus_version") if records else None,
        "model_control": records[0].get("model_control") if records else None,
        "environment": records[0].get("environment") if records else None,
        "upstream_quickstart_commit": (
            records[0].get("upstream_quickstart_commit") if records else None
        ),
        "custom_recipe_reference_commit": (
            records[0].get("custom_recipe_reference_commit") if records else None
        ),
        "required_sample_counts": required_counts,
        "winner": winner,
        "inconclusive_reason": inconclusive_reason,
        "candidates": candidates,
    }


def render_markdown(report: dict[str, Any]) -> str:
    winner = (
        f"Winner: `{report['winner']}`"
        if report["winner"]
        else f"Inconclusive: {report['inconclusive_reason']}"
    )
    lines = [
        "# Voice LLM Architecture Validation",
        "",
        winner,
        "",
        f"Corpus: `{report['corpus_version'] or 'unknown'}`",
        f"Upstream quickstart: `{report['upstream_quickstart_commit'] or 'unknown'}`",
        f"Custom LLM recipe reference: `{report['custom_recipe_reference_commit'] or 'unknown'}`",
        "",
        "| Candidate | Scored trials | Tool accuracy | Failure rate | p95 first response | Configuration steps | Disqualifiers |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for path in ("managed", "custom"):
        item = report["candidates"][path]
        lines.append(
            "| {path} | {scored} | {accuracy:.1%} | {failure:.1%} | "
            "{p95:.0f} ms | {steps} | {disqualifiers} |".format(
                path=path,
                scored=item["scored_trials"],
                accuracy=item["tool_accuracy"],
                failure=item["failure_rate"],
                p95=item["p95_first_response_ms"],
                steps=item["configuration_steps"],
                disqualifiers=", ".join(item["disqualifiers"]) or "None",
            )
        )
    lines.extend(["", "## Controls", "", "```json"])
    lines.append(json.dumps(report.get("model_control"), indent=2, sort_keys=True))
    lines.extend(["```", "", "## Public ingress", ""])
    for path in ("managed", "custom"):
        item = report["candidates"][path]
        lines.append(
            f"- `{path}` route isolation: "
            f"{'passed' if item['route_isolation_passed'] else 'not proven'}; "
            f"required secrets: {', '.join(item['required_secrets'])}."
        )
    return "\n".join(lines) + "\n"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()
    records = _load_jsonl(args.results_dir / "managed.jsonl")
    records += _load_jsonl(args.results_dir / "custom.jsonl")
    report = build_report(records)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    (args.results_dir / "architecture-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (args.results_dir / "architecture-validation.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    print(render_markdown(report), end="")
    return 0 if report["winner"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
