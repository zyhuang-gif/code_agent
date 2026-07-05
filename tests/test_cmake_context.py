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


def test_scan_cmake_context_extracts_target_local_relationships(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "third_party" / "json").mkdir(parents=True)
    (tmp_path / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.16)
project(Demo LANGUAGES CXX)
add_subdirectory(third_party/json)
add_library(mathx)
target_sources(mathx PRIVATE src/add.cpp src/scale.cpp)
target_include_directories(mathx PUBLIC include)
add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE mathx nlohmann_json::nlohmann_json)
""".strip(),
        encoding="utf-8",
    )

    context = scan_cmake_context(tmp_path, ProjectProfile(language="cmake"))

    assert context.subdirectories == ["third_party/json"]
    assert context.target_sources["mathx"] == ["src/add.cpp", "src/scale.cpp"]
    assert context.target_include_dirs["mathx"] == ["include"]
    assert context.target_links["app"] == ["mathx", "nlohmann_json::nlohmann_json"]


def test_scan_cmake_context_extracts_vcpkg_dependencies(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("project(Demo)\n", encoding="utf-8")
    (tmp_path / "vcpkg.json").write_text(
        '{"dependencies": ["fmt", {"name": "boost-graph"}, {"name": "poco", "features": ["postgresql"]}]}',
        encoding="utf-8",
    )

    context = scan_cmake_context(tmp_path, ProjectProfile(language="cmake"))

    assert context.vcpkg_dependencies == ["boost-graph", "fmt", "poco"]


def test_render_cmake_context_includes_relationships_compactly(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text(
        "add_library(mathx src/add.cpp)\n"
        "target_include_directories(mathx PUBLIC include)\n"
        "target_link_libraries(mathx PUBLIC Threads::Threads)\n",
        encoding="utf-8",
    )

    rendered = render_cmake_context(scan_cmake_context(tmp_path))

    assert "target links:" in rendered
    assert "mathx -> Threads::Threads" in rendered
    assert "target include dirs:" in rendered
    assert "mathx -> include" in rendered
