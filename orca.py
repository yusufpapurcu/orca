"""Animated orca that swims across the Windows desktop in a click-through overlay.

Anatomy is declared once in body space, deformed by a travelling spine wave,
rasterised with Pillow at 3x supersampling and pushed to a layered window with
per-pixel alpha (UpdateLayeredWindow). Quit with Ctrl+Alt+O or Ctrl+C.
"""

from __future__ import annotations

import argparse
import random
import time

from PIL import Image

from anatomy import compile_species
from behavior import SwimState
from bubbles import Bubbles
from overlay import Overlay, primary_work_area, user32, winmm
from render import Layout, Pose, body_anchor, make_sheet, render
from species import ORCA

FRAME_TIME = 1 / 60


def orca_length(screen_h: int) -> int:
    return max(200, min(520, round(screen_h * 0.296)))


def run(frames: int | None, snapshot: str | None) -> None:
    user32.SetProcessDpiAwarenessContext(-4)
    area = primary_work_area()
    lay = Layout.for_length(orca_length(area.bottom - area.top))
    rig = compile_species(ORCA)
    rng = random.Random()
    state = SwimState.start(area, lay.width / 2, rng)
    bubbles = Bubbles()

    winmm.timeBeginPeriod(1)
    overlay = Overlay(lay.width, lay.height)
    render_ms: list[float] = []
    total_ms: list[float] = []
    last: Image.Image | None = None
    try:
        overlay.show()
        prev = target = time.perf_counter()
        next_top = prev + 2.0
        n = 0
        while frames is None or n < frames:
            if not overlay.pump():
                break
            t0 = time.perf_counter()
            dt = min(t0 - prev, 0.1)
            prev = t0
            state.step(dt, ORCA, area, lay.width / 2, rng)

            dy, pitch = state.bob(lay.length)
            pose = Pose(state.phase, pitch, state.direction)
            sources = [body_anchor(rig, 0.2, ORCA.profile.rim_v(0.2, -1), pose, lay),
                       body_anchor(rig, 0.012, 0.035, pose, lay)]
            bubbles.update(dt, sources, -state.direction * state.speed * 0.3, rng)

            frame = render(rig, pose, bubbles, lay)
            t1 = time.perf_counter()
            overlay.present(frame, round(state.x - lay.cx), round(state.base_y + dy - lay.cy))
            t2 = time.perf_counter()
            render_ms.append((t1 - t0) * 1000)
            total_ms.append((t2 - t0) * 1000)
            last = frame
            n += 1

            if t2 > next_top:
                overlay.keep_on_top()
                next_top = t2 + 2.0
            target += FRAME_TIME
            now = time.perf_counter()
            if target < now:
                target = now
            elif target - now > 0.002:
                time.sleep(target - now - 0.0015)
            while time.perf_counter() < target:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        overlay.close()
        winmm.timeEndPeriod(1)

    if total_ms:
        print(f"frames={len(total_ms)} window={lay.width}x{lay.height} length={lay.length}px "
              f"render avg={sum(render_ms) / len(render_ms):.2f}ms "
              f"render+push avg={sum(total_ms) / len(total_ms):.2f}ms max={max(total_ms):.2f}ms")
    if snapshot and last is not None:
        last.convert("RGBA").save(snapshot)
        print(f"snapshot saved to {snapshot}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Orca swimming across your desktop. Quit with Ctrl+Alt+O.")
    ap.add_argument("--frames", type=int, help="run N frames then exit")
    ap.add_argument("--snapshot", help="after the run, save the last rendered RGBA frame to this PNG")
    ap.add_argument("--sheet", help="render 6 frames of one tail beat to this PNG and exit (no window)")
    args = ap.parse_args()
    if args.sheet:
        make_sheet(compile_species(ORCA), Layout.for_length(320)).save(args.sheet)
        print(f"sheet saved to {args.sheet}")
        return
    run(args.frames, args.snapshot)


if __name__ == "__main__":
    main()
