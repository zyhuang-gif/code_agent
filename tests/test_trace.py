from pathlib import Path
import json
from agent.trace import Trace


def test_trace_writes_llm_call_with_cost_fields(tmp_path: Path):
    trace = Trace(tmp_path / "trace.jsonl")
    trace.llm_call(step=1, model="deepseek-v4-flash", prompt_tokens=3, completion_tokens=4, cache_hit_tokens=1, cache_miss_tokens=2, cost_usd=0.5, latency_ms=10, tool_calls=["read_file"])
    row = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8"))
    assert row["t"] == "llm_call"
    assert row["cache_hit_tokens"] == 1
    assert row["cache_miss_tokens"] == 2
    assert row["cost_usd"] == 0.5


def test_trace_appends_events_in_order(tmp_path: Path):
    trace = Trace(tmp_path / "trace.jsonl")
    trace.tool_exec(step=1, tool="read_file", args={"path":"a"}, result_preview="ok", is_error=False, duration_ms=1)
    trace.run_summary(task_id="t01", steps=1, total_tokens=2, total_cost_usd=0.1, result="solved", diff_path="diff.patch")
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["t"] for row in rows] == ["tool_exec", "run_summary"]
