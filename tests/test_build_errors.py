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
