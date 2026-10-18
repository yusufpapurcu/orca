"""Rasterising a posed animal with Pillow at 3x supersampling.

The frame is the tight bounding box of the animal and its bubbles, not a fixed
window: at 3x a canvas that covers every possible pose costs more than the
drawing itself.

Geometry is placed a whole part at a time with numpy, since a part is hundreds of points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from anatomy import BakedPart, Rig, fin_height
from bubbles import Bubbles
from projection import CAM, PERSP_NEAR, S_NEAR, WIDTH, Camera, Placement, Pose, radii, tint

SS = 3
TUBE_STATIONS = 28
TUBE_SIDES = 14
DELTA0 = math.radians(55)  # how far a flipper hangs below horizontal in the art
SIN0 = math.sin(DELTA0)
MIN_ANG, MAX_ANG = math.radians(40), math.radians(72)  # a rolled pair of flippers still hangs down and out, never flat or straight down
BEHIND = 0.3  # a flipper this much on the near flank is in front of the body, otherwise it is behind it
FLANK_DEPTH = 0.1  # body lengths a flank lies toward the viewer of the spine, for drawing order
AWAY = 0.7  # sin(yaw) at which a head turned away from the viewer hides its jaw
BEHIND_HAZE = 0.135  # extra haze on a fin behind the body
END_ON = 0.07  # |sin(yaw)| above which a section of the body is seen far enough end-on to need its round cross-section
BLADE_ON = 0.05  # |sin(yaw)| above which a fin's end-on blade is drawn

TUBE_AT = (np.arange(TUBE_STATIONS) + 0.5) / TUBE_STATIONS
TUBE_ANGLE = 2 * np.pi * np.arange(TUBE_SIDES) / TUBE_SIDES

Layer = tuple[tuple[int, int, int, int], np.ndarray]  # colour, (n, 2) polygon


@dataclass(frozen=True)
class Layout:
    """Size of one animal on screen. `half` bounds any pose plus its bubbles."""

    length: int
    half: int

    @staticmethod
    def for_rig(rig: Rig, orca_length: float) -> "Layout":
        length = round(orca_length * rig.species.length_frac)
        reach = (rig.reach * (1 + 1.6 * PERSP_NEAR) + 1.6 * CAM) * S_NEAR * 1.3 + rig.species.bubble_room
        return Layout(length, math.ceil(reach * length))

    @property
    def size(self) -> int:
        return 2 * self.half


@dataclass(frozen=True)
class Sprite:
    image: Image.Image  # premultiplied "RGBa"
    x: int  # screen position of the top-left corner
    y: int
    alpha: float = 1.0  # whole-sprite opacity: a deep animal fades into the water


def _hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull, so a feature seen from both of its flanks fills in as one shape."""
    pts = sorted({(float(x), float(y)) for x, y in pts})
    if len(pts) < 3:
        return np.array(pts)

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out

    return np.array(half(pts)[:-1] + half(pts[::-1])[:-1])


def _grown(polys: list[np.ndarray], by: float) -> list[np.ndarray]:
    """The polygons pushed outward by `by` along their vertex normals, done for all of them at once."""
    sizes = np.array([len(p) for p in polys])
    ends = np.cumsum(sizes) - 1
    starts = ends - sizes + 1
    pts = np.concatenate(polys)
    nxt, prv = np.roll(pts, -1, axis=0), np.roll(pts, 1, axis=0)
    nxt[ends], prv[starts] = pts[starts], pts[ends]
    area = np.add.reduceat(pts[:, 0] * nxt[:, 1] - nxt[:, 0] * pts[:, 1], starts)
    along = nxt - prv
    out = np.stack([along[:, 1], -along[:, 0]], axis=1) * np.repeat(np.where(area > 0, 1.0, -1.0), sizes)[:, None]
    grown = pts + by * out / np.maximum(np.hypot(out[:, 0], out[:, 1]), 1e-9)[:, None]
    return np.split(grown, ends[:-1] + 1)


def _smooth(x: float, lo: float, hi: float) -> float:
    t = min(1.0, max(0.0, (x - lo) / (hi - lo)))
    return t * t * (3 - 2 * t)


