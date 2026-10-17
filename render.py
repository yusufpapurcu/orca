"""Rasterising a posed animal with Pillow at 3x supersampling.

The frame is the tight bounding box of the animal and its bubbles, not a fixed
window: at 3x a canvas that covers every possible pose costs more than the
drawing itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from anatomy import BakedPart, Rig, Triangle, fin_height
from bubbles import Bubbles
from projection import CAM, PERSP_NEAR, WIDTH, Placement, Pose, radii, tint

SS = 3
TUBE_STATIONS = 28
TUBE_SIDES = 14
DELTA0 = math.radians(55)  # how far a flipper hangs below horizontal in the art
SIN0 = math.sin(DELTA0)
MIN_ANG, MAX_ANG = math.radians(40), math.radians(72)  # a rolled pair of flippers still hangs down and out, never flat or straight down
BEHIND = 0.3  # a flipper this much on the near flank is in front of the body, otherwise it is behind it
FLANK_DEPTH = 0.1  # body lengths a flank or a jaw lies toward the viewer of the spine, for drawing order
AWAY = 0.7  # sin(yaw) at which a head turned away from the viewer hides its jaw
END_ON = 0.07  # |sin(yaw)| above which a section of the body is seen far enough end-on to need its round cross-section

Points = list[tuple[float, float]]
Layer = tuple[tuple[int, int, int, int], Points]


@dataclass(frozen=True)
class Layout:
    """Size of one animal on screen. `half` bounds any pose plus its bubbles."""

    length: int
    half: int

    @staticmethod
    def for_rig(rig: Rig, orca_length: float) -> "Layout":
        length = round(orca_length * rig.species.length_frac)
        reach = rig.reach * (1 + 1.6 * PERSP_NEAR) + 1.6 * CAM + rig.species.bubble_room
        return Layout(length, math.ceil(reach * length))

    @property
    def size(self) -> int:
        return 2 * self.half


@dataclass(frozen=True)
class Sprite:
    image: Image.Image  # premultiplied "RGBa"
    x: int  # screen position of the top-left corner
    y: int


def _hull(pts: Points) -> Points:
    """Convex hull, so a feature seen from both of its flanks fills in as one shape."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq: Points) -> Points:
        out: Points = []
        for p in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out

    lower, upper = half(pts), half(pts[::-1])
    return lower[:-1] + upper[:-1]


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
    ang = jaw.max_open * pose.jaw_open
    ca, sa = math.cos(ang), math.sin(ang)
    hu, hv = jaw.hinge
    z = pose.spin.z
    psi = pose.spin.at(hu)
    end_on = _smooth(abs(math.sin(psi)), 0.15, 0.5)
    if math.sin(psi) < -AWAY:
        return []

    def swing(u: float, v: float) -> tuple[float, float]:
        du, dv = u - hu, v - hv
        return hu + du * ca + dv * sa, hv - du * sa + dv * ca

    def sides(pts, reach: float = 0.9) -> tuple[Points, Points]:
        base = [place.surface(u, v) for u, v in pts]
        if end_on == 0.0:
            return base, []
        out = []
        for flank in (1, -1):
            out.append([(bx + end_on * (x - bx), by + end_on * (y - by))
                        for (bx, by), (x, y) in zip(base, (place.lateral(u, v, flank, reach) for u, v in pts))])
        return out[0], out[1]

    def filled(pts) -> Points:
        near, far = sides(pts)
        return _hull(near + far) if far else near

    def grown(tri: Triangle) -> Triangle:
        # Teeth grow with the gape so a barely open mouth is not a row of overlapping spikes.
        k = min(1.0, pose.jaw_open * 4)
        (au, av), (bu, bv), (cu, cv) = tri
        return (au, av), (bu, bv), (cu, av + (cv - av) * k)

    lip = len(jaw.lip)
    # The lower jaw's keel is the underside of a rounded jaw, so it sits partway out on the flanks.
    chin_near, chin_far = sides([swing(u, v) for u, v in bj.lower[:lip]])
    keel_near, keel_far = sides([swing(u, 0.85 * v) for u, v in bj.lower[lip:]], 0.6)
    chin = tint(bj.chin, z)
    layers = [(chin, chin_near + keel_near)]
    if chin_far:
        # Each flank is a loop of its own, joined by the cross-section at the hinge.
        layers += [(chin, chin_far + keel_far), (chin, [chin_near[-1], chin_far[-1], keel_far[0], keel_near[0]])]
    mouth = [*jaw.lip, *(swing(u, v) for u, v in reversed(jaw.lip[:-1]))]
    tooth = tint(bj.tooth, z)
    layers.insert(0, (tint(bj.mouth, z), filled(mouth)))
    for tri in bj.upper_teeth:
        layers += [(tooth, row) for row in sides(grown(tri)) if row]
    for tri in bj.lower_teeth:
        layers += [(tooth, row) for row in sides([swing(u, v) for u, v in grown(tri)]) if row]
    return layers


