"""Rasterising a posed animal with Pillow at 3x supersampling.

The frame is the tight bounding box of the animal and its bubbles, not a fixed
window: at 3x a canvas that covers every possible pose costs more than the
drawing itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from anatomy import Rig, fin_height
from bubbles import Bubbles
from kinematics import Body, projector, view

SS = 3


@dataclass(frozen=True)
class Pose:
    phase: float
    pitch: float  # nose up positive
    xscale: float  # signed horizontal scale: sign is the facing, 0 is mid-flip


def pose_of(body: Body, pitch_extra: float = 0.0) -> Pose:
    xscale, pitch = view(body)
    return Pose(body.phase, pitch + pitch_extra, xscale)


@dataclass(frozen=True)
class Layout:
    """Size of one animal on screen. `half` bounds any pose plus its bubbles."""

    length: int
    half: int

    @staticmethod
    def for_rig(rig: Rig, orca_length: float) -> "Layout":
        length = round(orca_length * rig.species.length_frac)
        return Layout(length, math.ceil((rig.reach + rig.species.bubble_room) * length))

    @property
    def size(self) -> int:
        return 2 * self.half


@dataclass(frozen=True)
class Sprite:
    image: Image.Image  # premultiplied "RGBa"
    x: int  # screen position of the top-left corner
    y: int


def _place(rig: Rig, pose: Pose, project):
    placed = []
    phase = pose.phase
    for part in rig.parts:
        if part.attach is None:
            pts = [project(*rig.bend(u, v, phase)) for u, v in part.points]
        else:
            fx, fy, tx, ty = rig.spine(part.attach, phase)
            nx, ny = -ty, tx
            k = fin_height(part.flutter, phase) if part.flutter else 1.0
            pts = [project(fx + a * tx + k * b * nx, fy + a * ty + k * b * ny) for a, b in part.points]
        placed.append((part, pts))
    return placed


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
    project = projector(((x - ax) * SS, (y - ay) * SS), lay.length * SS, pose.xscale, pose.pitch)
    placed = _place(rig, pose, project)

    lo_x = lo_y = math.inf
    hi_x = hi_y = -math.inf
    for _, pts in placed:
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
    for part, pts in placed:
        if part.outline:
            for dx, dy in rig.outline_offsets:
                draw.polygon([(px + dx - bx, py + dy - by) for px, py in pts], fill=rig.outline_color)
    for part, pts in placed:
        draw.polygon([(px - bx, py - by) for px, py in pts], fill=part.color)
    _draw_bubbles(draw, bubbles, ax, ay, bx, by, front=True)
    return Sprite(big.reduce(SS), ax + bx // SS, ay + by // SS)
