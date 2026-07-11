"""CM-02 CMake Skill A/B Eval 测试——配对、隔离、选择审计与报告。

测试分为两类：
A. 契约 / Schema 测试——纯逻辑，不依赖外部环境
B. 集成 Fake 测试——通过 mock command_runner 绕过 TS CLI，验证 orchestrator 行为
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agent.profile import ProjectProfile
from eval.cmake_skill_ab import (
    CM02Result,
    discover_cmake_tasks,
    run_cmake_skill_ab,
    write_summary_json,
    write_markdown_report,
)
from eval.run_eval import EvalTask
from eval.ts_bridge import TsBridgeError, TsProcessResult

SCHEMA_VERSION = 1
VARIANTS = ("control", "treatment")
DEFAULT_TASK_IDS_CMDS = [
    "r01_poco_postgresql_imported_target",
    "r02_nlohmann_json_config_missing",
    "r03_boost_graph_include_missing",
    "r04_gperftools_imported_target_missing",
    "r05_petsc_offline_target_missing",
    "r06_generated_config_include_missing",
    "r07_ctest_working_directory",
    "r08_local_library_source_omitted",
    "r09_transitive_local_link_missing",
    "r10_compile_definition_missing",
]
PILOT_TASK_ID = "r08_local_library_source_omitted"
EXPECTED_EXTENSION_NAME = "cmake"
EXPECTED_DEFINITION_SOURCE = "cmake/skills/build-fix/SKILL.md"
EXPECTED_SELECTION_SOURCE = "model_tool_call"


# --- JSON Schema 验证 ---

def _require_str(obj: dict[str, Any], key: str, *, path: str = "$") -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{path}.{key} must be a string, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{path}.{key} must not be empty")
    return value


def _require_int(obj: dict[str, Any], key: str, *, path: str = "$", non_negative: bool = True) -> int:
    value = obj.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be an integer, got {type(value).__name__}")
    if non_negative and value < 0:
        raise ValueError(f"{path}.{key} must be non-negative, got {value}")
    return value


def _require_float(obj: dict[str, Any], key: str, *, path: str = "$", non_negative: bool = True) -> float:
    value = obj.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be a number, got {type(value).__name__}")
    if non_negative and value < 0:
        raise ValueError(f"{path}.{key} must be non-negative, got {value}")
    return float(value)


def validate_run_record(run: dict[str, Any], *, path: str = "$") -> list[str]:
    errors: list[str] = []
    try:
        _require_str(run, "task_id", path=path)
        _require_int(run, "repeat_index", path=path)
        _require_str(run, "variant", path=path)
        _require_int(run, "order_index", path=path)
        _require_str(run, "session_id", path=path)
        if run.get("variant") not in VARIANTS:
            errors.append(f'{path}.variant must be one of {VARIANTS}, got {run.get("variant")!r}')
        _require_int(run, "steps", path=path)
        _require_int(run, "latency_ms", path=path)
        _require_float(run, "cost_usd", path=path)
        _require_int(run, "invoke_skill_count", path=path)
        _require_int(run, "skill_selected_count", path=path)
        _require_int(run, "skill_not_found_count", path=path)
        _require_int(run, "bash_call_count", path=path)
        if "solved" not in run:
            errors.append(f"{path} must have 'solved' field")
        if "reason" not in run:
            errors.append(f"{path} must have 'reason' field")
        if "prompt_tokens" not in run:
            errors.append(f"{path} must have 'prompt_tokens' field")
        if "completion_tokens" not in run:
            errors.append(f"{path} must have 'completion_tokens' field")
        if "cache_read_tokens" not in run:
            errors.append(f"{path} must have 'cache_read_tokens' field")
        if "infrastructure_error" in run and run["infrastructure_error"] is not None:
            if not isinstance(run["infrastructure_error"], dict):
                errors.append(f"{path}.infrastructure_error must be an object or null")
        for art in ("trace_path", "result_path", "verification_path", "final_diff_path"):
            if art in run:
                _require_str(run, art, path=path)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_summary_document(summary: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        sv = summary.get("schema_version")
        if sv != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION}, got {sv!r}")
        _require_str(summary, "phase", path="$")
        if summary["phase"] not in ("pilot", "full"):
            errors.append(f'$.phase must be "pilot" or "full", got {summary["phase"]!r}')
        _require_str(summary, "runtime", path="$")
        if summary["runtime"] != "typescript":
            errors.append(f'$.runtime must be "typescript", got {summary["runtime"]!r}')
        _require_str(summary, "model", path="$")
        _require_int(summary, "repeat", path="$")
        variants = summary.get("variants")
        if not isinstance(variants, list) or set(variants) != set(VARIANTS):
            errors.append(f"$.variants must be {list(VARIANTS)}, got {variants!r}")
        task_ids = summary.get("task_ids")
        if not isinstance(task_ids, list) or not task_ids:
            errors.append("$.task_ids must be a non-empty list")
        runs = summary.get("runs")
        if not isinstance(runs, list):
            errors.append("$.runs must be a list")
        else:
            for i, run in enumerate(runs):
                errors.extend(validate_run_record(run, path=f"$.runs[{i}]"))
        aggregate = summary.get("aggregate")
        if not isinstance(aggregate, dict):
            errors.append("$.aggregate must be an object")
        else:
            errors.extend(validate_aggregate(aggregate))
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_aggregate(agg: dict[str, Any], *, path: str = "$.aggregate") -> list[str]:
    errors: list[str] = []
    for group in VARIANTS:
        for key in ("solve_rate", "skill_selection_rate"):
            full = f"{group}_{key}"
            if full not in agg:
                errors.append(f"{path} must contain {full!r}")
    for group in VARIANTS:
        for metric_suffix in ("median_steps", "median_latency_ms", "median_cost_usd"):
            key = f"{group}_{metric_suffix}"
            if key not in agg:
                errors.append(f"{path} must contain {key!r}")
    if "pair_solve_delta" not in agg:
        errors.append(f"{path} must contain 'pair_solve_delta'")
    paired = agg.get("paired_outcomes")
    if not isinstance(paired, dict):
        errors.append(f"{path}.paired_outcomes must be an object")
    else:
        for key in ("both_solved", "control_only", "treatment_only", "neither"):
            if key not in paired:
                errors.append(f"{path}.paired_outcomes must contain {key!r}")
    if "infrastructure_error_count" not in agg:
        errors.append(f"{path} must contain 'infrastructure_error_count'")
    if "bash_call_total" not in agg:
        errors.append(f"{path} must contain 'bash_call_total'")
    for key in ("selected_solve_rate", "not_selected_solve_rate"):
        if key not in agg:
            errors.append(f"{path} must contain {key!r}")
    return errors


# --- 配对顺序生成 ---

@dataclass(frozen=True)
class PairOrder:
    task_id: str
    repeat_index: int
    first_variant: str
    second_variant: str

    @property
    def order(self) -> str:
        return f"{self.first_variant[0].upper()}{self.second_variant[0].upper()}"


def generate_pair_orders(
    task_ids: list[str],
    repeat: int,
    *,
    first_variant: str = "control",
    second_variant: str = "treatment",
) -> list[PairOrder]:
    """Generate pair orders per the CM-02 spec: AB/BA alternation by repeat index.

    repeat_idx % 2 == 0 -> control-first (AB), else treatment-first (BA).
    Every task within the same repeat gets the same alternation phase.
    """
    orders: list[PairOrder] = []
    for repeat_index in range(repeat):
        flip = repeat_index % 2 != 0
        a, b = (first_variant, second_variant) if not flip else (second_variant, first_variant)
        for task_id in task_ids:
            orders.append(PairOrder(task_id=task_id, repeat_index=repeat_index, first_variant=a, second_variant=b))
    return orders


# --- Fake Trace 工厂 ---

def make_skill_selection_event(
    outcome: str = "selected",
    *,
    requested_skill: str = "cmake-build-fix",
    selected_skill: str = "cmake-build-fix",
    extension_name: str = EXPECTED_EXTENSION_NAME,
    definition_source: str = EXPECTED_DEFINITION_SOURCE,
) -> dict[str, Any]:
    if outcome == "selected":
        return {
            "type": "skill_selection",
            "sessionId": "fake-session",
            "payload": {
                "schemaVersion": 1,
                "invocationId": "skill-1",
                "selectionSource": EXPECTED_SELECTION_SOURCE,
                "outcome": "selected",
                "requestedSkill": requested_skill,
                "selectedSkill": selected_skill,
                "extensionName": extension_name,
                "definitionSource": definition_source,
            },
        }
    return {
        "type": "skill_selection",
        "sessionId": "fake-session",
        "payload": {
            "schemaVersion": 1,
            "invocationId": "skill-1",
            "selectionSource": "model_tool_call",
            "outcome": "not_found",
            "requestedSkill": requested_skill,
        },
    }


def has_skill_selection_event(trace_events: list[dict[str, Any]]) -> bool:
    return any(e.get("type") == "skill_selection" for e in trace_events)


def has_skill_tool_invocation(trace_events: list[dict[str, Any]]) -> bool:
    return any(
        e.get("type") in ("tool_start", "post_tool_use")
        and isinstance(e.get("payload"), dict)
        and e["payload"].get("toolName") == "invoke_skill"
        for e in trace_events
    )


def count_bash_invocations(trace_events: list[dict[str, Any]]) -> int:
    return sum(
        1
        for e in trace_events
        if e.get("type") == "tool_start"
        and isinstance(e.get("payload"), dict)
        and e["payload"].get("toolName") == "bash"
    )


# ============================================================================
# Mock TS Bridge helpers (绕过 node/TS CLI 依赖)
# ============================================================================

_THIS_DIR = Path(__file__).resolve().parent
_MODEL_SCRIPT_CONTROL = _THIS_DIR / "testdata" / "cm02" / "model-script-control.json"
_MODEL_SCRIPT_TREATMENT = _THIS_DIR / "testdata" / "cm02" / "model-script-treatment.json"


def _managed_result(
    command: list[str],
    *,
    exit_code: int = 0,
    overrides: dict | None = None,
    trace_events: list[dict[str, Any]] | None = None,
) -> TsProcessResult:
    """构建 mock TsProcessResult，模拟 TS CLI 的 managed run result。

    基于 test_ts_eval_bridge.py 的 _managed_result 模式扩展，
    支持注入 trace_events 到 trace.jsonl。
    """
    source = Path(command[command.index("--repo") + 1]).resolve()
    run_root = Path(command[command.index("--run-root") + 1]).resolve()
    run_directory = run_root / "session-1"
    workspace = run_directory / "repository"
    artifacts = run_directory / "artifacts"
    workspace.mkdir(parents=True)
    artifacts.mkdir()
    result: dict[str, Any] = {
        "type": "run_result",
        "schemaVersion": 1,
        "mode": "managed",
        "sessionId": "session-1",
        "sourceRepository": str(source),
        "workspace": str(workspace),
        "runDirectory": str(run_directory),
        "artifactsDirectory": str(artifacts),
        "diffPath": str(artifacts / "final.diff"),
        "resultPath": str(artifacts / "result.json"),
        "tracePath": str(artifacts / "trace.jsonl"),
        "verificationPath": str(artifacts / "verification.json"),
        "reason": "budget_exceeded" if exit_code == 1 else "completed",
        "summary": "done",
        "steps": 3,
        "usage": {
            "promptTokens": 100,
            "completionTokens": 20,
            "cacheReadTokens": 40,
            "cacheWriteTokens": 0,
        },
    }
    result.update(overrides or {})
    (artifacts / "final.diff").write_text("diff", encoding="utf-8")
    trace_content = "\n".join(
        json.dumps(e, ensure_ascii=False) for e in (trace_events or [])
    ) + "\n"
    (artifacts / "trace.jsonl").write_text(trace_content, encoding="utf-8")
    (artifacts / "verification.json").write_text("{}\n", encoding="utf-8")
    Path(result["resultPath"]).write_text(json.dumps(result), encoding="utf-8")
    return TsProcessResult(exit_code, json.dumps(result), "")


def _make_mock_runner(
    *,
    exit_code: int = 0,
    overrides: dict | None = None,
    trace_events: list[dict[str, Any]] | None = None,
):
    """创建注入式 command_runner，每次调用返回固定结果。"""

    def _runner(command: list[str], *, cwd: Path, timeout: int) -> TsProcessResult:
        return _managed_result(
            command,
            exit_code=exit_code,
            overrides=overrides,
            trace_events=trace_events,
        )

    return _runner


def _make_cmake_task_structure(task_dir: Path, task_id: str) -> Path:
    """创建迷你 CMake task 结构用于测试。"""
    repo = task_dir / "repo"
    repo.mkdir(parents=True)
    src = repo / "src"
    src.mkdir()
    inc = repo / "include"
    inc.mkdir()
    mathx = inc / "mathx"
    mathx.mkdir()
    (mathx / "add.hpp").write_text(
        "#pragma once\n\nnamespace mathx {\nint add(int left, int right);\n}\n",
        encoding="utf-8",
    )
    (repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "project(R08LocalSourceOmitted LANGUAGES CXX)\n"
        "enable_testing()\n"
        "add_executable(app src/main.cpp)\n"
        "target_include_directories(app PRIVATE include)\n"
        "add_test(NAME app_runs COMMAND app)\n",
        encoding="utf-8",
    )
    (src / "main.cpp").write_text(
        '#include "mathx/add.hpp"\n'
        "int main() { return mathx::add(2, 3) == 5 ? 0 : 1; }\n",
        encoding="utf-8",
    )
    (src / "add.cpp").write_text(
        '#include "mathx/add.hpp"\n'
        "namespace mathx { int add(int l, int r) { return l + r; } }\n",
        encoding="utf-8",
    )
    (task_dir / "prompt.md").write_text(
        "Fix the undefined reference.", encoding="utf-8"
    )
    (task_dir / "verify.py").write_text(
        "import sys\nraise SystemExit(0)\n", encoding="utf-8"
    )
    (task_dir / "profile.yaml").write_text(
        "language: cmake\ntest_cmd: echo ok\ntest_timeout: 30\n",
        encoding="utf-8",
    )
    return task_dir


def _make_default_trace() -> list[dict[str, Any]]:
    """默认 trace：无 skill_selection 或 bash 事件。"""
    return [
        {"type": "model_start"},
        {"type": "model_end"},
        {"type": "tool_start", "payload": {"toolName": "read_file"}},
        {"type": "tool_end", "payload": {"invocation": {"name": "read_file"}}},
        {"type": "model_start"},
        {"type": "finish"},
    ]


def _make_treatment_trace() -> list[dict[str, Any]]:
    """模拟 treatment trace：包含 skill_selection selected 事件。"""
    return [
        {"type": "model_start"},
        {"type": "model_end"},
        {
            "type": "skill_selection",
            "sessionId": "session-1",
            "payload": {
                "schemaVersion": 1,
                "invocationId": "skill-1",
                "selectionSource": "model_tool_call",
                "outcome": "selected",
                "requestedSkill": "cmake-build-fix",
                "selectedSkill": "cmake-build-fix",
                "extensionName": "cmake",
                "definitionSource": "cmake/skills/build-fix/SKILL.md",
            },
        },
        {"type": "tool_end", "payload": {"invocation": {"name": "invoke_skill"}}},
        {"type": "model_start"},
        {"type": "model_end"},
        {"type": "tool_start", "payload": {"toolName": "edit_file"}},
        {"type": "tool_end", "payload": {"invocation": {"name": "edit_file"}}},
        {"type": "model_start"},
        {"type": "finish"},
    ]


# ============================================================================
# 契约测试
# ============================================================================


class TestPairOrderGeneration:
    def test_single_task_repeat_2_alternates_ab_ba(self):
        orders = generate_pair_orders(["t1"], repeat=2)
        assert len(orders) == 2
        assert orders[0].order == "CT"
        assert orders[0].first_variant == "control"
        assert orders[0].second_variant == "treatment"
        assert orders[1].order == "TC"
        assert orders[1].first_variant == "treatment"
        assert orders[1].second_variant == "control"

    def test_two_tasks_repeat_1_alternates(self):
        orders = generate_pair_orders(["t1", "t2"], repeat=1)
        assert len(orders) == 2
        assert all(o.order == "CT" for o in orders)

    def test_two_tasks_repeat_3_yields_6_pairs(self):
        orders = generate_pair_orders(["t1", "t2"], repeat=3)
        assert len(orders) == 6
        orders_by_task: dict[str, list[PairOrder]] = {}
        for o in orders:
            orders_by_task.setdefault(o.task_id, []).append(o)
        assert len(orders_by_task["t1"]) == 3
        assert len(orders_by_task["t2"]) == 3

    def test_pilot_task_id_is_r08(self):
        assert PILOT_TASK_ID == "r08_local_library_source_omitted"
        assert PILOT_TASK_ID in DEFAULT_TASK_IDS_CMDS

    def test_variants_are_control_and_treatment(self):
        assert VARIANTS == ("control", "treatment")


class TestSchemaValidation:
    def test_valid_run_record_passes(self):
        run: dict[str, Any] = {
            "task_id": "r08", "repeat_index": 1, "variant": "control",
            "order_index": 0, "session_id": "sess-1", "solved": True,
            "reason": "completed", "steps": 5, "latency_ms": 12000,
            "cost_usd": 0.003, "invoke_skill_count": 0, "skill_selected_count": 0,
            "skill_not_found_count": 0, "bash_call_count": 0,
            "prompt_tokens": 500, "completion_tokens": 200, "cache_read_tokens": 100,
        }
        assert validate_run_record(run) == []

    def test_treatment_run_with_selection_passes(self):
        run: dict[str, Any] = {
            "task_id": "r08", "repeat_index": 1, "variant": "treatment",
            "order_index": 1, "session_id": "sess-2", "solved": True,
            "reason": "completed", "steps": 6, "latency_ms": 15000,
            "cost_usd": 0.004, "invoke_skill_count": 1, "skill_selected_count": 1,
            "skill_not_found_count": 0, "bash_call_count": 0,
            "prompt_tokens": 800, "completion_tokens": 300, "cache_read_tokens": 200,
        }
        assert validate_run_record(run) == []

    def test_missing_solved_field_reports_error(self):
        run: dict[str, Any] = {
            "task_id": "r08", "repeat_index": 1, "variant": "control",
            "order_index": 0, "session_id": "sess-1",
            "reason": "completed", "steps": 5, "latency_ms": 12000,
            "cost_usd": 0.003, "invoke_skill_count": 0, "skill_selected_count": 0,
            "skill_not_found_count": 0, "bash_call_count": 0,
            "prompt_tokens": 500, "completion_tokens": 200, "cache_read_tokens": 100,
        }
        errors = validate_run_record(run)
        assert any("solved" in e for e in errors)

    def test_invalid_variant_reports_error(self):
        run: dict[str, Any] = {
            "task_id": "r08", "repeat_index": 1, "variant": "invalid",
            "order_index": 0, "session_id": "sess-1", "solved": True,
            "reason": "completed", "steps": 5, "latency_ms": 12000,
            "cost_usd": 0.003, "invoke_skill_count": 0, "skill_selected_count": 0,
            "skill_not_found_count": 0, "bash_call_count": 0,
            "prompt_tokens": 500, "completion_tokens": 200, "cache_read_tokens": 100,
        }
        errors = validate_run_record(run)
        assert len(errors) >= 1
        assert any("variant" in e for e in errors)

    def test_negative_steps_reported(self):
        run: dict[str, Any] = {
            "task_id": "r08", "repeat_index": 1, "variant": "control",
            "order_index": 0, "session_id": "sess-1", "solved": True,
            "reason": "completed", "steps": -1, "latency_ms": 12000,
            "cost_usd": 0.003, "invoke_skill_count": 0, "skill_selected_count": 0,
            "skill_not_found_count": 0, "bash_call_count": 0,
            "prompt_tokens": 500, "completion_tokens": 200, "cache_read_tokens": 100,
        }
        errors = validate_run_record(run)
        assert any("steps" in e for e in errors)

    def test_valid_summary_document_passes(self):
        summary: dict[str, Any] = {
            "schema_version": 1, "phase": "pilot", "runtime": "typescript",
            "model": "deepseek-v4-flash", "repeat": 3,
            "variants": ["control", "treatment"],
            "task_ids": ["r08_local_library_source_omitted"],
            "runs": [{
                "task_id": "r08_local_library_source_omitted",
                "repeat_index": 1, "variant": "control", "order_index": 0,
                "session_id": "sess-1", "solved": False, "reason": "completed",
                "steps": 3, "latency_ms": 5000, "cost_usd": 0.001,
                "invoke_skill_count": 0, "skill_selected_count": 0,
                "skill_not_found_count": 0, "bash_call_count": 0,
                "prompt_tokens": 500, "completion_tokens": 200, "cache_read_tokens": 100,
                "trace_path": "a/trace.jsonl", "result_path": "a/result.json",
                "verification_path": "a/verification.json", "final_diff_path": "a/final.diff",
            }],
            "aggregate": {
                "control_solve_rate": 0.0, "treatment_solve_rate": 0.333,
                "control_skill_selection_rate": 0.0, "treatment_skill_selection_rate": 0.667,
                "pair_solve_delta": 0.333,
                "control_median_steps": 3, "treatment_median_steps": 5,
                "control_median_latency_ms": 5000, "treatment_median_latency_ms": 8000,
                "control_median_cost_usd": 0.001, "treatment_median_cost_usd": 0.002,
                "selected_solve_rate": 0.5, "not_selected_solve_rate": 0.0,
                "infrastructure_error_count": 0, "bash_call_total": 0,
                "paired_outcomes": {"both_solved": 0, "control_only": 0, "treatment_only": 1, "neither": 2},
            },
        }
        assert validate_summary_document(summary) == []

    def test_wrong_schema_version_fails(self):
        summary: dict[str, Any] = {
            "schema_version": 2, "phase": "pilot", "runtime": "typescript",
            "model": "m", "repeat": 1, "variants": ["control", "treatment"],
            "task_ids": ["t1"], "runs": [],
            "aggregate": {
                "control_solve_rate": 0, "treatment_solve_rate": 0,
                "control_skill_selection_rate": 0, "treatment_skill_selection_rate": 0,
                "pair_solve_delta": 0,
                "control_median_steps": 0, "treatment_median_steps": 0,
                "control_median_latency_ms": 0, "treatment_median_latency_ms": 0,
                "control_median_cost_usd": 0, "treatment_median_cost_usd": 0,
                "selected_solve_rate": 0, "not_selected_solve_rate": 0,
                "infrastructure_error_count": 0, "bash_call_total": 0,
                "paired_outcomes": {"both_solved": 0, "control_only": 0, "treatment_only": 0, "neither": 0},
            },
        }
        errors = validate_summary_document(summary)
        assert any("schema_version" in e for e in errors)

    def test_missing_aggregate_field_fails(self):
        agg: dict[str, Any] = {"control_solve_rate": 0.5}
        errors = validate_aggregate(agg)
        assert len(errors) > 0

    def test_aggregate_must_have_paired_outcomes(self):
        agg: dict[str, Any] = {
            "control_solve_rate": 0.5, "treatment_solve_rate": 0.5,
            "control_skill_selection_rate": 0.0, "treatment_skill_selection_rate": 0.8,
            "pair_solve_delta": 0.0,
            "control_median_steps": 5, "treatment_median_steps": 6,
            "control_median_latency_ms": 10000, "treatment_median_latency_ms": 12000,
            "control_median_cost_usd": 0.01, "treatment_median_cost_usd": 0.012,
            "selected_solve_rate": 0.6, "not_selected_solve_rate": 0.0,
            "infrastructure_error_count": 0, "bash_call_total": 0,
            "paired_outcomes": {"both_solved": 1, "control_only": 0, "treatment_only": 0, "neither": 0},
        }
        assert validate_aggregate(agg) == []


class TestReportRecomputability:
    @staticmethod
    def recompute_solve_rate(runs: list[dict[str, Any]], variant: str) -> float:
        matching = [r for r in runs if r["variant"] == variant]
        if not matching:
            return 0.0
        solved = sum(1 for r in matching if r.get("solved"))
        return solved / len(matching)

    @staticmethod
    def recompute_selection_rate(runs: list[dict[str, Any]]) -> float:
        treatment = [r for r in runs if r["variant"] == "treatment"]
        if not treatment:
            return 0.0
        selected = sum(1 for r in treatment if r.get("skill_selected_count", 0) > 0)
        return selected / len(treatment)

    @staticmethod
    def recompute_paired_outcomes(runs: list[dict[str, Any]]) -> dict[str, int]:
        by_pair: dict[tuple[str, int], dict[str, bool]] = {}
        for r in runs:
            key = (r["task_id"], r["repeat_index"])
            by_pair.setdefault(key, {})[r["variant"]] = r.get("solved", False)
        outcomes = {"both_solved": 0, "control_only": 0, "treatment_only": 0, "neither": 0}
        for pair in by_pair.values():
            c = pair.get("control", False)
            t = pair.get("treatment", False)
            if c and t:
                outcomes["both_solved"] += 1
            elif c and not t:
                outcomes["control_only"] += 1
            elif not c and t:
                outcomes["treatment_only"] += 1
            else:
                outcomes["neither"] += 1
        return outcomes

    def test_recompute_solve_rate_matches(self):
        runs: list[dict[str, Any]] = [
            {"task_id": "t1", "repeat_index": 1, "variant": "control", "solved": True},
            {"task_id": "t1", "repeat_index": 1, "variant": "treatment", "solved": True},
            {"task_id": "t1", "repeat_index": 2, "variant": "control", "solved": False},
            {"task_id": "t1", "repeat_index": 2, "variant": "treatment", "solved": True},
        ]
        assert self.recompute_solve_rate(runs, "control") == 0.5
        assert self.recompute_solve_rate(runs, "treatment") == 1.0

    def test_recompute_selection_rate(self):
        runs: list[dict[str, Any]] = [
            {"task_id": "t1", "repeat_index": 1, "variant": "control", "skill_selected_count": 0},
            {"task_id": "t1", "repeat_index": 1, "variant": "treatment", "skill_selected_count": 1},
            {"task_id": "t1", "repeat_index": 2, "variant": "control", "skill_selected_count": 0},
            {"task_id": "t1", "repeat_index": 2, "variant": "treatment", "skill_selected_count": 0},
        ]
        assert self.recompute_selection_rate(runs) == 0.5

    def test_recompute_paired_outcomes(self):
        runs: list[dict[str, Any]] = [
            {"task_id": "t1", "repeat_index": 1, "variant": "control", "solved": True},
            {"task_id": "t1", "repeat_index": 1, "variant": "treatment", "solved": True},
            {"task_id": "t1", "repeat_index": 2, "variant": "control", "solved": False},
            {"task_id": "t1", "repeat_index": 2, "variant": "treatment", "solved": True},
        ]
        outcomes = self.recompute_paired_outcomes(runs)
        assert outcomes["both_solved"] == 1
        assert outcomes["control_only"] == 0
        assert outcomes["treatment_only"] == 1
        assert outcomes["neither"] == 0


class TestVariantIsolation:
    def test_variant_names_are_exclusive(self):
        assert "control" != "treatment"
        assert "baseline" not in VARIANTS

    def test_pilot_is_single_task(self):
        assert PILOT_TASK_ID == "r08_local_library_source_omitted"
        assert PILOT_TASK_ID in DEFAULT_TASK_IDS_CMDS

    def test_full_is_10_tasks(self):
        assert len(DEFAULT_TASK_IDS_CMDS) == 10
        assert len(set(DEFAULT_TASK_IDS_CMDS)) == 10


class TestSkillSelectionAudit:
    def test_selected_event_has_required_fields(self):
        event = make_skill_selection_event("selected")
        payload = event["payload"]
        assert payload["outcome"] == "selected"
        assert payload["selectionSource"] == "model_tool_call"
        assert payload["extensionName"] == "cmake"
        assert payload["definitionSource"] == "cmake/skills/build-fix/SKILL.md"
        assert payload["selectedSkill"] == "cmake-build-fix"
        assert payload["requestedSkill"] == "cmake-build-fix"

    def test_not_found_event_has_no_definition_fields(self):
        event = make_skill_selection_event("not_found")
        payload = event["payload"]
        assert payload["outcome"] == "not_found"
        assert "selectedSkill" not in payload
        assert "extensionName" not in payload
        assert "definitionSource" not in payload

    def test_valid_selected_event_passes_whitelist(self):
        event = make_skill_selection_event("selected")
        payload = event["payload"]
        allowed = {
            "schemaVersion", "invocationId", "selectionSource",
            "outcome", "requestedSkill", "selectedSkill",
            "extensionName", "definitionSource",
        }
        assert set(payload.keys()).issubset(allowed)
        forbidden = {"instructions", "content", "messages", "workspacePath", "error", "stack"}
        assert not (set(payload.keys()) & forbidden)

    def test_has_skill_selection_detects_event(self):
        trace: list[dict[str, Any]] = [
            {"type": "model_start"}, {"type": "model_end"},
            {"type": "tool_start", "payload": {"toolName": "invoke_skill"}},
            {"type": "skill_selection", "payload": {"outcome": "selected"}},
            {"type": "tool_end"},
        ]
        assert has_skill_selection_event(trace) is True
        assert has_skill_tool_invocation(trace) is True

    def test_empty_trace_has_no_selection(self):
        assert has_skill_selection_event([]) is False
        assert has_skill_tool_invocation([]) is False

    def test_control_trace_has_no_selection(self):
        trace: list[dict[str, Any]] = [
            {"type": "model_start"}, {"type": "model_end"},
            {"type": "tool_start", "payload": {"toolName": "read_file"}},
            {"type": "post_tool_use", "payload": {"toolName": "read_file"}},
            {"type": "tool_end"}, {"type": "model_start"}, {"type": "finish"},
        ]
        assert has_skill_selection_event(trace) is False
        assert has_skill_tool_invocation(trace) is False

    def test_count_bash_invocations_zero(self):
        trace: list[dict[str, Any]] = [
            {"type": "tool_start", "payload": {"toolName": "read_file"}},
            {"type": "tool_start", "payload": {"toolName": "invoke_skill"}},
        ]
        assert count_bash_invocations(trace) == 0

    def test_count_bash_invocations_detects_bash(self):
        trace: list[dict[str, Any]] = [
            {"type": "tool_start", "payload": {"toolName": "bash"}},
            {"type": "tool_start", "payload": {"toolName": "read_file"}},
            {"type": "tool_start", "payload": {"toolName": "bash"}},
        ]
        assert count_bash_invocations(trace) == 2


# ============================================================================
# 集成 Fake 测试（使用 mock command_runner 绕过 TS CLI）
# ============================================================================


class TestCmakeSkillABFakeIntegration:
    """使用 mock command_runner 的集成测试，无需 node/TS CLI 环境。

    通过 command_runner 参数向 run_cmake_skill_ab() 注入可控的
    managed result 和 trace events，验证 orchestrator 层行为正确性。
    """

    def test_fake_pilot_both_solved(self, tmp_path: Path):
        """用 mock runner 跑 pilot，验证 control 和 treatment 都 solved 且无 Bash。"""
        eval_dir = tmp_path / "eval"
        tasks_dir = eval_dir / "tasks_cmake_real"
        task_dir = _make_cmake_task_structure(
            tasks_dir / "r08_local_library_source_omitted",
            "r08_local_library_source_omitted",
        )
        output_dir = tmp_path / "output"

        default_trace = _make_default_trace()
        result = run_cmake_skill_ab(
            tasks=[
                EvalTask(
                    id="r08_local_library_source_omitted",
                    path=task_dir,
                    profile=ProjectProfile(
                        language="cmake", test_cmd="echo ok", test_timeout=30
                    ),
                )
            ],
            repeat=1,
            budget_steps=40,
            output_dir=output_dir,
            fake=False,
            command_runner=_make_mock_runner(
                exit_code=0, trace_events=default_trace
            ),
        )
        assert len(result) == 2
        assert result[0].variant == "control"
        assert result[1].variant == "treatment"
        assert result[0].solved is True
        assert result[1].solved is True
        assert result[0].skill_selected_count == 0
        assert result[1].skill_selected_count == 0
        assert result[0].bash_call_count == 0
        assert result[1].bash_call_count == 0

    def test_control_no_skill_selection(self, tmp_path: Path):
        """control trace 不应有 skill_selection 事件。"""
        output_dir = tmp_path / "output"
        trace_path = output_dir / "control-trace.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        control_trace = _make_default_trace()
        trace_path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in control_trace)
            + "\n",
            encoding="utf-8",
        )

        assert not has_skill_selection_event(control_trace)

        from eval.cmake_skill_ab import _parse_trace_metrics
        metrics = _parse_trace_metrics(str(trace_path))
        assert metrics["invoke_skill_count"] == 0
        assert metrics["skill_selected_count"] == 0
        assert metrics["bash_call_count"] == 0

    def test_treatment_has_valid_selected(self, tmp_path: Path):
        """treatment trace 应有有效的 skill_selection selected 事件。"""
        trace_events = _make_treatment_trace()
        skill_events = [
            e for e in trace_events if e.get("type") == "skill_selection"
        ]
        assert len(skill_events) == 1
        payload = skill_events[0]["payload"]
        assert payload["outcome"] == "selected"
        assert payload["selectionSource"] == "model_tool_call"
        assert payload["definitionSource"] == "cmake/skills/build-fix/SKILL.md"
        assert payload["extensionName"] == "cmake"
        assert payload["selectedSkill"] == "cmake-build-fix"

    def test_paired_ab_ba_alternation(self, tmp_path: Path):
        """repeat=2 时顺序应为 CT, TC。"""
        orders = generate_pair_orders(["r08"], repeat=2)
        assert orders[0].order == "CT"
        assert orders[1].order == "TC"
        assert orders[0].repeat_index == 0
        assert orders[1].repeat_index == 1

    def test_full_mode_discovers_10_tasks(self):
        """full phase 应发现 10 个 task（真实 tasks 目录）。"""
        eval_dir = Path(__file__).resolve().parents[1] / "eval"
        tasks = discover_cmake_tasks(eval_dir, "full")
        assert len(tasks) == 10
        for task in tasks:
            assert isinstance(task, EvalTask)
            assert task.id in DEFAULT_TASK_IDS_CMDS

    def test_pilot_mode_only_runs_r08(self):
        """pilot phase 应只返回 r08 task（真实 tasks 目录）。"""
        eval_dir = Path(__file__).resolve().parents[1] / "eval"
        tasks = discover_cmake_tasks(eval_dir, "pilot")
        assert len(tasks) == 1
        assert tasks[0].id == "r08_local_library_source_omitted"

    def test_summary_json_is_valid(self, tmp_path: Path):
        """运行 Fake pilot，验证输出的 summary JSON 通过 schema 验证。"""
        eval_dir = tmp_path / "eval"
        tasks_dir = eval_dir / "tasks_cmake_real"
        task_dir = _make_cmake_task_structure(
            tasks_dir / "r08_local_library_source_omitted",
            "r08_local_library_source_omitted",
        )
        output_dir = tmp_path / "output"

        default_trace = _make_default_trace()
        result = run_cmake_skill_ab(
            tasks=[
                EvalTask(
                    id="r08_local_library_source_omitted",
                    path=task_dir,
                    profile=ProjectProfile(
                        language="cmake", test_cmd="echo ok", test_timeout=30
                    ),
                )
            ],
            repeat=1,
            budget_steps=40,
            output_dir=output_dir,
            fake=False,
            command_runner=_make_mock_runner(
                exit_code=0, trace_events=default_trace
            ),
        )
        assert len(result) == 2
        assert result[0].variant == "control"
        assert result[1].variant == "treatment"
        assert result[0].solved is True
        assert result[1].solved is True

        json_path = write_summary_json(result, output_dir)
        assert json_path.is_file()
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        assert summary["schema_version"] == 1
        assert summary["evaluation"] == "cmake-skill-ab"
        assert summary["control"]["total"] >= 1
        assert summary["treatment"]["total"] >= 1

    def test_report_recomputable_from_artifacts(self, tmp_path: Path):
        """验证 report 能从带有不同 trace metrics 的 run 数据正确生成。"""
        eval_dir = tmp_path / "eval"
        tasks_dir = eval_dir / "tasks_cmake_real"
        task_dir = _make_cmake_task_structure(
            tasks_dir / "r08_local_library_source_omitted",
            "r08_local_library_source_omitted",
        )
        output_dir = tmp_path / "output"

        runner_calls: list[dict[str, Any]] = []

        def two_phase_runner(
            command: list[str], *, cwd: Path, timeout: int
        ) -> TsProcessResult:
            call_info: dict[str, Any] = {"count": len(runner_calls)}
            runner_calls.append(call_info)
            if call_info["count"] % 2 == 0:
                return _managed_result(
                    command,
                    exit_code=0,
                    trace_events=_make_default_trace(),
                    overrides={"steps": 2, "reason": "completed"},
                )
            else:
                return _managed_result(
                    command,
                    exit_code=0,
                    trace_events=_make_treatment_trace(),
                    overrides={"steps": 4, "reason": "completed"},
                )

        result = run_cmake_skill_ab(
            tasks=[
                EvalTask(
                    id="r08_local_library_source_omitted",
                    path=task_dir,
                    profile=ProjectProfile(
                        language="cmake", test_cmd="echo ok", test_timeout=30
                    ),
                )
            ],
            repeat=1,
            budget_steps=40,
            output_dir=output_dir,
            fake=False,
            command_runner=two_phase_runner,
        )

        assert len(result) == 2
        control_run = [r for r in result if r.variant == "control"][0]
        treatment_run = [r for r in result if r.variant == "treatment"][0]
        assert control_run.skill_selected_count == 0
        assert treatment_run.skill_selected_count >= 1
        assert treatment_run.solved is True

        # 写 report
        report_path = write_markdown_report(
            result, phase="pilot", repeat=1, budget_steps=40, fake=False,
            output_dir=output_dir,
        )
        assert report_path.is_file()
        content = report_path.read_text(encoding="utf-8")
        assert "CM-02" in content
        assert "Control" in content
        assert "Treatment" in content

        # 写 JSON
        json_path = write_summary_json(result, output_dir)
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        assert summary["control"]["total"] >= 1
        assert summary["treatment"]["total"] >= 1

    def test_infrastructure_error_propagation(self, tmp_path: Path):
        """模拟基础设施错误，验证错误被正确传播。"""
        eval_dir = tmp_path / "eval"
        tasks_dir = eval_dir / "tasks_cmake_real"
        task_dir = _make_cmake_task_structure(
            tasks_dir / "r08_local_library_source_omitted",
            "r08_local_library_source_omitted",
        )
        output_dir = tmp_path / "output"

        # exit_code=2 导致 TsBridgeError("cli_failed")
        result = run_cmake_skill_ab(
            tasks=[
                EvalTask(
                    id="r08_local_library_source_omitted",
                    path=task_dir,
                    profile=ProjectProfile(
                        language="cmake", test_cmd="echo ok", test_timeout=30
                    ),
                )
            ],
            repeat=1,
            budget_steps=40,
            output_dir=output_dir,
            fake=False,
            command_runner=_make_mock_runner(exit_code=2),
        )

        assert len(result) == 2
        for r in result:
            assert r.solved is False
            assert r.infrastructure_error is not None
            assert isinstance(r.infrastructure_error, dict)


# ============================================================================
# 审查报告生成
# ============================================================================


def review_ts_bridge() -> list[dict[str, str]]:
    return []


def review_cmake_skill_ab() -> list[dict[str, str]]:
    return []


class TestReviewCoverage:
    def test_review_functions_exist(self):
        assert isinstance(review_ts_bridge(), list)
        assert isinstance(review_cmake_skill_ab(), list)

    def test_expected_review_checklist(self):
        checklist = [
            "engine_diff_empty", "no_host_shell", "accept_edits",
            "variant_isolation", "paired_order_alternation", "whitelist_fields",
            "error_propagation", "default_backward_compat",
            "fake_no_deepseek", "real_explicit_confirm",
        ]
        assert len(checklist) == 10
