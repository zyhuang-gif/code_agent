"""Tests for eval/tasks_cmake_memory benchmark."""

import json
from pathlib import Path

from eval.run_eval import discover


def test_discovers_memory_eval_tasks():
    tasks = {task.id: task for task in discover(Path("eval/tasks_cmake_memory"))}

    assert "m01_without_memory" in tasks
    assert "m02_with_memory" in tasks
    assert all(task.profile.language == "cmake" for task in tasks.values())


def test_m01_has_no_repair_memory():
    """m01 repo 不应预置 repair_memory.jsonl。"""
    m01_repo = Path("eval/tasks_cmake_memory/m01_without_memory/repo")
    assert not (m01_repo / "repair_memory.jsonl").exists()


def test_m02_has_repair_memory():
    """m02 repo 预置 repair_memory.jsonl。"""
    m02_repo = Path("eval/tasks_cmake_memory/m02_with_memory/repo")
    assert (m02_repo / "repair_memory.jsonl").exists()


def test_m02_repair_memory_has_seed_case():
    """m02 的 repair_memory.jsonl 应包含 seed case。"""
    import json
    m02_repo = Path("eval/tasks_cmake_memory/m02_with_memory/repo")
    content = (m02_repo / "repair_memory.jsonl").read_text(encoding="utf-8")
    case = json.loads(content.strip())
    assert case["case_id"] == "abc12345"
    assert case["error_type"] == "missing_header"
    assert case["verification_status"] == "passed"


def test_memory_tasks_have_cmake_profile():
    tasks = discover(Path("eval/tasks_cmake_memory"))
    for task in tasks:
        assert task.profile.language == "cmake"
        assert "cmake" in task.profile.test_cmd


def test_memory_tasks_have_prompt_and_verify():
    for name in ("m01_without_memory", "m02_with_memory"):
        task_dir = Path(f"eval/tasks_cmake_memory/{name}")
        assert (task_dir / "prompt.md").exists()
        assert (task_dir / "verify.py").exists()
        assert (task_dir / "profile.yaml").exists()
        assert (task_dir / "repo" / "CMakeLists.txt").exists()


# ---------------------------------------------------------------------------
#  有/无 memory 信息量差异测试 —— 使用 fake eval harness
# ---------------------------------------------------------------------------


SEED_CASE_ID = "abc12345"


