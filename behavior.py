"""The simulation: two actors as explicit state machines, steered in free 2D.

World is pure. It owns the actors and the rng and never touches rendering or
Win32, so it runs headless and deterministically for a given seed.

Orca:   CRUISE -> STALK -> LUNGE -> CHOMP -> SATED -> CRUISE (a new salmon spawns)
                    ^        |
                    +--miss--+
Salmon: ENTER -> WANDER <-> FLEE, then CAUGHT when the orca's mouth reaches it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum, auto

from anatomy import compile_species
from bubbles import Bubbles
from kinematics import STEER_GAIN, Body, Rect, accelerate, advance, avoid_edges, steer, wrap
from projection import Placement, Pose
from species import ORCA, SALMON

REF_LENGTH = 310.0  # px; speeds and accelerations below are written for an orca this long


def orca_length(screen_h: int) -> int:
    return max(200, min(520, round(screen_h * 0.296)))


class OrcaMode(Enum):
    CRUISE = auto()
    STALK = auto()
    LUNGE = auto()
    CHOMP = auto()
    SATED = auto()


class FishMode(Enum):
    ENTER = auto()  # swimming in from off-screen
    WANDER = auto()
    FLEE = auto()
    CAUGHT = auto()


@dataclass(frozen=True)
class Gait:
    speed: tuple[float, float]  # px/s at REF_LENGTH
    accel: float  # px/s^2
    turn: float  # max turn rate, rad/s


ORCA_GAITS = {
    OrcaMode.CRUISE: Gait((120, 160), 120, 1.3),
    OrcaMode.STALK: Gait((200, 240), 220, 1.8),
    OrcaMode.LUNGE: Gait((520, 520), 1500, 4.5),
    OrcaMode.CHOMP: Gait((30, 60), 900, 1.5),
    OrcaMode.SATED: Gait((70, 100), 150, 1.3),
}

FISH_GAITS = {
    FishMode.ENTER: Gait((150, 150), 300, 1.5),
    FishMode.WANDER: Gait((80, 100), 150, 1.4),
    FishMode.FLEE: Gait((110, 300), 250, 3.0),  # speed rises with the orca's proximity
}

# Speed in px/s at REF_LENGTH at which the tail beats at species.beat_hz.
ORCA_BEAT_SPEED = 140.0
FISH_BEAT_SPEED = 90.0

CRUISE_SECONDS = (3.0, 6.0)  # before the orca notices a salmon
SATED_SECONDS = (2.6, 3.4)
CHOMP_SECONDS = 1.2
LUNGE_SECONDS = 1.2
LUNGE_RANGE = 1.6  # orca lengths, centre to centre
LUNGE_ALIGN = math.radians(20)  # the orca only lunges when it is already pointing at the salmon
LUNGE_ROOM = 0.8  # seconds of open water the orca wants ahead of it before it lunges
LUNGE_COOLDOWN = 0.8  # a fresh stalk, or one after a miss, closes in before it lunges
CONTACT_REACH = 1.2  # orca lengths between centres beyond which no mouth, however it is drawn, can reach the salmon
STALK_GIVE_UP = 14.0
THREAT_RANGE = 3.0  # orca lengths at which a stalking orca alarms the salmon
THREAT_RELEASE = 3.6
FLEE_REACTION = 0.4  # seconds before a startled salmon actually bolts
JAW_OPEN_RATE, JAW_CLOSE_RATE = 7.0, 16.0  # per second; the chomp snaps shut


@dataclass
class Orca:
    body: Body
    mode: OrcaMode
    bubbles: Bubbles
    age: float = 0.0  # seconds in this mode
    dwell: float = 0.0  # how long CRUISE or SATED lasts
    speed_goal: float = 0.0
    wander: float = 0.0  # heading bias drifting as a slow random process
    jaw_open: float = 0.0

    def pose(self) -> Pose:
        """The pose to draw. In a chomp the head shakes as the jaw snaps shut."""
        shake = 0.0
        if self.mode is OrcaMode.CHOMP:
            shake = 0.3 * math.exp(-3.5 * self.age) * math.sin(2 * math.pi * 5 * self.age)
        return self.body.pose(shake, self.jaw_open)


@dataclass
class Fish:
    body: Body
    mode: FishMode
    goal: tuple[float, float]  # where ENTER swims to
    age: float = 0.0
    speed_goal: float = 0.0
    wander: float = 0.0
    dodge: float = 0.0  # heading offset while fleeing, re-rolled every fraction of a second
    dodge_left: float = 0.0

    def pose(self) -> Pose:
        return self.body.pose()


@dataclass(frozen=True)
class Transition:
    t: float
    actor: str
    old: Enum | None
    new: Enum

    def __str__(self) -> str:
        return f"[{self.t:7.2f}s] {self.actor} {self.old.name if self.old else 'start'} -> {self.new.name}"


@dataclass(frozen=True)
class Turn:
    """The orca starts turning around, through the viewer's side or the far side."""

    t: float
    toward_viewer: bool

    def __str__(self) -> str:
        return f"[{self.t:7.2f}s] orca TURN {'toward' if self.toward_viewer else 'away from'} the viewer"


