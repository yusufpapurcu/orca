"""The simulation: two actors as explicit state machines, steered in free 3D.

World is pure. It owns the actors, the camera's frustum and the rng and never
touches rendering or Win32, so it runs headless and deterministically for a
given seed.

Orca:   CRUISE -> STALK -> LUNGE -> CHOMP -> SATED -> CRUISE (a new salmon spawns)
                    ^        |
                    +--miss--+
Salmon: ENTER -> WANDER <-> FLEE, then CAUGHT when the orca's mouth reaches it.

A mode that roams (CRUISE, SATED, WANDER) swims toward a waypoint drawn from
one of two depth bands, shallow or deep, and the band it draws from next is
a coin weighted by the band it is in, so a trip into the deep lingers there.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum, auto

from anatomy import compile_species
from bubbles import Bubbles
from kinematics import BODY_LAG, OMEGA0, OMEGA1, STEER_GAIN, Body, Vec, accelerate, advance, avoid_edges, bearing, direction, dist, dot, steer, sub, unit, wrap
from projection import FOCAL, Camera, Placement, Pose, Rect
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
    ENTER = auto()  # swimming in from off-screen or out of the haze
    WANDER = auto()
    FLEE = auto()
    CAUGHT = auto()


@dataclass(frozen=True)
class Roam:
    """Where a roaming mode's waypoints lie. Depths are fractions of the way from the near limit to the far."""

    shallow: tuple[float, float]
    deep: tuple[float, float]
    go_deep: float  # chance the waypoint after a shallow one is deep
    stay_deep: float  # chance the waypoint after a deep one is deep too


@dataclass(frozen=True)
class Gait:
    speed: tuple[float, float]  # px/s at REF_LENGTH
    accel: float  # px/s^2
    turn: float  # max turn rate, rad/s
    roam: Roam | None = None  # None: the mode aims at something instead


ORCA_GAITS = {
    OrcaMode.CRUISE: Gait((120, 160), 120, 1.3, Roam((0.03, 0.2), (0.6, 0.85), 0.15, 0.3)),
    OrcaMode.STALK: Gait((230, 270), 220, 1.8),
    OrcaMode.LUNGE: Gait((520, 520), 1500, 4.5),
    OrcaMode.CHOMP: Gait((30, 60), 900, 1.5),
    OrcaMode.SATED: Gait((120, 160), 150, 1.3, Roam((0.6, 0.85), (0.6, 0.85), 1.0, 1.0)),
}

FISH_GAITS = {
    FishMode.ENTER: Gait((150, 190), 300, 1.5),
    FishMode.WANDER: Gait((80, 100), 150, 1.4, Roam((0.03, 0.2), (0.3, 0.5), 0.2, 0.4)),
    FishMode.FLEE: Gait((110, 300), 250, 3.0),  # speed rises with the orca's proximity
}

# Speed in px/s at REF_LENGTH at which the tail beats at species.beat_hz.
ORCA_BEAT_SPEED = 140.0
FISH_BEAT_SPEED = 90.0

