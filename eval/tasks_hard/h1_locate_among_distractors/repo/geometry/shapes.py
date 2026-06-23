from __future__ import annotations

import math
from dataclasses import dataclass

from .utils import positive


@dataclass(frozen=True)
class Circle:
    radius: float

    def area(self) -> float:
        radius = positive(self.radius, "radius")
        return math.pi * radius * radius * radius


@dataclass(frozen=True)
class Rectangle:
    width: float
    height: float

    def area(self) -> float:
        width = positive(self.width, "width")
        height = positive(self.height, "height")
        return width + height


