"""How the animal moves."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from anatomy import Species

BOB_PERIOD = 4.2
BOB_AMP_FRAC = 0.07


@dataclass
class SwimState:
    x: float
    base_y: float
    direction: int
    phase: float
    pass_index: int
    speed: float
    clock: float = 0.0

    @staticmethod
    def start(area: "Rect", half_w: float, rng: random.Random) -> "SwimState":
        s = SwimState(0.0, 0.0, rng.choice((-1, 1)), 0.0, 0, 0.0)
        s.begin_pass(area, half_w, rng, flip=False)
        return s

    def begin_pass(self, area: "Rect", half_w: float, rng: random.Random, flip: bool = True) -> None:
        if flip:
            self.direction = -self.direction
            self.pass_index += 1
        h = area.bottom - area.top
        self.base_y = area.top + h * rng.uniform(0.15, 0.85)
        self.speed = rng.uniform(200, 260)
        self.x = area.left - half_w if self.direction > 0 else area.right + half_w
        self.clock = 0.0

    def step(self, dt: float, species: Species, area: "Rect", half_w: float, rng: random.Random) -> None:
        self.x += self.direction * self.speed * dt
        self.clock += dt
        self.phase += species.beat_hz * dt
        gone = self.x > area.right + half_w if self.direction > 0 else self.x < area.left - half_w
        if gone:
            self.begin_pass(area, half_w, rng)

    def bob(self, length: float) -> tuple[float, float]:
        """Vertical offset in px and body pitch in radians (nose up positive)."""
        w = 2 * math.pi / BOB_PERIOD
        amp = BOB_AMP_FRAC * length
        dy = amp * math.sin(w * self.clock)
        vy = amp * w * math.cos(w * self.clock)
        return dy, math.atan2(-vy, self.speed) * 0.7
