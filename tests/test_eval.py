from pathlib import Path
from eval.run_eval import EvalTask, run_task, summarize


def test_run_eval_marks_solved_and_failed(tmp_path: Path):
    task_dir = tmp_path / "task"; repo = task_dir / "repo"; repo.mkdir(parents=True)
    (repo / "answer.txt").write_text("bad", encoding="utf-8")
    (task_dir / "prompt.md").write_text("fix", encoding="utf-8")
    (task_dir / "verify.py").write_text("from pathlib import Path\nraise SystemExit(0 if Path('answer.txt').read_text() == 'ok' else 1)\n", encoding="utf-8")
    def fake_agent(workspace, prompt):
        (workspace / "answer.txt").write_text("ok", encoding="utf-8")
        return {"steps": 2, "cost_usd": 0.1}
    result = run_task(EvalTask("t", task_dir), fake_agent, tmp_path / "work")
    assert result.status == "solved"
    def no_fix(workspace, prompt): return {"steps": 1, "cost_usd": 0.0}
    failed = run_task(EvalTask("t", task_dir), no_fix, tmp_path / "work2")
    assert failed.status == "failed"


def test_summarize_reports_solution_rate():
    summary = summarize([type("R", (), {"status":"solved", "steps":2, "cost_usd":0.1})(), type("R", (), {"status":"failed", "steps":4, "cost_usd":0.3})()])
    assert summary["solved"] == 1
    assert summary["total"] == 2
    assert summary["solution_rate"] == 0.5
    assert summary["avg_steps"] == 3
