---
name: cmake-build-fix
description: Diagnose and repair CMake configure, compile, link, and CTest failures in repositories that contain CMakeLists.txt or CMakePresets.json.
allowed-tools: list_dir, read_file, grep, edit_file, write_file, bash, finish
---
# CMake build repair

Use this workflow when the task or repository indicates CMake, C++, compiler, linker, or CTest failures.

## Workflow

1. Inspect the repository before editing. Locate the nearest relevant CMakeLists.txt, CMakePresets.json, source file, and target definition.
2. Reproduce the failure and classify its phase: configure, compile, link, or test.
3. Prefer target-scoped CMake fixes such as target_sources, target_include_directories, and target_link_libraries. Avoid global include_directories or link_directories unless the project already relies on them.
4. Make the smallest source or build-system change that addresses the observed evidence. Do not redesign unrelated targets.
5. Re-run configure, build, and CTest when available. Do not call finish while the relevant verification still fails.

## Common checks

- Missing header: identify the target compiling the source file and inspect its include directories and package dependencies.
- Missing source: inspect add_executable, add_library, target_sources, generated files, and add_subdirectory relationships.
- Undefined reference: inspect target_link_libraries, target names, library ordering where applicable, and whether the implementation source belongs to the target.
- Missing package: inspect find_package, presets, toolchain files, vcpkg manifests, and documented setup requirements.
- CTest failure: reproduce the named test and distinguish build-system errors from product-code failures.

All shell commands still pass through the normal permission, hook, and Bash-safety systems.
