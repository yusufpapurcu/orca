"""Contact sheets for looking at the animals and a hunt without a window."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

from anatomy import Rig, compile_species
from behavior import OrcaMode, World, head_shake
from bubbles import Bubbles
from render import Layout, Pose, Sprite, pose_of, render
from sim import DT, new_world
from species import ORCA, SALMON

SHEET_BG = (96, 140, 176, 255)
FILM_BG = (22, 29, 39, 255)


def grid(rig: Rig, lay: Layout, poses: list[Pose], cols: int) -> Image.Image:
    cw, ch = math.ceil(2 * rig.reach * lay.length), math.ceil(rig.reach * lay.length)
    rows = math.ceil(len(poses) / cols)
    sheet = Image.new("RGBA", (cw * cols, ch * rows), SHEET_BG)
    for k, pose in enumerate(poses):
        cx, cy = (k % cols) * cw + cw / 2, (k // cols) * ch + ch / 2
        s = render(rig, pose, Bubbles(), lay, cx, cy)
        sheet.alpha_composite(s.image.convert("RGBA"), (s.x, s.y))
    return sheet


def stack(parts: list[Image.Image]) -> Image.Image:
    sheet = Image.new("RGBA", (max(p.width for p in parts), sum(p.height for p in parts)), SHEET_BG)
    y = 0
    for p in parts:
        sheet.paste(p, (0, y))
        y += p.height
    return sheet


def make_sheet() -> Image.Image:
    """The orca's tail beat and jaw at 0, 0.5 and 1, and the salmon's tail beat, enlarged to be readable."""
    orca, salmon = compile_species(ORCA), compile_species(SALMON)
    beat = [Pose(k / 6, 0.0, 1.0) for k in range(6)]
    jaw = [Pose(0.1, 0.0, 1.0, j) for j in (0.0, 0.5, 1.0)]
    return stack([
        grid(orca, Layout.for_rig(orca, 320), beat, 3),
        grid(orca, Layout.for_rig(orca, 600), jaw, 3),
        grid(salmon, Layout.for_rig(salmon, 800), beat, 3),
    ])


def _blit(canvas: Image.Image, sprite: Sprite) -> None:
    rgba = sprite.image.convert("RGBA")
    canvas.paste(rgba, (sprite.x, sprite.y), rgba)


def snapshot(world: World, lays: tuple[Layout, Layout]) -> Image.Image:
    """The whole work area with both actors where they truly are."""
    a = world.area
    canvas = Image.new("RGBA", (round(a.right - a.left), round(a.bottom - a.top)), FILM_BG)
    f, o = world.fish, world.orca
    if f:
        _blit(canvas, render(world.fish_rig, pose_of(f.body), Bubbles(), lays[1], f.body.x - a.left, f.body.y - a.top))
    _blit(canvas, render(world.orca_rig, pose_of(o.body, head_shake(o), o.jaw_open), o.bubbles, lays[0],
                         o.body.x - a.left, o.body.y - a.top))
    return canvas


def find_hunt(seed: int, shortest: float, longest: float, limit: float = 1200.0) -> float:
    """Time of the first catch whose stalk began between `shortest` and `longest` seconds before it."""
    world = new_world(seed)
    stalk = None
    while world.t < limit:
        for e in world.step(DT):
            if e.actor != "orca":
                continue
            if e.new is OrcaMode.STALK and e.old is OrcaMode.CRUISE:
                stalk = e.t
            elif e.new is OrcaMode.CHOMP and stalk is not None and shortest <= e.t - stalk <= longest:
                return e.t
    raise RuntimeError(f"seed {seed}: no hunt of {shortest}-{longest}s in {limit:.0f}s")


def make_film(seed: int, frames: int = 12, step: float = 0.5, cols: int = 3, width: int = 640) -> Image.Image:
    """Contact sheet of one hunt, from just before the stalk to half a second after the catch."""
    span = (frames - 2) * step
    catch = find_hunt(seed, span - 0.7, span)
    start = catch - span
    world = new_world(seed)
    lays = (Layout.for_rig(world.orca_rig, world.orca_length), Layout.for_rig(world.fish_rig, world.orca_length))
    a = world.area
    height = round(width * (a.bottom - a.top) / (a.right - a.left))
    font = ImageFont.load_default(size=15)
    shots: list[Image.Image] = []
    for k in range(frames):
        until = start + k * step
        while world.t < until - DT / 2:
            world.step(DT)
        img = snapshot(world, lays).resize((width, height), Image.LANCZOS)
        fish = world.fish.mode.name if world.fish else "-"
        d = ImageDraw.Draw(img)
        d.text((8, 6), f"t{world.t - catch:+.1f}s  orca {world.orca.mode.name}  salmon {fish}", fill=(220, 230, 240, 255), font=font)
        shots.append(img)
    rows = math.ceil(frames / cols)
    sheet = Image.new("RGBA", (cols * width + (cols + 1) * 4, rows * height + (rows + 1) * 4), (60, 70, 85, 255))
    for k, img in enumerate(shots):
        sheet.paste(img, (4 + (k % cols) * (width + 4), 4 + (k // cols) * (height + 4)))
    return sheet
