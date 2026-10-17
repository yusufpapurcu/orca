"""Where a posed animal lands on the screen.

The single mapping from a pose in 3D to pixels. Everything that needs a point
on an animal (the drawing, the bubble vents, the nose that touches the fish)
goes through a Placement, so they cannot disagree.

Yaw lives in the (x, depth) plane as an unwrapped angle: 0 faces right, pi
faces left having swum round the viewer's side, -pi round the far side. The
head's yaw leads and the angles further down the spine lag, so the body is a
curve in depth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

from anatomy import Rig

NODES = 5  # yaw samples along the spine, nose to tail
TABLE = 33  # integration samples along the spine (odd, so the middle is exact)

PERSP_NEAR = 0.27  # extra size at depth +1 (toward the viewer)
PERSP_FAR = 0.20  # size lost at depth -1
PERSP_BODY = 0.5  # how much of the body's own depth shows as perspective along it
DEPTH_UNIT = 0.45  # body lengths that one unit of depth spans along the body
CAM = 0.18  # screen drop per unit depth, in body lengths: the camera looks slightly down
WIDTH = 0.95  # body width as a share of its height
HAZE = (84, 128, 172)
HAZE_MAX = 0.45
PERSP_CLAMP = 1.7


@dataclass(frozen=True)
class Spin:
    yaw: tuple[float, ...]  # unwrapped heading in the (x, depth) plane at each node
    z: float = 0.0  # +1 toward the viewer
    bank: float = 0.0  # signed roll: positive tips the back toward the inside of a positive yaw rate

    @staticmethod
    def flat() -> "Spin":
        return Spin((0.0,) * NODES)

    def at(self, u: float) -> float:
        t = min(max(u, 0.0), 1.0) * (NODES - 1)
        i = min(int(t), NODES - 2)
        return self.yaw[i] + (self.yaw[i + 1] - self.yaw[i]) * (t - i)


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
def radius_table(profile) -> tuple[tuple[float, ...], tuple[float, ...]]:
    n = 256
    us = [i / n for i in range(n + 1)]
    return (tuple(max(-profile.rim_v(u, -1), 0.0) for u in us), tuple(max(profile.rim_v(u, 1), 0.0) for u in us))


def radii(profile, u: float) -> tuple[float, float]:
    rd, rv = radius_table(profile)
    t = min(max(u, 0.0), 1.0) * (len(rd) - 1)
    i = min(int(t), len(rd) - 2)
    f = t - i
    return rd[i] + (rd[i + 1] - rd[i]) * f, rv[i] + (rv[i + 1] - rv[i]) * f


def projector(spin: Spin, pitch: float, length: float, origin: tuple[float, float]):
    """Map spine space (u along, v across, in body lengths) to the screen.

    `dx` is an extra horizontal offset in body lengths, how a point off the
    spine's plane (a flank, a fin leaning with the bank) shows up when yawed.
    """
    n = TABLE
    h = 1.0 / (n - 1)
    cs = [math.cos(spin.at(i * h)) for i in range(n)]
    ss = [math.sin(spin.at(i * h)) for i in range(n)]
    ic, isn = [0.0] * n, [0.0] * n
    for i in range(1, n):
        ic[i] = ic[i - 1] + 0.5 * h * (cs[i - 1] + cs[i])
        isn[i] = isn[i - 1] + 0.5 * h * (ss[i - 1] + ss[i])
    mid = (n - 1) // 2
    icm, ism = ic[mid], isn[mid]
    c, s = math.cos(pitch), math.sin(pitch)
    ox, oy = origin
    z0 = spin.z
    last = n - 1

    def project(bx: float, by: float, dx: float = 0.0) -> tuple[float, float]:
        if bx < 0.0:
            ci, si, ca = bx * cs[0], bx * ss[0], cs[0]
        elif bx > 1.0:
            ci, si, ca = ic[last] + (bx - 1.0) * cs[last], isn[last] + (bx - 1.0) * ss[last], cs[last]
        else:
            t = bx * last
            i = int(t)
            if i >= last:
                i = last - 1
            f = t - i
            ci = ic[i] + (ic[i + 1] - ic[i]) * f
            si = isn[i] + (isn[i + 1] - isn[i]) * f
            ca = cs[i] + (cs[i + 1] - cs[i]) * f
        x = ((icm - ci) * c + ca * by * s + dx) * length
        y = (by * c - (0.5 - bx) * s) * length
        zp = z0 + PERSP_BODY * (ism - si) / DEPTH_UNIT
        zp = max(-PERSP_CLAMP, min(PERSP_CLAMP, zp))
        p = 1.0 + (PERSP_NEAR * zp if zp > 0 else PERSP_FAR * zp)
        return ox + p * x, oy + p * y + CAM * zp * length

    def depth(u: float) -> float:
        """How far toward the viewer the spine is at u, so what is nearer can be drawn later."""
        return -isn[min(int(u * last + 0.5), last)]

    return project, depth


def flanker(profile, spin: Spin):
    """Where a mark on the body surface lands once the body has rolled and yawed.

    Marks are painted at (u, v), v being height across the body. A roll slides
    them around the round body: a mark on the flank at surface angle th goes to
    th + phi, phi being how far the back tips toward the viewer. Points on the
    outline stay on it. The yaw pushes a mark toward the viewer-facing flank's
    lateral offset, which shows up as a horizontal shift.
    """
    bank = spin.bank
    n = 64
    cps = [math.cos(spin.at(i / n)) for i in range(n + 1)]
    sps = [math.sin(spin.at(i / n)) for i in range(n + 1)]
    if abs(bank) < 0.004 and max(abs(x) for x in sps) < 0.004:
        return None
    rd_t, rv_t = radius_table(profile)
    m = len(rd_t) - 1

    def flank(u: float, v: float) -> tuple[float, float]:
        j = int(u * n + 0.5)
        j = 0 if j < 0 else n if j > n else j
        cp, sp = cps[j], sps[j]
        phi = bank * cp
        if abs(phi) < 0.004 and abs(sp) < 0.004:
            return v, 0.0
        k = int(u * m + 0.5)
        k = 0 if k < 0 else m if k > m else k
        rd, rv = rd_t[k], rv_t[k]
        r = rd if v < 0 else rv
        f = v / r if r > 1e-6 else 0.0
        if f >= 0.985 or f <= -0.985:
            return v, 0.0
        th = max(-1.5707, min(1.5707, math.asin(f) + phi))
        f2 = math.sin(th)
        return f2 * (rv if f2 > 0 else rd), -sp * cp * WIDTH * 0.5 * (rd + rv) * math.cos(th)

    return flank


def tint(color: tuple[int, int, int, int], z: float) -> tuple[int, int, int, int]:
    """Water haze: far away the colours lose contrast toward a pale blue."""
    k = -z * HAZE_MAX
    if k <= 0.01:
        return color
    k = min(k, HAZE_MAX)
    r, g, b, a = color
    return (round(r + (HAZE[0] - r) * k), round(g + (HAZE[1] - g) * k), round(b + (HAZE[2] - b) * k), a)


class Placement:
    """One animal's pose set on the screen: body space in, pixels out."""

    def __init__(self, rig: Rig, pose: Pose, length: float, origin: tuple[float, float]):
        self.rig, self.pose = rig, pose
        self.project, self.depth = projector(pose.spin, pose.pitch, length, origin)
        self.flank = flanker(rig.species.profile, pose.spin)

    def outline(self, u: float, v: float) -> tuple[float, float]:
        """A point of the silhouette: it stays on the outline however the body is rolled."""
        return self.project(*self.rig.bend(u, v, self.pose.phase))

    def surface(self, u: float, v: float) -> tuple[float, float]:
        """A point on the round body, so a marking slides around it when the body rolls."""
        if self.flank is None:
            return self.outline(u, v)
        v2, dx = self.flank(u, v)
        x, y = self.rig.bend(u, v2, self.pose.phase)
        return self.project(x, y, dx)

    def lateral(self, u: float, v: float, side: int, reach: float = 1.0) -> tuple[float, float]:
        """A point of the body surface on its near (+1) or far (-1) flank, `reach` of the way out from the spine.

        Seen end-on the two flanks are the two sides of the head, where the mouth
        and teeth sit, and a roll lifts one flank while it drops the other.
        """
        spin = self.pose.spin
        rd, rv = radii(self.rig.species.profile, u)
        r = rd if v < 0 else rv
        th = math.asin(max(-1.0, min(1.0, v / r))) if r > 1e-6 else 0.0
        psi = spin.at(u)
        th2 = max(-1.5707, min(1.5707, th + side * spin.bank * math.cos(psi)))
        v2 = math.sin(th2) * (rv if th2 > 0 else rd)
        dx = -side * math.sin(psi) * WIDTH * 0.5 * (rd + rv) * math.cos(th2) * reach
        x, y = self.rig.bend(u, v2, self.pose.phase)
        return self.project(x, y, dx)

