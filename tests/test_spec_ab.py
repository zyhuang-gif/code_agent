from pathlib import Path

import pytest

from eval.spec_ab import (
    PROMPT_INJECTION,
    VARIANTS,
    build_agentspec_command,
    cleanup_agentspec_side_outputs,
    render_minimal_agents_md,
)


def test_variants_define_baseline_minimal_and_full():
    assert list(VARIANTS) == ["baseline", "agentspec-minimal", "agentspec-full"]
    assert VARIANTS["baseline"].requires_agentspec is False
    assert VARIANTS["baseline"].minimal is False
    assert VARIANTS["agentspec-minimal"].requires_agentspec is True
    assert VARIANTS["agentspec-minimal"].minimal is True
    assert VARIANTS["agentspec-full"].requires_agentspec is True
    assert VARIANTS["agentspec-full"].minimal is False
    assert PROMPT_INJECTION == "There is an AGENTS.md at repo root. Read it before you start."


def test_build_agentspec_command_uses_uv_project_and_no_llm(tmp_path: Path):
    work_root = tmp_path / "work"
    project = Path("D:/source/agent/agentspec")

    cmd = build_agentspec_command(work_root, project)

    assert cmd == [
        "uv",
        "run",
        "--project",
        str(project),
        "agentspec",
        "scan",
        str(work_root),
        "--write",
        "--force",
        "--no-llm",
    ]


def test_render_minimal_agents_md_keeps_only_commands_and_safety():
    full = """# AGENTS.md

<!-- agentspec:managed name="overview" -->
## Project Overview
Python
<!-- agentspec:end name="overview" -->

<!-- agentspec:managed name="architecture-notes" -->
## Architecture Notes
Lots of architecture.
<!-- agentspec:end name="architecture-notes" -->

<!-- agentspec:managed name="commands" -->
## Commands
- Use `pytest`.
<!-- agentspec:end name="commands" -->

<!-- agentspec:managed name="safety" -->
## Safety
- Do not run destructive commands.
<!-- agentspec:end name="safety" -->
"""

    minimal = render_minimal_agents_md(full)

    assert minimal.startswith("# AGENTS.md\n")
    assert "## Commands" in minimal
    assert "Use `pytest`" in minimal
    assert "## Safety" in minimal
    assert "destructive" in minimal
    assert "Project Overview" not in minimal
    assert "Architecture Notes" not in minimal


def test_render_minimal_agents_md_requires_both_blocks():
    full = """# AGENTS.md
<!-- agentspec:managed name="commands" -->
## Commands
<!-- agentspec:end name="commands" -->
"""

    with pytest.raises(ValueError, match="commands and safety"):
        render_minimal_agents_md(full)


