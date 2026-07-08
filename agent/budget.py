"""Execution budgets and loop detection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class Budget:
    max_steps: int = 40
    max_tokens: int = 400_000
    max_wallclock_s: int = 600
    clock: Callable[[], float] = time.monotonic
    steps: int = 0
    tokens: int = 0
    start: float = field(init=False)

    def __post_init__(self) -> None:
        self.start = self.clock()

    def ok(self) -> bool:
        return self.steps < self.max_steps and self.tokens < self.max_tokens and (self.clock() - self.start) <= self.max_wallclock_s

    def tick(self, tokens: int = 0) -> None:
        self.steps += 1
        self.tokens += tokens


class LoopDetector:
    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self.counts: dict[str, int] = {}

    def is_repeating(self, action: dict[str, Any]) -> bool:
        key = json.dumps(action, sort_keys=True)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key] >= self.threshold
