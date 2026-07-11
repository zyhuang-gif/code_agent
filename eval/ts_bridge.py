"""Adapter that runs the TypeScript managed CLI from the Python Eval harness."""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agent.profile import ProjectProfile


@dataclass(frozen=True)
class TsProcessResult:
    exit_code: int
    stdout: str
    stderr: str


TsCommandRunner = Callable[..., TsProcessResult]


class TsBridgeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def default_ts_command_runner(command: list[str], *, cwd: Path, timeout: int) -> TsProcessResult:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        shell=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            taskkill = shutil.which("taskkill")
            if taskkill:
                try:
                    subprocess.run(
                        [taskkill, "/pid", str(process.pid), "/t", "/f"],
                        shell=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise
    return TsProcessResult(process.returncode, stdout, stderr)


def _inside(parent: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _result_path(
    result: dict[str, Any],
    key: str,
    run_root: Path,
    *,
    kind: str,
) -> Path:
    raw = result.get(key)
    if not isinstance(raw, str) or not raw:
        raise TsBridgeError("invalid_result", f"TypeScript run result is missing {key}")
    candidate = Path(raw).resolve()
    if not _inside(run_root, candidate):
        raise TsBridgeError("unsafe_result_path", f"TypeScript run result {key} is outside the Eval run root")
    if kind == "file" and not candidate.is_file():
        raise TsBridgeError("missing_artifact", f"TypeScript artifact does not exist: {key}")
    if kind == "directory" and not candidate.is_dir():
        raise TsBridgeError("missing_workspace", f"TypeScript directory does not exist: {key}")
    return candidate


def _usage(result: dict[str, Any]) -> dict[str, int]:
    raw = result.get("usage")
    if not isinstance(raw, dict):
        raise TsBridgeError("invalid_result", "TypeScript run result usage must be an object")
    parsed: dict[str, int] = {}
    for key in ("promptTokens", "completionTokens", "cacheReadTokens", "cacheWriteTokens"):
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TsBridgeError("invalid_result", f"TypeScript run result usage.{key} must be a non-negative integer")
        parsed[key] = value
    return parsed


def estimate_deepseek_cost_usd(usage: dict[str, int]) -> float:
    """Estimate the current DeepSeek-compatible Eval metric from token usage."""
    cache_read = usage["cacheReadTokens"]
    uncached_input = max(usage["promptTokens"] - cache_read, 0)
    completion = usage["completionTokens"]
    return (cache_read * 0.0028 + uncached_input * 0.14 + completion * 0.28) / 1_000_000


def _parse_managed_result(process: TsProcessResult, source: Path, run_root: Path) -> dict[str, Any]:
    if process.exit_code not in {0, 1}:
        detail = process.stderr.strip() or process.stdout.strip() or "no CLI diagnostics"
        raise TsBridgeError("cli_failed", f"TypeScript CLI exited with {process.exit_code}: {detail[:2000]}")
    stdout = process.stdout.strip()
    if not stdout:
        raise TsBridgeError("missing_result", "TypeScript CLI did not emit a managed run result")
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise TsBridgeError("invalid_result_json", "TypeScript CLI stdout is not one JSON result") from exc
    if not isinstance(value, dict):
        raise TsBridgeError("invalid_result", "TypeScript CLI result must be an object")
    if value.get("type") != "run_result" or value.get("mode") != "managed" or value.get("schemaVersion") != 1:
        raise TsBridgeError("unsupported_result", "TypeScript CLI did not emit ManagedRunResult schema v1")

    session_id = value.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise TsBridgeError("invalid_result", "TypeScript run result has an invalid sessionId")
    source_repository = value.get("sourceRepository")
    if not isinstance(source_repository, str) or Path(source_repository).resolve() != source:
        raise TsBridgeError("source_mismatch", "TypeScript run result sourceRepository does not match the Eval workspace")

    run_directory = _result_path(value, "runDirectory", run_root, kind="directory")
    workspace = _result_path(value, "workspace", run_root, kind="directory")
    artifacts = _result_path(value, "artifactsDirectory", run_root, kind="directory")
    expected_run_directory = (run_root / session_id).resolve()
    if run_directory != expected_run_directory:
        raise TsBridgeError("invalid_artifact_layout", "TypeScript runDirectory does not match runRoot/sessionId")
    if workspace != (run_directory / "repository").resolve():
        raise TsBridgeError("invalid_artifact_layout", "TypeScript workspace does not match the v1 repository path")
    if artifacts != (run_directory / "artifacts").resolve():
        raise TsBridgeError("invalid_artifact_layout", "TypeScript artifactsDirectory does not match the v1 layout")

    expected_files = {
        "resultPath": artifacts / "result.json",
        "tracePath": artifacts / "trace.jsonl",
        "diffPath": artifacts / "final.diff",
        "verificationPath": artifacts / "verification.json",
    }
    resolved_files = {}
    for key, expected in expected_files.items():
        resolved = _result_path(value, key, run_root, kind="file")
        if resolved != expected.resolve():
            raise TsBridgeError("invalid_artifact_layout", f"TypeScript artifact path does not match v1 layout: {key}")
        resolved_files[key] = resolved

    try:
        persisted = json.loads(resolved_files["resultPath"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TsBridgeError("invalid_persisted_result", "TypeScript result.json cannot be read") from exc
    if persisted != value:
        raise TsBridgeError("result_mismatch", "TypeScript stdout result does not match result.json")

    steps = value.get("steps")
    reason = value.get("reason")
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 0:
        raise TsBridgeError("invalid_result", "TypeScript run result steps must be a non-negative integer")
    if not isinstance(reason, str) or not reason:
        raise TsBridgeError("invalid_result", "TypeScript run result reason must be a non-empty string")
    value["usage"] = _usage(value)
    return value


def typescript_agent_factory(
    *,
    budget_steps: int | None = None,
    fake: bool = False,
    model_script: Path | None = None,
    allow_unsafe_host_shell: bool = False,
    cli_root: Path | None = None,
    run_root_parent: Path | None = None,
    timeout_seconds: int = 3600,
    command_runner: TsCommandRunner = default_ts_command_runner,
):
    if budget_steps is not None and budget_steps < 1:
        raise ValueError("budget_steps must be a positive integer")
    if fake and model_script is not None:
        raise ValueError("fake and model_script are mutually exclusive")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be a positive integer")
    root = (cli_root or Path(__file__).resolve().parents[1]).resolve()
    runs_parent = (run_root_parent or Path(tempfile.gettempdir())).resolve()
    script_path = model_script.resolve() if model_script is not None else None
    if script_path is not None and not script_path.is_file():
        raise TsBridgeError("model_script_not_found", f"TypeScript model script does not exist: {script_path}")

    def agent(workspace: Path, prompt: str, profile: ProjectProfile) -> dict[str, Any]:
        source = workspace.resolve()
        run_root = (runs_parent / f"ca-ts-{uuid4().hex[:12]}").resolve()
        if _inside(source, run_root) or _inside(run_root, source) or source == run_root:
            raise TsBridgeError("unsafe_run_root", "TypeScript Eval run root must be disjoint from the source workspace")
        runs_parent.mkdir(parents=True, exist_ok=True)
        run_root.mkdir(parents=True, exist_ok=False)
        profile_path = run_root / "profile.json"
        profile_path.write_text(json.dumps(asdict(profile), indent=2, sort_keys=True), encoding="utf-8")
        prompt_path = run_root / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        node = shutil.which("node")
        tsx_cli = root / "node_modules" / "tsx" / "dist" / "cli.mjs"
        cli_entry = root / "src" / "cli.ts"
        if not node or not tsx_cli.is_file() or not cli_entry.is_file():
            raise TsBridgeError("cli_not_found", "TypeScript CLI runtime is not installed in the configured cli_root")

        command = [
            node,
            str(tsx_cli),
            str(cli_entry),
            "--task-file",
            str(prompt_path),
            "--repo",
            str(source),
            "--run-root",
            str(run_root),
            "--profile",
            str(profile_path),
            "--extensions",
            str(root / "extensions"),
            "--permission-mode",
            "bypass" if allow_unsafe_host_shell else "accept_edits",
            "--max-steps",
            str(budget_steps or 40),
            "--result-json",
        ]
        if allow_unsafe_host_shell:
            command.append("--allow-host-shell")
        if script_path is not None:
            command.extend(["--model-script", str(script_path)])
        elif fake:
            command.append("--fake")
        try:
            process = command_runner(command, cwd=root, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise TsBridgeError("cli_timeout", f"TypeScript CLI exceeded {timeout_seconds} seconds") from exc
        except OSError as exc:
            raise TsBridgeError("cli_spawn_failed", "TypeScript CLI could not be started") from exc
        if not isinstance(process, TsProcessResult):
            raise TsBridgeError("invalid_runner_result", "TypeScript command runner returned an invalid result")

        result = _parse_managed_result(process, source, run_root)
        usage = result["usage"]
        return {
            "steps": result["steps"],
            "cost_usd": estimate_deepseek_cost_usd(usage),
            "reason": result["reason"],
            "workspace_path": result["workspace"],
            "trace_path": result["tracePath"],
            "diff_path": result["diffPath"],
            "result_path": result["resultPath"],
            "verification_path": result["verificationPath"],
            "session_id": result["sessionId"],
            "usage": usage,
        }

    return agent
