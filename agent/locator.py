"""Code locator interfaces and a pure Python grep implementation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent.profile import ProjectProfile


@dataclass(frozen=True)
class Hit:
    path: str
    line_no: int
    line: str


class Locator(Protocol):
    def search(self, pattern: str, glob: str | None = None) -> list[Hit]: ...
    def symbols(self, path: str) -> list[object]: ...


class GrepLocator:
    def __init__(self, root: str | Path, profile: ProjectProfile):
        self.root = Path(root)
        self.profile = profile

    def search(self, pattern: str, glob: str | None = None) -> list[Hit]:
        regex = re.compile(pattern)
        hits: list[Hit] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if self.profile.should_ignore(rel):
                continue
            if glob and not path.match(glob):
                continue
            if path.stat().st_size > self.profile.max_file_bytes:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for index, line in enumerate(lines, start=1):
                if regex.search(line):
                    hits.append(Hit(path=rel, line_no=index, line=line))
        return hits

    def symbols(self, path: str) -> list[object]:
        raise NotImplementedError("Symbol lookup is reserved for L2 locators.")
