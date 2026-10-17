"""Bodies, steering and how a heading becomes a side-view pose. No actor knowledge."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, NamedTuple

STEER_GAIN = 4.0  # 1/s; turn rate is proportional to the heading error, then capped
FLIP_SECONDS = 0.35
FLIP_DEADBAND = 0.15  # cos(heading) must point this far the other way before the sprite flips
MAX_PITCH = math.radians(55)
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
class Body:
    x: float  # px, centre of the spine
    y: float
    heading: float  # radians in screen space (y down), free to point anywhere
    speed: float  # px/s
    phase: float = 0.0  # tail-beat cycles
    facing: int = 1  # side the sprite shows: +1 right, -1 left
    turn: float = 1.0  # flip progress, 1 when not flipping


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def steer(body: Body, target_heading: float, max_turn_rate: float, dt: float) -> None:
    rate = wrap(target_heading - body.heading) * STEER_GAIN
    rate = max(-max_turn_rate, min(max_turn_rate, rate))
    body.heading = wrap(body.heading + rate * dt)


def accelerate(body: Body, target_speed: float, accel: float, dt: float) -> None:
    step = accel * dt
    body.speed += max(-step, min(step, target_speed - body.speed))


def advance(body: Body, beat_hz: float, dt: float) -> None:
    body.x += math.cos(body.heading) * body.speed * dt
    body.y += math.sin(body.heading) * body.speed * dt
    body.phase += beat_hz * dt
    if body.turn < 1.0:
        body.turn = min(1.0, body.turn + dt / FLIP_SECONDS)
    elif math.cos(body.heading) * body.facing < -FLIP_DEADBAND:
        body.facing = -body.facing
        body.turn = 0.0


def avoid_edges(body: Body, target_heading: float, area: Rect, margin: float) -> tuple[float, float]:
    """Bend target_heading so the body slides along an edge and then away from it.

    Returns the heading and a turn-rate multiplier. Only a target that points at
    an edge is changed: it becomes the edge's tangent on the side the body
    already leans toward (the middle breaks a head-on tie), tilted inward more
    the deeper the body is inside `margin`. The multiplier rises with depth so
    a late turn is tighter, as an animal in a hurry would.
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
    if math.cos(target_heading) * nx + math.sin(target_heading) * ny >= 0:
        return target_heading, boost
    lean = math.sin(body.heading) * nx - math.cos(body.heading) * ny
    mx, my = (area.left + area.right) / 2 - body.x, (area.top + area.bottom) / 2 - body.y
    lean += 0.35 * (my * nx - mx * ny) / (math.hypot(mx, my) or 1.0)
    side = 1.0 if lean >= 0 else -1.0
    return math.atan2(side * nx + EDGE_TILT * d * ny, -side * ny + EDGE_TILT * d * nx), boost


def view(body: Body) -> tuple[float, float]:
    """Signed horizontal scale and nose-up pitch to draw the body with.

    Sprites are side views and must never be upside down, so the heading is
    folded into the facing half-plane and the pitch clamped. A flip scales the
    sprite 1 -> 0 -> -1 with a cosine ease: the animal turns toward the viewer.
    """
    xscale = -body.facing * math.cos(math.pi * body.turn)
    pitch = math.atan2(-math.sin(body.heading), abs(math.cos(body.heading)))
    return xscale, max(-MAX_PITCH, min(MAX_PITCH, pitch))


def projector(origin: tuple[float, float], length: float, xscale: float, pitch: float) -> Callable[[float, float], tuple[float, float]]:
    """Map spine-space (length units, nose at x=0) to the plane around `origin`.

    The body's centre is lx = 0.5. A negative xscale mirrors the animal.
    """
    c, s = math.cos(pitch), math.sin(pitch)
    ox, oy = origin

    def project(lx: float, ly: float) -> tuple[float, float]:
        x, y = (0.5 - lx) * length, ly * length
        return ox + xscale * (x * c + y * s), oy + (y * c - x * s)

    return project
