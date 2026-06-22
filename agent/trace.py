"""JSONL trace writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _preview(value: Any, limit: int = 4000) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[: limit // 2] + "\n...<truncated>...\n" + value[-limit // 2 :]
    if isinstance(value, dict):
        return {key: _preview(item, limit) for key, item in value.items()}
    return value


class Trace:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_preview(event), ensure_ascii=False) + "\n")

    def llm_call(self, **kwargs: Any) -> None:
        self.write({"t": "llm_call", **kwargs})

    def tool_exec(self, **kwargs: Any) -> None:
        self.write({"t": "tool_exec", **kwargs})

    def run_summary(self, **kwargs: Any) -> None:
        self.write({"t": "run_summary", **kwargs})