def _jaw_layers(place: Placement) -> list[Layer]:
    """Mouth wedge, lower jaw and teeth for the current gape, back to front.

    The jaw hinges in the side plane. Seen end-on, each outline is placed on
    both flanks of the head and filled between, so the mouth is a gape across
    the face with a row of teeth down each side. In profile the far flank is
    hidden behind the near one and only the near outline is drawn. A mouth that
    points away from the viewer is hidden behind the head.
    """
    rig, pose = place.rig, place.pose
    bj = rig.jaw
    jaw = bj.jaw
    hu, hv = jaw.hinge
    psi = float(pose.spin.at(hu))
    if math.sin(psi) > AWAY:
        return []
    z = place.haze
    end_on = _smooth(abs(math.sin(psi)), 0.15, 0.5)
    ang = jaw.max_open * pose.jaw_open
    ca, sa = math.cos(ang), math.sin(ang)
    grow = min(1.0, pose.jaw_open * 4)  # teeth grow with the gape so a barely open mouth is not a row of overlapping spikes

    def swing(p: np.ndarray) -> np.ndarray:
        du, dv = p[..., 0] - hu, p[..., 1] - hv
        return np.stack([hu + du * ca + dv * sa, hv - du * sa + dv * ca], axis=-1)

    def grown(tris: np.ndarray) -> np.ndarray:
        out = tris.copy()
        out[:, 2, 1] = out[:, 0, 1] + (out[:, 2, 1] - out[:, 0, 1]) * grow
        return out

    n = len(bj.lip)
    underside = bj.lower[n:] * [1.0, 0.85]  # the jaw's underside is rounded, so it sits partway out on the flanks
    shapes = [  # (outline in body space, reach out toward the flanks)
        (np.concatenate([bj.lip, swing(bj.lip[:-1][::-1])]), 0.9),
        (swing(bj.lower[:n]), 0.9),
        (swing(underside), 0.6),
        *((t, 0.9) for t in grown(bj.upper_teeth)),
        *((swing(t), 0.9) for t in grown(bj.lower_teeth)),
    ]
    uv = np.concatenate([s for s, _ in shapes])
    reach = np.concatenate([np.full(len(s), r) for s, r in shapes])
    cuts = np.cumsum([len(s) for s, _ in shapes])[:-1]

    base = place.surface(uv[:, 0], uv[:, 1])
    if end_on > 0.0:
        sides = [base + end_on * (place.lateral(uv[:, 0], uv[:, 1], f, reach) - base) for f in (1, -1)]
    else:
        sides = [base]
    near, *far = (np.split(s, cuts) for s in sides)

    mouth = _hull(np.concatenate([near[0], far[0][0]])) if far else near[0]
    chin = tint(bj.chin, z)
    layers = [(tint(bj.mouth, z), mouth), (chin, np.concatenate([near[1], near[2]]))]
    if far:
        # Each flank is a loop of its own, joined by the cross-section at the hinge.
        layers += [(chin, np.concatenate([far[0][1], far[0][2]])),
                   (chin, np.array([near[1][-1], far[0][1][-1], far[0][2][0], near[2][0]]))]
    tooth = tint(bj.tooth, z)
    for side in (near, *far):
        layers += [(tooth, t) for t in side[3:]]
    return layers


def _slabs(pts: np.ndarray, nxt: np.ndarray) -> list[np.ndarray]:
    """Each section joined to the one after it as a single convex piece: the hull of the two.

    Sections are convex loops with the same vertex order. The hull of a pair is
    the first loop's edges, except the ones that face the way the section moves,
    which come from the second loop, with a bridge where the two meet. Stacked
    sections then leave no scallops between them.
    """
    loop = np.roll(pts, -1, axis=1)
    edge = loop - pts
    area = np.sum(pts[..., 0] * loop[..., 1] - loop[..., 0] * pts[..., 1], axis=1)
    facing = np.stack([edge[..., 1], -edge[..., 0]], axis=-1) * np.where(area > 0, 1.0, -1.0)[:, None, None]
    move = nxt - pts
    move = 0.5 * (move + np.roll(move, -1, axis=1))
    ahead = np.sum(facing * move, axis=-1) > 0
    behind = np.roll(ahead, 1, axis=1)
    first = np.where(behind[..., None], nxt, pts)
    second = np.where(ahead[..., None], nxt, pts)
    both = np.stack([first, second], axis=2).reshape(len(pts), -1, 2)
    keep = np.stack([np.ones_like(ahead), ahead != behind], axis=2).reshape(len(pts), -1)
    return [p[k] for p, k in zip(both, keep)]


