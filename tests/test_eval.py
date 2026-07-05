from pathlib import Path
import os
import shutil
import stat
import runpy
import sys
import ast
import pytest
from eval.run_eval import EvalTask, discover, real_agent_factory, run_task, summarize


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


def test_run_task_runs_setup_cmd_before_agent_with_injected_runner(tmp_path: Path):
    task_dir = make_task(tmp_path / "t_setup")
    (task_dir / "profile.yaml").write_text(
        "setup_cmd: python -m pip install -e .\n"
        "setup_needs_network: true\n",
        encoding="utf-8",
    )
    events = []

    def command_runner(cmd, cwd=None, timeout=None, allow_network=False):
        events.append(("setup", cmd, cwd, timeout, allow_network))
        assert cwd == tmp_path / "work"
        (cwd / "installed.txt").write_text("yes", encoding="utf-8")
        return {"exit_code": 0, "stdout": "installed\n", "stderr": ""}

    def fake_agent(workspace, prompt, profile):
        events.append(("agent", (workspace / "installed.txt").read_text(encoding="utf-8")))
        (workspace / "answer.txt").write_text("ok", encoding="utf-8")
        return {"steps": 1, "cost_usd": 0.0}

    task = discover(tmp_path)[0]
    result = run_task(task, fake_agent, tmp_path / "work", command_runner=command_runner)

    assert result.status == "solved"
    assert events == [
        ("setup", "python -m pip install -e .", tmp_path / "work", 300, True),
        ("agent", "yes"),
    ]


def test_run_task_raises_when_setup_cmd_fails(tmp_path: Path):
    task_dir = make_task(tmp_path / "t_setup")
    (task_dir / "profile.yaml").write_text("setup_cmd: install deps\n", encoding="utf-8")

    def command_runner(cmd, cwd=None, timeout=None, allow_network=False):
        return {"exit_code": 23, "stdout": "", "stderr": "boom"}

    def fake_agent(workspace, prompt, profile):
        raise AssertionError("agent should not run after setup failure")

    task = discover(tmp_path)[0]

    with pytest.raises(RuntimeError, match="setup_cmd failed"):
        run_task(task, fake_agent, tmp_path / "work", command_runner=command_runner)

def test_robust_rmtree_removes_readonly_files(tmp_path: Path):
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    ordinary_file = ordinary / "object"
    ordinary_file.write_text("readonly", encoding="utf-8")
    os.chmod(ordinary_file, stat.S_IREAD)
    try:
        with pytest.raises(PermissionError):
            shutil.rmtree(ordinary)
    finally:
        if ordinary_file.exists():
            os.chmod(ordinary_file, stat.S_IWRITE)
        shutil.rmtree(ordinary, ignore_errors=True)

    target = tmp_path / "target"
    target.mkdir()
    target_file = target / "object"
    target_file.write_text("readonly", encoding="utf-8")
    os.chmod(target_file, stat.S_IREAD)

    from eval import run_eval

    run_eval.robust_rmtree(target)

    assert not target.exists()
def test_run_eval_script_imports_when_executed_by_path(monkeypatch):
    root = Path.cwd().resolve()
    eval_dir = root / "eval"
    filtered = []
    for entry in sys.path:
        if not entry:
            continue
        try:
            if Path(entry).resolve() == root:
                continue
        except OSError:
            pass
        filtered.append(entry)
    monkeypatch.setattr(sys, "path", [str(eval_dir), *filtered])

    runpy.run_path(str(eval_dir / "run_eval.py"), run_name="eval_script_import_test")

def test_discover_finds_tested_eval_tasks_with_profiles():
    tasks = {task.id: task for task in discover(Path("eval/tasks"))}

    assert tasks["t04_fix_tested_bug"].profile.test_cmd == "python -m pytest -q"
    assert tasks["t05_multifile"].profile.test_cmd == "python -m pytest -q"


def test_discover_finds_hard_eval_tasks_with_profiles():
    tasks = {task.id: task for task in discover(Path("eval/tasks_hard"))}

    assert set(tasks) == {
        "h1_locate_among_distractors",
        "h2_cross_file_rootcause",
        "h3_multi_case",
        "h4_extend_dispatcher",
    }
    assert all(task.profile.test_cmd for task in tasks.values())
