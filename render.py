"""Rasterising a posed animal with Pillow at 3x supersampling."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from anatomy import Rig
from bubbles import Bubbles

SS = 3


@dataclass(frozen=True)
class Pose:
    phase: float
    pitch: float
    facing: int  # +1 swims right, -1 swims left


@dataclass(frozen=True)
class Layout:
    length: int
    width: int
    height: int
    cx: float
    cy: float

    @staticmethod
    def for_length(length: int) -> "Layout":
        w, h = round(length * 1.5), round(length * 1.0)
        return Layout(length, w, h, w / 2, h * 0.58)


def projector(pose: Pose, lay: Layout, scale: float):
    """Map spine-space (length units, nose at x=0) to canvas pixels."""
    k = lay.length * scale
    c, s = math.cos(pose.pitch), math.sin(pose.pitch)
    f, ox, oy = pose.facing, lay.cx * scale, lay.cy * scale

    def project(lx: float, ly: float) -> tuple[float, float]:
        x, y = (0.5 - lx) * k, ly * k
        return ox + f * (x * c + y * s), oy + (y * c - x * s)

    return project


def body_anchor(rig: Rig, u: float, v: float, pose: Pose, lay: Layout) -> tuple[float, float]:
    return projector(pose, lay, 1)(*rig.bend(u, v, pose.phase))


def draw_animal(draw: ImageDraw.ImageDraw, rig: Rig, pose: Pose, lay: Layout) -> None:
    project = projector(pose, lay, SS)
    phase = pose.phase
    placed = []
    for part in rig.parts:
        if part.attach is None:
            pts = [project(*rig.bend(u, v, phase)) for u, v in part.points]
        else:
            fx, fy, tx, ty = rig.spine(part.attach, phase)
            nx, ny = -ty, tx
            pts = [project(fx + a * tx + b * nx, fy + a * ty + b * ny) for a, b in part.points]
        placed.append((part, pts))
    # Outline copies are drawn underneath everything as offset polygons (a wide
    # draw.line is several times slower).
    for part, pts in placed:
        if part.outline:
            for dx, dy in rig.outline_offsets:
                draw.polygon([(x + dx, y + dy) for x, y in pts], fill=rig.outline_color)
    for part, pts in placed:
        draw.polygon(pts, fill=part.color)


def draw_bubbles(draw: ImageDraw.ImageDraw, bubbles: Bubbles) -> None:
    for b in bubbles.items:
        fade = 1.0 - (b.age / b.life) ** 2
        x, y, r = b.x * SS, b.y * SS, b.r * SS
        fill, line = int(46 * fade), int(215 * fade)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(fill,) * 4, outline=(line,) * 4, width=max(1, SS - 1))


def render(rig: Rig, pose: Pose, bubbles: Bubbles, lay: Layout) -> Image.Image:
    """Return the frame as a premultiplied "RGBa" image of the window size.

    The canvas is premultiplied from the start (opaque parts have alpha 255,
    bubbles use equal colour and alpha), so the box reduce is a correct
    premultiplied downsample with no per-frame RGBA/RGBa conversion.
    """
    big = Image.new("RGBa", (lay.width * SS, lay.height * SS))
    draw = ImageDraw.Draw(big)
    draw_bubbles(draw, bubbles)
    draw_animal(draw, rig, pose, lay)
    return big.reduce(SS)


def make_sheet(rig: Rig, lay: Layout, frames: int = 6) -> Image.Image:
    cols = 3
    rows = math.ceil(frames / cols)
    bg = Image.new("RGBA", (lay.width * cols, lay.height * rows), (96, 140, 176, 255))
    for k in range(frames):
        frame = render(rig, Pose(k / frames, 0.0, 1), Bubbles(), lay).convert("RGBA")
        bg.alpha_composite(frame, ((k % cols) * lay.width, (k // cols) * lay.height))
    return bg
