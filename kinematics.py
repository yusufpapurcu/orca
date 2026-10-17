"""Bodies, steering and the 3D attitude of a swimmer. No actor knowledge.

A body swims in a plane the screen sees from the side. To turn around it yaws
through depth: the head swings toward k * pi, the spine follows a moment later,
and the animal banks into the turn. Nothing is a timer; the turn is the spring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import NamedTuple

from projection import NODES, Pose, Spin

STEER_GAIN = 4.0  # 1/s; pitch follows the target's climb at this gain, then is capped
FLIP_DEADBAND = 0.15  # cos(heading) must point this far behind before the animal turns around
FLIP_COOLDOWN = 0.9  # seconds before a half-hearted target may turn it around again
FLIP_FORCE = 0.6  # ... unless the target points this firmly the other way
OMEGA0, OMEGA1 = 2.0, 1.6  # yaw spring: natural frequency = OMEGA0 + OMEGA1 * turn rate (1/s)
BODY_LAG = 0.26  # seconds the tail lags the head in yaw
BANK_MAX = math.radians(38)
BANK_RATE_REF = 3.5  # yaw rate (rad/s) at which the roll is nearly full
BANK_SECONDS = 0.10
Z_ARC = 0.6  # how far the middle of the body bulges toward or away from the viewer in a half turn
MAX_PITCH = math.radians(55)
BRAKE = 3.0
EDGE_TILT = 2.0
EDGE_URGENCY = 2.0


class Rect(NamedTuple):
    left: float
    top: float
    right: float
    bottom: float

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def inset(self, m: float) -> "Rect":
        return Rect(self.left + m, self.top + m, self.right - m, self.bottom - m)


@dataclass
class Attitude:
    """Yaw chain, roll and depth of a swimmer: the one owner of its 3D pose.

    The committed goal is k * pi, even k facing right and odd k facing left.
    Depth is not state. It is the arc a half turn sweeps, sin(yaw) at the middle
    of the body, so the animal is back in its swimming plane the moment the
    turn ends and size changes belong to the turn.
    """

    k: int = 0
    yaw: list[float] = field(default_factory=lambda: [0.0] * NODES)
    rate: float = 0.0  # head yaw rate, rad/s
    bank: float = 0.0
    agility: float = 1.0  # the steering turn-rate cap, which also stiffens the yaw spring
    cooldown: float = 0.0
    dip: int = 1  # which side of depth the next turn from rest bulges toward: +1 viewer, -1 away

    @staticmethod
    def facing(k: int) -> "Attitude":
        return Attitude(k, [k * math.pi] * NODES)

    @property
    def side(self) -> int:
        return 1 if self.k % 2 == 0 else -1

    @property
    def z(self) -> float:
        return Z_ARC * math.sin(self.yaw[NODES // 2])

    @property
    def turning(self) -> bool:
        goal = self.k * math.pi
        return abs(self.yaw[0] - goal) > 0.25 or abs(self.yaw[-1] - goal) > 0.25

    @property
    def spin(self) -> Spin:
        return Spin(tuple(self.yaw), self.z, self.bank)

    def reverse(self) -> None:
        """Commit to the other side. Mid-turn that is the nearer one, otherwise the turn alternates its depth bulge."""
        head = self.yaw[0]
        if abs(head - self.k * math.pi) > 0.35:
            self.k = min((self.k - 1, self.k + 1), key=lambda k: abs(head - k * math.pi))
        else:
            # sin(yaw) between k * pi and (k + d) * pi has the sign of d * (-1) ** k
            self.k += self.dip * (-1) ** self.k
            self.dip = -self.dip
        self.cooldown = FLIP_COOLDOWN

    def advance(self, dt: float) -> None:
        """Yaw the head with a critically damped spring and let each node follow the one before it."""
        omega = OMEGA0 + OMEGA1 * self.agility
        err = self.k * math.pi - self.yaw[0]
        self.rate += (omega * omega * err - 2 * omega * self.rate) * dt
        self.yaw[0] += self.rate * dt
        keep = 1.0 - math.exp(-dt * (NODES - 1) / BODY_LAG)
        for i in range(1, NODES):
            self.yaw[i] += (self.yaw[i - 1] - self.yaw[i]) * keep
        goal = BANK_MAX * math.tanh(self.rate / BANK_RATE_REF)
        self.bank += (goal - self.bank) * (1.0 - math.exp(-dt / BANK_SECONDS))


@dataclass
class Body:
    """A swimmer in 3D that the screen sees from the side.

    x, y is the centre of the spine in the swimming plane. The yaw and depth
    live in the attitude. `heading` is the screen direction the animal is
    committed to, which steering and targeting work with.
    """

    x: float  # px
    y: float
    speed: float  # px/s
    phase: float = 0.0  # tail-beat cycles
    pitch: float = 0.0  # nose up positive, radians
    att: Attitude = field(default_factory=Attitude)

    @staticmethod
    def launch(x: float, y: float, heading: float, speed: float = 0.0) -> "Body":
        pitch = math.atan2(-math.sin(heading), abs(math.cos(heading)))
        return Body(x, y, speed, 0.0, pitch, Attitude.facing(0 if math.cos(heading) >= 0 else 1))

    @property
    def heading(self) -> float:
        return math.atan2(-math.sin(self.pitch), self.att.side * math.cos(self.pitch))

    @property
    def vx(self) -> float:
        """The speed is along the real 3D heading, so the sideways part of a turn leaves less for x."""
        return self.speed * math.cos(self.pitch) * math.cos(self.att.yaw[NODES // 2])

    @property
    def vy(self) -> float:
        return -self.speed * math.sin(self.pitch)

    def pose(self, pitch_extra: float = 0.0, jaw_open: float = 0.0) -> Pose:
        """The pose to draw. Sprites are side views and never go upside down, so the pitch is clamped."""
        pitch = max(-MAX_PITCH, min(MAX_PITCH, self.pitch))
        return Pose(self.phase, pitch + pitch_extra, self.att.spin, jaw_open)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def steer(body: Body, target_heading: float, max_turn_rate: float, dt: float) -> None:
    """Pitch follows the target's climb at the usual rate. A target behind starts a turn through depth."""
    att = body.att
    att.agility = max_turn_rate
    att.cooldown -= dt
    cx = math.cos(target_heading)
    if cx * att.side < -FLIP_DEADBAND and (att.cooldown <= 0 or cx * att.side < -FLIP_FORCE):
        att.reverse()
    want = math.atan2(-math.sin(target_heading), abs(cx))
    rate = max(-max_turn_rate, min(max_turn_rate, (want - body.pitch) * STEER_GAIN))
    body.pitch = max(-math.pi / 2, min(math.pi / 2, body.pitch + rate * dt))


