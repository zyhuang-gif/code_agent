"""CM-02 Trace 解析、报告生成、schema 验证（独立模块，无 cmake_skill_ab 依赖）。

本模块不导入 eval/cmake_skill_ab.py，避免循环依赖。提供：
1. 基于 TS CLI trace.jsonl 结构的 fail-closed Trace 解析
2. CM-02 schema v1 JSON 摘要 + Markdown 报告构建
3. Schema 验证函数（供测试与 CI 复用）
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
VARIANTS = ("control", "treatment")


# ============================================================================
# 1. Trace 解析（fail-closed）
# ============================================================================


def parse_trace_metrics(trace_path: str) -> dict[str, int]:
    """从 TS CLI trace.jsonl 逐行解析事件，提取技能选择与 bash 调用指标。

    解析失败或文件不存在均抛异常（fail-closed），不静默返回全 0。

    Returns
    -------
    dict
        invoke_skill_count, skill_selected_count, skill_not_found_count,
        bash_call_count, invalid_selection_audit_count,
        prompt_tokens, completion_tokens, cache_read_tokens
    """
    tp = Path(trace_path)
    if not tp.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    metrics: dict[str, int] = {
        "invoke_skill_count": 0,
        "skill_selected_count": 0,
        "skill_not_found_count": 0,
        "bash_call_count": 0,
        "invalid_selection_audit_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
    }

    try:
        with open(tp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Corrupted JSONL line in trace: {trace_path}"
                    ) from exc

                if not isinstance(event, dict):
                    raise ValueError(
                        f"Non-object JSONL line in trace: {trace_path}"
                    )

                etype = event.get("type", "")
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}

                # ---- skill_selection 事件 ----
                if etype == "skill_selection":
                    metrics["invoke_skill_count"] += 1
                    outcome = payload.get("outcome", "")
                    if outcome == "selected":
                        metrics["skill_selected_count"] += 1
                    elif outcome == "not_found":
                        metrics["skill_not_found_count"] += 1

                    # 审计：检查 payload 完整性
                    if _is_invalid_skill_selection(payload):
                        metrics["invalid_selection_audit_count"] += 1

                # ---- tool_end 事件：bash 调用计数 ----
                if etype == "tool_end":
                    if _is_bash_tool(payload):
                        metrics["bash_call_count"] += 1

                # ---- model_end 事件：累计 token 用量 ----
                if etype == "model_end":
                    usage = payload.get("usage", {})
                    if isinstance(usage, dict):
                        metrics["prompt_tokens"] += _safe_int(
                            usage.get("promptTokens", 0)
                        )
                        metrics["completion_tokens"] += _safe_int(
                            usage.get("completionTokens", 0)
                        )
                        metrics["cache_read_tokens"] += _safe_int(
                            usage.get("cacheReadTokens", 0)
                        )

    except OSError as exc:
        raise OSError(f"Failed to read trace file: {trace_path}") from exc

    return metrics


def _safe_int(value: Any) -> int:
    """将值安全转为 int，非整数返回 0。"""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _is_invalid_skill_selection(payload: dict[str, Any]) -> bool:
    """检查 skill_selection payload 是否不合规。"""
    for key in ("schemaVersion", "selectionSource", "outcome"):
        if key not in payload:
            return True
    if payload.get("outcome") == "selected":
        for key in ("extensionName", "definitionSource", "selectedSkill"):
            if key not in payload:
                return True
    return False


def _is_bash_tool(payload: dict[str, Any]) -> bool:
    """检查 tool_end payload 是否对应 bash 工具调用。"""
    invocation = payload.get("invocation", {})
    if isinstance(invocation, dict) and invocation.get("name") == "bash":
        return True
    record = payload.get("record", {})
    if isinstance(record, dict):
        rec_invocation = record.get("invocation", {})
        if isinstance(rec_invocation, dict) and rec_invocation.get("name") == "bash":
            return True
    return False


# ============================================================================
# 2. 辅助函数
# ============================================================================


def calc_median(values: list[float]) -> float:
    """计算中位数。空列表返回 0.0。"""
    if not values:
        return 0.0
    return float(statistics.median(values))


def calc_percentile(values: list[float], p: float) -> float:
    """计算第 p 百分位数（p 为 0-100），线性插值。"""
    if not values:
        return 0.0
    if p < 0 or p > 100:
        raise ValueError(f"Percentile must be in [0, 100], got {p}")
    sorted_values = sorted(values)
    n = len(sorted_values)
    rank = (p / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_values[lo])
    frac = rank - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def calc_paired_outcomes(runs: list[dict[str, Any]]) -> dict[str, int]:
    """从 runs 列表计算成对结局分布。"""
    by_pair: dict[tuple[str, int], dict[str, bool]] = {}
    for r in runs:
        key = (r["task_id"], r["repeat_index"])
        by_pair.setdefault(key, {})[r["variant"]] = bool(r.get("solved", False))
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


def resolve_safe_relative_path(abs_path: str, output_dir: Path) -> str:
    """验证路径在 output_dir 内，返回相对路径。"""
    if not isinstance(abs_path, str) or not abs_path:
        return ""
    candidate = Path(abs_path).resolve()
    resolved_output = output_dir.resolve()
    try:
        candidate.relative_to(resolved_output)
    except ValueError:
        raise ValueError(
            f"Artifact path outside output_dir: {abs_path} "
            f"(output_dir={resolved_output})"
        ) from None
    return str(candidate.relative_to(resolved_output)).replace("\\", "/")


# ============================================================================
# 3. 报告构建
# ============================================================================


def build_cm02_report(
    results: list[dict[str, Any]],
    phase: str,
    model: str,
    repeat: int,
    output_dir: Path,
) -> tuple[Path, Path]:
    """构建 CM-02 schema v1 JSON 摘要和 Markdown 报告。

    Returns
    -------
    tuple[Path, Path]
        (json_path, md_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    enriched: list[dict[str, Any]] = []
    for r in results:
        run = dict(r)
        tp = run.get("trace_path", "")
        trace_metrics: dict[str, int] = {}
        if tp:
            try:
                trace_metrics = parse_trace_metrics(tp)
            except (FileNotFoundError, ValueError, OSError):
                trace_metrics = {}
        run.setdefault("invoke_skill_count", trace_metrics.get("invoke_skill_count", 0))
        run.setdefault("skill_selected_count", trace_metrics.get("skill_selected_count", 0))
        run.setdefault("skill_not_found_count", trace_metrics.get("skill_not_found_count", 0))
        run.setdefault("bash_call_count", trace_metrics.get("bash_call_count", 0))
        tu = run.get("token_usage", {})
        if isinstance(tu, dict):
            for src_key, dst_key in (
                ("promptTokens", "prompt_tokens"),
                ("prompt_tokens", "prompt_tokens"),
                ("completionTokens", "completion_tokens"),
                ("completion_tokens", "completion_tokens"),
                ("cacheReadTokens", "cache_read_tokens"),
                ("cache_read_tokens", "cache_read_tokens"),
            ):
                if src_key in tu:
                    run.setdefault(dst_key, tu[src_key])
        run.setdefault("prompt_tokens", 0)
        run.setdefault("completion_tokens", 0)
        run.setdefault("cache_read_tokens", 0)
        for art_key in ("trace_path", "result_path", "verification_path", "diff_path"):
            abs_val = run.get(art_key, "")
            if abs_val:
                try:
                    run[f"_rel_{art_key}"] = resolve_safe_relative_path(abs_val, output_dir)
                except ValueError:
                    run[f"_rel_{art_key}"] = ""
            else:
                run[f"_rel_{art_key}"] = ""
        enriched.append(run)

    control_runs = [r for r in enriched if r["variant"] == "control"]
    treatment_runs = [r for r in enriched if r["variant"] == "treatment"]

    control_solved = sum(1 for r in control_runs if r.get("solved"))
    treatment_solved = sum(1 for r in treatment_runs if r.get("solved"))
    control_total = len(control_runs)
    treatment_total = len(treatment_runs)
    control_solve_rate = control_solved / control_total if control_total else 0.0
    treatment_solve_rate = treatment_solved / treatment_total if treatment_total else 0.0

    treatment_selected = sum(1 for r in treatment_runs if r.get("skill_selected_count", 0) > 0)
    treatment_skill_selection_rate = treatment_selected / treatment_total if treatment_total else 0.0
    control_skill_selection_rate = 0.0
    pair_solve_delta = treatment_solve_rate - control_solve_rate

    control_steps = [r["steps"] for r in control_runs]
    treatment_steps = [r["steps"] for r in treatment_runs]
    control_latency = [r["latency_ms"] for r in control_runs]
    treatment_latency = [r["latency_ms"] for r in treatment_runs]
    control_cost = [r["cost_usd"] for r in control_runs]
    treatment_cost = [r["cost_usd"] for r in treatment_runs]

    selected_runs = [r for r in treatment_runs if r.get("skill_selected_count", 0) > 0]
    not_selected_runs = [r for r in treatment_runs if r.get("skill_selected_count", 0) == 0]
    selected_solve_rate = sum(1 for r in selected_runs if r.get("solved")) / len(selected_runs) if selected_runs else 0.0
    not_selected_solve_rate = sum(1 for r in not_selected_runs if r.get("solved")) / len(not_selected_runs) if not_selected_runs else 0.0

    infrastructure_error_count = sum(1 for r in enriched if r.get("infrastructure_error") is not None)
    bash_call_total = sum(r.get("bash_call_count", 0) for r in enriched)

    invalid_selection_audit_count = 0
    for r in enriched:
        tp_ia = r.get("trace_path", "")
        if tp_ia:
            try:
                tm = parse_trace_metrics(tp_ia)
                invalid_selection_audit_count += tm.get("invalid_selection_audit_count", 0)
            except (FileNotFoundError, ValueError, OSError):
                pass

    aggregate = {
        "control_solve_rate": round(control_solve_rate, 6),
        "treatment_solve_rate": round(treatment_solve_rate, 6),
        "control_skill_selection_rate": round(control_skill_selection_rate, 6),
        "treatment_skill_selection_rate": round(treatment_skill_selection_rate, 6),
        "pair_solve_delta": round(pair_solve_delta, 6),
        "control_median_steps": round(calc_median(control_steps), 1),
        "control_p25_steps": round(calc_percentile(control_steps, 25), 1),
        "control_p75_steps": round(calc_percentile(control_steps, 75), 1),
        "control_median_latency_ms": round(calc_median(control_latency), 0),
        "control_p25_latency_ms": round(calc_percentile(control_latency, 25), 0),
        "control_p75_latency_ms": round(calc_percentile(control_latency, 75), 0),
        "control_median_cost_usd": calc_median(control_cost),
        "control_p25_cost_usd": calc_percentile(control_cost, 25),
        "control_p75_cost_usd": calc_percentile(control_cost, 75),
        "treatment_median_steps": round(calc_median(treatment_steps), 1),
        "treatment_p25_steps": round(calc_percentile(treatment_steps, 25), 1),
        "treatment_p75_steps": round(calc_percentile(treatment_steps, 75), 1),
        "treatment_median_latency_ms": round(calc_median(treatment_latency), 0),
        "treatment_p25_latency_ms": round(calc_percentile(treatment_latency, 25), 0),
        "treatment_p75_latency_ms": round(calc_percentile(treatment_latency, 75), 0),
        "treatment_median_cost_usd": calc_median(treatment_cost),
        "treatment_p25_cost_usd": calc_percentile(treatment_cost, 25),
        "treatment_p75_cost_usd": calc_percentile(treatment_cost, 75),
        "selected_solve_rate": round(selected_solve_rate, 6),
        "not_selected_solve_rate": round(not_selected_solve_rate, 6),
        "infrastructure_error_count": infrastructure_error_count,
        "bash_call_total": bash_call_total,
        "invalid_selection_audit_count": invalid_selection_audit_count,
        "paired_outcomes": calc_paired_outcomes(enriched),
    }

    task_ids = sorted({r["task_id"] for r in enriched})
    runs_output: list[dict[str, Any]] = []
    for r in enriched:
        runs_output.append({
            "task_id": r["task_id"],
            "repeat_index": r["repeat_index"],
            "variant": r["variant"],
            "order_index": r["order_index"],
            "session_id": r.get("session_id", ""),
            "solved": r.get("solved", False),
            "reason": r.get("reason", ""),
            "steps": r.get("steps", 0),
            "latency_ms": r.get("latency_ms", 0),
            "cost_usd": r.get("cost_usd", 0.0),
            "prompt_tokens": r.get("prompt_tokens", 0),
            "completion_tokens": r.get("completion_tokens", 0),
            "cache_read_tokens": r.get("cache_read_tokens", 0),
            "invoke_skill_count": r.get("invoke_skill_count", 0),
            "skill_selected_count": r.get("skill_selected_count", 0),
            "skill_not_found_count": r.get("skill_not_found_count", 0),
            "bash_call_count": r.get("bash_call_count", 0),
            "infrastructure_error": r.get("infrastructure_error"),
            "trace_path": r.get("_rel_trace_path", ""),
            "result_path": r.get("_rel_result_path", ""),
            "verification_path": r.get("_rel_verification_path", ""),
            "final_diff_path": r.get("_rel_diff_path", ""),
        })

    summary = {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "runtime": "typescript",
        "model": model,
        "repeat": repeat,
        "variants": list(VARIANTS),
        "task_ids": task_ids,
        "runs": runs_output,
        "aggregate": aggregate,
    }

    json_path = output_dir / "cm02-summary.json"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    md_path = _write_markdown_report(enriched=enriched, aggregate=aggregate, phase=phase, model=model, repeat=repeat, output_dir=output_dir)
    return json_path, md_path


def _write_markdown_report(enriched, aggregate, phase, model, repeat, output_dir):
    """生成 cm02-report.md。"""
    def _delta(ctrl_val, treat_val):
        d = treat_val - ctrl_val
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.4f}"

    control_runs = [r for r in enriched if r["variant"] == "control"]
    treatment_runs = [r for r in enriched if r["variant"] == "treatment"]
    c_solved = sum(1 for r in control_runs if r.get("solved"))
    t_solved = sum(1 for r in treatment_runs if r.get("solved"))
    c_total = len(control_runs)
    t_total = len(treatment_runs)

    lines = [
        "# CM-02 CMake Skill A/B Evaluation Report",
        "",
        f"- **Phase**: {phase}",
        f"- **Model**: {model}",
        f"- **Runtime**: typescript",
        f"- **Repeat**: {repeat}",
        "- **Control**: empty extensions root (no invoke_skill tool)",
        "- **Treatment**: workspace extensions (cmake build-fix skill)",
        f"- **Schema version**: {SCHEMA_VERSION}",
        "",
        "## Summary",
        "",
        "| Metric | Control | Treatment | Delta |",
        "|---|---:|---:|---:|",
        f"| Solve Rate | {aggregate['control_solve_rate']:.4f} | {aggregate['treatment_solve_rate']:.4f} | {_delta(aggregate['control_solve_rate'], aggregate['treatment_solve_rate'])} |",
        f"| Solved / Total | {c_solved}/{c_total} | {t_solved}/{t_total} | |",
        f"| Skill Selection Rate | {aggregate['control_skill_selection_rate']:.4f} | {aggregate['treatment_skill_selection_rate']:.4f} | |",
        f"| Pair Solve Delta | - | - | {aggregate['pair_solve_delta']:+.4f} |",
        "",
        "### Steps",
        "",
        "| Metric | Control | Treatment |",
        "|---|---:|---:|",
        f"| Median | {aggregate['control_median_steps']:.1f} | {aggregate['treatment_median_steps']:.1f} |",
        f"| P25 | {aggregate['control_p25_steps']:.1f} | {aggregate['treatment_p25_steps']:.1f} |",
        f"| P75 | {aggregate['control_p75_steps']:.1f} | {aggregate['treatment_p75_steps']:.1f} |",
        "",
        "### Latency (ms)",
        "",
        "| Metric | Control | Treatment |",
        "|---|---:|---:|",
        f"| Median | {aggregate['control_median_latency_ms']:.0f} | {aggregate['treatment_median_latency_ms']:.0f} |",
        f"| P25 | {aggregate['control_p25_latency_ms']:.0f} | {aggregate['treatment_p25_latency_ms']:.0f} |",
        f"| P75 | {aggregate['control_p75_latency_ms']:.0f} | {aggregate['treatment_p75_latency_ms']:.0f} |",
        "",
        "### Cost (USD)",
        "",
        "| Metric | Control | Treatment |",
        "|---|---:|---:|",
        f"| Median | {aggregate['control_median_cost_usd']:.6f} | {aggregate['treatment_median_cost_usd']:.6f} |",
        f"| P25 | {aggregate['control_p25_cost_usd']:.6f} | {aggregate['treatment_p25_cost_usd']:.6f} |",
        f"| P75 | {aggregate['control_p75_cost_usd']:.6f} | {aggregate['treatment_p75_cost_usd']:.6f} |",
        "",
        "### Skill Selection & Audit",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Selected Solve Rate | {aggregate['selected_solve_rate']:.4f} |",
        f"| Not-Selected Solve Rate | {aggregate['not_selected_solve_rate']:.4f} |",
        f"| Bash Call Total | {aggregate['bash_call_total']} |",
        f"| Invalid Selection Audits | {aggregate['invalid_selection_audit_count']} |",
        f"| Infrastructure Errors | {aggregate['infrastructure_error_count']} |",
        "",
        "### Paired Outcomes",
        "",
        "| Outcome | Count |",
        "|---|---:|",
        f"| Both Solved | {aggregate['paired_outcomes']['both_solved']} |",
        f"| Control Only | {aggregate['paired_outcomes']['control_only']} |",
        f"| Treatment Only | {aggregate['paired_outcomes']['treatment_only']} |",
        f"| Neither | {aggregate['paired_outcomes']['neither']} |",
        "",
    ]

    task_ids = sorted({r["task_id"] for r in enriched})
    lines.append("## Per-Task Results")
    lines.append("")
    for tid in task_ids:
        lines.append(f"### {tid}")
        lines.append("")
        lines.append("| Repeat | Variant | Order | Solved | Steps | Latency (ms) | Cost (USD) | prompt_tok | compl_tok | cache_tok | invoke_skill | selected | not_found | bash |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        task_runs = sorted([r for r in enriched if r["task_id"] == tid], key=lambda r: (r["repeat_index"], r["order_index"]))
        for r in task_runs:
            lines.append(f"| {r['repeat_index']} | {r['variant']} | {r['order_index']} | {'yes' if r.get('solved') else 'no'} | {r.get('steps', 0)} | {r.get('latency_ms', 0)} | {r.get('cost_usd', 0.0):.6f} | {r.get('prompt_tokens', 0)} | {r.get('completion_tokens', 0)} | {r.get('cache_read_tokens', 0)} | {r.get('invoke_skill_count', 0)} | {r.get('skill_selected_count', 0)} | {r.get('skill_not_found_count', 0)} | {r.get('bash_call_count', 0)} |")
        lines.append("")

    errors_list = [r for r in enriched if r.get("infrastructure_error") is not None]
    if errors_list:
        lines.append("## Infrastructure Errors")
        lines.append("")
        for r in errors_list:
            ie = r["infrastructure_error"]
            if isinstance(ie, dict):
                msg = (ie.get("message", "") or "")[:200]
                lines.append(f"- **{r['task_id']}** repeat={r['repeat_index']} variant={r['variant']}: `{ie.get('type', '')}` code={ie.get('code', '')}{': ' + msg if msg else ''}")
        lines.append("")

    lines.extend(["## Notes", "", "LLM evals are inherently noisy. Never draw conclusions from a single solve rate. Use mean +/- std across repeated runs and inspect traces for qualitative differences.", ""])

    report_path = output_dir / "cm02-report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ============================================================================
# 4. Schema 验证
# ============================================================================


def _require_str(obj, key, *, path="$"):
    value = obj.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{path}.{key} must be a string, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{path}.{key} must not be empty")
    return value


def _require_int(obj, key, *, path="$", non_negative=True):
    value = obj.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be an integer, got {type(value).__name__}")
    if non_negative and value < 0:
        raise ValueError(f"{path}.{key} must be non-negative, got {value}")
    return value


def _require_float(obj, key, *, path="$", non_negative=True):
    value = obj.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be a number, got {type(value).__name__}")
    if non_negative and value < 0:
        raise ValueError(f"{path}.{key} must be non-negative, got {value}")
    return float(value)


def validate_run_record(run, *, path="$"):
    """验证单条 run 记录符合 CM-02 schema v1。"""
    errors = []
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
        for key in ("solved", "reason", "prompt_tokens", "completion_tokens", "cache_read_tokens"):
            if key not in run:
                errors.append(f"{path} must have {key!r} field")
        if run.get("infrastructure_error") is not None and not isinstance(run["infrastructure_error"], dict):
            errors.append(f"{path}.infrastructure_error must be an object or null")
        for art in ("trace_path", "result_path", "verification_path", "final_diff_path"):
            if art in run:
                _require_str(run, art, path=path)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_aggregate(agg, *, path="$.aggregate"):
    """验证 aggregate 对象符合 CM-02 schema v1。"""
    errors = []
    for group in VARIANTS:
        for key in ("solve_rate", "skill_selection_rate"):
            if f"{group}_{key}" not in agg:
                errors.append(f"{path} must contain {group}_{key!r}")
    for group in VARIANTS:
        for suffix in ("median_steps", "median_latency_ms", "median_cost_usd"):
            if f"{group}_{suffix}" not in agg:
                errors.append(f"{path} must contain {group}_{suffix!r}")
    if "pair_solve_delta" not in agg:
        errors.append(f"{path} must contain 'pair_solve_delta'")
    paired = agg.get("paired_outcomes")
    if not isinstance(paired, dict):
        errors.append(f"{path}.paired_outcomes must be an object")
    else:
        for key in ("both_solved", "control_only", "treatment_only", "neither"):
            if key not in paired:
                errors.append(f"{path}.paired_outcomes must contain {key!r}")
    for key in ("infrastructure_error_count", "bash_call_total", "selected_solve_rate", "not_selected_solve_rate"):
        if key not in agg:
            errors.append(f"{path} must contain {key!r}")
    return errors


def validate_summary_document(summary):
    """验证 cm02-summary.json 全文档符合 CM-02 schema v1。"""
    errors = []
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
