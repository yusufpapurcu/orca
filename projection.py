"""Where a posed animal lands on the screen.

One Camera maps the world to pixels. World x and y are px measured at the
screen plane, z is depth in the same px, positive away from the viewer. A point
at depth z is drawn at scale F / (F + z) about the vanishing point, so what the
screen sees is a frustum: at depth z the world box that maps onto the work
area is 1 / s(z) wider. Nothing else does perspective arithmetic.

The Placement is the single mapping from a pose in 3D to pixels. Everything
that needs a point on an animal (the drawing, the bubble vents, the nose that
touches the fish) goes through it, so they cannot disagree.

Yaw lives in the (x, depth) plane as an unwrapped angle: 0 faces right, pi
faces left, pi / 2 faces straight into the screen and -pi / 2 straight at the
viewer. The head's yaw leads and the angles further down the spine lag, so the
body is a curve in depth.

Every mapping takes numpy arrays, a whole part at a time, or plain floats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache, cached_property
from typing import NamedTuple

import numpy as np

from anatomy import Rig

NODES = 5  # yaw samples along the spine, nose to tail
TABLE = 33  # integration samples along the spine (odd, so the middle is exact)

S_NEAR = 1.15  # scale at the near limit of the world, toward the viewer
S_FAR = 0.35  # scale at the far limit
FOCAL = 1.4  # the camera's distance from the screen plane, in orca lengths: how fast size falls off with depth
HAZE = (84, 128, 172)
HAZE_FAR = 0.6  # how far colours go toward the haze at the far limit
FADE_FAR = 0.55  # opacity at the far limit
FADE_OUT = 1.35  # depth, in far limits, at which an animal has faded out altogether

PERSP_NEAR = 0.27  # extra size at depth +1 (toward the viewer)
PERSP_FAR = 0.20  # size lost at depth -1
PERSP_BODY = 0.5  # how much of the body's own depth shows as perspective along it
DEPTH_UNIT = 0.45  # body lengths that one unit of depth spans along the body
CAM = 0.18  # screen drop per unit depth, in body lengths: the camera looks slightly down
WIDTH = 0.95  # body width as a share of its height
PERSP_CLAMP = 1.7
SURFACE_STEPS = 64  # yaw samples along the spine for placing markings

NODE_AT = np.linspace(0.0, 1.0, NODES)
TABLE_AT = np.linspace(0.0, 1.0, TABLE)
SURFACE_AT = np.linspace(0.0, 1.0, SURFACE_STEPS + 1)


class Rect(NamedTuple):
    left: float
    top: float
    right: float
    bottom: float

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def inset(self, m: float) -> "Rect":
        return Rect(self.left + m, self.top + m, self.right - m, self.bottom - m)

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.right) / 2, (self.top + self.bottom) / 2


@dataclass(frozen=True)
class Camera:
    """The perspective: world (x, y, z) to screen pixels and the scale there.

    The vanishing point is the middle of the work area. Depth runs from `near`
    (slightly toward the viewer, S_NEAR) to `far` (deep in the haze, S_FAR).
    """

    area: Rect
    focal: float  # px

    @property
    def near(self) -> float:
        return self.focal * (1.0 / S_NEAR - 1.0)

    @property
    def far(self) -> float:
        return self.focal * (1.0 / S_FAR - 1.0)

    @property
    def mid(self) -> float:
        return (self.near + self.far) / 2

    def scale(self, z):
        return self.focal / (self.focal + z)

    def to_screen(self, x, y, z):
        """Screen x, y and the scale at that depth."""
        vx, vy = self.area.center
        s = self.scale(z)
        return vx + s * (x - vx), vy + s * (y - vy), s

    def to_world(self, sx: float, sy: float, z: float) -> tuple[float, float]:
        vx, vy = self.area.center
        s = self.scale(z)
        return vx + (sx - vx) / s, vy + (sy - vy) / s

    def frustum(self, z: float) -> Rect:
        """The world box at depth z that maps onto the work area."""
        vx, vy = self.area.center
        k = 1.0 / self.scale(z)
        a = self.area
        return Rect(vx + (a.left - vx) * k, vy + (a.top - vy) * k, vx + (a.right - vx) * k, vy + (a.bottom - vy) * k)

    @cached_property
    def walls(self) -> tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...]:
        """The six planes of the visible volume as (a point on the plane, inward unit normal).

        The side walls slant outward with depth, so their normals lean into the
        screen: sliding along one while swimming toward the viewer means
        closing in on the middle as the view narrows.
        """
        vx, vy = self.area.center
        a, f = self.area, self.focal

        def plane(point, normal):
            n = math.sqrt(sum(c * c for c in normal))
            return point, tuple(c / n for c in normal)

        return (
            plane((a.left, 0.0, 0.0), (1.0, 0.0, (vx - a.left) / f)),
            plane((a.right, 0.0, 0.0), (-1.0, 0.0, (a.right - vx) / f)),
            plane((0.0, a.top, 0.0), (0.0, 1.0, (vy - a.top) / f)),
            plane((0.0, a.bottom, 0.0), (0.0, -1.0, (a.bottom - vy) / f)),
            plane((0.0, 0.0, self.near), (0.0, 0.0, 1.0)),
            plane((0.0, 0.0, self.far), (0.0, 0.0, -1.0)),
        )

    def clearance(self, x: float, y: float, z: float) -> list[tuple[float, tuple[float, float, float]]]:
        """Signed distance inside each wall, with the wall's inward normal."""
        return [((x - px) * n[0] + (y - py) * n[1] + (z - pz) * n[2], n) for (px, py, pz), n in self.walls]

    def inside(self, x: float, y: float, z: float, pad: float = 0.0) -> bool:
        return all(d >= pad for d, _ in self.clearance(x, y, z))

    def haze(self, z: float) -> float:
        return HAZE_FAR * min(1.0, max(0.0, z / self.far))

    def fade(self, z: float) -> float:
        k = z / self.far
        if k <= 1.0:
            return min(1.0, 1.0 - (1.0 - FADE_FAR) * k)
        return max(0.0, FADE_FAR * (FADE_OUT - k) / (FADE_OUT - 1.0))


