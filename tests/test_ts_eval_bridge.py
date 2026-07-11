from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from agent.profile import ProjectProfile
from eval.run_eval import discover, main, robust_rmtree, run_task
from eval.ts_bridge import (
    TsBridgeError,
    TsProcessResult,
    default_ts_command_runner,
    typescript_agent_factory,
)


def _managed_result(command: list[str], *, exit_code: int = 0, overrides: dict | None = None) -> TsProcessResult:
    source = Path(command[command.index("--repo") + 1]).resolve()
    run_root = Path(command[command.index("--run-root") + 1]).resolve()
    run_directory = run_root / "session-1"
    workspace = run_directory / "repository"
    artifacts = run_directory / "artifacts"
    workspace.mkdir(parents=True)
    artifacts.mkdir()
    result = {
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
    (artifacts / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    (artifacts / "verification.json").write_text("{}\n", encoding="utf-8")
    Path(result["resultPath"]).write_text(json.dumps(result), encoding="utf-8")
    return TsProcessResult(exit_code, json.dumps(result), "")


def test_typescript_bridge_builds_fixed_argv_and_maps_managed_result(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()
    captured = {}

    def runner(command, *, cwd, timeout):
        captured.update(command=command, cwd=cwd, timeout=timeout)
        profile_path = Path(command[command.index("--profile") + 1])
        captured["profile"] = json.loads(profile_path.read_text(encoding="utf-8"))
        return _managed_result(command, exit_code=1)

    agent = typescript_agent_factory(
        budget_steps=7,
        fake=True,
        allow_unsafe_host_shell=True,
        cli_root=Path(__file__).resolve().parents[1],
        timeout_seconds=91,
        command_runner=runner,
    )
    meta = agent(source, "fix this", ProjectProfile(language="python", test_cmd="pytest -q"))

    command = captured["command"]
    assert command[0].lower().endswith(("node", "node.exe"))
    assert "--result-json" in command
    assert "--json" not in command
    assert "--fake" in command
    assert "fix this" not in command
    prompt_path = Path(command[command.index("--task-file") + 1])
    assert prompt_path.read_text(encoding="utf-8") == "fix this"
    assert command[command.index("--permission-mode") + 1] == "bypass"
    assert command[command.index("--max-steps") + 1] == "7"
    assert captured["timeout"] == 91
    assert captured["cwd"] == Path(__file__).resolve().parents[1]
    assert captured["profile"]["test_cmd"] == "pytest -q"
    assert meta["steps"] == 3
    assert meta["reason"] == "budget_exceeded"
    assert meta["cost_usd"] == pytest.approx((40 * 0.0028 + 60 * 0.14 + 20 * 0.28) / 1_000_000)
    assert Path(meta["workspace_path"]).is_dir()
    assert Path(meta["trace_path"]).is_file()
    assert Path(meta["diff_path"]).is_file()


@pytest.mark.parametrize(
    ("runner", "code"),
    [
        (lambda command, **kwargs: TsProcessResult(2, "", "bad args"), "cli_failed"),
        (lambda command, **kwargs: TsProcessResult(0, "not-json", ""), "invalid_result_json"),
        (lambda command, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(command, 1)), "cli_timeout"),
    ],
)
def test_typescript_bridge_reports_process_and_result_failures(tmp_path: Path, runner, code: str):
    source = tmp_path / "staging"
    source.mkdir()
    agent = typescript_agent_factory(
        fake=True,
        cli_root=Path(__file__).resolve().parents[1],
        timeout_seconds=1,
        command_runner=runner,
    )

    with pytest.raises(TsBridgeError) as raised:
        agent(source, "fix", ProjectProfile())
    assert raised.value.code == code


def test_default_ts_runner_terminates_descendants_on_timeout(tmp_path: Path):
    marker = tmp_path / "descendant-finished.txt"
    child_code = (
        "import time; from pathlib import Path; "
        f"time.sleep(2); Path({str(marker)!r}).write_text('alive', encoding='utf-8')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        default_ts_command_runner([sys.executable, "-c", parent_code], cwd=tmp_path, timeout=1)
    time.sleep(2.5)
    assert not marker.exists()


def test_typescript_bridge_rejects_artifact_paths_outside_run_root(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()
    outside = tmp_path / "outside.trace"
    outside.write_text("{}\n", encoding="utf-8")

    def runner(command, **kwargs):
        return _managed_result(command, overrides={"tracePath": str(outside)})

    agent = typescript_agent_factory(
        fake=True,
        cli_root=Path(__file__).resolve().parents[1],
        command_runner=runner,
    )
    with pytest.raises(TsBridgeError) as raised:
        agent(source, "fix", ProjectProfile())
    assert raised.value.code == "unsafe_result_path"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sessionId": "different-session"},
        {"workspace": "RUN_DIRECTORY"},
    ],
)
def test_typescript_bridge_binds_session_to_v1_directory_layout(tmp_path: Path, overrides: dict):
    source = tmp_path / "staging"
    source.mkdir()

    def runner(command, **kwargs):
        values = dict(overrides)
        if values.get("workspace") == "RUN_DIRECTORY":
            run_root = Path(command[command.index("--run-root") + 1]).resolve()
            values["workspace"] = str(run_root / "session-1")
        return _managed_result(command, overrides=values)

    agent = typescript_agent_factory(
        fake=True,
        cli_root=Path(__file__).resolve().parents[1],
        command_runner=runner,
    )
    with pytest.raises(TsBridgeError) as raised:
        agent(source, "fix", ProjectProfile())
    assert raised.value.code == "invalid_artifact_layout"


def test_typescript_bridge_requires_every_v1_artifact(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()

    def runner(command, **kwargs):
        process = _managed_result(command)
        result = json.loads(process.stdout)
        Path(result["tracePath"]).unlink()
        return process

    agent = typescript_agent_factory(
        fake=True,
        cli_root=Path(__file__).resolve().parents[1],
        command_runner=runner,
    )
    with pytest.raises(TsBridgeError) as raised:
        agent(source, "fix", ProjectProfile())
    assert raised.value.code == "missing_artifact"


def test_typescript_bridge_passes_a_model_script_without_enabling_fake(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()
    script = tmp_path / "model-script.json"
    script.write_text('{"schemaVersion":1,"responses":[]}', encoding="utf-8")
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        return _managed_result(command)

    agent = typescript_agent_factory(
        model_script=script,
        cli_root=Path(__file__).resolve().parents[1],
        command_runner=runner,
    )
    agent(source, "fix", ProjectProfile())
    command = captured["command"]
    assert command[command.index("--model-script") + 1] == str(script.resolve())
    assert "--fake" not in command

    with pytest.raises(ValueError, match="mutually exclusive"):
        typescript_agent_factory(fake=True, model_script=script)
    with pytest.raises(TsBridgeError) as raised:
        typescript_agent_factory(model_script=tmp_path / "missing.json")
    assert raised.value.code == "model_script_not_found"


def _make_task(task_dir: Path, answer: str) -> None:
    repo = task_dir / "repo"
    repo.mkdir(parents=True)
    (repo / "answer.txt").write_text(answer, encoding="utf-8")
    (task_dir / "prompt.md").write_text("keep the answer valid", encoding="utf-8")
    (task_dir / "verify.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if Path('answer.txt').read_text(encoding='utf-8') == 'ok' else 1)\n",
        encoding="utf-8",
    )


def test_run_task_verifies_agent_workspace_and_uses_explicit_artifacts(tmp_path: Path):
    _make_task(tmp_path / "tasks" / "t1", "bad")
    final_workspace = tmp_path / "managed" / "repository"
    trace = tmp_path / "managed" / "artifacts" / "trace.jsonl"
    diff = tmp_path / "managed" / "artifacts" / "final.diff"

    def agent(workspace, prompt, profile):
        final_workspace.mkdir(parents=True)
        (final_workspace / "answer.txt").write_text("ok", encoding="utf-8")
        trace.parent.mkdir()
        trace.write_text("{}\n", encoding="utf-8")
        diff.write_text("diff", encoding="utf-8")
        return {
            "steps": 2,
            "cost_usd": 0.1,
            "reason": "completed",
            "workspace_path": str(final_workspace),
            "trace_path": str(trace),
            "diff_path": str(diff),
        }

    result = run_task(discover(tmp_path / "tasks")[0], agent, tmp_path / "staging")

    assert result.status == "solved"
    assert result.workspace_path == str(final_workspace.resolve())
    assert result.trace_path == str(trace)
    assert result.diff_path == str(diff)
    assert (tmp_path / "staging" / "answer.txt").read_text(encoding="utf-8") == "bad"


def test_run_eval_typescript_fake_smoke_reads_managed_artifacts():
    scratch_parent = Path.cwd() / ".tmp"
    scratch_parent.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="ts-eval-smoke-", dir=scratch_parent))
    try:
        task_dir = root / "tasks" / "already-solved"
        _make_task(task_dir, "ok")
        (task_dir / "profile.yaml").write_text(
            "language: python\n"
            "test_cmd: node -e \"process.exit(0)\"\n"
            "test_timeout: 30\n",
            encoding="utf-8",
        )
        (task_dir / "model-script.json").write_text(json.dumps({
            "schemaVersion": 1,
            "responses": [{
                "content": None,
                "toolCalls": [{
                    "id": "finish-1",
                    "name": "finish",
                    "input": {"summary": "already solved"},
                }],
            }],
        }), encoding="utf-8")
        summary_path = root / "summary.json"

        code = main(
            [
                str(task_dir.parent),
                "--runtime",
                "typescript",
                "--fake",
                "--json-summary",
                str(summary_path),
            ],
            work_root=root / "eval-work",
        )

        assert code == 0
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        [result] = summary["tasks"]["already-solved"]["results"]
        assert result["status"] == "solved"
        assert result["steps"] == 1
        assert result["cost_usd"] == 0.0
        assert result["reason"] == "completed"
        assert result["session_id"]
        assert Path(result["result_path"]).is_file()
        assert Path(result["verification_path"]).is_file()
        assert result["usage"] == {
            "promptTokens": 0,
            "completionTokens": 0,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
        }
        assert Path(result["workspace_path"]).is_dir()
        assert Path(result["trace_path"]).is_file()
        assert Path(result["diff_path"]).is_file()
        assert (task_dir / "repo" / "answer.txt").read_text(encoding="utf-8") == "ok"
    finally:
        robust_rmtree(root)


def test_typescript_scripted_fake_solves_all_basic_tasks():
    scratch_parent = Path.cwd() / ".tmp"
    scratch_parent.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="ts-basic-fake-", dir=scratch_parent))
    try:
        summary_path = root / "summary.json"
        code = main(
            [
                str(Path("eval/tasks").resolve()),
                "--runtime",
                "typescript",
                "--fake",
                "--json-summary",
                str(summary_path),
            ],
            work_root=root / "eval-work",
        )

        assert code == 0
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["schema_version"] == 1
        assert summary["runtime"] == "typescript"
        assert summary["mode"] == "fake"
        assert summary["total"] == 5
        assert summary["solved"] == 5
        assert summary["infrastructure_errors"] == 0
        assert summary["task_ids"] == [
            "t01_implement",
            "t02_fix_bug",
            "t03_add_case",
            "t04_fix_tested_bug",
            "t05_multifile",
        ]
        for task in summary["tasks"].values():
            [result] = task["results"]
            assert result["status"] == "solved"
            assert result["reason"] == "completed"
            assert result["session_id"]
            assert Path(result["trace_path"]).is_file()
            assert Path(result["diff_path"]).is_file()
            assert Path(result["result_path"]).is_file()
            assert Path(result["verification_path"]).is_file()
    finally:
        robust_rmtree(root)


