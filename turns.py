"""Scripted turns for looking at the 3D turn without a window: a contact sheet and GIFs.

They drive a real Body with the real steering, so what they show is what the
desktop shows. Nothing here is a second implementation of the turn.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from anatomy import Rig, compile_species
from behavior import FISH_BEAT_SPEED, FISH_GAITS, ORCA_BEAT_SPEED, ORCA_GAITS, REF_LENGTH, FishMode, OrcaMode
from bubbles import Bubbles
from kinematics import Body, accelerate, advance, steer
from render import Layout, render
from species import ORCA, SALMON

DT = 1 / 60
BLUE = (96, 140, 176, 255)
GUIDE = (70, 105, 135, 255)
INK = (240, 246, 250, 255)
DARK = (22, 29, 39, 255)
FONT = ImageFont.load_default(size=13)
SETTLED = 0.12  # radians the tail may still be off its goal when a turn counts as over


@dataclass
class Swimmer:
    rig: Rig
    lay: Layout
    turn_rate: float
    cruise: float  # px/s
    beat_hz: float
    beat_speed: float
    unit: float
    body: Body

    @staticmethod
    def make(kind: str, orca_len: float, x: float = 0.0, y: float = 0.0) -> "Swimmer":
        unit = orca_len / REF_LENGTH
        if kind == "orca":
            sp, gait, speed, beat_speed = ORCA, ORCA_GAITS[OrcaMode.CRUISE], 150.0, ORCA_BEAT_SPEED
        else:
            sp, gait, speed, beat_speed = SALMON, FISH_GAITS[FishMode.WANDER], 130.0, FISH_BEAT_SPEED
        rig = compile_species(sp)
        body = Body.launch(x, y, 0.0, speed * unit)
        return Swimmer(rig, Layout.for_rig(rig, orca_len), gait.turn, speed * unit, sp.beat_hz, beat_speed, unit, body)

    def step(self, heading: float) -> None:
        b = self.body
        steer(b, heading, self.turn_rate, DT)
        accelerate(b, self.cruise, 400, DT)
        advance(b, self.beat_hz * (0.6 + 0.4 * b.speed / (self.beat_speed * self.unit)), DT)

    def snap(self) -> Body:
        return copy.deepcopy(self.body)

    def draw(self, canvas: Image.Image, body: Body, dx: float = 0.0, dy: float = 0.0, alpha: float = 1.0, jaw: float = 0.0) -> None:
        s = render(self.rig, body.pose(0.0, jaw), Bubbles(), self.lay, body.x + dx, body.y + dy)
        img = s.image.convert("RGBA")
        if alpha < 1.0:
            img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
        canvas.paste(img, (s.x, s.y), img)


def record_turn(kind: str, orca_len: float, dip: int) -> tuple[Swimmer, list[Body]]:
    """Swim right, then ask for a heading to the left. Returns the bodies from just before the request until the tail settles."""
    sw = Swimmer.make(kind, orca_len)
    sw.body.att.dip = dip
    for _ in range(30):
        sw.step(0.0)
    states = [sw.snap()]
    settled = 0
    for _ in range(round(4.0 / DT)):
        sw.step(math.pi)
        states.append(sw.snap())
        a = states[-1].att
        settled = settled + 1 if abs(a.yaw[-1] - a.k * math.pi) < SETTLED else 0
        if settled > 6:
            break
    return sw, states


def _label(d: ImageDraw.ImageDraw, x: int, y: int, body: Body, k: int, dx: float) -> None:
    a = body.att
    head, tail = abs(math.degrees(a.yaw[0])), abs(math.degrees(a.yaw[-1]))
    d.text((x, y), f"#{k + 1}  head {head:3.0f}  tail {tail:3.0f}  bank {math.degrees(a.bank):+3.0f}", fill=INK, font=FONT)
    d.text((x, y + 15), f"depth {a.z:+.2f}   dx {dx:+4.0f}", fill=INK, font=FONT)


def turn_rows(kind: str, orca_len: float, dip: int, jaw: float = 0.0, frames: int = 12, cols: int = 6) -> list[Image.Image]:
    sw, states = record_turn(kind, orca_len, dip)
    idx = [round(i * (len(states) - 1) / (frames - 1)) for i in range(frames)]
    sel = [states[i] for i in idx]
    x0 = sel[0].x
    reach = sw.lay.half * 0.62
    cw, ch, label = round(2 * reach), round(2 * reach * 0.8), 34
    rows = []
    for r in range(frames // cols):
        row = Image.new("RGBA", (cw * cols, ch + label), BLUE)
        d = ImageDraw.Draw(row)
        for c in range(cols):
            k = r * cols + c
            body = sel[k]
            cell = Image.new("RGBA", row.size, (0, 0, 0, 0))
            sw.draw(cell, body, c * cw + cw / 2 - body.x, ch / 2 - body.y, jaw=jaw)
            row.alpha_composite(cell)
            d.line([(c * cw, 0), (c * cw, ch + label)], fill=GUIDE)
            d.line([(c * cw, ch / 2), (c * cw + cw, ch / 2)], fill=GUIDE)
            _label(d, c * cw + 6, ch + 3, body, k, body.x - x0)
        rows.append(row)
    xs = [b.x - x0 for b in sel]
    path = Image.new("RGBA", (cw * cols, ch), BLUE)
    margin = (path.width - (max(xs) - min(xs))) / 2 - min(xs)
    for k, body in enumerate(sel):
        sw.draw(path, body, margin + body.x - x0 - body.x, ch / 2 - body.y, alpha=0.18 + 0.82 * (k / (frames - 1)) ** 2, jaw=jaw)
    ImageDraw.Draw(path).text((8, 6), f"{kind}{', jaw open' if jaw else ''}, {'toward' if dip > 0 else 'away from'} the viewer: all {frames} frames at true screen positions, newest solid", fill=INK, font=FONT)
    return rows + [path]


def make_turn_sheet(orca_len: float = 260.0) -> Image.Image:
    """Twelve frames across a turn toward the viewer and twelve across a turn away, for the orca, the orca with its jaw open and the salmon."""
    sections: list[Image.Image] = []
    for kind, length, jaw in (("orca", orca_len, 0.0), ("orca", orca_len, 1.0), ("salmon", orca_len * 2.4, 0.0)):
        for dip in (1, -1):
            sections += turn_rows(kind, length, dip, jaw)
    w = max(s.width for s in sections)
    sheet = Image.new("RGBA", (w, sum(s.height + 6 for s in sections)), (60, 78, 98, 255))
    y = 0
    for s in sections:
        sheet.paste(s, (0, y))
        y += s.height + 6
    return sheet


def make_turn_gif(kind: str, path: str, orca_len: float = 240.0) -> None:
    """A few turns at true screen motion: out to the right, back, out again, 30 fps."""
    w, h = 900, 330
    scene = [(0.0, 0.0), (0.7, math.pi), (2.45, 0.0), (4.2, math.pi), (5.5, 0.0)]
    seconds = 7.0

    def run(x0: float, y0: float) -> tuple[Swimmer, list[Body]]:
        sw = Swimmer.make(kind, orca_len, x0, y0)
        out = []
        for f in range(round(seconds * 30)):
            target = [hd for t0, hd in scene if f / 30 >= t0][-1]
            sw.step(target)
            sw.step(target)
            out.append(sw.snap())
        return sw, out

    _, trial = run(0.0, 0.0)
    lo, hi = min(b.x for b in trial), max(b.x for b in trial)
    sw, bodies = run((w - (hi - lo)) / 2 - lo, h / 2)
    frames = []
    for b in bodies:
        img = Image.new("RGBA", (w, h), DARK)
        sw.draw(img, b)
        frames.append(img.convert("RGB"))
    pal = Image.new("RGB", (w, h * 3))
    for i, k in enumerate((10, len(frames) // 3, 2 * len(frames) // 3)):
        pal.paste(frames[k], (0, i * h))
    pal = pal.quantize(colors=250, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=33, loop=0, disposal=2, optimize=False)