@dataclass(frozen=True)
class Spin:
    yaw: tuple[float, ...]  # unwrapped heading in the (x, depth) plane at each node
    bank: float = 0.0  # signed roll: positive tips the back toward the inside of a positive yaw rate

    @staticmethod
    def flat() -> "Spin":
        return Spin((0.0,) * NODES)

    def at(self, u):
        return np.interp(u, NODE_AT, self.yaw)


@dataclass(frozen=True)
class Pose:
    """Everything the drawing and the anchors need to know about one animal."""

    phase: float
    pitch: float  # nose up positive
    spin: Spin
    jaw_open: float = 0.0  # 0 closed .. 1 fully open

    @staticmethod
    def side(phase: float, jaw_open: float = 0.0) -> "Pose":
        return Pose(phase, 0.0, Spin.flat(), jaw_open)


@cache
def radius_table(profile) -> tuple[np.ndarray, np.ndarray]:
    us = np.linspace(0.0, 1.0, 257)
    return (np.array([max(-profile.rim_v(u, -1), 0.0) for u in us]),
            np.array([max(profile.rim_v(u, 1), 0.0) for u in us]))


def radii(profile, u):
    rd, rv = radius_table(profile)
    grid = np.linspace(0.0, 1.0, len(rd))
    return np.interp(u, grid, rd), np.interp(u, grid, rv)


class Projector:
    """Map spine space (u along, v across, in body lengths) to the screen.

    `dx` is an extra horizontal offset in body lengths, how a point off the
    spine's plane (a flank, a fin leaning with the bank) shows up when yawed.
    The body's own depth extent shows as perspective along it, on top of the
    camera's scale, which is already in `length`.
    """

    def __init__(self, spin: Spin, pitch: float, length: float, origin: tuple[float, float]):
        h = 1.0 / (TABLE - 1)
        psi = spin.at(TABLE_AT)
        self.cs, self.ss = np.cos(psi), np.sin(psi)
        self.ic = np.concatenate(([0.0], np.cumsum(0.5 * h * (self.cs[1:] + self.cs[:-1]))))
        self.isn = np.concatenate(([0.0], np.cumsum(0.5 * h * (self.ss[1:] + self.ss[:-1]))))
        mid = (TABLE - 1) // 2
        self.icm, self.ism = self.ic[mid], self.isn[mid]
        self.c, self.s = math.cos(pitch), math.sin(pitch)
        self.length = length
        self.ox, self.oy = origin

    def __call__(self, bx, by, dx=0.0) -> np.ndarray:
        bx, by = np.asarray(bx, dtype=float), np.asarray(by, dtype=float)
        # Past either end the body carries straight on along its end yaw.
        lo, hi = np.minimum(bx, 0.0), np.maximum(bx - 1.0, 0.0)
        ci = np.interp(bx, TABLE_AT, self.ic) + lo * self.cs[0] + hi * self.cs[-1]
        si = np.interp(bx, TABLE_AT, self.isn) + lo * self.ss[0] + hi * self.ss[-1]
        ca = np.interp(bx, TABLE_AT, self.cs)
        x = ((self.icm - ci) * self.c + ca * by * self.s + dx) * self.length
        y = (by * self.c - (0.5 - bx) * self.s) * self.length
        zp = np.clip(PERSP_BODY * (si - self.ism) / DEPTH_UNIT, -PERSP_CLAMP, PERSP_CLAMP)
        p = 1.0 + np.where(zp > 0, PERSP_NEAR * zp, PERSP_FAR * zp)
        return np.stack([self.ox + p * x, self.oy + p * y + CAM * zp * self.length], axis=-1)

    def depth(self, u: float) -> float:
        """How far toward the viewer the spine is at u, from the middle of the body, in body lengths."""
        return float(self.isn[min(int(u * (TABLE - 1) + 0.5), TABLE - 1)] - self.ism)