class World:
    def __init__(self, area: Rect, length: float, rng: random.Random):
        self.area = area
        self.orca_length = length
        self.fish_length = length * SALMON.length_frac
        self.unit = length / REF_LENGTH
        self.rng = rng
        self.t = 0.0
        self.orca_rig = compile_species(ORCA)
        self.fish_rig = compile_species(SALMON)
        self._events: list[Transition | Turn] = []

        heading = rng.uniform(-math.pi, math.pi)
        body = Body.launch(*self._center(), heading)
        self.orca = Orca(body, OrcaMode.CRUISE, Bubbles())
        self._begin_orca_mode(OrcaMode.CRUISE)
        self.fish: Fish | None = None
        self._spawn_fish()

    def step(self, dt: float) -> list[Transition | Turn]:
        self.t += dt
        self._step_orca(dt)
        if self.fish:
            self._step_fish(dt)
        events, self._events = self._events, []
        return events

    def _orca_placement(self) -> Placement:
        """The orca as drawn this frame, so what it touches and emits from matches what is seen."""
        o = self.orca
        return Placement(self.orca_rig, o.pose(), self.orca_length, (o.body.x, o.body.y))

    def _fish_placement(self) -> Placement:
        f = self.fish
        return Placement(self.fish_rig, f.pose(), self.fish_length, (f.body.x, f.body.y))

    def _center(self) -> tuple[float, float]:
        a = self.area
        return (a.left + a.right) / 2, (a.top + a.bottom) / 2

    def _emit(self, actor: str, old: Enum | None, new: Enum) -> None:
        self._events.append(Transition(self.t, actor, old, new))

    def _steer_orca(self, target: float, rate: float, dt: float) -> None:
        att = self.orca.body.att
        k = att.k
        steer(self.orca.body, target, rate, dt)
        if att.k != k:
            # the bulge of sin(yaw) between k * pi and (k + d) * pi has the sign of d * (-1) ** k
            self._events.append(Turn(self.t, (att.k - k) * (-1) ** k > 0))

    def _margin(self, body: Body, speed_goal: float, gait: Gait) -> float:
        """Distance from an edge at which to start turning away: the turning radius plus the steering lag."""
        speed = max(body.speed, speed_goal)
        return 0.15 * self.orca_length + 1.15 * speed / gait.turn + 0.5 * speed / STEER_GAIN

    def _wander_heading(self, actor: Orca | Fish, dt: float) -> float:
        actor.wander += (-actor.wander / 1.5) * dt + 0.35 * math.sqrt(2 * dt / 1.5) * self.rng.gauss(0, 1)
        # Pull toward horizontal so side-view animals do not drift into climbing.
        h = actor.body.heading
        return h + actor.wander - 0.35 * math.sin(2 * h)

    def _gap(self) -> float:
        """Distance between the orca and the salmon, centre to centre, in px."""
        a, b = self.orca.body, self.fish.body
        return math.hypot(b.x - a.x, b.y - a.y)

    # ------------------------------------------------------------------ orca

    def _contact(self) -> bool:
        """The orca's mouth, where it is drawn, is within the salmon's half-length of the salmon's drawn centre.

        Only a head that has settled bites. Mid-turn it sweeps across the screen
        too fast to snap at anything, and counting it would make every flip a
        free catch.
        """
        if self.orca.body.att.turning or self._gap() > CONTACT_REACH * self.orca_length:
            return False
        mx, my = self._orca_placement().outline(0.0, 0.0)
        fx, fy = self._fish_placement().outline(0.5, 0.0)
        return math.hypot(fx - mx, fy - my) < 0.5 * self.fish_length

    def _orca_next(self, o: Orca) -> OrcaMode:
        f = self.fish
        match o.mode:
            case OrcaMode.CRUISE:
                if f and f.mode is not FishMode.ENTER and o.age >= o.dwell:
                    return OrcaMode.STALK
            case OrcaMode.STALK:
                if not f or o.age >= STALK_GIVE_UP:
                    return OrcaMode.CRUISE
                if self._contact():
                    return OrcaMode.CHOMP
                if (o.age >= LUNGE_COOLDOWN and self._gap() <= LUNGE_RANGE * self.orca_length
                        and self._aligned(o) and self._room_ahead(o)):
                    return OrcaMode.LUNGE
            case OrcaMode.LUNGE:
                if f and self._contact():
                    return OrcaMode.CHOMP
                if not f or o.age >= LUNGE_SECONDS or not self._room_ahead(o, 0.3):
                    return OrcaMode.STALK
            case OrcaMode.CHOMP:
                if o.age >= CHOMP_SECONDS:
                    return OrcaMode.SATED
            case OrcaMode.SATED:
                if o.age >= o.dwell:
                    return OrcaMode.CRUISE
        return o.mode

    def _aligned(self, o: Orca) -> bool:
        fb = self.fish.body
        bearing = math.atan2(fb.y - o.body.y, fb.x - o.body.x)
        return abs(wrap(bearing - o.body.heading)) < LUNGE_ALIGN and not o.body.att.turning

    def _room_ahead(self, o: Orca, seconds: float = LUNGE_ROOM) -> bool:
        """Whether a lunge's straight path stays inside the work area, with a little slack."""
        reach = ORCA_GAITS[OrcaMode.LUNGE].speed[1] * self.unit * seconds
        b = o.body
        return self.area.inset(0.2 * self.orca_length).contains(
            b.x + math.cos(b.heading) * reach, b.y + math.sin(b.heading) * reach)

    def _begin_orca_mode(self, mode: OrcaMode) -> None:
        o = self.orca
        o.mode, o.age = mode, 0.0
        o.speed_goal = self.rng.uniform(*ORCA_GAITS[mode].speed) * self.unit
        if mode is OrcaMode.CRUISE:
            o.dwell = self.rng.uniform(*CRUISE_SECONDS)
        elif mode is OrcaMode.SATED:
            o.dwell = self.rng.uniform(*SATED_SECONDS)

    def _enter_orca_mode(self, new: OrcaMode) -> None:
        old = self.orca.mode
        self._emit("orca", old, new)
        self._begin_orca_mode(new)
        if new is OrcaMode.CHOMP:
            self._catch()
        elif old is OrcaMode.SATED and new is OrcaMode.CRUISE:
            self._spawn_fish()

    def _catch(self) -> None:
        o, f = self.orca, self.fish
        self._emit("salmon", f.mode, FishMode.CAUGHT)
        self.fish = None
        mx, my = self._orca_placement().outline(0.0, 0.0)
        o.bubbles.burst(mx, my, o.body.vx, o.body.vy, self.rng)

    def _aim(self, lead: float) -> float:
        """Heading toward where the salmon will be if it keeps going, `lead` scaling how far ahead."""
        b, fb = self.orca.body, self.fish.body
        t = min(lead * self._gap() / max(b.speed, 200 * self.unit), 1.0)
        return math.atan2(fb.y + math.sin(fb.heading) * fb.speed * t - b.y,
                          fb.x + math.cos(fb.heading) * fb.speed * t - b.x)

    def _step_orca(self, dt: float) -> None:
        o, b = self.orca, self.orca.body
        o.age += dt
        nxt = self._orca_next(o)
        if nxt is not o.mode:
            self._enter_orca_mode(nxt)
        gait = ORCA_GAITS[o.mode]
        if o.mode is OrcaMode.STALK:
            want = self._aim(0.5)
        elif o.mode is OrcaMode.LUNGE:
            want = self._aim(1.0)
        else:
            want = self._wander_heading(o, dt)
        target, boost = avoid_edges(b, want, self.area, self._margin(b, o.speed_goal, gait))
        self._steer_orca(target, gait.turn * boost, dt)
        accelerate(b, o.speed_goal, gait.accel * self.unit, dt)
        advance(b, ORCA.beat_hz * (0.6 + 0.4 * b.speed / (ORCA_BEAT_SPEED * self.unit)), dt)

        goal = 1.0 if o.mode is OrcaMode.LUNGE else 0.0
        rate = (JAW_OPEN_RATE if goal > o.jaw_open else JAW_CLOSE_RATE) * dt
        o.jaw_open += max(-rate, min(rate, goal - o.jaw_open))

        o.bubbles.emit(dt, lambda: self._orca_placement().surface(*zip(*ORCA.vents)).tolist(), b.vx, b.vy, self.rng)
        o.bubbles.update(dt)

    # ------------------------------------------------------------------ fish

    def _spawn_fish(self) -> None:
        """A new salmon just off a random edge, away from the orca, swimming in."""
        a, rng = self.area, self.rng
        inner = self._fish_inner()
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
        body = Body.launch(x, y, heading)
        self.fish = Fish(body, FishMode.ENTER, goal)
        self._begin_fish_mode(FishMode.ENTER)
        self._emit("salmon", None, FishMode.ENTER)

    def _fish_inner(self) -> Rect:
        """Where a wandering salmon lives; ENTER swims to a point in here and ends on reaching it."""
        gait = FISH_GAITS[FishMode.WANDER]
        return self.area.inset(self._margin(Body(0, 0, 0), gait.speed[1] * self.unit, gait))

    def _begin_fish_mode(self, mode: FishMode) -> None:
        f = self.fish
        f.mode, f.age, f.dodge_left = mode, 0.0, 0.0
        lo, hi = FISH_GAITS[mode].speed
        f.speed_goal = (lo if mode is FishMode.FLEE else self.rng.uniform(lo, hi)) * self.unit

    def _fish_next(self, f: Fish) -> FishMode:
        hunted = self.orca.mode in (OrcaMode.STALK, OrcaMode.LUNGE)
        reach = self.orca_length * (THREAT_RELEASE if f.mode is FishMode.FLEE else THREAT_RANGE)
        match f.mode:
            case FishMode.ENTER:
                if self._fish_inner().contains(f.body.x, f.body.y):
                    return FishMode.WANDER
            case FishMode.WANDER:
                if hunted and self._gap() < reach:
                    return FishMode.FLEE
            case FishMode.FLEE:
                if not (hunted and self._gap() < reach):
                    return FishMode.WANDER
        return f.mode

    def _flee_heading(self, f: Fish, dt: float) -> float:
        """Directly away from the orca, plus jittery dodges to either side."""
        f.dodge_left -= dt
        if f.dodge_left <= 0:
            f.dodge_left = self.rng.uniform(0.2, 0.5)
            f.dodge = self.rng.choice((-1, 1)) * self.rng.uniform(0.5, 1.0)
        ob, b = self.orca.body, f.body
        return math.atan2(b.y - ob.y, b.x - ob.x) + f.dodge

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
            if f.mode is FishMode.FLEE:
                if f.age >= FLEE_REACTION:
                    close = max(0.0, 1.0 - self._gap() / (THREAT_RANGE * self.orca_length))
                    f.speed_goal = (gait.speed[0] + (gait.speed[1] - gait.speed[0]) * close) * self.unit
                want = self._flee_heading(f, dt)
            else:
                want = self._wander_heading(f, dt)
            target, boost = avoid_edges(b, want, self.area, self._margin(b, f.speed_goal, gait))
        steer(b, target, gait.turn * boost, dt)
        accelerate(b, f.speed_goal, gait.accel * self.unit, dt)
        advance(b, SALMON.beat_hz * (0.6 + 0.4 * b.speed / (FISH_BEAT_SPEED * self.unit)), dt)
