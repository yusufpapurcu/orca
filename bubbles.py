"""Bubbles in world space. They belong to the actor that emits them."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

DRAG = 2.0  # 1/s, horizontal velocity decay and the pull of vertical velocity toward rising
MAX_AMBIENT = 14

Point = tuple[float, float, float]


@dataclass
class Bubble:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    r: float  # px at the screen plane
    life: float
    rise: float
    age: float = 0.0
    wobble: float = 0.0
    front: bool = False  # drawn over the animal instead of behind it


@dataclass
class Bubbles:
    items: list[Bubble] = field(default_factory=list)
    cooldown: float = 0.4

    def emit(self, dt: float, sources: Callable[[], list[Point]], velocity: Point, rng: random.Random) -> None:
        """Trickle of bubbles from random sources, carried along by the swimmer's wake.

        The sources are only worked out when a trickle is actually due.
        """
        self.cooldown -= dt
        if self.cooldown > 0 or len(self.items) >= MAX_AMBIENT:
            return
        sources = sources()
        if not sources:
            return
        self.cooldown = rng.uniform(0.25, 0.7)
        sx, sy, sz = rng.choice(sources)
        vx, vy, vz = velocity
        for _ in range(rng.randint(1, 3)):
            rise = rng.uniform(35, 75)
            self.items.append(Bubble(
                sx + rng.uniform(-3, 3), sy + rng.uniform(-3, 3), sz,
                vx * 0.45 * rng.uniform(0.6, 1.0), vy * 0.45 - rise, vz * 0.45,
                rng.uniform(2.0, 5.5), rng.uniform(1.0, 1.8), rise,
                wobble=rng.uniform(0, 6.28),
            ))

    def burst(self, at: Point, velocity: Point, rng: random.Random, count: int = 18) -> None:
        x, y, z = at
        vx, vy, vz = velocity
        for _ in range(count):
            a, sp = rng.uniform(0, 2 * math.pi), rng.uniform(30, 150)
            self.items.append(Bubble(
                x + rng.uniform(-6, 6), y + rng.uniform(-6, 6), z,
                vx * 0.5 + math.cos(a) * sp, vy * 0.5 + math.sin(a) * sp, vz * 0.5,
                rng.uniform(2.5, 8.0), rng.uniform(0.9, 1.7), rng.uniform(40, 90),
                wobble=rng.uniform(0, 6.28), front=True,
            ))

    def update(self, dt: float) -> None:
        keep = math.exp(-DRAG * dt)
        for b in self.items:
            b.age += dt
            b.wobble += dt * 5
            b.vx *= keep
            b.vz *= keep
            b.vy = -b.rise + (b.vy + b.rise) * keep
            b.x += (b.vx + 10 * math.sin(b.wobble)) * dt
            b.y += b.vy * dt
            b.z += b.vz * dt
        self.items = [b for b in self.items if b.age < b.life]
