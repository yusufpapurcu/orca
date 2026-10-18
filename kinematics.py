"""Bodies, steering and the attitude of a swimmer in 3D. No actor knowledge.

A body has a position in the world, a speed and a heading: a yaw in the
(x, depth) plane and a pitch. Steering turns the heading toward a target
direction under a rate cap. The attitude is the yaw as drawn along the spine:
the head springs after the body's yaw and each node follows the one before
it, so a turn is a curve through depth, and the animal banks with the yaw
rate. Nothing is a timer; a turn is just the heading swinging round.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from projection import NODES, Camera, Pose, Spin

STEER_GAIN = 4.0  # 1/s; yaw and pitch follow the target at this gain, then are capped
OMEGA0, OMEGA1 = 3.5, 1.6  # yaw spring: natural frequency = OMEGA0 + OMEGA1 * turn rate (1/s)
BODY_LAG = 0.26  # seconds the tail lags the head in yaw
BANK_MAX = math.radians(38)
BANK_RATE_REF = 1.6  # head yaw rate (rad/s) at which the roll is nearly full
BANK_SECONDS = 0.10
SETTLED = 0.25  # radians the head and tail may be off the body's yaw for the attitude to count as settled
MAX_PITCH = math.radians(55)
BRAKE = 3.0
EDGE_TILT = 2.0
EDGE_URGENCY = 2.0
EDGE_REVERSE = -0.17  # cos of the angle beyond which a way out is a reversal, to be turned through the inside
EDGE_SIDE = 4.0  # pads from a screen edge within which it decides which way round a reversal turns

Vec = tuple[float, float, float]


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def direction(yaw: float, pitch: float) -> Vec:
    """Unit vector of a heading: yaw 0 is +x, pi / 2 is into the screen, pitch is nose up."""
    c = math.cos(pitch)
    return c * math.cos(yaw), -math.sin(pitch), c * math.sin(yaw)


def bearing(v: Vec) -> tuple[float, float]:
    """Yaw and pitch of a direction."""
    x, y, z = v
    return math.atan2(z, x), math.atan2(-y, math.hypot(x, z))


def unit(v: Vec) -> Vec:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-9 else (1.0, 0.0, 0.0)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a: Vec, b: Vec) -> Vec:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def dist(a: Vec, b: Vec) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


@dataclass
class Attitude:
    """The yaw chain and roll of a swimmer: its pose as drawn.

    The head springs toward the body's yaw, the nodes down the spine follow the
    one before them, and the roll follows the head's yaw rate.
    """

    yaw: list[float] = field(default_factory=lambda: [0.0] * NODES)
    rate: float = 0.0  # head yaw rate, rad/s
    bank: float = 0.0
    agility: float = 1.0  # the steering turn-rate cap, which also stiffens the yaw spring

    @staticmethod
    def facing(yaw: float) -> "Attitude":
        return Attitude([yaw] * NODES)

    @property
    def spin(self) -> Spin:
        return Spin(tuple(self.yaw), self.bank)

    def settled(self, yaw: float) -> bool:
        return abs(wrap(self.yaw[0] - yaw)) < SETTLED and abs(wrap(self.yaw[-1] - yaw)) < SETTLED

    def advance(self, yaw: float, dt: float) -> None:
        """Yaw the head toward `yaw` with a critically damped spring and let each node follow the one before it."""
        omega = OMEGA0 + OMEGA1 * self.agility
        err = wrap(yaw - self.yaw[0])
        self.rate += (omega * omega * err - 2 * omega * self.rate) * dt
        self.yaw[0] += self.rate * dt
        keep = 1.0 - math.exp(-dt * (NODES - 1) / BODY_LAG)
        for i in range(1, NODES):
            self.yaw[i] += (self.yaw[i - 1] - self.yaw[i]) * keep
        goal = BANK_MAX * math.tanh(self.rate / BANK_RATE_REF)
        self.bank += (goal - self.bank) * (1.0 - math.exp(-dt / BANK_SECONDS))


@dataclass
class Body:
    """A swimmer in the world.

    x, y, z is the centre of the spine in world px (z positive away from the
    viewer). `yaw` and `pitch` are the heading steering works with; the
    attitude's yaw chain trails them, and the body moves along its drawn
    head, so a turning animal goes where its head is seen to point.
    """

    x: float
    y: float
    z: float
    speed: float  # px/s
    yaw: float = 0.0
    pitch: float = 0.0  # nose up positive, radians
    phase: float = 0.0  # tail-beat cycles
    att: Attitude = field(default_factory=Attitude)

    @staticmethod
    def launch(x: float, y: float, z: float, toward: Vec, speed: float = 0.0) -> "Body":
        yaw, pitch = bearing(toward)
        return Body(x, y, z, speed, yaw, pitch, 0.0, Attitude.facing(yaw))

    @property
    def pos(self) -> Vec:
        return self.x, self.y, self.z

    @property
    def heading(self) -> Vec:
        return direction(self.yaw, self.pitch)

    @property
    def velocity(self) -> Vec:
        vx, vy, vz = direction(self.att.yaw[0], self.pitch)
        return vx * self.speed, vy * self.speed, vz * self.speed

    @property
    def settled(self) -> bool:
        return self.att.settled(self.yaw)

    def pose(self, pitch_extra: float = 0.0, jaw_open: float = 0.0) -> Pose:
        """The pose to draw. Sprites are side views and never go upside down, so the pitch is clamped."""
        pitch = max(-MAX_PITCH, min(MAX_PITCH, self.pitch))
        return Pose(self.phase, pitch + pitch_extra, self.att.spin, jaw_open)


def steer(body: Body, target: Vec, max_turn_rate: float, dt: float) -> None:
    """Turn the heading toward `target`, yaw the short way round, each under the rate cap."""
    body.att.agility = max_turn_rate
    yaw, pitch = bearing(target)
    rate = max(-max_turn_rate, min(max_turn_rate, wrap(yaw - body.yaw) * STEER_GAIN))
    body.yaw = wrap(body.yaw + rate * dt)
    rate = max(-max_turn_rate, min(max_turn_rate, (pitch - body.pitch) * STEER_GAIN))
    body.pitch = max(-math.pi / 2, min(math.pi / 2, body.pitch + rate * dt))


def accelerate(body: Body, target_speed: float, accel: float, dt: float) -> None:
    """Move speed toward the target. Animals brake harder than they accelerate."""
    err = target_speed - body.speed
    step = accel * dt * (1.0 if err > 0 else BRAKE)
    body.speed += max(-step, min(step, err))


def advance(body: Body, beat_hz: float, dt: float) -> None:
    body.att.advance(body.yaw, dt)
    vx, vy, vz = body.velocity
    body.x += vx * dt
    body.y += vy * dt
    body.z += vz * dt
    body.phase += beat_hz * dt


def _along(v: Vec, n: Vec) -> Vec:
    """The part of v along a wall whose inward normal is n."""
    k = dot(v, n)
    return v[0] - k * n[0], v[1] - k * n[1], v[2] - k * n[2]


def _slide(v: Vec, walls: list[tuple[float, Vec]]) -> Vec:
    """v with its part into each wall taken out, by the wall's weight, twice over so a corner holds."""
    for _ in range(2):
        for w, n in walls:
            k = dot(v, n)
            if k < 0:
                v = (v[0] - w * k * n[0], v[1] - w * k * n[1], v[2] - w * k * n[2])
    return v