def test_typescript_fake_missing_script_writes_error_report(tmp_path: Path):
    task_dir = tmp_path / "tasks" / "missing-script"
    _make_task(task_dir, "bad")
    summary_path = tmp_path / "summary.json"

    code = main(
        [
            str(task_dir.parent),
            "--runtime",
            "typescript",
            "--fake",
            "--json-summary",
            str(summary_path),
        ],
        work_root=tmp_path / "eval-work",
    )

    assert code == 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["infrastructure_errors"] == 1
    [result] = summary["tasks"]["missing-script"]["results"]
    assert result["status"] == "error"
    assert result["infrastructure_error"]["code"] == "model_script_not_found"
    assert result["workspace_path"] == ""


def test_discovery_errors_are_reported_without_skipping_valid_tasks(tmp_path: Path):
    tasks_root = tmp_path / "tasks"
    invalid = tasks_root / "a-invalid"
    valid = tasks_root / "b-valid"
    invalid.mkdir(parents=True)
    (invalid / "profile.yaml").write_text("[invalid", encoding="utf-8")
    _make_task(valid, "ok")
    (valid / "repo" / "CMakeLists.txt").write_text("", encoding="utf-8")
    summary_path = tmp_path / "summary.json"

    code = main(
        [str(tasks_root), "--fake", "--json-summary", str(summary_path)],
        work_root=tmp_path / "eval-work",
    )

    assert code == 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["task_ids"] == ["a-invalid", "b-valid"]
    assert summary["infrastructure_errors"] == 1
    assert summary["tasks"]["a-invalid"]["results"][0]["workspace_path"] == ""
    assert summary["tasks"]["b-valid"]["results"][0]["status"] == "solved"


