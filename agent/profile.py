"""Project profile configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProjectProfile:
    ignore: list[str] = field(default_factory=list)
    syntax_check: dict[str, str] = field(default_factory=dict)
    setup_cmd: str | None = None
    setup_needs_network: bool = True
    test_cmd: str | None = None
    pass_when: str = "exit_zero"
    parse_test_output: str | None = None
    language: str | None = None
    max_file_bytes: int = 200_000

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProjectProfile":
        data = data or {}
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in allowed})

    def should_ignore(self, rel_path: str | Path) -> bool:
        normalized = Path(rel_path).as_posix()
        parts = normalized.split("/")
        for pattern in self.ignore:
            if pattern in parts:
                return True
            if fnmatch(normalized, pattern) or any(fnmatch(part, pattern) for part in parts):
                return True
        return False


def load_profile(path: str | Path) -> ProjectProfile:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return ProjectProfile.from_dict(data)