CRUISE_SECONDS = (3.0, 6.0)  # before the orca notices a salmon
SATED_SECONDS = (3.2, 4.2)
CHOMP_SECONDS = 1.2
LUNGE_SECONDS = 1.2
LUNGE_RANGE = 1.6  # orca lengths, centre to centre
LUNGE_ALIGN = math.radians(20)  # the orca only lunges when it is already pointing at the salmon
LUNGE_ROOM = 0.8  # seconds of open water the orca wants ahead of it before it lunges
LUNGE_COOLDOWN = 0.8  # a fresh stalk, or one after a miss, closes in before it lunges
CONTACT_REACH = 1.2  # orca lengths between centres beyond which no mouth, however it is drawn, can reach the salmon
CONTACT_ALIGN = 0.5  # radians the head may be off the bearing to the salmon and still bite
CONTACT_STRAIGHT = 0.6  # radians the tail may trail the head in yaw: a spine still whipping round does not bite
FISH_FAR = 0.4  # the salmon keeps to the front: fleeing deeper than this fraction of the way from near to far, it pulls nearer
STALK_GIVE_UP = 14.0
THREAT_RANGE = 3.0  # orca lengths at which a stalking orca alarms the salmon
THREAT_RELEASE = 3.6
FLEE_REACTION = 0.4  # seconds before a startled salmon actually bolts
JAW_OPEN_RATE, JAW_CLOSE_RATE = 7.0, 16.0  # per second; the chomp snaps shut
EDGE_PAD = 0.15  # orca lengths inside the frustum an animal keeps
WAYPOINT_REACH = 0.6  # orca lengths from a waypoint at which it counts as reached
WAYPOINT_SECONDS = 9.0  # ... or given up on
HAZE_ENTRY = 0.4  # share of salmon that come out of the deep instead of in from an edge
HAZE_DEPTH = (1.15, 1.3)  # where they start, in far limits: beyond it, mostly faded out


@dataclass
class Orca:
    body: Body
    mode: OrcaMode
    bubbles: Bubbles
    age: float = 0.0  # seconds in this mode
    dwell: float = 0.0  # how long CRUISE or SATED lasts
    speed_goal: float = 0.0
    wander: float = 0.0  # yaw bias drifting as a slow random process
    waypoint: Vec | None = None
    waypoint_age: float = 0.0
    deep: bool = False  # which band the waypoint came from
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
    waypoint: Vec | None  # where ENTER swims to, then where WANDER heads
    age: float = 0.0
    speed_goal: float = 0.0
    wander: float = 0.0
    waypoint_age: float = 0.0
    deep: bool = False
    dodge: float = 0.0  # yaw offset while fleeing, re-rolled every fraction of a second
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
    """The orca turns round, its heading swinging through the viewer's side or the far side."""

    t: float
    toward_viewer: bool

    def __str__(self) -> str:
        return f"[{self.t:7.2f}s] orca TURN {'toward' if self.toward_viewer else 'away from'} the viewer"


@dataclass(frozen=True)
class Dive:
    """An actor crosses the halfway depth, going deep or coming near. Screen position and scale for a watcher."""

    t: float
    actor: str
    deep: bool
    sx: float
    sy: float
    scale: float

    def __str__(self) -> str:
        return f"[{self.t:7.2f}s] {self.actor} {'DEEP' if self.deep else 'NEAR'} at ({self.sx:.0f}, {self.sy:.0f}) {self.scale:.2f}x"


@dataclass(frozen=True)
class Order:
    """Which animal is nearer the viewer changed, so it should now be drawn on top."""

    t: float
    salmon_front: bool

    def __str__(self) -> str:
        return f"[{self.t:7.2f}s] {'salmon' if self.salmon_front else 'orca'} in front"


Event = Transition | Turn | Dive | Order


