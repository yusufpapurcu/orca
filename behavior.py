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
from species import ORCA, SALMON

REF_LENGTH = 310.0  # px; the speeds below are written for an orca this long


class OrcaMode(Enum):
    CRUISE = auto()


class FishMode(Enum):
    ENTER = auto()  # swimming in from off-screen
    WANDER = auto()


@dataclass(frozen=True)
class Gait:
    speed: tuple[float, float]  # px/s at REF_LENGTH
    accel: float  # px/s^2
    turn: float  # max turn rate, rad/s


ORCA_GAITS = {
    OrcaMode.CRUISE: Gait((120, 160), 120, 1.3),
}

FISH_GAITS = {
    FishMode.ENTER: Gait((150, 150), 300, 1.5),
    FishMode.WANDER: Gait((80, 100), 150, 1.4),
}

# Speed in px/s at REF_LENGTH at which the tail beats at species.beat_hz.
ORCA_BEAT_SPEED = 140.0
FISH_BEAT_SPEED = 90.0


@dataclass
class Orca:
    body: Body
    mode: OrcaMode
    bubbles: Bubbles
    age: float = 0.0  # seconds in this mode
    speed_goal: float = 0.0
    wander: float = 0.0  # heading bias drifting as a slow random process


@dataclass
class Fish:
    body: Body
    mode: FishMode
    goal: tuple[float, float]  # where ENTER swims to
    age: float = 0.0
    speed_goal: float = 0.0
    wander: float = 0.0


@dataclass(frozen=True)
class Transition:
    t: float
    actor: str
    old: Enum | None
    new: Enum

    def __str__(self) -> str:
        return f"[{self.t:7.2f}s] {self.actor} {self.old.name if self.old else 'start'} -> {self.new.name}"


