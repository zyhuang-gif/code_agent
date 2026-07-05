from pathlib import Path

import yaml

from agent.profile import ProjectProfile, load_profile


def test_project_profile_from_dict_uses_defaults_and_values():
    profile = ProjectProfile.from_dict({"ignore": ["node_modules"], "language": "python"})

    assert profile.ignore == ["node_modules"]
    assert profile.language == "python"
    assert profile.pass_when == "exit_zero"
    assert profile.max_file_bytes == 200_000
    assert profile.syntax_check == {}


def test_load_profile_reads_yaml(tmp_path: Path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "ignore": [".git"],
                "syntax_check": {".py": "python -m py_compile {file}"},
                "test_cmd": "pytest",
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile(path)

    assert profile.ignore == [".git"]
    assert profile.syntax_check[".py"] == "python -m py_compile {file}"
    assert profile.test_cmd == "pytest"


def test_load_profile_with_only_ignore_keeps_other_defaults(tmp_path: Path):
    path = tmp_path / "minimal.yaml"
    path.write_text("ignore:\n  - __pycache__\n", encoding="utf-8")

    profile = load_profile(path)

    assert profile.ignore == ["__pycache__"]
    assert profile.setup_cmd is None
    assert profile.setup_needs_network is True
    assert profile.pass_when == "exit_zero"


def test_should_ignore_matches_directory_names_and_globs():
    profile = ProjectProfile(ignore=["node_modules", "*.pyc", "build/*"])

    assert profile.should_ignore("node_modules/pkg/index.js") is True
    assert profile.should_ignore("pkg/node_modules/index.js") is True
    assert profile.should_ignore("app/cache.pyc") is True
    assert profile.should_ignore("build/output/app.js") is True
    assert profile.should_ignore("src/app.py") is False


def test_builtin_python_profile_declares_test_cmd_and_empty_profile_does_not():
    python_profile = load_profile("profiles/python.yaml")
    empty_profile = load_profile("profiles/empty.yaml")

    assert python_profile.test_cmd == "pytest -q"
    assert empty_profile.test_cmd is None


def test_should_ignore_always_skips_vcs_and_cache_even_with_empty_ignore():
    # .git / __pycache__ / *.pyc / *.egg-info 是通用垃圾，无论 profile 配没配 ignore 都不该展示给 agent
    profile = ProjectProfile()  # ignore 为空
    assert profile.should_ignore(".git/objects/ab/cdef") is True
    assert profile.should_ignore("src/click/__pycache__/core.cpython-313.pyc") is True
    assert profile.should_ignore("src/foo.pyc") is True
    assert profile.should_ignore("src/click.egg-info/PKG-INFO") is True
    assert profile.should_ignore("src/click/parser.py") is False


def test_builtin_cmake_profile_declares_language_and_build_command():
    cmake_profile = load_profile("profiles/cmake.yaml")

    assert cmake_profile.language == "cmake"
    assert "cmake -S . -B build" in cmake_profile.test_cmd
    assert "ctest --test-dir build" in cmake_profile.test_cmd
    assert cmake_profile.test_timeout == 120
    assert cmake_profile.should_ignore("build/CMakeCache.txt") is True
    assert cmake_profile.should_ignore("cmake-build-debug/CMakeCache.txt") is True