def test_discover_finds_real_click_eval_tasks_with_profiles():
    tasks = {task.id: task for task in discover(Path("eval/tasks_real"))}

    assert set(tasks) == {
        "click_t1_short_help_truncation",
        "click_t2_option_prefix_parsing",
        "click_t3_preserve_paragraph_wrapping",
    }
    assert all(task.profile.setup_cmd == "python -m pip install -e ." for task in tasks.values())
    assert all(task.profile.test_cmd for task in tasks.values())
    assert all((task.path / "repo" / "src" / "click").is_dir() for task in tasks.values())

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

def test_real_agent_factory_uses_task_profile_and_writes_trace_outside_workspace(tmp_path: Path, monkeypatch):
    task_dir = make_task(tmp_path / "tasks" / "t_profile")
    (task_dir / "profile.yaml").write_text(
        "language: python\n"
        "test_cmd: python -m pytest -q\n",
        encoding="utf-8",
    )
    captured = {}

    class FakeLLMClient:
        def __init__(self, trace):
            captured["llm_trace_path"] = trace.path

    class FakeLoop:
        def __init__(self, llm, tools):
            pass

        def run(self, prompt, ctx):
            captured["profile"] = ctx.profile
            captured["trace_path"] = ctx.trace.path
            ctx.trace.write({"t": "fake_loop"})
            (ctx.workspace / "answer.txt").write_text("ok", encoding="utf-8")
            return type("Result", (), {"reason": "finished", "cost_usd": 0.25})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    task = discover(task_dir.parent)[0]
    work_root = tmp_path / "work" / task.id
    result = run_task(task, real_agent_factory(), work_root)

    assert result.status == "solved"
    assert result.cost_usd == 0.25
    assert captured["profile"] is task.profile
    assert captured["trace_path"] == work_root.parent / f"{work_root.name}.trace.jsonl"
    assert captured["llm_trace_path"] == captured["trace_path"]
    assert captured["trace_path"].exists()
    assert not (work_root / "trace.jsonl").exists()

def test_eval_main_without_key_reports_error_instead_of_using_fake(tmp_path: Path, monkeypatch, capsys):
    tasks = tmp_path / "tasks"; tasks.mkdir()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from eval.run_eval import main

    code = main([str(tasks)], work_root=tmp_path / "work")

    captured = capsys.readouterr()
    assert code == 2
    assert "DEEPSEEK_API_KEY" in captured.err
