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

import numpy as np
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
    # Rigid appendages only: how far the height shrinks over a beat. A side
    # view of a tail sweeping side to side sees the fin foreshorten.
    flutter: float = 0.0
    # Rigid appendages only: a flipper-like part that comes as a left and right pair.
    paired: bool = False
    # Rigid appendages only: thickness at the root, in body lengths. Seen end-on a
    # fin is not a hairline but a blade this wide, tapering toward the tip.
    girth: float = 0.0


def ellipse(cu: float, cv: float, ru: float, rv: float, deg: float, n: int = 12) -> tuple[Pt, ...]:
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        x, y = ru * math.cos(t), rv * math.sin(t)
        pts.append(Pt(cu + x * ca - y * sa, cv + x * sa + y * ca))
    return tuple(pts)


@dataclass(frozen=True)
class Jaw:
    """A hinged lower jaw. Opening it paints a mouth wedge between the lips."""

    hinge: tuple[float, float]  # (u, v) of the mouth corner
    lip: tuple[tuple[float, float], ...]  # mouth line, nose end first, hinge last
    max_open: float  # radians when fully open
    teeth: int  # per jaw
    order: int  # drawn after every part with order <= this
    mouth: str  # palette keys
    chin: str
    tooth: str


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
    jaw: Jaw | None = None


MAX_STEP = 0.012


BLADE_STEPS = 4
BLADE_TIP = 0.4  # width at the tip, as a share of the root's


@dataclass(frozen=True, eq=False)
class Fin:
    """A rigid appendage as the pose code needs it, in its own (along, perpendicular) frame.

    `ab` holds the side silhouette followed by the end-on blades, `hw` each row's
    half width across the blade (zero on the silhouette) and `spans` where each
    shape starts and stops. Seen end-on a fin is not a hairline but a blade
    `girth` thick at the root, so a blade is a centre line from root to tip with
    a width on either side.
    """

    ab: np.ndarray
    hw: np.ndarray
    spans: tuple[tuple[int, int], ...]
    base: float  # smallest perpendicular offset: where the root meets the body


def fin_of(part: Part, silhouette: np.ndarray) -> Fin | None:
    if part.attach is None:
        return None
    rows, hws, spans = [silhouette], [np.zeros(len(silhouette))], [(0, len(silhouette))]
    n = len(silhouette)
    for side in (-1, 1) if part.girth else ():
        pts = [(p.u, p.v) for p in part.points if p.v * side > 0]
        if not pts:
            continue
        near = min(abs(b) for _, b in pts)
        root = [a for a, b in pts if abs(b) < near + 0.02]
        a0, b0 = sum(root) / len(root), near * side
        a1, b1 = max(pts, key=lambda p: abs(p[1]))
        ts = np.linspace(0.0, 1.0, BLADE_STEPS + 1)
        centre = np.stack([a0 + (a1 - a0) * ts, b0 + (b1 - b0) * ts], axis=1)
        half = 0.5 * part.girth * (1 - (1 - BLADE_TIP) * ts)
        rows += [centre, centre[::-1]]
        hws += [half, -half[::-1]]
        spans.append((n, n + 2 * len(ts)))
        n += 2 * len(ts)
    return Fin(np.concatenate(rows), np.concatenate(hws), tuple(spans), float(silhouette[:, 1].min()))


def bake(part: Part, profile: Profile) -> np.ndarray:
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
    return np.array(out)


@dataclass(frozen=True, eq=False)
class BakedPart:
    name: str
    color: tuple[int, int, int, int]
    attach: float | None
    outline: bool
    flutter: float
    paired: bool
    fin: Fin | None  # set for a rigid appendage
    points: np.ndarray  # (n, 2) rows of (u, v), or of (along, perpendicular) for an appendage


def fin_height(flutter: float, phase: float) -> float:
    """Height factor of a fluttering fin: two dips per beat plus a slow sway."""
    dip = 0.5 + 0.5 * math.cos(4 * math.pi * phase)
    return max(0.3, 1.0 - flutter * dip + 0.25 * flutter * math.sin(2 * math.pi * phase))


Triangle = tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class BakedJaw:
    jaw: Jaw
    mouth: tuple[int, int, int, int]
    chin: tuple[int, int, int, int]
    tooth: tuple[int, int, int, int]
    lip: np.ndarray  # (n, 2) the mouth line, nose end first, hinge last
    lower: np.ndarray  # (n, 2) the lower jaw outline: the lip, then the underside from the hinge to the chin
    upper_teeth: np.ndarray  # (teeth, 3, 2) triangles, base then tip
    lower_teeth: np.ndarray  # in the closed jaw's frame, so they rotate with it
    parts_below: int  # how many parts are drawn before the jaw