def _tube(place: Placement) -> tuple[list[tuple[float, list[Layer]]], list[Points]]:
    """The body as a round tube, so seen from the front or back it keeps its width.

    Cross-sections, widened by sin(yaw) at each station, are unioned with the
    side-view silhouette. Returns the fills, each with its depth, and the pale halos around them.
    """
    rig, pose = place.rig, place.pose
    spin, phase = pose.spin, pose.phase
    prof = rig.species.profile
    body = next(p for p in rig.parts if p.name == "body")
    color = tint(body.color, spin.z)
    k = rig.species.outline_px
    fills: list[tuple[float, list[Layer]]] = []
    halos: list[Points] = []
    for i in range(TUBE_STATIONS):
        u = (i + 0.5) / TUBE_STATIONS
        sp = math.sin(spin.at(u))
        if abs(sp) < END_ON:
            continue
        rd, rv = radii(prof, u)
        wide = WIDTH * 0.5 * (rd + rv) * sp
        pts = []
        for j in range(TUBE_SIDES):
            t = 2 * math.pi * j / TUBE_SIDES
            sn = math.sin(t)
            bx, by = rig.bend(u, sn * (rv if sn > 0 else rd), phase)
            pts.append(place.project(bx, by, wide * math.cos(t)))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        halo = []
        for px, py in pts:
            d = math.hypot(px - cx, py - cy) or 1.0
            halo.append((px + k * (px - cx) / d, py + k * (py - cy) / d))
        fills.append((place.depth(u), [(color, pts)]))
        halos.append(halo)
    return fills, halos


def _midline_fin(place: Placement, part: BakedPart) -> list[Points]:
    """A fin on the midline: the roll shortens it and leans it toward the inside of the turn.

    Returns the side silhouette followed by its end-on blades. The silhouette
    narrows to nothing as the body yaws side-on to the fin, the blades widen to
    their full thickness, and drawn together they never leave a hairline.
    """
    rig, pose, project = place.rig, place.pose, place.project
    spin = pose.spin
    fx, fy, tx, ty = rig.spine(part.attach, pose.phase)
    nx, ny = -ty, tx
    k = fin_height(part.flutter, pose.phase) if part.flutter else 1.0
    cb, sb = math.cos(spin.bank), math.sin(spin.bank)
    sp = math.sin(spin.at(part.attach))

    def at(a: float, b: float, lateral: float = 0.0) -> tuple[float, float]:
        return project(fx + a * tx + k * b * cb * nx, fy + a * ty + k * b * cb * ny, sp * k * b * sb + lateral)

    shapes = [[at(a, b) for a, b in part.points]]
    if abs(sp) > 0.05:
        for blade in part.blades:
            shapes.append([at(a, b, hw * abs(sp)) for a, b, hw in blade] + [at(a, b, -hw * abs(sp)) for a, b, hw in reversed(blade)])
    return shapes


def _flipper(place: Placement, part: BakedPart, flank: int) -> tuple[list[Points], float] | None:
    """One of a pair, hanging down and out from its side of the body.

    The yaw spreads the pair apart and the roll drops one flipper while it lifts
    the other. Returns the side silhouette followed by the end-on blades, and
    how far onto the viewer's flank it sits (negative: the far one).
    """
    rig, pose, project = place.rig, place.pose, place.project
    spin = pose.spin
    fx, fy, tx, ty = rig.spine(part.attach, pose.phase)
    nx, ny = -ty, tx
    psi = spin.at(part.attach)
    sp, cp = math.sin(psi), math.cos(psi)
    near = flank * cp
    if near < 0 and abs(spin.bank) < 0.02 and abs(sp) < 0.03:
        return None
    rd, rv = radii(rig.species.profile, part.attach)
    root = 0.9 * WIDTH * 0.5 * (rd + rv)
    base = min(b for _, b in part.points)
    ang = max(MIN_ANG, min(MAX_ANG, DELTA0 + flank * spin.bank * 0.5))
    kv, kl = max(math.sin(ang) / SIN0, 0.15), 0.65 * math.cos(ang) / SIN0

    def at(a: float, b: float, lateral: float = 0.0) -> tuple[float, float]:
        out = -sp * flank * (root + max(b - base, 0.0) * kl)
        return project(fx + a * tx + b * kv * nx, fy + a * ty + b * kv * ny, out + lateral)

    shapes = [[at(a, b) for a, b in part.points]]
    if abs(sp) > 0.05:
        for blade in part.blades:
            shapes.append([at(a, b, hw * abs(sp)) for a, b, hw in blade] + [at(a, b, -hw * abs(sp)) for a, b, hw in reversed(blade)])
    return shapes, near


