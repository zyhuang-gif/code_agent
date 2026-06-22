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
