from pathlib import Path

from agent.cmake_prompt import build_cmake_task_prompt
from agent.profile import ProjectProfile


def test_build_cmake_task_prompt_includes_context_error_and_hints(tmp_path: Path):
    (tmp_path / "include").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/main.cpp)\n", encoding="utf-8")

    prompt = build_cmake_task_prompt(
        "Fix the build.",
        tmp_path,
        ProjectProfile(language="cmake"),
        "src/main.cpp:1:10: fatal error: mathx/add.hpp: No such file or directory",
    )

    assert "Task: Fix the build." in prompt
    assert "CMake project context:" in prompt
    assert "Build error summary:" in prompt
    assert "type: missing_header" in prompt
    assert "Repair hints:" in prompt
    assert "Do not install packages" in prompt


def test_cmake_prompt_renders_attempt_summary_and_trace(tmp_path: Path):
    import json
    from agent.build_runner import BuildAttempt
    from agent.cmake_prompt import build_cmake_task_prompt
    from agent.profile import ProjectProfile
    from agent.trace import Trace

    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/main.cpp)\n", encoding="utf-8")
    trace = Trace(tmp_path / "trace.jsonl")
    attempts = [
        BuildAttempt("cmake -S . -B build", "configure", 0, "configured"),
        BuildAttempt("cmake --build build", "build", 1, "fatal error: mathx/add.hpp: No such file or directory"),
    ]

    prompt = build_cmake_task_prompt(
        "Fix build",
        tmp_path,
        ProjectProfile(language="cmake"),
        initial_attempts=attempts,
        trace=trace,
    )

    assert "Initial verification attempts:" in prompt
    assert "- build: exit_code=1 command=cmake --build build" in prompt
    assert "missing header: mathx/add.hpp" in prompt
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert "cmake_attempt_summary" in [row["t"] for row in rows]
