from pathlib import Path

from agent.cmake_prompt import build_cmake_task_prompt
from agent.profile import ProjectProfile
from agent.repair_memory import RepairMemoryCase, RepairMemoryMatch


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


def test_cmake_prompt_injects_repair_memory_section(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/main.cpp)\n", encoding="utf-8")

    memory_case = RepairMemoryCase(
        case_id="abc12345",
        schema_version=1,
        task="Fix build",
        error_type="missing_header",
        root_cause="Missing target_include_directories.",
        edited_files=["CMakeLists.txt"],
        verification_status="passed",
        verification_commands=["cmake --build build"],
        initial_phase="build",
        final_phase="build",
        evidence=["fatal error: mathx/add.hpp: No such file or directory"],
        diff_excerpt="+target_include_directories(app PRIVATE include)",
        source="eval/tasks_cmake/c01",
    )
    matches = [RepairMemoryMatch(case=memory_case, score=85.0)]

    prompt = build_cmake_task_prompt(
        "Fix build",
        tmp_path,
        ProjectProfile(language="cmake"),
        repair_memory_matches=matches,
    )

    assert "Relevant repair memory:" in prompt
    assert "Case 1" in prompt
    assert "abc12345" in prompt
    assert "score: 85.0" in prompt
    assert "missing_header" in prompt
    assert "target_include_directories" in prompt


def test_cmake_prompt_no_repair_memory_when_empty(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/main.cpp)\n", encoding="utf-8")

    prompt = build_cmake_task_prompt(
        "Fix build",
        tmp_path,
        ProjectProfile(language="cmake"),
        repair_memory_matches=[],
    )

    assert "Relevant repair memory:" not in prompt


def test_cmake_prompt_writes_repair_memory_matches_trace(tmp_path: Path):
    import json
    from agent.trace import Trace

    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/main.cpp)\n", encoding="utf-8")
    trace = Trace(tmp_path / "trace.jsonl")

    memory_case = RepairMemoryCase(
        case_id="mem01",
        schema_version=1,
        task="Fix build",
        error_type="missing_header",
        root_cause="...",
        edited_files=["CMakeLists.txt"],
        verification_status="passed",
        verification_commands=[],
        initial_phase="build",
        final_phase="build",
        evidence=["fatal error: add.hpp: No such file or directory"],
        diff_excerpt="+target_include_directories",
        source="eval/c01",
    )
    matches = [RepairMemoryMatch(case=memory_case, score=90.0)]

    build_cmake_task_prompt(
        "Fix build",
        tmp_path,
        ProjectProfile(language="cmake"),
        trace=trace,
        repair_memory_matches=matches,
    )

    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    memory_events = [row for row in rows if row.get("t") == "repair_memory_matches"]
    assert len(memory_events) == 1
    assert memory_events[0]["matches"][0]["case_id"] == "mem01"
    assert memory_events[0]["matches"][0]["score"] == 90.0