def _tube(place: Placement) -> list[tuple[float, list[Layer]]]:
    """The body as a round tube, so seen from the front or back it keeps its width.

    Cross-sections, widened by sin(yaw) at each station and joined in pairs, are
    unioned with the side-view silhouette. Returns the fills, each with its depth.
    """
    rig, pose = place.rig, place.pose
    spin = pose.spin
    sp = np.sin(spin.at(TUBE_AT))
    on = np.abs(sp) >= END_ON
    active = np.nonzero(on)[0]
    if len(active) == 0:
        return []
    u, sp = TUBE_AT[:, None], sp[:, None]
    rd, rv = radii(rig.species.profile, u)
    sn = np.sin(TUBE_ANGLE)[None, :]
    bx, by = rig.bend(u, sn * np.where(sn > 0, rv, rd), pose.phase)
    pts = place.project(bx, by, -WIDTH * 0.5 * (rd + rv) * sp * np.cos(TUBE_ANGLE)[None, :])
    nxt = np.concatenate([pts[1:], pts[-1:]])
    lone = ~np.append(on[1:], False)
    nxt[lone] = pts[lone]
    body = next(p for p in rig.parts if p.name == "body")
    color = tint(body.color, place.haze)
    slabs = _slabs(pts[active], nxt[active])
    return [(place.depth(float(ui)), [(color, p)]) for ui, p in zip(TUBE_AT[active], slabs)]


def _midline_fin(place: Placement, part: BakedPart) -> list[np.ndarray]:
    """A fin on the midline: the roll shortens it and leans it toward the inside of the turn.

    Returns the side silhouette followed by its end-on blades. The silhouette
    narrows to nothing as the body yaws side-on to the fin, the blades widen to
    their full thickness, and drawn together they never leave a hairline.
    """
    rig, pose = place.rig, place.pose
    spin, fin = pose.spin, part.fin
    fx, fy, tx, ty = rig.spine(part.attach, pose.phase)
    k = fin_height(part.flutter, pose.phase) if part.flutter else 1.0
    cb, sb = math.cos(spin.bank), math.sin(spin.bank)
    sp = math.sin(spin.at(part.attach))
    a, b = fin.ab[:, 0], fin.ab[:, 1] * k
    pts = place.project(fx + a * tx - b * cb * ty, fy + a * ty + b * cb * tx, sp * b * sb + fin.hw * abs(sp))
    return [pts[lo:hi] for lo, hi in (fin.spans if abs(sp) > BLADE_ON else fin.spans[:1])]


def _flipper(place: Placement, part: BakedPart, flank: int) -> tuple[list[np.ndarray], float] | None:
    """One of a pair, hanging down and out from its side of the body.

    The yaw spreads the pair apart and the roll drops one flipper while it lifts
    the other. Returns the side silhouette followed by the end-on blades, and
    how far onto the viewer's flank it sits (negative: the far one).
    """
    rig, pose = place.rig, place.pose
    spin, fin = pose.spin, part.fin
    fx, fy, tx, ty = rig.spine(part.attach, pose.phase)
    psi = float(spin.at(part.attach))
    sp, cp = math.sin(psi), math.cos(psi)
    near = flank * cp
    if near < 0 and abs(spin.bank) < 0.02 and abs(sp) < 0.03:
        return None
    rd, rv = radii(rig.species.profile, part.attach)
    root = 0.9 * WIDTH * 0.5 * float(rd + rv)
    ang = max(MIN_ANG, min(MAX_ANG, DELTA0 - flank * spin.bank * 0.5))
    kv, kl = max(math.sin(ang) / SIN0, 0.15), 0.65 * math.cos(ang) / SIN0
    a, b = fin.ab[:, 0], fin.ab[:, 1]
    out = sp * flank * (root + np.maximum(b - fin.base, 0.0) * kl)
    pts = place.project(fx + a * tx - b * kv * ty, fy + a * ty + b * kv * tx, out + fin.hw * abs(sp))
    return [pts[lo:hi] for lo, hi in (fin.spans if abs(sp) > BLADE_ON else fin.spans[:1])], near