def avoid_edges(body: Body, target: Vec, cam: Camera, seconds: float, pad: float, speed: float) -> tuple[Vec, float]:
    """Bend `target` so the body slides along a wall of the frustum and then away from it.

    The body is looked at `seconds` ahead along its motion, at `speed` if that
    is more than it is doing. A wall counts, more the further that point is
    inside `pad` of it, and only when the target or the body points at a wall
    that counts does anything change. The target then keeps only its part
    along the walls (or the body's own lean along them, nudged toward the
    middle, when it points straight in), tilted inward more the nearer the body
    is to the worst wall. In a corner the tilt is along the bisector of the
    walls, which points into the wedge however they lean. A way out that is
    nearly a reversal is reached by turning square to the heading first, on
    the side the nearest screen edges favour, since the short way round could
    be through one of them. Returns the direction and a turn-rate multiplier
    that rises with that nearness, so a late turn is tighter, as an animal
    in a hurry would.
    """
    reach = max(body.speed, speed) * seconds
    h = unit(body.velocity) if body.speed > 1e-6 else body.heading
    walls = sorted(((min((pad - d) / pad, 1.0), n) for d, n
                    in cam.clearance(body.x + h[0] * reach, body.y + h[1] * reach, body.z + h[2] * reach) if d < pad),
                   reverse=True)
    if not walls:
        return target, 1.0
    worst = max(pad - d for d, _ in cam.clearance(body.x + h[0] * reach, body.y + h[1] * reach, body.z + h[2] * reach))
    d = min(worst / reach, 1.0) if reach > 1e-6 else 1.0
    boost = 1.0 + EDGE_URGENCY * d
    out = unit((sum(w * n[0] for w, n in walls), sum(w * n[1] for w, n in walls), sum(w * n[2] for w, n in walls)))
    # Which way round a reversal goes is decided by the screen edges near the body, not by the walls the
    # lookahead point crosses: those move with the heading, and a choice that moves with the heading chatters.
    side = (0.0, 0.0, 0.0)
    for dist_, n in cam.clearance(body.x, body.y, body.z):
        if abs(n[2]) < 0.99:
            w = min(max(1.0 - dist_ / (EDGE_SIDE * pad), 0.0), 1.0)
            side = (side[0] + w * n[0], side[1] + w * n[1], side[2] + w * n[2])
    if all(dot(target, n) >= 0 for _, n in walls) and all(dot(h, n) >= 0 for _, n in walls):
        return _through_inside(target, h, side, out), boost
    t = _slide(target, walls)
    if dot(t, t) < 0.05:
        mx, my = cam.area.center
        c = unit((mx - body.x, my - body.y, cam.mid - body.z))
        lean, bias = _slide(h, walls), _slide(c, walls)
        t = (lean[0] + 0.35 * bias[0], lean[1] + 0.35 * bias[1], lean[2] + 0.35 * bias[2])
        if dot(t, t) < 1e-6:
            t = _slide((0.0, 0.0, 1.0) if abs(out[2]) < 0.9 else (1.0, 0.0, 0.0), walls)
    t = unit(t)
    way = unit((t[0] + EDGE_TILT * d * out[0], t[1] + EDGE_TILT * d * out[1], t[2] + EDGE_TILT * d * out[2]))
    return _through_inside(way, h, side, out), boost


def _through_inside(way: Vec, h: Vec, side: Vec, out: Vec) -> Vec:
    """`way`, unless it is nearly a reversal of the heading `h`: then the first leg of the turn.

    Of the two directions square to the heading, the one that agrees with
    `side`, the inward pull of the screen edges near the body. The near and
    far limits are soft, a screen edge is not. The tilt `out` adds the climb
    or dive and keeps the leg on the inside.
    """
    if dot(way, h) >= EDGE_REVERSE:
        return way
    left, right = (-h[2], 0.0, h[0]), (h[2], 0.0, -h[0])
    p = left if dot(left, side) >= dot(right, side) else right
    return unit((p[0] + 0.5 * out[0], out[1], p[2] + 0.5 * out[2]))
