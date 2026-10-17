"""The simulation: actors as explicit state machines, steered in free 2D.

World is pure. It owns the actors and the rng and never touches rendering or
Win32, so it runs headless and deterministically for a given seed.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum, auto

from anatomy import compile_species
from bubbles import Bubbles
from kinematics import Body, Rect, accelerate, advance, avoid_edges, projector, steer, view
from species import ORCA

REF_LENGTH = 310.0  # px; the speeds below are written for an orca this long


class OrcaMode(Enum):
    CRUISE = auto()


@dataclass(frozen=True)
class Gait:
    speed: tuple[float, float]  # px/s at REF_LENGTH
    accel: float  # px/s^2
    turn: float  # max turn rate, rad/s


ORCA_GAITS = {
    OrcaMode.CRUISE: Gait((120, 160), 120, 1.3),
}

# Cruise speed in px/s at REF_LENGTH; the tail beats at species.beat_hz there.
ORCA_BEAT_SPEED = 140.0


@dataclass
class Orca:
    body: Body
    mode: OrcaMode
    bubbles: Bubbles
    age: float = 0.0  # seconds in this mode
    speed_goal: float = 0.0
    wander: float = 0.0  # heading bias drifting as a slow random process


@dataclass(frozen=True)
class Transition:
    t: float
    actor: str
    old: Enum
    new: Enum

    def __str__(self) -> str:
        return f"[{self.t:7.2f}s] {self.actor} {self.old.name} -> {self.new.name}"


class World:
    def __init__(self, area: Rect, orca_length: float, rng: random.Random):
        self.area = area
        self.orca_length = orca_length
        self.unit = orca_length / REF_LENGTH
        self.rng = rng
        self.t = 0.0
        self.orca_rig = compile_species(ORCA)
        heading = rng.uniform(-math.pi, math.pi)
        cx, cy = (area.left + area.right) / 2, (area.top + area.bottom) / 2
        body = Body(cx, cy, heading, 0.0, facing=1 if math.cos(heading) >= 0 else -1)
        self.orca = Orca(body, OrcaMode.CRUISE, Bubbles())
        self._begin_orca_mode(OrcaMode.CRUISE)

    def step(self, dt: float) -> list[Transition]:
        events: list[Transition] = []
        self.t += dt
        self._step_orca(dt, events)
        return events

    def anchor(self, body: Body, length: float, u: float, v: float) -> tuple[float, float]:
        """Screen position of body-space point (u, v) on the orca."""
        xscale, pitch = view(body)
        project = projector((body.x, body.y), length, xscale, pitch)
        return project(*self.orca_rig.bend(u, v, body.phase))

    def _margin(self, body: Body, speed_goal: float, gait: Gait) -> float:
        """Distance from an edge at which to start turning away: the turning radius plus slack."""
        return 0.15 * self.orca_length + 1.15 * max(body.speed, speed_goal) / gait.turn

    def _wander_heading(self, body: Body, o: Orca, dt: float) -> float:
        o.wander += (-o.wander / 1.5) * dt + 0.35 * math.sqrt(2 * dt / 1.5) * self.rng.gauss(0, 1)
        # Pull toward horizontal so side-view animals do not drift into climbing.
        return body.heading + o.wander - 0.35 * math.sin(2 * body.heading)

    def _begin_orca_mode(self, mode: OrcaMode) -> None:
        o = self.orca
        o.mode, o.age = mode, 0.0
        o.speed_goal = self.rng.uniform(*ORCA_GAITS[mode].speed) * self.unit

    def _step_orca(self, dt: float, events: list[Transition]) -> None:
        o, b = self.orca, self.orca.body
        gait = ORCA_GAITS[o.mode]
        o.age += dt
        target, boost = avoid_edges(b, self._wander_heading(b, o, dt), self.area, self._margin(b, o.speed_goal, gait))
        steer(b, target, gait.turn * boost, dt)
        accelerate(b, o.speed_goal, gait.accel * self.unit, dt)
        advance(b, ORCA.beat_hz * (0.6 + 0.4 * b.speed / (ORCA_BEAT_SPEED * self.unit)), dt)
        vents = [self.anchor(b, self.orca_length, u, v) for u, v in ORCA.vents]
        o.bubbles.emit(dt, vents, math.cos(b.heading) * b.speed, math.sin(b.heading) * b.speed, self.rng)
        o.bubbles.update(dt)