TOOTH_W, TOOTH_H = 0.005, 0.013


@dataclass(frozen=True, eq=False)
class Rig:
    """A compiled Species: baked parts in draw order plus the spine deformation."""

    species: Species
    parts: tuple[BakedPart, ...]
    outline_color: tuple[int, int, int, int]
    reach: float  # radius, in body lengths, around the centre that holds the animal at any pose
    fixed: np.ndarray  # (n, 2) every point of the parts that bend with the spine, in draw order
    fixed_spans: tuple[tuple[int, int, int], ...]  # (part index, start, stop) rows of `fixed`
    jaw: BakedJaw | None = None

    def spine(self, u, phase: float):
        """Spine point and unit tangent at u. Phase is in tail-beat cycles.

        The wave displaces y, growing from almost nothing at the head to the tail.
        """
        sp = self.species
        th = 2 * math.pi * (sp.wave_cycles * u - phase)
        s, c = np.sin(th), np.cos(th)
        env = u * u
        y = sp.wave_amp * env * s
        slope = sp.wave_amp * (2 * u * s + env * 2 * math.pi * sp.wave_cycles * c)
        inv = 1.0 / np.sqrt(1.0 + slope * slope)
        return u, y, inv, slope * inv

    def bend(self, u, v, phase: float):
        x, y, tx, ty = self.spine(u, phase)
        return x - v * ty, y + v * tx


@cache
def compile_species(sp: Species) -> Rig:
    def rgba(key: str) -> tuple[int, int, int, int]:
        return (*ImageColor.getrgb(sp.palette[key]), 255)

    ordered = sorted(sp.parts, key=lambda p: p.order)
    pts = [bake(p, sp.profile) for p in ordered]
    parts = tuple(
        BakedPart(p.name, rgba(p.color), p.attach, p.outline, p.flutter, p.paired, fin_of(p, xy), xy)
        for p, xy in zip(ordered, pts)
    )
    spans, rows, n = [], [], 0
    for i, part in enumerate(parts):
        if part.attach is None:
            spans.append((i, n, n + len(part.points)))
            rows.append(part.points)
            n += len(part.points)
    assert parts[spans[0][0]].name == "body", "the body is the first part that bends with the spine"
    rig = Rig(sp, parts, (*ImageColor.getrgb(sp.outline_color), 255), 0.0,
              np.concatenate(rows), tuple(spans), _bake_jaw(sp, rgba) if sp.jaw else None)
    object.__setattr__(rig, "reach", _reach(rig))
    return rig


def _bake_jaw(sp: Species, rgba) -> BakedJaw:
    jaw = sp.jaw
    hu = jaw.hinge[0]
    ventral = [(hu * (1 - i / 6), sp.profile.rim_v(hu * (1 - i / 6), 1)) for i in range(7)]
    lower = (*jaw.lip, *ventral)

    seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(jaw.lip, jaw.lip[1:])]
    total = sum(seg)

    def on_lip(frac: float) -> tuple[float, float]:
        d = frac * total
        for (a, b), n in zip(zip(jaw.lip, jaw.lip[1:]), seg):
            if d <= n:
                t = d / n
                return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            d -= n
        return jaw.lip[-1]

    def teeth(dv: float) -> np.ndarray:
        out = []
        for k in range(jaw.teeth):
            u, v = on_lip(0.14 + 0.72 * k / max(1, jaw.teeth - 1))
            out.append(((u - TOOTH_W, v), (u + TOOTH_W, v), (u, v + dv)))
        return np.array(out)

    below = sum(1 for p in sp.parts if p.order <= jaw.order)
    return BakedJaw(jaw, rgba(jaw.mouth), rgba(jaw.chin), rgba(jaw.tooth), np.array(jaw.lip), np.array(lower),
                    teeth(TOOTH_H), teeth(-TOOTH_H), below)


def _reach(rig: Rig) -> float:
    far = 0.0
    for phase in (i / 8 for i in range(8)):
        for part in rig.parts:
            u, v = part.points[:, 0], part.points[:, 1]
            if part.attach is None:
                x, y = rig.bend(u, v, phase)
            else:
                fx, fy, tx, ty = rig.spine(part.attach, phase)
                x, y = fx + u * tx - v * ty, fy + u * ty + v * tx
            far = max(far, float(np.hypot(0.5 - x, y).max()))
    return far
