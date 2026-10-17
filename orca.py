"""Animated orca that swims across the Windows desktop in a click-through overlay.

Anatomy is declared once in body space, deformed by a travelling spine wave,
rasterised with Pillow at 3x supersampling and pushed to a layered window with
per-pixel alpha (UpdateLayeredWindow). Quit with Ctrl+Alt+O or Ctrl+C.
"""

from __future__ import annotations

import argparse
import random
import time

from behavior import World
from overlay import Overlay, primary_work_area, user32, winmm
from render import Layout, Sprite, make_sheet, pose_of, render
from species import ORCA
from anatomy import compile_species

FRAME_TIME = 1 / 60


def orca_length(screen_h: int) -> int:
    return max(200, min(520, round(screen_h * 0.296)))


def run(frames: int | None, snapshot: str | None, seed: int | None) -> None:
    user32.SetProcessDpiAwarenessContext(-4)
    area = primary_work_area()
    world = World(area, orca_length(area.bottom - area.top), random.Random(seed))
    rig = world.orca_rig
    lay = Layout.for_rig(rig, world.orca_length)

    winmm.timeBeginPeriod(1)
    overlay = Overlay(lay.size, "Orca", hotkey=True)
    render_ms: list[float] = []
    total_ms: list[float] = []
    last: Sprite | None = None
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
            for event in world.step(dt):
                print(event, flush=True)

            o = world.orca
            sprite = render(rig, pose_of(o.body), o.bubbles, lay, o.body.x, o.body.y)
            t1 = time.perf_counter()
            overlay.present(sprite)
            t2 = time.perf_counter()
            render_ms.append((t1 - t0) * 1000)
            total_ms.append((t2 - t0) * 1000)
            last = sprite
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
        print(f"frames={len(total_ms)} length={lay.length}px "
              f"render avg={sum(render_ms) / len(render_ms):.2f}ms "
              f"render+push avg={sum(total_ms) / len(total_ms):.2f}ms max={max(total_ms):.2f}ms")
    if snapshot and last is not None:
        last.image.convert("RGBA").save(snapshot)
        print(f"snapshot saved to {snapshot}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Orca swimming across your desktop. Quit with Ctrl+Alt+O.")
    ap.add_argument("--frames", type=int, help="run N frames then exit")
    ap.add_argument("--snapshot", help="after the run, save the last rendered RGBA frame to this PNG")
    ap.add_argument("--seed", type=int, help="seed the random number generator")
    ap.add_argument("--sheet", help="render 6 frames of one tail beat to this PNG and exit (no window)")
    args = ap.parse_args()
    if args.sheet:
        make_sheet(compile_species(ORCA), Layout.for_rig(compile_species(ORCA), 320)).save(args.sheet)
        print(f"sheet saved to {args.sheet}")
        return
    run(args.frames, args.snapshot, args.seed)


if __name__ == "__main__":
    main()
