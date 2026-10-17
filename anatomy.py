"""Species anatomy in body space, shared by every animal.

Body space is (u, v): u runs nose (0) to tail stock (1) along the spine, v is
the signed offset perpendicular to the spine in body lengths, negative toward
the back (up on screen). A Species is plain tables. compile_species turns it
into a Rig: parts resampled densely so they bend smoothly under the spine wave.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from functools import cache, cached_property
from typing import NamedTuple

from PIL import ImageColor


def _hermite(x: float, xs: list[float], ys: list[float]) -> float:
    i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
    h = xs[i + 1] - xs[i]

    def slope(k: int) -> float:
        lo, hi = max(k - 1, 0), min(k + 1, len(xs) - 1)
        return (ys[hi] - ys[lo]) / (xs[hi] - xs[lo])

    t = (x - xs[i]) / h
    t2, t3 = t * t, t * t * t
    return (
        (2 * t3 - 3 * t2 + 1) * ys[i]
        + (t3 - 2 * t2 + t) * h * slope(i)
        + (-2 * t3 + 3 * t2) * ys[i + 1]
        + (t3 - t2) * h * slope(i + 1)
    )


@dataclass(frozen=True)
class Profile:
    """Rows of (u, dorsal half-thickness, ventral half-thickness)."""

    rows: tuple[tuple[float, float, float], ...]

    @cached_property
    def _us(self) -> list[float]:
        return [r[0] for r in self.rows]

    @cached_property
    def _dorsal(self) -> list[float]:
        return [r[1] for r in self.rows]

    @cached_property
    def _ventral(self) -> list[float]:
        return [r[2] for r in self.rows]

    def rim_v(self, u: float, f: float) -> float:
        """v of the point a fraction f of the way from the spine to the body edge.

        f = -1 is the dorsal outline, +1 the ventral outline. Markings that touch
        the outline use this so they share its exact vertices.
        """
        if f == 0:
            return 0.0
        ys = self._dorsal if f < 0 else self._ventral
        return f * max(_hermite(u, self._us, ys), 0.0)


class Rim(NamedTuple):
    f: float


class Pt(NamedTuple):
    u: float
    v: float | Rim
    corner: bool = False


@dataclass(frozen=True)
class Part:
    name: str
    color: str  # key into Species.palette
    order: int
    points: tuple[Pt, ...]
    # None: points are (u, v) body coordinates bent along the spine.
    # u0: rigid appendage, points are (a, b) = (along, perpendicular) in the
    # spine frame at u0, so it inherits that point's position and rotation.
    attach: float | None = None
    # Drawn again underneath, shifted, in Species.outline_color.
    outline: bool = False


def ellipse(cu: float, cv: float, ru: float, rv: float, deg: float, n: int = 12) -> tuple[Pt, ...]:
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        x, y = ru * math.cos(t), rv * math.sin(t)
        pts.append(Pt(cu + x * ca - y * sa, cv + x * sa + y * ca))
    return tuple(pts)


@dataclass(frozen=True, eq=False)
class Species:
    name: str
    profile: Profile
    parts: tuple[Part, ...]
    palette: dict[str, str]
    wave_amp: float  # peak lateral displacement of the tail, in body lengths
    wave_cycles: float  # wavelengths along the body
    beat_hz: float
    length_frac: float  # body length as a fraction of the orca's
    vents: tuple[tuple[float, float], ...]  # (u, v) points bubbles rise from
    bubble_room: float  # window margin for bubbles, in body lengths
    outline_color: str
    outline_px: int  # supersampled pixels the outline copies are shifted by


MAX_STEP = 0.012


def bake(part: Part, profile: Profile) -> list[tuple[float, float]]:
    """Resample a part densely so it bends smoothly under the spine wave."""
    pts = part.points
    n = len(pts)
    ev = [(p.u, profile.rim_v(p.u, p.v.f) if isinstance(p.v, Rim) else p.v) for p in pts]
    out: list[tuple[float, float]] = []
    for i in range(n):
        j = (i + 1) % n
        a, b = pts[i], pts[j]
        (u0, v0), (u1, v1) = ev[i], ev[j]
        dist = math.hypot(u1 - u0, v1 - v0)
        steps = max(1, math.ceil(dist / MAX_STEP))
        if isinstance(a.v, Rim) and isinstance(b.v, Rim):
            for k in range(steps):
                t = k / steps
                u = u0 + (u1 - u0) * t
                out.append((u, profile.rim_v(u, a.v.f + (b.v.f - a.v.f) * t)))
            continue
        pm, pn = ev[i - 1], ev[(j + 1) % n]
        m0 = (u1 - u0, v1 - v0) if a.corner else ((u1 - pm[0]) / 2, (v1 - pm[1]) / 2)
        m1 = (u1 - u0, v1 - v0) if b.corner else ((pn[0] - u0) / 2, (pn[1] - v0) / 2)
        for k in range(steps):
            t = k / steps
            t2, t3 = t * t, t * t * t
            h00, h10, h01, h11 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, -2 * t3 + 3 * t2, t3 - t2
            out.append((
                h00 * u0 + h10 * m0[0] + h01 * u1 + h11 * m1[0],
                h00 * v0 + h10 * m0[1] + h01 * v1 + h11 * m1[1],
            ))
    return out


@dataclass(frozen=True)
class BakedPart:
    color: tuple[int, int, int, int]
    attach: float | None
    outline: bool
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, eq=False)
class Rig:
    """A compiled Species: baked parts in draw order plus the spine deformation."""

    species: Species
    parts: tuple[BakedPart, ...]
    outline_color: tuple[int, int, int, int]
    outline_offsets: tuple[tuple[int, int], ...]
    reach: float  # radius, in body lengths, around the centre that holds the animal at any pose

    def spine(self, u: float, phase: float) -> tuple[float, float, float, float]:
        """Spine point and unit tangent at u. Phase is in tail-beat cycles.

        The wave displaces y, growing from almost nothing at the head to the tail.
        """
        sp = self.species
        th = 2 * math.pi * (sp.wave_cycles * u - phase)
        s, c = math.sin(th), math.cos(th)
        env = u * u
        y = sp.wave_amp * env * s
        slope = sp.wave_amp * (2 * u * s + env * 2 * math.pi * sp.wave_cycles * c)
        inv = 1.0 / math.sqrt(1.0 + slope * slope)
        return u, y, inv, slope * inv

    def bend(self, u: float, v: float, phase: float) -> tuple[float, float]:
        x, y, tx, ty = self.spine(u, phase)
        return x - v * ty, y + v * tx


@cache
def compile_species(sp: Species) -> Rig:
    def rgba(key: str) -> tuple[int, int, int, int]:
        return (*ImageColor.getrgb(sp.palette[key]), 255)

    parts = tuple(
        BakedPart(rgba(p.color), p.attach, p.outline, tuple(bake(p, sp.profile)))
        for p in sorted(sp.parts, key=lambda p: p.order)
    )
    k = sp.outline_px
    rig = Rig(sp, parts, (*ImageColor.getrgb(sp.outline_color), 255), ((k, 0), (-k, 0), (0, k), (0, -k)), 0.0)
    object.__setattr__(rig, "reach", _reach(rig))
    return rig


def _reach(rig: Rig) -> float:
    far = 0.0
    for phase in (i / 8 for i in range(8)):
        for part in rig.parts:
            if part.attach is None:
                pts = [rig.bend(u, v, phase) for u, v in part.points]
            else:
                fx, fy, tx, ty = rig.spine(part.attach, phase)
                pts = [(fx + a * tx - b * ty, fy + a * ty + b * tx) for a, b in part.points]
            far = max(far, max(math.hypot(0.5 - x, y) for x, y in pts))
    return far