def test_missing_task_root_writes_discovery_error_report(tmp_path: Path):
    summary_path = tmp_path / "summary.json"

    code = main(
        [str(tmp_path / "missing"), "--fake", "--json-summary", str(summary_path)],
        work_root=tmp_path / "eval-work",
    )

    assert code == 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["task_ids"] == ["__discovery__"]
    [result] = summary["tasks"]["__discovery__"]["results"]
    assert result["status"] == "error"
    assert result["infrastructure_error"]["type"] == "FileNotFoundError"


def test_python_fake_report_uses_fake_model_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task_dir = tmp_path / "tasks" / "already-solved"
    _make_task(task_dir, "ok")
    (task_dir / "repo" / "CMakeLists.txt").write_text("", encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    monkeypatch.setenv("DEEPSEEK_MODEL", "must-not-leak-into-fake")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "must-not-leak-into-fake")

    code = main(
        [str(task_dir.parent), "--fake", "--json-summary", str(summary_path)],
        work_root=tmp_path / "eval-work",
    )

    assert code == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["model"] == "fake"
    assert summary["reasoning_effort"] == ""
    assert summary["cost_pricing_basis"] == "none"


# ── extensions_root bridge tests ──────────────────────────────────────────


def _capture_extensions_arg(command: list[str]) -> str | None:
    idx = command.index("--extensions") if "--extensions" in command else -1
    if idx < 0:
        return None
    return command[idx + 1]


