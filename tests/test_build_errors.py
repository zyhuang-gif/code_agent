from agent.build_errors import classify_build_output
from agent.cmake_context import CMakeContext
from agent.repair_hints import render_repair_hints


def test_classifies_missing_header_from_gcc_output(tmp_path):
    output = "src/main.cpp:1:10: fatal error: mathx/add.hpp: No such file or directory\ncompilation terminated."

    summary = classify_build_output(output)

    assert summary.error_type == "missing_header"
    assert summary.missing_header == "mathx/add.hpp"
    assert "fatal error" in summary.message
    assert summary.evidence_lines


def test_classifies_undefined_reference():
    output = "main.cpp:(.text+0x1a): undefined reference to `mathx::add(int, int)'"

    summary = classify_build_output(output)

    assert summary.error_type == "undefined_reference"
    assert summary.missing_symbol == "mathx::add(int, int)"


def test_classifies_missing_package_from_cmake_output():
    output = 'Could not find a package configuration file provided by "nlohmann_json" with any of the following names:'

    summary = classify_build_output(output)

    assert summary.error_type == "missing_package"
    assert summary.missing_package == "nlohmann_json"


def test_classifies_missing_target_from_cmake_output():
    output = 'Target "app" links to: MathX::Core but the target was not found.'

    summary = classify_build_output(output)

    assert summary.error_type == "missing_target"
    assert summary.missing_target == "MathX::Core"
    assert summary.target == "app"


def test_render_repair_hints_mentions_target_based_cmake_for_link_errors(tmp_path):
    summary = classify_build_output("undefined reference to `mathx::add(int, int)'")
    context = CMakeContext(root=tmp_path, cmake_files=["CMakeLists.txt"], targets=["app", "mathx"])

    hints = render_repair_hints(summary, context)

    assert "Repair hints:" in hints
    assert "target_link_libraries" in hints
    assert "CMakeLists.txt" in hints


def test_classifies_msvc_missing_header():
    output = 'src\\main.cpp(3): fatal error C1083: Cannot open include file: \'mathx/add.hpp\': No such file or directory'

    summary = classify_build_output(output, phase="build", command="cmake --build build")

    assert summary.error_type == "missing_header"
    assert summary.missing_header == "mathx/add.hpp"
    assert summary.phase == "build"
    assert summary.failing_command == "cmake --build build"
    assert summary.source_file == "src/main.cpp"


def test_classifies_cmake_could_not_find_package():
    output = (
        "CMake Error at CMakeLists.txt:7 (find_package):\n"
        "  Could NOT find Gperftools (missing: GPERFTOOLS_LIBRARIES)"
    )

    summary = classify_build_output(output, phase="configure")

    assert summary.error_type == "missing_package"
    assert summary.missing_package == "Gperftools"
    assert summary.phase == "configure"


def test_classifies_missing_link_library_from_gnu_linker():
    output = (
        "C:/mingw/bin/ld.exe: cannot find -lprofiler: No such file or directory\n"
        "collect2.exe: error: ld returned 1 exit status"
    )

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "link_library_missing"
    assert summary.missing_library == "profiler"
    assert summary.phase == "build"


def test_classifies_missing_link_library_from_msvc_linker():
    output = "LINK : fatal error LNK1104: cannot open file 'profiler.lib'"

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "link_library_missing"
    assert summary.missing_library == "profiler.lib"


def test_classifies_msvc_unresolved_external():
    output = (
        'main.obj : error LNK2019: unresolved external symbol '
        '"int __cdecl mathx::add(int,int)" referenced in function main'
    )

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "unresolved_external"
    assert "mathx::add" in summary.missing_symbol


def test_classifies_missing_source_from_ninja_output():
    output = (
        "ninja: error: 'src/generated.cpp', needed by "
        "'CMakeFiles/app.dir/src/generated.cpp.obj', missing and no known rule to make it"
    )

    summary = classify_build_output(output, phase="build")

    assert summary.error_type == "missing_source"
    assert summary.missing_source == "src/generated.cpp"


def test_classifies_ctest_named_failure():
    output = (
        "The following tests FAILED:\n"
        "\t  1 - scale_test (Failed)\n"
        "Errors while running CTest"
    )

    summary = classify_build_output(output, phase="test")

    assert summary.error_type == "test_failure"
    assert summary.test_name == "scale_test"
    assert summary.phase == "test"