class World:
    def __init__(self, area: Rect, orca_length: float, rng: random.Random):
        self.area = area
        self.orca_length = orca_length
        self.fish_length = orca_length * SALMON.length_frac
        self.unit = orca_length / REF_LENGTH
        self.rng = rng
        self.t = 0.0
        self.orca_rig = compile_species(ORCA)
        self.fish_rig = compile_species(SALMON)
        self._events: list[Transition] = []

        heading = rng.uniform(-math.pi, math.pi)
        body = Body(*self._center(), heading, 0.0, facing=1 if math.cos(heading) >= 0 else -1)
        self.orca = Orca(body, OrcaMode.CRUISE, Bubbles())
        self._begin_orca_mode(OrcaMode.CRUISE)
        self.fish: Fish | None = None
        self._spawn_fish()

    def step(self, dt: float) -> list[Transition]:
        self.t += dt
        self._step_orca(dt)
        if self.fish:
            self._step_fish(dt)
        events, self._events = self._events, []
        return events

    def anchor(self, body: Body, length: float, u: float, v: float) -> tuple[float, float]:
        """Screen position of body-space point (u, v) on the orca."""
        xscale, pitch = view(body)
        project = projector((body.x, body.y), length, xscale, pitch)
        return project(*self.orca_rig.bend(u, v, body.phase))

    def _center(self) -> tuple[float, float]:
        a = self.area
        return (a.left + a.right) / 2, (a.top + a.bottom) / 2

    def _emit(self, actor: str, old: Enum | None, new: Enum) -> None:
        self._events.append(Transition(self.t, actor, old, new))

    def _margin(self, body: Body, speed_goal: float, gait: Gait) -> float:
        """Distance from an edge at which to start turning away: the turning radius plus slack."""
        return 0.15 * self.orca_length + 1.15 * max(body.speed, speed_goal) / gait.turn

    def _wander_heading(self, actor: Orca | Fish, dt: float) -> float:
        actor.wander += (-actor.wander / 1.5) * dt + 0.35 * math.sqrt(2 * dt / 1.5) * self.rng.gauss(0, 1)
        # Pull toward horizontal so side-view animals do not drift into climbing.
        h = actor.body.heading
        return h + actor.wander - 0.35 * math.sin(2 * h)

    # ------------------------------------------------------------------ orca

    def _begin_orca_mode(self, mode: OrcaMode) -> None:
        o = self.orca
        o.mode, o.age = mode, 0.0
        o.speed_goal = self.rng.uniform(*ORCA_GAITS[mode].speed) * self.unit

    def _step_orca(self, dt: float) -> None:
        o, b = self.orca, self.orca.body
        gait = ORCA_GAITS[o.mode]
        o.age += dt
        target, boost = avoid_edges(b, self._wander_heading(o, dt), self.area, self._margin(b, o.speed_goal, gait))
        steer(b, target, gait.turn * boost, dt)
        accelerate(b, o.speed_goal, gait.accel * self.unit, dt)
        advance(b, ORCA.beat_hz * (0.6 + 0.4 * b.speed / (ORCA_BEAT_SPEED * self.unit)), dt)
        vents = [self.anchor(b, self.orca_length, u, v) for u, v in ORCA.vents]
        o.bubbles.emit(dt, vents, math.cos(b.heading) * b.speed, math.sin(b.heading) * b.speed, self.rng)
        o.bubbles.update(dt)

    # ------------------------------------------------------------------ fish

    def _spawn_fish(self) -> None:
        """A new salmon just off a random edge, away from the orca, swimming in."""
        a, rng = self.area, self.rng
        wander_gait = FISH_GAITS[FishMode.WANDER]
        inner = a.inset(self._margin(Body(0, 0, 0, 0), wander_gait.speed[1] * self.unit, wander_gait))
        off = 0.5 * self.fish_length + 30

        def candidate() -> tuple[float, float]:
            side = rng.randrange(4)
            along = rng.uniform(0.15, 0.85)
            if side < 2:
                return (a.left - off if side == 0 else a.right + off), a.top + along * (a.bottom - a.top)
            return a.left + along * (a.right - a.left), (a.top - off if side == 2 else a.bottom + off)

        ob = self.orca.body
        x, y = max((candidate() for _ in range(4)), key=lambda p: math.hypot(p[0] - ob.x, p[1] - ob.y))
        goal = (rng.uniform(inner.left, inner.right), rng.uniform(inner.top, inner.bottom))
        heading = math.atan2(goal[1] - y, goal[0] - x)
        body = Body(x, y, heading, 0.0, facing=1 if math.cos(heading) >= 0 else -1)
        self.fish = Fish(body, FishMode.ENTER, goal)
        self._begin_fish_mode(FishMode.ENTER)
        self._emit("salmon", None, FishMode.ENTER)

    def _begin_fish_mode(self, mode: FishMode) -> None:
        f = self.fish
        f.mode, f.age = mode, 0.0
        f.speed_goal = self.rng.uniform(*FISH_GAITS[mode].speed) * self.unit

    def _fish_next(self, f: Fish) -> FishMode:
        if f.mode is FishMode.ENTER:
            gait = FISH_GAITS[FishMode.WANDER]
            if self.area.inset(self._margin(f.body, f.speed_goal, gait)).contains(f.body.x, f.body.y):
                return FishMode.WANDER
        return f.mode

    def _step_fish(self, dt: float) -> None:
        f, b = self.fish, self.fish.body
        f.age += dt
        nxt = self._fish_next(f)
        if nxt is not f.mode:
            self._emit("salmon", f.mode, nxt)
            self._begin_fish_mode(nxt)
        gait = FISH_GAITS[f.mode]
        boost = 1.0
        if f.mode is FishMode.ENTER:
            target = math.atan2(f.goal[1] - b.y, f.goal[0] - b.x)
        else:
            target, boost = avoid_edges(b, self._wander_heading(f, dt), self.area, self._margin(b, f.speed_goal, gait))
        steer(b, target, gait.turn * boost, dt)
        accelerate(b, f.speed_goal, gait.accel * self.unit, dt)
        advance(b, SALMON.beat_hz * (0.6 + 0.4 * b.speed / (FISH_BEAT_SPEED * self.unit)), dt)