class World:
    def __init__(self, area: Rect, length: float, rng: random.Random):
        self.area = area
        self.cam = Camera(area, FOCAL * length)
        self.orca_length = length
        self.fish_length = length * SALMON.length_frac
        self.unit = length / REF_LENGTH
        self.pad = EDGE_PAD * length
        self.rng = rng
        self.t = 0.0
        self.orca_rig = compile_species(ORCA)
        self.fish_rig = compile_species(SALMON)
        self._events: list[Event] = []
        self.salmon_front: bool | None = None

        yaw = rng.uniform(-math.pi, math.pi)
        cx, cy = area.center
        body = Body.launch(cx, cy, 0.0, direction(yaw, 0.0))
        self.orca = Orca(body, OrcaMode.CRUISE, Bubbles())
        self._begin_orca_mode(OrcaMode.CRUISE)
        self.fish: Fish | None = None
        self._spawn_fish()

    def step(self, dt: float) -> list[Event]:
        self.t += dt
        self._step_orca(dt)
        if self.fish:
            self._step_fish(dt)
            front = self.fish.body.z < self.orca.body.z
            if front != self.salmon_front:
                self.salmon_front = front
                self._events.append(Order(self.t, front))
        events, self._events = self._events, []
        return events

    def _orca_placement(self) -> Placement:
        """The orca as posed this frame, in world px, so what it touches and emits from matches what is seen."""
        o = self.orca
        return Placement(self.orca_rig, o.pose(), self.orca_length, (o.body.x, o.body.y))

    def _fish_placement(self) -> Placement:
        f = self.fish
        return Placement(self.fish_rig, f.pose(), self.fish_length, (f.body.x, f.body.y))

    def _emit(self, actor: str, old: Enum | None, new: Enum) -> None:
        self._events.append(Transition(self.t, actor, old, new))

    def _lookahead(self, gait: Gait) -> float:
        """Seconds ahead an animal looks for a wall: the time a turn takes plus the lag before the body follows."""
        return 1.15 / gait.turn + 0.5 / STEER_GAIN + 2.0 / (OMEGA0 + OMEGA1 * gait.turn) + BODY_LAG / 2

    def _avoid(self, body: Body, want: Vec, gait: Gait, speed_goal: float) -> tuple[Vec, float]:
        return avoid_edges(body, want, self.cam, self._lookahead(gait), self.pad, speed_goal)

    def _advance(self, actor: Orca | Fish, target: Vec, turn: float, gait: Gait, species, beat_speed: float, dt: float) -> None:
        b = actor.body
        was_deep = b.z > self.cam.mid
        steer(b, target, turn, dt)
        accelerate(b, actor.speed_goal, gait.accel * self.unit, dt)
        advance(b, species.beat_hz * (0.6 + 0.4 * b.speed / (beat_speed * self.unit)), dt)
        deep = b.z > self.cam.mid
        if deep != was_deep:
            sx, sy, s = self.cam.to_screen(b.x, b.y, b.z)
            self._events.append(Dive(self.t, species.name, deep, sx, sy, s))

    # ------------------------------------------------------------------ roaming

    def _depth(self, f: float) -> float:
        return self.cam.near + f * (self.cam.far - self.cam.near)

    def _pick_waypoint(self, actor: Orca | Fish, roam: Roam) -> None:
        actor.deep = self.rng.random() < (roam.stay_deep if actor.deep else roam.go_deep)
        z = self._depth(self.rng.uniform(*(roam.deep if actor.deep else roam.shallow)))
        box = self.cam.frustum(z).inset(self.pad + 0.3 * self.orca_length)
        actor.waypoint = (self.rng.uniform(box.left, box.right), self.rng.uniform(box.top, box.bottom), z)
        actor.waypoint_age = 0.0

    def _roam(self, actor: Orca | Fish, roam: Roam, dt: float) -> Vec:
        """Toward the waypoint, the yaw wandering about it as a slow random process."""
        b = actor.body
        actor.waypoint_age += dt
        if (actor.waypoint is None or actor.waypoint_age > WAYPOINT_SECONDS
                or dist(b.pos, actor.waypoint) < WAYPOINT_REACH * self.orca_length):
            self._pick_waypoint(actor, roam)
        actor.wander += (-actor.wander / 1.5) * dt + 0.35 * math.sqrt(2 * dt / 1.5) * self.rng.gauss(0, 1)
        yaw, pitch = bearing(sub(actor.waypoint, b.pos))
        return direction(yaw + actor.wander, pitch)

    # ------------------------------------------------------------------ orca

    def _gap(self) -> float:
        """Distance between the orca and the salmon, centre to centre, in world px."""
        return dist(self.orca.body.pos, self.fish.body.pos)

    def _bearing_to_fish(self) -> Vec:
        return unit(sub(self.fish.body.pos, self.orca.body.pos))

    def _mouth(self) -> Vec:
        """Where the orca's mouth is in the world, as it is drawn."""
        place = self._orca_placement()
        mx, my = place.outline(0.0, 0.0)
        return float(mx), float(my), self.orca.body.z - place.depth(0.0) * self.orca_length

    def _contact(self) -> bool:
        """The orca's mouth, where it is drawn, is within the salmon's half-length of the salmon's centre.

        Only a head that points at the salmon, in yaw and pitch, with the spine
        straight behind it bites. Mid-turn the head sweeps past too fast to
        snap at anything, and counting it would make every turn a free catch.
        """
        o = self.orca
        if self._gap() > CONTACT_REACH * self.orca_length:
            return False
        yaw, pitch = bearing(self._bearing_to_fish())
        chain = o.body.att.yaw
        if (abs(wrap(chain[0] - yaw)) > CONTACT_ALIGN or abs(pitch - o.body.pitch) > CONTACT_ALIGN
                or abs(wrap(chain[-1] - chain[0])) > CONTACT_STRAIGHT):
            return False
        fx, fy = self._fish_placement().outline(0.5, 0.0)
        return dist(self._mouth(), (float(fx), float(fy), self.fish.body.z)) < 0.5 * self.fish_length

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
        return dot(o.body.heading, self._bearing_to_fish()) > math.cos(LUNGE_ALIGN)

    def _room_ahead(self, o: Orca, seconds: float = LUNGE_ROOM) -> bool:
        """Whether a lunge's straight path stays inside the frustum, with a little slack."""
        reach = ORCA_GAITS[OrcaMode.LUNGE].speed[1] * self.unit * seconds
        b = o.body
        hx, hy, hz = b.heading
        return self.cam.inside(b.x + hx * reach, b.y + hy * reach, b.z + hz * reach, 0.2 * self.orca_length)

    def _begin_orca_mode(self, mode: OrcaMode) -> None:
        o = self.orca
        o.mode, o.age = mode, 0.0
        o.speed_goal = self.rng.uniform(*ORCA_GAITS[mode].speed) * self.unit
        o.waypoint = None
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
            self._spawn_fish()

    def _catch(self) -> None:
        o, f = self.orca, self.fish
        self._emit("salmon", f.mode, FishMode.CAUGHT)
        self.fish = None
        self.salmon_front = None
        o.bubbles.burst(self._mouth(), o.body.velocity, self.rng)

    def _aim(self, lead: float) -> Vec:
        """Toward where the salmon will be if it keeps going, `lead` scaling how far ahead."""
        b, fb = self.orca.body, self.fish.body
        t = min(lead * self._gap() / max(b.speed, 200 * self.unit), 1.0)
        vx, vy, vz = fb.velocity
        return unit((fb.x + vx * t - b.x, fb.y + vy * t - b.y, fb.z + vz * t - b.z))

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
        elif gait.roam:
            want = self._roam(o, gait.roam, dt)
        else:
            want = b.heading
        target, boost = self._avoid(b, want, gait, o.speed_goal)
        facing = math.cos(b.yaw) >= 0
        self._advance(o, target, gait.turn * boost, gait, ORCA, ORCA_BEAT_SPEED, dt)
        if (math.cos(b.yaw) >= 0) != facing:
            self._events.append(Turn(self.t, math.sin(b.yaw) < 0))

        goal = 1.0 if o.mode is OrcaMode.LUNGE else 0.0
        rate = (JAW_OPEN_RATE if goal > o.jaw_open else JAW_CLOSE_RATE) * dt
        o.jaw_open += max(-rate, min(rate, goal - o.jaw_open))

        o.bubbles.emit(dt, self._vents, b.velocity, self.rng)
        o.bubbles.update(dt)

    def _vents(self) -> list[Vec]:
        place = self._orca_placement()
        pts = place.surface(*zip(*ORCA.vents))
        return [(float(x), float(y), self.orca.body.z - place.depth(u) * self.orca_length)
                for (x, y), (u, _) in zip(pts, ORCA.vents)]

    # ------------------------------------------------------------------ fish

    def _spawn_fish(self) -> None:
        """A new salmon swimming in, from just off a random edge or out of the haze, away from the orca.

        One from the haze comes out toward the viewer close to where it
        appeared, so it is not crossing the whole wide deep end of the frustum.
        """
        a, rng, cam = self.area, self.rng, self.cam
        off = 0.5 * self.fish_length + 30
        z = self._depth(rng.uniform(*FISH_GAITS[FishMode.WANDER].roam.shallow))
        box = cam.frustum(z).inset(self.pad + 0.3 * self.orca_length)

        def candidate() -> tuple[Vec, Vec]:
            if rng.random() < HAZE_ENTRY:
                z0 = cam.far * rng.uniform(*HAZE_DEPTH)
                sx = a.left + rng.uniform(0.2, 0.8) * (a.right - a.left)
                sy = a.top + rng.uniform(0.2, 0.8) * (a.bottom - a.top)
                gx, gy = cam.to_world(sx + rng.uniform(-300, 300), sy + rng.uniform(-200, 200), z)
                goal = (min(max(gx, box.left), box.right), min(max(gy, box.top), box.bottom), z)
            else:
                z0 = self._depth(rng.uniform(0.03, 0.2))
                side = rng.randrange(4)
                along = rng.uniform(0.15, 0.85)
                if side < 2:
                    sx, sy = (a.left - off if side == 0 else a.right + off), a.top + along * (a.bottom - a.top)
                else:
                    sx, sy = a.left + along * (a.right - a.left), (a.top - off if side == 2 else a.bottom + off)
                goal = (rng.uniform(box.left, box.right), rng.uniform(box.top, box.bottom), z)
            return (*cam.to_world(sx, sy, z0), z0), goal

        ob = self.orca.body
        start, goal = max((candidate() for _ in range(4)), key=lambda c: dist(c[0], ob.pos))
        body = Body.launch(*start, unit(sub(goal, start)))
        self.fish = Fish(body, FishMode.ENTER, goal)
        self._begin_fish_mode(FishMode.ENTER)
        self._emit("salmon", None, FishMode.ENTER)

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
                b = f.body
                if ((self.cam.inside(b.x, b.y, b.z, self.pad) and b.z < self._depth(FISH_FAR))
                        or dist(b.pos, f.waypoint) < WAYPOINT_REACH * self.orca_length):
                    return FishMode.WANDER
            case FishMode.WANDER:
                if hunted and self._gap() < reach:
                    return FishMode.FLEE
            case FishMode.FLEE:
                if not (hunted and self._gap() < reach):
                    return FishMode.WANDER
        return f.mode

    def _flee(self, f: Fish, dt: float) -> Vec:
        """Away from the orca, plus jittery dodges to either side, which may dive away or dart at the viewer.

        A salmon chased into the deep pulls back toward the front, the more
        the deeper it is, so the hunt stays where it can be seen.
        """
        f.dodge_left -= dt
        if f.dodge_left <= 0:
            f.dodge_left = self.rng.uniform(0.2, 0.5)
            f.dodge = self.rng.choice((-1, 1)) * self.rng.uniform(0.5, 1.0)
        yaw, pitch = bearing(sub(f.body.pos, self.orca.body.pos))
        ax, ay, az = direction(yaw + f.dodge, pitch)
        up = min(1.0, max(0.0, (f.body.z - self._depth(FISH_FAR)) / (0.25 * (self.cam.far - self.cam.near))))
        return unit((ax, ay, az - 1.5 * up))

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
            target = unit(sub(f.waypoint, b.pos))
        else:
            if f.mode is FishMode.FLEE:
                if f.age >= FLEE_REACTION:
                    close = max(0.0, 1.0 - self._gap() / (THREAT_RANGE * self.orca_length))
                    f.speed_goal = (gait.speed[0] + (gait.speed[1] - gait.speed[0]) * close) * self.unit
                want = self._flee(f, dt)
            else:
                want = self._roam(f, gait.roam, dt)
            target, boost = self._avoid(b, want, gait, f.speed_goal)
        self._advance(f, target, gait.turn * boost, gait, SALMON, FISH_BEAT_SPEED, dt)
