"""CLI entry point."""

from __future__ import annotations

import argparse
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent.budget import Budget
from agent.editor import SearchReplaceEditor
from agent.locator import GrepLocator
from agent.loop import AgentLoop
from agent.profile import ProjectProfile, load_profile
from agent.tools import RunContext, build_default_registry
from agent.trace import Trace


@dataclass
class FakeCall:
    id: str
    name: str
    args: dict


@dataclass
class FakeResp:
    content: str | None
    tool_calls: list[FakeCall]
    assistant_message: dict
    prompt_tokens: int = 1
    completion_tokens: int = 1
    cost_usd: float = 0.0


class FakeLLM:
    def chat(self, messages, tools):
        return FakeResp(None, [FakeCall("f", "finish", {"summary": "fake run"})], {"role": "assistant", "content": None})


def create_workspace_copy(repo: Path, workspace_root: Path) -> Path:
    workspace_root.mkdir(parents=True, exist_ok=True)
    run_dir = workspace_root / f"run-{uuid.uuid4().hex}"
    shutil.copytree(repo, run_dir, ignore=shutil.ignore_patterns(".git"))
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args(argv)
    source_repo = args.repo.resolve()
    workspace = create_workspace_copy(source_repo, args.workspace)
    profile = load_profile(args.profile) if args.profile else ProjectProfile()
    trace = Trace(workspace.parent / f"{workspace.name}.trace.jsonl")
    ctx = RunContext(workspace, profile, trace, Budget(), GrepLocator(workspace, profile), SearchReplaceEditor(profile))
    llm = FakeLLM() if args.fake else None
    if llm is None:
        from agent.llm import LLMClient
        llm = LLMClient(trace=trace)
    task = args.task
    initial_output = ""
    repair_memory_matches = None
    if profile.language == "cmake":
        from agent.build_runner import run_cmake_verification
        from agent.cmake_prompt import build_cmake_task_prompt
        from agent.repair_memory import select_cmake_repair_memory
        from agent.tools import default_runner

        initial_attempts = run_cmake_verification(workspace, profile, ctx.runner or default_runner, trace)
        initial_output = "\n".join(attempt.output_preview for attempt in initial_attempts)

        # 从 source_repo 加载 repair memory 并匹配当前错误
        from agent.build_errors import classify_build_output
        first_failure = next((a for a in initial_attempts if a.exit_code != 0), None)
        error = classify_build_output(initial_output, phase=first_failure.phase if first_failure else None, command=first_failure.command if first_failure else None)
        repair_memory_matches = select_cmake_repair_memory(source_repo, error)

        task = build_cmake_task_prompt(args.task, workspace, profile, initial_output, trace,
                                       initial_attempts=initial_attempts,
                                       repair_memory_matches=repair_memory_matches)
    result = AgentLoop(llm, build_default_registry()).run(task, ctx)
    if profile.language == "cmake":
        from agent.build_runner import run_cmake_verification
        from agent.fix_report import build_fix_report, write_fix_report
        from agent.repair_memory import append_repair_case, extract_repair_case, repair_memory_jsonl
        from agent.tools import default_runner

        attempts = run_cmake_verification(workspace, profile, ctx.runner or default_runner, trace)
        final_output = "\n".join(attempt.output_preview for attempt in attempts)
        report = build_fix_report(args.task, result, attempts, workspace, initial_output, final_output, initial_attempts=initial_attempts, repair_memory_matches=repair_memory_matches)
        write_fix_report(report, workspace / "fix_report.md", trace)

        # 提取 repair case 并写入 source_repo 的 repair_memory.jsonl（不写入 workspace）
        diff_content = result.diff
        source = str(source_repo.relative_to(source_repo.parent) if source_repo.parent != source_repo else source_repo)
        repair_case = extract_repair_case(report, diff_content, source)
        append_repair_case(repair_memory_jsonl(source_repo), repair_case)

        print(f"fix_report={workspace / 'fix_report.md'}")
    diff_path = workspace / "final.diff"
    diff_path.write_text(result.diff, encoding="utf-8")
    print(f"workspace={workspace}")
    print(f"diff_path={diff_path}")
    print(f"reason={result.reason} cost_usd={result.cost_usd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

