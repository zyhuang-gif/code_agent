from pathlib import Path
from eval.run_eval import EvalTask, discover, run_task, summarize


def make_task(task_dir: Path, answer: str = "bad") -> Path:
    repo = task_dir / "repo"
    repo.mkdir(parents=True)
    (repo / "answer.txt").write_text(answer, encoding="utf-8")
    (task_dir / "prompt.md").write_text("fix", encoding="utf-8")
    (task_dir / "verify.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if Path('answer.txt').read_text() == 'ok' else 1)\n",
        encoding="utf-8",
    )
    return task_dir


def test_run_eval_marks_solved_and_failed(tmp_path: Path):
    task_dir = make_task(tmp_path / "task")
    def fake_agent(workspace, prompt, profile):
        (workspace / "answer.txt").write_text("ok", encoding="utf-8")
        return {"steps": 2, "cost_usd": 0.1}
    result = run_task(discover(tmp_path)[0], fake_agent, tmp_path / "work")
    assert result.status == "solved"
    def no_fix(workspace, prompt, profile): return {"steps": 1, "cost_usd": 0.0}
    failed = run_task(discover(tmp_path)[0], no_fix, tmp_path / "work2")
    assert failed.status == "failed"


def test_discover_loads_task_profile(tmp_path: Path):
    task_dir = make_task(tmp_path / "t_profile")
    (task_dir / "profile.yaml").write_text(
        "language: python\n"
        "test_cmd: python -m pytest -q\n",
        encoding="utf-8",
    )

    [task] = discover(tmp_path)

    assert task.profile.language == "python"
    assert task.profile.test_cmd == "python -m pytest -q"


def test_run_task_passes_discovered_profile_to_agent(tmp_path: Path):
    task_dir = make_task(tmp_path / "t_profile")
    (task_dir / "profile.yaml").write_text(
        "language: python\n"
        "test_cmd: python -m pytest -q\n",
        encoding="utf-8",
    )
    received = []

    def fake_agent(workspace, prompt, profile):
        received.append(profile)
        (workspace / "answer.txt").write_text("ok", encoding="utf-8")
        return {"steps": 2, "cost_usd": 0.1}

    task = discover(tmp_path)[0]
    result = run_task(task, fake_agent, tmp_path / "work")

    assert result.status == "solved"
    assert received == [task.profile]


def test_summarize_reports_solution_rate():
    summary = summarize([type("R", (), {"status":"solved", "steps":2, "cost_usd":0.1})(), type("R", (), {"status":"failed", "steps":4, "cost_usd":0.3})()])
    assert summary["solved"] == 1
    assert summary["total"] == 2
    assert summary["solution_rate"] == 0.5
    assert summary["avg_steps"] == 3


def test_eval_main_without_fake_uses_injected_real_factory(tmp_path: Path, monkeypatch):
    task_dir = make_task(tmp_path / "tasks" / "t")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    called = []
    def real_factory():
        called.append(True)
        def agent(workspace, prompt, profile):
            (workspace / "answer.txt").write_text("ok", encoding="utf-8")
            return {"steps": 3, "cost_usd": 0.2}
        return agent

    from eval.run_eval import main
    code = main([str(task_dir.parent)], agent_factory=real_factory, work_root=tmp_path / "work")

    assert code == 0
    assert called == [True]


def test_eval_main_without_key_reports_error_instead_of_using_fake(tmp_path: Path, monkeypatch, capsys):
    tasks = tmp_path / "tasks"; tasks.mkdir()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from eval.run_eval import main

    code = main([str(tasks)], work_root=tmp_path / "work")

    captured = capsys.readouterr()
    assert code == 2
    assert "DEEPSEEK_API_KEY" in captured.err