def accelerate(body: Body, target_speed: float, accel: float, dt: float) -> None:
    """Move speed toward the target. Animals brake harder than they accelerate."""
    err = target_speed - body.speed
    step = accel * dt * (1.0 if err > 0 else BRAKE)
    body.speed += max(-step, min(step, err))


def advance(body: Body, beat_hz: float, dt: float) -> None:
    body.att.advance(dt)
    body.x += body.vx * dt
    body.y += body.vy * dt
    body.phase += beat_hz * dt


def avoid_edges(body: Body, target_heading: float, area: Rect, margin: float) -> tuple[float, float]:
    """Bend target_heading so the body slides along an edge and then away from it.

    Returns the heading and a turn-rate multiplier. Only a target, or a body,
    that points at an edge triggers it. The target then becomes the edge's
    tangent on the side the body already leans toward (the middle breaks a
    head-on tie), tilted inward more the deeper the body is inside `margin`.
    The multiplier rises with depth so a late turn is tighter, as an animal
    in a hurry would.
    """
    def depth(c: float, lo: float, hi: float) -> float:
        return max(0.0, (lo + margin - c) / margin) - max(0.0, (c - (hi - margin)) / margin)

    px, py = depth(body.x, area.left, area.right), depth(body.y, area.top, area.bottom)
    d = math.hypot(px, py)
    if d == 0:
        return target_heading, 1.0
    d = min(d, 1.0)
    nx, ny = px / math.hypot(px, py), py / math.hypot(px, py)
    boost = 1.0 + EDGE_URGENCY * d
    if (math.cos(target_heading) * nx + math.sin(target_heading) * ny >= 0
            and math.cos(body.heading) * nx + math.sin(body.heading) * ny >= 0):
        return target_heading, boost
    lean = math.sin(body.heading) * nx - math.cos(body.heading) * ny
    mx, my = (area.left + area.right) / 2 - body.x, (area.top + area.bottom) / 2 - body.y
    lean += 0.35 * (my * nx - mx * ny) / (math.hypot(mx, my) or 1.0)
    side = 1.0 if lean >= 0 else -1.0
    return math.atan2(side * nx + EDGE_TILT * d * ny, -side * ny + EDGE_TILT * d * nx), boost
