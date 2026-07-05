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