def test_extensions_root_defaults_to_cli_extensions(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()
    captured: dict = {}

    def runner(command, *, cwd, timeout):
        captured["ext"] = _capture_extensions_arg(command)
        return _managed_result(command)

    agent = typescript_agent_factory(
        fake=True,
        cli_root=Path(__file__).resolve().parents[1],
        command_runner=runner,
    )
    agent(source, "fix", ProjectProfile())
    cli_root = Path(__file__).resolve().parents[1]
    assert captured["ext"] == str(cli_root / "extensions")


def test_extensions_root_explicit_empty_dir_is_passed_through(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()
    empty = tmp_path / "empty-ext"
    empty.mkdir()
    captured: dict = {}

    def runner(command, *, cwd, timeout):
        captured["ext"] = _capture_extensions_arg(command)
        return _managed_result(command)

    agent = typescript_agent_factory(
        fake=True,
        cli_root=Path(__file__).resolve().parents[1],
        extensions_root=empty,
        command_runner=runner,
    )
    agent(source, "fix", ProjectProfile())
    assert captured["ext"] == str(empty.resolve())


def test_extensions_root_explicit_treatment_dir_is_passed_through(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()
    treatment = tmp_path / "treatment-ext"
    treatment.mkdir()
    captured: dict = {}

    def runner(command, *, cwd, timeout):
        captured["ext"] = _capture_extensions_arg(command)
        return _managed_result(command)

    agent = typescript_agent_factory(
        fake=True,
        cli_root=Path(__file__).resolve().parents[1],
        extensions_root=treatment,
        command_runner=runner,
    )
    agent(source, "fix", ProjectProfile())
    assert captured["ext"] == str(treatment.resolve())


def test_extensions_root_does_not_enable_host_shell(tmp_path: Path):
    source = tmp_path / "staging"
    source.mkdir()
    captured: dict = {}

    def runner(command, *, cwd, timeout):
        captured["cmd"] = command
        return _managed_result(command)

    agent = typescript_agent_factory(
        fake=True,
        extensions_root=tmp_path / "any-ext",
        cli_root=Path(__file__).resolve().parents[1],
        command_runner=runner,
    )
    agent(source, "fix", ProjectProfile())
    assert "--allow-host-shell" not in captured["cmd"]