def _place(place: Placement) -> tuple[list[Points], list[Points], list[Layer]]:
    """Outline polygons, tube halos and the colour layers, back to front, in canvas coordinates.

    The body outline goes down first, then a scene sorted by how far toward the
    viewer each piece is: the round body's cross-sections and any fin seen more
    end-on than side-on, so a head that points at the viewer hides the fin
    behind it. The markings and the jaw follow, and the fins seen side-on last.
    """
    rig, pose = place.rig, place.pose
    spin = pose.spin
    z = spin.z
    jaw = rig.jaw if pose.jaw_open > 0.02 else None

    outlines: list[Points] = []
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
            pts = [place.outline(u, v) if part.name == "body" else place.surface(u, v) for u, v in part.points]
            if part.outline:
                outlines.append(pts)
            layers.append((color, pts))
            continue
        flanks = (1, -1) if part.paired else (0,)
        for flank in flanks:
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
                back += [(tint(part.color, z - 0.3), pts) for pts in shapes]
            elif end_on:
                scene.append((place.depth(part.attach) + FLANK_DEPTH * near * bool(flank), [(color, pts) for pts in shapes]))
            else:
                late += [(color, pts) for pts in shapes]
    if jaw:
        layers += _jaw_layers(place)
    halos: list[Points] = []
    if any(abs(math.sin(y)) > END_ON for y in spin.yaw):
        fills, halos = _tube(place)
        scene += fills
    scene.sort(key=lambda item: item[0])
    body_i = next(i for i, p in enumerate(p for p in rig.parts if p.attach is None) if p.name == "body")
    layers[body_i + 1:body_i + 1] = [layer for _, group in scene for layer in group]
    layers[body_i:body_i] = back
    return outlines, halos, layers + late


def _draw_bubbles(draw: ImageDraw.ImageDraw, bubbles: Bubbles, ax: int, ay: int, bx: int, by: int, front: bool) -> None:
    for b in bubbles.items:
        if b.front != front:
            continue
        fade = 1.0 - (b.age / b.life) ** 2
        x, y, r = (b.x - ax) * SS - bx, (b.y - ay) * SS - by, b.r * SS
        fill, line = int(46 * fade), int(215 * fade)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(fill,) * 4, outline=(line,) * 4, width=max(1, SS - 1))


def render(rig: Rig, pose: Pose, bubbles: Bubbles, lay: Layout, x: float, y: float) -> Sprite:
    """Draw the animal centred on screen position (x, y).

    The canvas is premultiplied "RGBa" from the start (opaque parts have alpha
    255, bubbles use equal colour and alpha), so the box reduce is a correct
    premultiplied downsample with no per-frame RGBA/RGBa conversion.
    """
    ax, ay = round(x), round(y)
    place = Placement(rig, pose, lay.length * SS, ((x - ax) * SS, (y - ay) * SS))
    outlines, halos, layers = _place(place)

    lo_x = lo_y = math.inf
    hi_x = hi_y = -math.inf
    for _, pts in layers:
        xs, ys = zip(*pts)
        lo_x, hi_x = min(lo_x, min(xs)), max(hi_x, max(xs))
        lo_y, hi_y = min(lo_y, min(ys)), max(hi_y, max(ys))
    pad = rig.species.outline_px + SS
    lo_x, hi_x, lo_y, hi_y = lo_x - pad, hi_x + pad, lo_y - pad, hi_y + pad
    for b in bubbles.items:
        r = (b.r + 1) * SS
        bxc, byc = (b.x - ax) * SS, (b.y - ay) * SS
        lo_x, hi_x = min(lo_x, bxc - r), max(hi_x, bxc + r)
        lo_y, hi_y = min(lo_y, byc - r), max(hi_y, byc + r)
    cap = lay.half * SS
    bx = max(-cap, math.floor(lo_x / SS) * SS)
    by = max(-cap, math.floor(lo_y / SS) * SS)
    w = min(cap, math.ceil(hi_x / SS) * SS) - bx
    h = min(cap, math.ceil(hi_y / SS) * SS) - by

    big = Image.new("RGBa", (w, h))
    draw = ImageDraw.Draw(big)
    _draw_bubbles(draw, bubbles, ax, ay, bx, by, front=False)
    # Outline copies go underneath everything as shifted polygons (a wide
    # draw.line is several times slower).
    rim = tint(rig.outline_color, pose.spin.z)
    for pts in outlines:
        for dx, dy in rig.outline_offsets:
            draw.polygon([(px + dx - bx, py + dy - by) for px, py in pts], fill=rim)
    for pts in halos:
        draw.polygon([(px - bx, py - by) for px, py in pts], fill=rim)
    for color, pts in layers:
        draw.polygon([(px - bx, py - by) for px, py in pts], fill=color)
    _draw_bubbles(draw, bubbles, ax, ay, bx, by, front=True)
    return Sprite(big.reduce(SS), ax + bx // SS, ay + by // SS)