def tint(color: tuple[int, int, int, int], k: float) -> tuple[int, int, int, int]:
    """Water haze: `k` of the way from the colour to a pale blue, so far away the colours lose contrast."""
    if k <= 0.01:
        return color
    k = min(k, 1.0)
    r, g, b, a = color
    return (round(r + (HAZE[0] - r) * k), round(g + (HAZE[1] - g) * k), round(b + (HAZE[2] - b) * k), a)


class Placement:
    """One animal's pose set down at a scale: body space in, px out.

    `length` is the body length in the px the output is in, so the Camera's
    scale goes in here. `haze` is how far the colours go toward the water.
    """

    def __init__(self, rig: Rig, pose: Pose, length: float, origin: tuple[float, float], haze: float = 0.0):
        self.rig, self.pose, self.haze = rig, pose, haze
        self.project = Projector(pose.spin, pose.pitch, length, origin)
        self.depth = self.project.depth
        spin = pose.spin
        psi = spin.at(SURFACE_AT)
        self._cp, self._sp = np.cos(psi), np.sin(psi)
        self._rolled = abs(spin.bank) >= 0.004 or bool(np.abs(self._sp).max() >= 0.004)

    def outline(self, u, v) -> np.ndarray:
        """Points of the silhouette: they stay on the outline however the body is rolled."""
        return self.project(*self.rig.bend(np.asarray(u, dtype=float), np.asarray(v, dtype=float), self.pose.phase))

    def surface(self, u, v) -> np.ndarray:
        """Points on the round body, so a marking slides around it when the body rolls.

        Marks are painted at (u, v), v being height across the body. A roll slides
        them around the round body: a mark on the flank at surface angle th goes to
        th + phi, phi being how far the back tips toward the viewer. Points on the
        outline stay on it. The yaw pushes a mark toward the viewer-facing flank's
        lateral offset, which shows up as a horizontal shift.
        """
        if not self._rolled:
            return self.outline(u, v)
        u, v = np.asarray(u, dtype=float), np.asarray(v, dtype=float)
        j = np.clip(np.floor(u * SURFACE_STEPS + 0.5), 0, SURFACE_STEPS).astype(int)
        cp, sp = self._cp[j], self._sp[j]
        rd, rv = radii(self.rig.species.profile, u)
        r = np.where(v < 0, rd, rv)
        f = np.where(r > 1e-6, v / np.maximum(r, 1e-6), 0.0)
        rim = np.abs(f) >= 0.985
        th = np.clip(np.arcsin(np.clip(f, -1.0, 1.0)) - self.pose.spin.bank * cp, -1.5707, 1.5707)
        f2 = np.sin(th)
        v2 = np.where(rim, v, f2 * np.where(f2 > 0, rv, rd))
        dx = np.where(rim, 0.0, sp * cp * WIDTH * 0.5 * (rd + rv) * np.cos(th))
        return self.project(*self.rig.bend(u, v2, self.pose.phase), dx)

    def lateral(self, u, v, side: int, reach=1.0) -> np.ndarray:
        """Points on the right (+1) or left (-1) flank, `reach` of the way out from the spine.

        Seen end-on the two flanks are the two sides of the head, where the mouth
        and teeth sit, and a roll lifts one flank while it drops the other.
        """
        spin = self.pose.spin
        u, v = np.asarray(u, dtype=float), np.asarray(v, dtype=float)
        rd, rv = radii(self.rig.species.profile, u)
        r = np.where(v < 0, rd, rv)
        th = np.arcsin(np.clip(np.where(r > 1e-6, v / np.maximum(r, 1e-6), 0.0), -1.0, 1.0))
        psi = spin.at(u)
        th2 = np.clip(th - side * spin.bank * np.cos(psi), -1.5707, 1.5707)
        v2 = np.sin(th2) * np.where(th2 > 0, rv, rd)
        dx = side * np.sin(psi) * WIDTH * 0.5 * (rd + rv) * np.cos(th2) * reach
        return self.project(*self.rig.bend(u, v2, self.pose.phase), dx)