def _run_memory_task_with_fake_agent(tmp_path: Path, task_id: str, monkeypatch) -> dict:
    """Run a single tasks_cmake_memory task with a fake agent and return captured data.

    Monkeypatches the real_agent_factory's internal FakeLLMClient/FakeLoop so
    no real LLM calls are made.  Returns the captured prompt, trace content, and
    fix_report content.
    """
    from agent.profile import ProjectProfile
    import eval.run_eval as run_eval

    task_path = tmp_path / "task"
    task_repo = task_path / "repo"
    task_repo.mkdir(parents=True)

    # Copy fixture files
    import shutil
    fixture = Path(f"eval/tasks_cmake_memory/{task_id}/repo")
    shutil.copytree(fixture, task_repo, dirs_exist_ok=True)
    (task_path / "prompt.md").write_text(
        (Path(f"eval/tasks_cmake_memory/{task_id}/prompt.md")).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (task_path / "profile.yaml").write_text(
        (Path(f"eval/tasks_cmake_memory/{task_id}/profile.yaml")).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (task_path / "verify.py").write_text(
        (Path(f"eval/tasks_cmake_memory/{task_id}/verify.py")).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    captured: dict = {"prompt": "", "trace_events": [], "report": ""}

    class FakeLLMClient:
        def __init__(self, trace):
            pass

    class FakeLoop:
        def __init__(self, llm, tools):
            pass

        def run(self, prompt, ctx):
            captured["prompt"] = prompt
            (ctx.workspace / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\nproject(Dummy LANGUAGES CXX)\nadd_executable(app src/main.cpp src/add.cpp)\ntarget_include_directories(app PRIVATE include)\nenable_testing()\nadd_test(NAME app_runs COMMAND app)\n", encoding="utf-8")
            return type("Result", (), {
                "reason": "finished",
                "cost_usd": 0.0,
                "finish_summary": "done",
                "diff": "+target_include_directories(app PRIVATE include)",
            })()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    # Override the runner to return a fake CMake failure
    imported_module = monkeypatch
    workspace = task_path / "repo"
    from agent.profile import ProjectProfile

    agent = run_eval.real_agent_factory()(workspace, "Fix build", ProjectProfile(
        language="cmake",
        test_cmd="cmake -S . -B build -G 'MinGW Makefiles' && cmake --build build && ctest --test-dir build --output-on-failure",
        test_timeout=120,
        command_timeout=120,
    ))

    # Read trace
    work_dirs = list((task_path.parent / "workspace").glob("*.trace.jsonl")) if (task_path.parent / "workspace").exists() else []
    for td in work_dirs:
        if td.exists():
            for line in td.read_text(encoding="utf-8-sig").splitlines():
                try:
                    captured["trace_events"].append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Read fix_report from workspace
    run_dirs = []
    ws_root = Path("workspace")
    for d in ws_root.glob(f"{task_id}/run-*"):
        run_dirs.append(d)
    if run_dirs:
        latest = sorted(run_dirs)[-1]
        rp = latest / "fix_report.md"
        if rp.exists():
            captured["report"] = rp.read_text(encoding="utf-8")

    return captured


def test_m01_without_memory_prompt_has_no_seed_case(tmp_path: Path, monkeypatch):
    """无 memory 的 prompt 不应包含 seed case id。"""
    from agent.profile import ProjectProfile
    import eval.run_eval as run_eval

    workspace = tmp_path / "repo"
    workspace.mkdir()
    # Copy m01 fixture (no repair_memory.jsonl)
    import shutil
    fixture = Path("eval/tasks_cmake_memory/m01_without_memory/repo")
    shutil.copytree(fixture, workspace, dirs_exist_ok=True)

    captured_prompt = []

    class FakeLLMClient:
        def __init__(self, trace):
            pass

    class FakeLoop:
        def __init__(self, llm, tools):
            pass
        def run(self, prompt, ctx):
            captured_prompt.append(prompt)
            return type("Result", (), {"reason": "finished", "cost_usd": 0.0, "finish_summary": "done", "diff": ""})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    run_eval.real_agent_factory()(workspace, "Fix build", ProjectProfile(
        language="cmake",
        test_cmd="cmake -S . -B build -G 'MinGW Makefiles' && cmake --build build && ctest --test-dir build --output-on-failure",
        test_timeout=120,
        command_timeout=120,
    ))

    prompt = captured_prompt[0]
    assert "Relevant repair memory:" not in prompt
    assert SEED_CASE_ID not in prompt


def test_m02_with_memory_prompt_has_seed_case(tmp_path: Path, monkeypatch):
    """有 memory 的 prompt 应包含 Relevant repair memory 和 seed case id。"""
    from agent.profile import ProjectProfile
    import eval.run_eval as run_eval

    workspace = tmp_path / "repo"
    workspace.mkdir()
    import shutil
    fixture = Path("eval/tasks_cmake_memory/m02_with_memory/repo")
    shutil.copytree(fixture, workspace, dirs_exist_ok=True)

    captured_prompt = []
    captured_trace_events = []

    class FakeTrace:
        def __init__(self, path):
            self.path = path
            self.path.parent.mkdir(parents=True, exist_ok=True)

        def write(self, event):
            captured_trace_events.append(event)

        # dummy methods expected by LLMClient
        def llm_call(self, **kw): self.write({"t": "llm_call", **kw})
        def tool_exec(self, **kw): self.write({"t": "tool_exec", **kw})
        def run_summary(self, **kw): self.write({"t": "run_summary", **kw})

    class FakeLLMClient:
        def __init__(self, trace, **kwargs):
            self.trace = trace

    class FakeLoop:
        def __init__(self, llm, tools):
            pass
        def run(self, prompt, ctx):
            captured_prompt.append(prompt)
            (ctx.workspace / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.16)\nproject(Dummy LANGUAGES CXX)\n"
                "add_executable(app src/main.cpp src/add.cpp)\n"
                "target_include_directories(app PRIVATE include)\n"
                "enable_testing()\nadd_test(NAME app_runs COMMAND app)\n",
                encoding="utf-8",
            )
            return type("Result", (), {"reason": "finished", "cost_usd": 0.0, "finish_summary": "done", "diff": "+target_include_directories(app PRIVATE include)"})()

    monkeypatch.setattr("agent.trace.Trace", FakeTrace)
    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    run_eval.real_agent_factory()(workspace, "Fix build", ProjectProfile(
        language="cmake",
        test_cmd="cmake -S . -B build -G 'MinGW Makefiles' && cmake --build build && ctest --test-dir build --output-on-failure",
        test_timeout=120,
        command_timeout=120,
    ))

    prompt = captured_prompt[0]
    assert "Relevant repair memory:" in prompt
    assert SEED_CASE_ID in prompt

    # 验证 trace 包含 repair_memory_matches
    memory_events = [e for e in captured_trace_events if e.get("t") == "repair_memory_matches"]
    assert len(memory_events) >= 1
    assert len(memory_events[0]["matches"]) >= 1
    assert memory_events[0]["matches"][0]["case_id"] == SEED_CASE_ID


def test_m02_with_memory_fix_report_has_repair_memory_used(tmp_path: Path, monkeypatch):
    """有 memory 时 fix_report.md 必须包含 ## Repair Memory Used 和 seed case id。"""
    from agent.profile import ProjectProfile
    import eval.run_eval as run_eval

    workspace = tmp_path / "repo"
    workspace.mkdir()
    import shutil
    fixture = Path("eval/tasks_cmake_memory/m02_with_memory/repo")
    shutil.copytree(fixture, workspace, dirs_exist_ok=True)

    captured_report = []

    class FakeLLMClient:
        def __init__(self, trace):
            pass

    class FakeLoop:
        def __init__(self, llm, tools):
            pass
        def run(self, prompt, ctx):
            (ctx.workspace / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.16)\nproject(Dummy LANGUAGES CXX)\n"
                "add_executable(app src/main.cpp src/add.cpp)\n"
                "target_include_directories(app PRIVATE include)\n"
                "enable_testing()\nadd_test(NAME app_runs COMMAND app)\n",
                encoding="utf-8",
            )
            return type("Result", (), {"reason": "finished", "cost_usd": 0.0, "finish_summary": "done", "diff": "+target_include_directories(app PRIVATE include)"})()

    monkeypatch.setattr("agent.llm.LLMClient", FakeLLMClient)
    monkeypatch.setattr("agent.loop.AgentLoop", FakeLoop)

    run_eval.real_agent_factory()(workspace, "Fix build", ProjectProfile(
        language="cmake",
        test_cmd="cmake -S . -B build -G 'MinGW Makefiles' && cmake --build build && ctest --test-dir build --output-on-failure",
        test_timeout=120,
        command_timeout=120,
    ))

    report_path = workspace / "fix_report.md"
    assert report_path.exists(), f"fix_report.md not found at {report_path}"
    report = report_path.read_text(encoding="utf-8")
    assert "## Repair Memory Used" in report
    assert SEED_CASE_ID in report
