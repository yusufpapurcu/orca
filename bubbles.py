"""Rising bubbles."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class Bubble:
    x: float
    y: float
    vx: float
    vy: float
    r: float
    life: float
    age: float = 0.0
    wobble: float = 0.0


@dataclass
class Bubbles:
    items: list[Bubble] = field(default_factory=list)
    cooldown: float = 0.4

    def update(self, dt: float, sources: list[tuple[float, float]], drift: float, rng: random.Random) -> None:
        self.cooldown -= dt
        if self.cooldown <= 0 and len(self.items) < 14:
            self.cooldown = rng.uniform(0.25, 0.7)
            sx, sy = rng.choice(sources)
            for _ in range(rng.randint(1, 3)):
                self.items.append(Bubble(
                    sx + rng.uniform(-3, 3), sy + rng.uniform(-3, 3),
                    drift * rng.uniform(0.6, 1.0), -rng.uniform(35, 75),
                    rng.uniform(2.0, 5.5), rng.uniform(1.0, 1.8),
                    wobble=rng.uniform(0, 6.28),
                ))
        for b in self.items:
            b.age += dt
            b.wobble += dt * 5
            b.x += (b.vx + 10 * math.sin(b.wobble)) * dt
            b.y += b.vy * dt
        self.items = [b for b in self.items if b.age < b.life]
