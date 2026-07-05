from pathlib import Path

from agent.cmake_context import CMakeContext, render_cmake_context, scan_cmake_context
from agent.profile import ProjectProfile


def test_scan_cmake_context_finds_core_project_facts(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "cmake").mkdir()
    (tmp_path / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.16)
project(Demo LANGUAGES CXX)
find_package(Threads REQUIRED)
add_library(mathx src/add.cpp)
add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE mathx Threads::Threads)
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cmake" / "Helpers.cmake").write_text("# helper\n", encoding="utf-8")
    (tmp_path / "vcpkg.json").write_text('{"dependencies":["fmt"]}\n', encoding="utf-8")
    (tmp_path / "CMakePresets.json").write_text(
        '{"version": 3, "configurePresets": [{"name": "mingw"}]}\n',
        encoding="utf-8",
    )

    context = scan_cmake_context(tmp_path, ProjectProfile(language="cmake"))

    assert context.cmake_files == ["CMakeLists.txt", "cmake/Helpers.cmake"]
    assert context.presets == ["mingw"]
    assert context.manifest_files == ["vcpkg.json"]
    assert context.source_dirs == ["src"]
    assert context.include_dirs == ["include"]
    assert context.test_dirs == ["tests"]
    assert context.targets == ["app", "mathx"]
    assert context.packages == ["Threads"]


def test_render_cmake_context_is_compact_and_relative(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("add_executable(app main.cpp)\n", encoding="utf-8")

    context = scan_cmake_context(tmp_path)
    rendered = render_cmake_context(context)

    assert "CMake project context:" in rendered
    assert "CMakeLists.txt" in rendered
    assert "targets: app" in rendered
    assert str(tmp_path) not in rendered
