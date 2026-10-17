"""Contact sheets for looking at the animals without a window."""

from __future__ import annotations

import math

from PIL import Image

from anatomy import Rig, compile_species
from bubbles import Bubbles
from render import Layout, Pose, render
from species import ORCA, SALMON

SHEET_BG = (96, 140, 176, 255)


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
    """Orca and salmon tail beats, the salmon enlarged to be readable."""
    orca, salmon = compile_species(ORCA), compile_species(SALMON)
    beat = [Pose(k / 6, 0.0, 1.0) for k in range(6)]
    return stack([
        grid(orca, Layout.for_rig(orca, 320), beat, 3),
        grid(salmon, Layout.for_rig(salmon, 800), beat, 3),
    ])