def test_cleanup_agentspec_side_outputs_removes_only_generated_side_outputs(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("keep", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("remove", encoding="utf-8")
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "source-map.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_text("print('ok')\n", encoding="utf-8")

    cleanup_agentspec_side_outputs(tmp_path)

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".agent").exists()
    assert (tmp_path / "src" / "code.py").exists()


import subprocess
import sys

from agent.profile import ProjectProfile
from eval.spec_ab import (
    AgentspecGeneration,
    SpecRunSkipped,
    run_agentspec_for_variant,
    variant_agent,
)


def test_run_agentspec_for_full_invokes_cli_and_keeps_generated_agents(tmp_path: Path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    project = Path("D:/source/agent/agentspec")
    calls = []

    def fake_run(cmd, text, capture_output, timeout):
        calls.append((cmd, text, capture_output, timeout))
        (work_root / "AGENTS.md").write_text("# AGENTS.md\n\nfull\n", encoding="utf-8")
        (work_root / "CLAUDE.md").write_text("side output\n", encoding="utf-8")
        (work_root / ".agent").mkdir()
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    generation = run_agentspec_for_variant(
        work_root,
        VARIANTS["agentspec-full"],
        agentspec_project=project,
        timeout=77,
        run=fake_run,
    )

    assert calls == [(build_agentspec_command(work_root, project), True, True, 77)]
    assert generation.variant == "agentspec-full"
    assert generation.agents_path == work_root / "AGENTS.md"
    assert (work_root / "AGENTS.md").read_text(encoding="utf-8") == "# AGENTS.md\n\nfull\n"
    assert not (work_root / "CLAUDE.md").exists()
    assert not (work_root / ".agent").exists()


def test_run_agentspec_for_minimal_trims_generated_agents(tmp_path: Path):
    work_root = tmp_path / "work"
    work_root.mkdir()

    def fake_run(cmd, text, capture_output, timeout):
        (work_root / "AGENTS.md").write_text(
            """# AGENTS.md

<!-- agentspec:managed name="overview" -->
## Project Overview
omit
<!-- agentspec:end name="overview" -->

<!-- agentspec:managed name="commands" -->
## Commands
- Use `pytest`.
<!-- agentspec:end name="commands" -->

<!-- agentspec:managed name="safety" -->
## Safety
- Ask before destructive commands.
<!-- agentspec:end name="safety" -->
""",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    run_agentspec_for_variant(
        work_root,
        VARIANTS["agentspec-minimal"],
        agentspec_project=Path("D:/source/agent/agentspec"),
        timeout=60,
        run=fake_run,
    )

    text = (work_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Commands" in text
    assert "## Safety" in text
    assert "Project Overview" not in text


def test_run_agentspec_failure_raises_skipped_run(tmp_path: Path):
    work_root = tmp_path / "work"
    work_root.mkdir()

    def fake_run(cmd, text, capture_output, timeout):
        return subprocess.CompletedProcess(cmd, 23, stdout="out", stderr="boom")

    with pytest.raises(SpecRunSkipped) as excinfo:
        run_agentspec_for_variant(
            work_root,
            VARIANTS["agentspec-full"],
            agentspec_project=Path("D:/source/agent/agentspec"),
            timeout=60,
            run=fake_run,
        )

    assert "AgentSpec generation failed" in str(excinfo.value)
    assert excinfo.value.stdout == "out"
    assert excinfo.value.stderr == "boom"


def test_run_agentspec_timeout_raises_skipped_run(tmp_path: Path):
    work_root = tmp_path / "work"
    work_root.mkdir()

    def fake_run(cmd, text, capture_output, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout, output="partial", stderr="slow")

    with pytest.raises(SpecRunSkipped) as excinfo:
        run_agentspec_for_variant(
            work_root,
            VARIANTS["agentspec-full"],
            agentspec_project=Path("D:/source/agent/agentspec"),
            timeout=12,
            run=fake_run,
        )

    assert "timed out" in str(excinfo.value)
    assert excinfo.value.stdout == "partial"
    assert excinfo.value.stderr == "slow"


def test_variant_agent_baseline_removes_stale_agents_and_keeps_prompt(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("stale", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("stale", encoding="utf-8")
    (tmp_path / ".agent").mkdir()
    calls = []

    def base_agent(workspace, prompt, profile):
        calls.append((workspace, prompt, (workspace / "AGENTS.md").exists(), (workspace / "CLAUDE.md").exists()))
        return {"steps": 1, "cost_usd": 0.0}

    wrapped = variant_agent(base_agent, VARIANTS["baseline"], generator=None)
    meta = wrapped(tmp_path, "fix this", ProjectProfile())

    assert meta == {"steps": 1, "cost_usd": 0.0}
    assert calls == [(tmp_path, "fix this", False, False)]
    assert not (tmp_path / ".agent").exists()


def test_variant_agent_generates_agents_and_injects_prompt(tmp_path: Path):
    calls = []

    def generator(workspace, variant):
        (workspace / "AGENTS.md").write_text("# AGENTS.md\n", encoding="utf-8")
        return AgentspecGeneration(variant=variant.name, agents_path=workspace / "AGENTS.md", stdout="ok", stderr="")

    def base_agent(workspace, prompt, profile):
        calls.append((workspace, prompt, (workspace / "AGENTS.md").exists()))
        return {"steps": 2, "cost_usd": 0.1}

    wrapped = variant_agent(base_agent, VARIANTS["agentspec-full"], generator=generator)
    meta = wrapped(tmp_path, "fix this", ProjectProfile())

    assert meta == {"steps": 2, "cost_usd": 0.1}
    assert calls == [(tmp_path, f"fix this\n\n{PROMPT_INJECTION}", True)]


from eval.spec_ab import GroupRun, SkippedRun, load_tasks, run_spec_ab


def make_tiny_eval_task(task_dir: Path) -> Path:
    repo = task_dir / "repo"
    repo.mkdir(parents=True)
    (repo / "greeting.py").write_text("def greet(name):\n    return 'bad'\n", encoding="utf-8")
    # fake_agent in run_eval.py reads CMakeLists.txt unconditionally (line 278);
    # provide a minimal one so integration tests pass without touching run_eval.py.
    (repo / "CMakeLists.txt").write_text("", encoding="utf-8")
    (task_dir / "prompt.md").write_text("fix greeting", encoding="utf-8")
    (task_dir / "verify.py").write_text(
        "import greeting\n"
        "raise SystemExit(0 if greeting.greet('Ada') == 'Hello, Ada!' else 1)\n",
        encoding="utf-8",
    )
    return task_dir


def test_load_tasks_filters_by_task_id(tmp_path: Path):
    make_tiny_eval_task(tmp_path / "tasks" / "keep")
    make_tiny_eval_task(tmp_path / "tasks" / "drop")

    tasks = load_tasks([tmp_path / "tasks"], task_ids={"keep"})

    assert [task.id for task in tasks] == ["keep"]


def test_run_spec_ab_runs_all_groups_repeats_and_isolated_workspaces(tmp_path: Path):
    make_tiny_eval_task(tmp_path / "tasks" / "hello")
    calls = []

    def generator(workspace, variant):
        (workspace / "AGENTS.md").write_text(f"# {variant.name}\n", encoding="utf-8")
        return AgentspecGeneration(variant=variant.name, agents_path=workspace / "AGENTS.md")

    def solving_agent(workspace, prompt, profile):
        calls.append((workspace, prompt, (workspace / "AGENTS.md").exists()))
        (workspace / "greeting.py").write_text("def greet(name):\n    return f'Hello, {name}!'\n", encoding="utf-8")
        return {"steps": 3, "cost_usd": 0.25, "reason": "fixed"}

    runs = run_spec_ab(
        [tmp_path / "tasks"],
        groups=["baseline", "agentspec-minimal", "agentspec-full"],
        repeat=2,
        agent=solving_agent,
        work_root=tmp_path / "work",
        generator=generator,
    )

    assert list(runs) == ["baseline", "agentspec-minimal", "agentspec-full"]
    assert all(isinstance(group_run, GroupRun) for group_run in runs.values())
    assert {group: len(group_run.results) for group, group_run in runs.items()} == {
        "baseline": 2,
        "agentspec-minimal": 2,
        "agentspec-full": 2,
    }
    assert all(not group_run.skipped for group_run in runs.values())
    baseline_calls = [call for call in calls if call[0].parts[-3] == "baseline"]
    treated_calls = [call for call in calls if call[0].parts[-3] != "baseline"]
    assert all(call[1] == "fix greeting" and call[2] is False for call in baseline_calls)
    assert all(call[1].endswith(PROMPT_INJECTION) and call[2] is True for call in treated_calls)
    assert (tmp_path / "work" / "agentspec-full" / "hello" / "run-2" / "AGENTS.md").exists()


def test_run_spec_ab_records_generation_skip_without_result(tmp_path: Path):
    make_tiny_eval_task(tmp_path / "tasks" / "hello")
    calls = []

    def generator(workspace, variant):
        raise SpecRunSkipped("AgentSpec generation failed for test", stdout="out", stderr="err")

    def solving_agent(workspace, prompt, profile):
        calls.append((workspace, prompt))
        (workspace / "greeting.py").write_text("def greet(name):\n    return f'Hello, {name}!'\n", encoding="utf-8")
        return {"steps": 1, "cost_usd": 0.0}

    runs = run_spec_ab(
        [tmp_path / "tasks"],
        groups=["agentspec-full"],
        repeat=1,
        agent=solving_agent,
        work_root=tmp_path / "work",
        generator=generator,
    )

    group_run = runs["agentspec-full"]
    assert group_run.results == []
    assert len(group_run.skipped) == 1
    assert isinstance(group_run.skipped[0], SkippedRun)
    assert group_run.skipped[0].task_id == "hello"
    assert group_run.skipped[0].run_index == 1
    assert "generation failed" in group_run.skipped[0].reason
    assert group_run.skipped[0].stdout == "out"
    assert group_run.skipped[0].stderr == "err"
    assert calls == []


from eval.run_eval import EvalResult
from eval.spec_ab import render_markdown_report, summarize_groups


def test_summarize_groups_reports_mean_std_and_skips():
    runs = {
        "baseline": GroupRun(
            group="baseline",
            results=[
                EvalResult("t1", "solved", 2, 0.10, trace_path="trace-a.jsonl", workspace_path="w1"),
                EvalResult("t1", "failed", 4, 0.30, trace_path="trace-b.jsonl", workspace_path="w2"),
                EvalResult("t2", "solved", 6, 0.50, trace_path="trace-c.jsonl", workspace_path="w3"),
            ],
            skipped=[
                SkippedRun("baseline", "t2", 2, "w4", "skip reason", stdout="out", stderr="err"),
            ],
        )
    }

    summary = summarize_groups(runs)

    group = summary["groups"]["baseline"]
    assert group["base_summary"]["total"] == 3
    assert group["skipped_runs"] == 1
    assert group["metrics"]["pass_rate"]["mean"] == pytest.approx(2 / 3)
    assert group["metrics"]["pass_rate"]["std"] == pytest.approx(0.4714045207)
    assert group["metrics"]["steps"]["mean"] == pytest.approx(4.0)
    assert group["metrics"]["steps"]["std"] == pytest.approx(1.6329931618)
    assert group["tasks"]["t1"]["pass_rate"]["mean"] == 0.5
    assert group["tasks"]["t1"]["pass_rate"]["std"] == 0.5
    assert group["tasks"]["t1"]["steps"]["mean"] == 3.0
    assert group["tasks"]["t1"]["cost_usd"]["mean"] == pytest.approx(0.2)
    assert group["tasks"]["t2"]["skipped"] == 1
    assert group["trace_samples"] == ["trace-a.jsonl"]
    assert group["skips"][0]["stderr"] == "err"


def test_render_markdown_report_includes_noise_warning_per_task_and_traces():
    summary = summarize_groups(
        {
            "agentspec-full": GroupRun(
                group="agentspec-full",
                results=[
                    EvalResult("task-a", "solved", 3, 0.2, trace_path="trace-a.jsonl", workspace_path="w1"),
                ],
                skipped=[],
            )
        }
    )

    markdown = render_markdown_report(summary)

    assert "# AgentSpec A/B Evaluation Report" in markdown
    assert "LLM evals are noisy" in markdown
    assert "never draw conclusions from a single solution_rate" in markdown
    assert "agentspec-full" in markdown
    assert "task-a" in markdown
    assert "trace-a.jsonl" in markdown
    assert "mean±std" in markdown


import json

from eval.spec_ab import default_task_roots, main


def test_default_task_roots_are_real_and_swebench():
    roots = default_task_roots(Path("eval"))

    assert roots == [Path("eval") / "tasks_real", Path("eval") / "tasks_swebench"]


def test_main_without_fake_requires_deepseek_key(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    make_tiny_eval_task(tmp_path / "tasks" / "hello")

    code = main(
        ["--tasks", str(tmp_path / "tasks"), "--groups", "baseline"],
        work_root=tmp_path / "work",
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "DEEPSEEK_API_KEY" in captured.err


def test_main_fake_writes_json_and_markdown_for_all_groups(tmp_path: Path, monkeypatch):
    make_tiny_eval_task(tmp_path / "tasks" / "hello")
    summary_path = tmp_path / "summary.json"
    report_path = tmp_path / "report.md"

    def generator(workspace, variant):
        (workspace / "AGENTS.md").write_text(
            """# AGENTS.md

<!-- agentspec:managed name="commands" -->
## Commands
- Use `python`.
<!-- agentspec:end name="commands" -->

<!-- agentspec:managed name="safety" -->
## Safety
- Ask before destructive commands.
<!-- agentspec:end name="safety" -->
""",
            encoding="utf-8",
        )
        return AgentspecGeneration(variant=variant.name, agents_path=workspace / "AGENTS.md")

    code = main(
        [
            "--fake",
            "--tasks",
            str(tmp_path / "tasks"),
            "--repeat",
            "1",
            "--groups",
            "baseline",
            "agentspec-minimal",
            "agentspec-full",
            "--json-summary",
            str(summary_path),
            "--markdown-report",
            str(report_path),
        ],
        work_root=tmp_path / "work",
        generator=generator,
    )

    assert code == 0
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert set(data["groups"]) == {"baseline", "agentspec-minimal", "agentspec-full"}
    assert data["groups"]["baseline"]["tasks"]["hello"]["runs"] == 1
    assert data["groups"]["agentspec-minimal"]["tasks"]["hello"]["runs"] == 1
    assert "LLM evals are noisy" in report_path.read_text(encoding="utf-8")
    assert not (tmp_path / "tasks" / "hello" / "repo" / "AGENTS.md").exists()
    assert not (tmp_path / "work" / "baseline" / "hello" / "run-1" / "AGENTS.md").exists()
    assert (tmp_path / "work" / "agentspec-minimal" / "hello" / "run-1" / "AGENTS.md").exists()


def test_main_task_id_filters_fake_run(tmp_path: Path):
    make_tiny_eval_task(tmp_path / "tasks" / "keep")
    make_tiny_eval_task(tmp_path / "tasks" / "drop")

    code = main(
        [
            "--fake",
            "--tasks",
            str(tmp_path / "tasks"),
            "--task-id",
            "keep",
            "--groups",
            "baseline",
        ],
        work_root=tmp_path / "work",
    )

    assert code == 0
    assert (tmp_path / "work" / "baseline" / "keep" / "run-1").exists()
    assert not (tmp_path / "work" / "baseline" / "drop").exists()


def test_spec_ab_script_imports_when_executed_by_path(tmp_path: Path):
    """spec_ab.py must bootstrap sys.path like run_eval.py for direct execution."""
    root = Path.cwd().resolve()
    eval_path = root / "eval" / "spec_ab.py"
    # 用子进程直接执行脚本，模拟真实终端 python eval\spec_ab.py 场景。
    # 子进程不受 pytest.ini pythonpath 影响，能忠实再现 bug。
    proc = subprocess.run(
        [sys.executable, str(eval_path), "--help"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    # 修复后应返回 0，表示 bootstrap 正确工作
    assert proc.returncode == 0, f"stderr: {proc.stderr}"


def test_main_fake_default_generator_calls_agentspec_for_bc_groups(tmp_path: Path, monkeypatch):
    """B/C groups must use default_generator (real AgentSpec CLI), even with --fake."""
    make_tiny_eval_task(tmp_path / "tasks" / "hello")
    calls = []

    def fake_run_agentspec(workspace, variant, *, agentspec_project, timeout):
        calls.append((workspace, variant))
        (workspace / "AGENTS.md").write_text(
            """# AGENTS.md

<!-- agentspec:managed name="commands" -->
## Commands
- Use `python`.
<!-- agentspec:end name="commands" -->

<!-- agentspec:managed name="safety" -->
## Safety
- Ask before destructive commands.
<!-- agentspec:end name="safety" -->
""",
            encoding="utf-8",
        )
        return AgentspecGeneration(variant=variant.name, agents_path=workspace / "AGENTS.md")

    monkeypatch.setattr("eval.spec_ab.run_agentspec_for_variant", fake_run_agentspec)

    code = main(
        [
            "--fake",
            "--tasks",
            str(tmp_path / "tasks"),
            "--groups",
            "baseline",
            "agentspec-minimal",
            "agentspec-full",
        ],
        work_root=tmp_path / "work",
    )

    assert code == 0
    # B 和 C 组各调了一次 run_agentspec_for_variant
    called_variants = {call[1].name for call in calls}
    assert called_variants == {"agentspec-minimal", "agentspec-full"}
    # A 组 workspace 没有 AGENTS.md
    assert not (tmp_path / "work" / "baseline" / "hello" / "run-1" / "AGENTS.md").exists()
    # B/C 组 workspace 有 AGENTS.md
    assert (tmp_path / "work" / "agentspec-minimal" / "hello" / "run-1" / "AGENTS.md").exists()
    assert (tmp_path / "work" / "agentspec-full" / "hello" / "run-1" / "AGENTS.md").exists()
