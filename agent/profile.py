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
    setup_timeout: int = 300
    test_cmd: str | None = None
    test_timeout: int = 300
    command_timeout: int = 300
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
        # 硬忽略通用 VCS/缓存垃圾（不依赖 self.ignore，永不展示给 agent）
        if {".git", "__pycache__"} & set(parts):
            return True
        if normalized.endswith(".pyc") or any(part.endswith(".egg-info") for part in parts):
            return True
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