def test_eval_main_multi_uses_multi_agent_factory(tmp_path, monkeypatch):
    task_dir = tmp_path / "tasks" / "t"
    repo = task_dir / "repo"
    repo.mkdir(parents=True)
    (repo / "answer.txt").write_text("bad", encoding="utf-8")
    (task_dir / "prompt.md").write_text("fix", encoding="utf-8")
    (task_dir / "verify.py").write_text(
        "from pathlib import Path\nraise SystemExit(0 if Path('answer.txt').read_text()=='ok' else 1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    called = []

    def multi_factory():
        called.append(True)

        def agent(workspace, prompt, profile):
            (workspace / "answer.txt").write_text("ok", encoding="utf-8")
            return {"steps": 5, "cost_usd": 0.3}

        return agent

    from eval.run_eval import main

    code = main([str(task_dir.parent), "--multi"], agent_factory=multi_factory, work_root=tmp_path / "work")
    assert code == 0
    assert called == [True]

def test_eval_main_repeat_reports_per_task_pass_rate_and_overall_stats(tmp_path, monkeypatch, capsys):
    task_dir = make_task(tmp_path / "tasks" / "flaky")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def factory():
        def agent(workspace, prompt, profile):
            calls.append(workspace)
            if len(calls) == 1:
                (workspace / "answer.txt").write_text("ok", encoding="utf-8")
            return {"steps": len(calls), "cost_usd": 0.1 * len(calls)}

        return agent

    from eval.run_eval import main

    code = main([str(task_dir.parent), "--repeat", "2"], agent_factory=factory, work_root=tmp_path / "work")

    summary = ast.literal_eval(capsys.readouterr().out.strip())
    assert code == 1
    assert [path.name for path in calls] == ["run-1", "run-2"]
    assert calls[0].parent == tmp_path / "work" / "flaky"
    assert summary["tasks"]["flaky"]["pass_rate"] == 0.5
    assert summary["mean_solution_rate"] == 0.5
    assert summary["std_solution_rate"] == 0.0

def test_real_agent_factory_configures_llm_from_environment(tmp_path, monkeypatch):
    from agent.profile import ProjectProfile
    from eval.run_eval import real_agent_factory

    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-prover")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "high")
    captured = {}

    class FakeLLMClient:
        def __init__(self, **kwargs):
            captured["llm_kwargs"] = kwargs

    class FakeLoop:
        def __init__(self, llm, tools):
            pass

        def run(self, prompt, ctx):
            return type("Result", (), {"reason": "finished", "cost_usd": 0.0})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    workspace = tmp_path / "repo"
    workspace.mkdir()
    real_agent_factory()(workspace, "fix", ProjectProfile())

    assert captured["llm_kwargs"]["model"] == "deepseek-prover"
    assert captured["llm_kwargs"]["reasoning_effort"] == "high"


def test_multi_agent_factory_configures_role_llms_from_environment(tmp_path, monkeypatch):
    from agent.profile import ProjectProfile
    from eval.run_eval import multi_agent_factory

    monkeypatch.setenv("DEEPSEEK_MODEL", "coder-model")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "coder-effort")
    monkeypatch.setenv("PLANNER_MODEL", "planner-model")
    monkeypatch.setenv("PLANNER_REASONING_EFFORT", "planner-effort")
    monkeypatch.setenv("REVIEWER_MODEL", "reviewer-model")
    monkeypatch.setenv("REVIEWER_REASONING_EFFORT", "reviewer-effort")
    llm_kwargs = []
    orchestrator_kwargs = {}

    class FakeLLMClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            llm_kwargs.append(kwargs)

    class FakeOrchestrator:
        def __init__(self, llm, tools, **kwargs):
            orchestrator_kwargs["llm"] = llm
            orchestrator_kwargs.update(kwargs)

        def run(self, prompt, ctx):
            return type("Result", (), {"steps": 0, "cost_usd": 0.0, "reason": "finished"})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.multi_agent.MultiAgentOrchestrator", FakeOrchestrator)

    workspace = tmp_path / "repo"
    workspace.mkdir()
    multi_agent_factory()(workspace, "fix", ProjectProfile())

    assert llm_kwargs[0]["model"] == "coder-model"
    assert llm_kwargs[0]["reasoning_effort"] == "coder-effort"
    assert orchestrator_kwargs["planner_llm"].kwargs["model"] == "planner-model"
    assert orchestrator_kwargs["planner_llm"].kwargs["reasoning_effort"] == "planner-effort"
    assert orchestrator_kwargs["reviewer_llm"].kwargs["model"] == "reviewer-model"
    assert orchestrator_kwargs["reviewer_llm"].kwargs["reasoning_effort"] == "reviewer-effort"

def test_multi_agent_factory_returns_orchestrator_steps_and_cost(tmp_path, monkeypatch):
    from agent.profile import ProjectProfile
    from eval.run_eval import multi_agent_factory

    captured = {}

    class FakeLLMClient:
        def __init__(self, trace):
            captured["llm_trace_path"] = trace.path

    class FakeOrchestrator:
        def __init__(self, llm, tools):
            pass

        def run(self, prompt, ctx):
            captured["ctx_steps"] = ctx.budget.steps
            return type("Result", (), {"steps": 7, "cost_usd": 1.25, "reason": "finished"})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.multi_agent.MultiAgentOrchestrator", FakeOrchestrator)

    workspace = tmp_path / "repo"
    workspace.mkdir()
    result = multi_agent_factory()(workspace, "fix", ProjectProfile())

    assert captured["ctx_steps"] == 0
    assert result["steps"] == 7
    assert result["cost_usd"] == 1.25


def test_real_agent_factory_enriches_cmake_prompt(tmp_path: Path, monkeypatch):
    from agent.profile import ProjectProfile
    import eval.run_eval as run_eval

    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "CMakeLists.txt").write_text("add_executable(app main.cpp)\n", encoding="utf-8")
    captured = {}

    class FakeLLMClient:
        def __init__(self, trace, **kwargs):
            pass

    class FakeLoop:
        def __init__(self, llm, tools):
            pass

        def run(self, prompt, ctx):
            captured["prompt"] = prompt
            return type("Result", (), {"cost_usd": 0.0, "reason": "finished"})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    profile = ProjectProfile(language="cmake", test_cmd="cmake -S . -B build")
    run_eval.real_agent_factory()(workspace, "Fix build", profile)

    assert "CMake project context:" in captured["prompt"]
    assert "Build error summary:" in captured["prompt"]


def test_discovers_cmake_tasks_with_cmake_profile():
    tasks = discover(Path("eval/tasks_cmake"))

    assert len(tasks) >= 5
    assert all(task.profile.language == "cmake" for task in tasks)
    assert all("cmake -S . -B build" in task.profile.test_cmd for task in tasks)
