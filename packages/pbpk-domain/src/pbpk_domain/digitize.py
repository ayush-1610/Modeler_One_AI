"""Figure digitization with a human-set axis calibration (task T-19, plan §9.2).

A person marks two reference points on each axis of a published figure and types their values (linear or log
scale); every data point is then a pixel position mapped to data units by code. Nothing is detected or guessed here:
which marker is a data point, and which series it belongs to, is the person's call, and the overlay (the mapped
points drawn back on the figure) is approved before the dataset is used. The resolution (data units per pixel at
each point) is reported as the digitization uncertainty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Scale = Literal["linear", "log"]


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class AxisCalibration:
    """Two reference points on one axis: pixel coordinate → data value."""

    p1: float
    v1: float
    p2: float
    v2: float
    scale: Scale = "linear"

    def __post_init__(self) -> None:
        if self.p1 == self.p2:
            raise CalibrationError("the two reference points of an axis must be at different pixels")
        if self.v1 == self.v2:
            raise CalibrationError("the two reference values of an axis must differ")
        if self.scale == "log" and (self.v1 <= 0 or self.v2 <= 0):
            raise CalibrationError("a log axis needs positive reference values")

    def _t(self, v: float) -> float:
        return math.log10(v) if self.scale == "log" else v

    def value(self, pixel: float) -> float:
        a, b = self._t(self.v1), self._t(self.v2)
        t = a + (pixel - self.p1) * (b - a) / (self.p2 - self.p1)
        return 10 ** t if self.scale == "log" else t

    def pixel(self, value: float) -> float:
        a, b = self._t(self.v1), self._t(self.v2)
        return self.p1 + (self._t(value) - a) * (self.p2 - self.p1) / (b - a)

    def resolution(self, pixel: float) -> float:
        """Data units spanned by one pixel at `pixel` (the digitization uncertainty, half of it either way)."""
        return abs(self.value(pixel + 0.5) - self.value(pixel - 0.5))


@dataclass(frozen=True)
class Calibration:
    x: AxisCalibration
    y: AxisCalibration


@dataclass(frozen=True)
class DigitizedPoint:
    px: float
    py: float
    x: float
    y: float
    dx: float   # resolution in x (data units per pixel)
    dy: float


def digitize(calibration: Calibration, pixels: list[tuple[float, float]]) -> list[DigitizedPoint]:
    """Map picked pixel positions to data, in the order picked, sorted by x."""
    points = [DigitizedPoint(px=px, py=py, x=calibration.x.value(px), y=calibration.y.value(py),
                             dx=calibration.x.resolution(px), dy=calibration.y.resolution(py)) for px, py in pixels]
    return sorted(points, key=lambda p: p.x)
