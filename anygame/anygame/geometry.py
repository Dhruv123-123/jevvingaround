"""Zones are rectangles in normalized [0,1] screen coordinates; grids split a zone into named cells."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def px(self, w: int, h: int) -> tuple[int, int, int, int]:
        return (int(self.x0 * w), int(self.y0 * h), int(self.x1 * w), int(self.y1 * h))

    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @staticmethod
    def parse(v) -> "Rect":
        if isinstance(v, Rect):
            return v
        x0, y0, x1, y1 = [float(t) for t in v]
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError(f"rect must be normalized [x0,y0,x1,y1] with x0<x1, y0<y1: {v}")
        return Rect(x0, y0, x1, y1)


@dataclass(frozen=True)
class Zone:
    name: str
    rect: Rect
    grid: tuple[int, int] | None = None  # (cols, rows)

    def cells(self) -> dict[str, Rect]:
        """Named sub-rects. A 1-D grid names cells 1..n; a 2-D grid names them c<col>r<row> (1-based)."""
        if not self.grid:
            return {self.name: self.rect}
        cols, rows = self.grid
        cw = (self.rect.x1 - self.rect.x0) / cols
        rh = (self.rect.y1 - self.rect.y0) / rows
        out: dict[str, Rect] = {}
        for r in range(rows):
            for c in range(cols):
                key = f"{self.name}.{c + 1}" if rows == 1 else (f"{self.name}.{r + 1}" if cols == 1 else f"{self.name}.c{c + 1}r{r + 1}")
                out[key] = Rect(self.rect.x0 + c * cw, self.rect.y0 + r * rh, self.rect.x0 + (c + 1) * cw, self.rect.y0 + (r + 1) * rh)
        return out

    def cell_of(self, nx: float, ny: float) -> str | None:
        if not (self.rect.x0 <= nx <= self.rect.x1 and self.rect.y0 <= ny <= self.rect.y1):
            return None
        for name, r in self.cells().items():
            if r.x0 <= nx <= r.x1 and r.y0 <= ny <= r.y1:
                return name
        return None