def _place(place: Placement) -> tuple[list[np.ndarray], list[Layer]]:
    """Outline polygons and the colour layers, back to front, in canvas coordinates.

    The body outline goes down first, then a scene sorted by how far toward the
    viewer each piece is: the round body's cross-sections and any fin seen more
    end-on than side-on, so a head that points at the viewer hides the fin
    behind it. The markings and the jaw follow, and the fins seen side-on last.
    """
    rig, pose = place.rig, place.pose
    spin = pose.spin
    z = place.haze
    jaw = rig.jaw if pose.jaw_open > 0.02 else None

    (body_i, body_lo, body_hi), *marks = rig.fixed_spans
    fixed = {body_i: place.outline(rig.fixed[body_lo:body_hi, 0], rig.fixed[body_lo:body_hi, 1])}
    if marks:
        m_lo, m_hi = marks[0][1], marks[-1][2]
        placed = place.surface(rig.fixed[m_lo:m_hi, 0], rig.fixed[m_lo:m_hi, 1])
        fixed.update({i: placed[lo - m_lo:hi - m_lo] for i, lo, hi in marks})

    outlines: list[np.ndarray] = []
    layers: list[Layer] = []
    back: list[Layer] = []
    late: list[Layer] = []
    scene: list[tuple[float, list[Layer]]] = []
    for i, part in enumerate(rig.parts):
        if jaw and i >= jaw.parts_below:
            layers += _jaw_layers(place)
            jaw = None
        color = tint(part.color, z)
        if part.attach is None:
            pts = fixed[i]
            if part.outline:
                outlines.append(pts)
            layers.append((color, pts))
            continue
        for flank in (1, -1) if part.paired else (0,):
            if part.paired:
                placed = _flipper(place, part, flank)
                if placed is None:
                    continue
                shapes, near = placed
            else:
                shapes, near = _midline_fin(place, part), 1.0
            if part.outline:
                outlines += shapes
            end_on = abs(math.sin(spin.at(part.attach))) >= 0.5
            if near < -BEHIND:
                back += [(tint(part.color, z + BEHIND_HAZE), pts) for pts in shapes]
            elif end_on:
                scene.append((place.depth(part.attach) + FLANK_DEPTH * near * bool(flank), [(color, pts) for pts in shapes]))
            else:
                late += [(color, pts) for pts in shapes]
    if jaw:
        layers += _jaw_layers(place)
    tube = _tube(place)
    outlines += [pts for _, group in tube for _, pts in group]
    scene += tube
    scene.sort(key=lambda item: item[0])
    layers[1:1] = [layer for _, group in scene for layer in group]
    layers[0:0] = back
    return outlines, layers + late


def _draw_bubbles(draw: ImageDraw.ImageDraw, bubbles: list[tuple[float, float, float, float, bool]], front: bool) -> None:
    for x, y, r, fade, in_front in bubbles:
        if in_front != front:
            continue
        fill, line = int(46 * fade), int(215 * fade)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(fill,) * 4, outline=(line,) * 4, width=max(1, SS - 1))


def render(rig: Rig, pose: Pose, bubbles: Bubbles, lay: Layout, cam: Camera, x: float, y: float, z: float) -> Sprite:
    """Draw the animal at world position (x, y, z) as the camera sees it.

    The canvas is premultiplied "RGBa" from the start (opaque parts have alpha
    255, bubbles use equal colour and alpha), so the box reduce is a correct
    premultiplied downsample with no per-frame RGBA/RGBa conversion.
    """
    sx, sy, s = cam.to_screen(x, y, z)
    ax, ay = round(sx), round(sy)
    place = Placement(rig, pose, lay.length * SS * s, ((sx - ax) * SS, (sy - ay) * SS), cam.haze(z))
    outlines, layers = _place(place)

    every = np.concatenate([pts for _, pts in layers])
    pad = rig.species.outline_px + SS
    lo_x, lo_y = every.min(axis=0) - pad
    hi_x, hi_y = every.max(axis=0) + pad
    drops = []
    for b in bubbles.items:
        px, py, ps = cam.to_screen(b.x, b.y, b.z)
        r = b.r * ps * SS
        bxc, byc = (px - ax) * SS, (py - ay) * SS
        drops.append((bxc, byc, r, 1.0 - (b.age / b.life) ** 2, b.front))
        lo_x, hi_x = min(lo_x, bxc - r - SS), max(hi_x, bxc + r + SS)
        lo_y, hi_y = min(lo_y, byc - r - SS), max(hi_y, byc + r + SS)
    cap = lay.half * SS
    bx = max(-cap, math.floor(lo_x / SS) * SS)
    by = max(-cap, math.floor(lo_y / SS) * SS)
    w = min(cap, math.ceil(hi_x / SS) * SS) - bx
    h = min(cap, math.ceil(hi_y / SS) * SS) - by

    big = Image.new("RGBa", (w, h))
    draw = ImageDraw.Draw(big)
    shift = np.array([-bx, -by], dtype=float)
    drops = [(px - bx, py - by, r, fade, front) for px, py, r, fade, front in drops]
    _draw_bubbles(draw, drops, front=False)
    # The rim is a slightly larger copy of each outline drawn underneath everything, because a wide
    # draw.line is several times slower.
    rim = tint(rig.outline_color, place.haze)
    for pts in _grown(outlines, rig.species.outline_px):
        draw.polygon((pts + shift).ravel().tolist(), fill=rim)
    for color, pts in layers:
        draw.polygon((pts + shift).ravel().tolist(), fill=color)
    _draw_bubbles(draw, drops, front=True)
    return Sprite(big.reduce(SS), ax + bx // SS, ay + by // SS, cam.fade(z))
