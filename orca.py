"""Animated orca that swims across the Windows desktop in a click-through overlay.

Anatomy is declared once in body space, deformed by a travelling spine wave,
rasterised with Pillow at 3x supersampling and pushed to layered windows with
per-pixel alpha (UpdateLayeredWindow). Quit with Ctrl+Alt+O or Ctrl+C.
"""

from __future__ import annotations

import argparse
import random
import time

from behavior import World, head_shake, orca_length
from bubbles import Bubbles
from film import make_film, make_sheet
from overlay import Overlay, primary_work_area, user32, winmm
from render import Layout, Sprite, pose_of, render
from sim import simulate

FRAME_TIME = 1 / 60


def run(frames: int | None, snapshot: str | None, seed: int | None) -> None:
    user32.SetProcessDpiAwarenessContext(-4)
    area = primary_work_area()
    world = World(area, orca_length(area.bottom - area.top), random.Random(seed))
    orca_lay = Layout.for_rig(world.orca_rig, world.orca_length)
    fish_lay = Layout.for_rig(world.fish_rig, world.orca_length)

    winmm.timeBeginPeriod(1)
    orca_win = Overlay(orca_lay.size, "Orca", hotkey=True)
    fish_win = Overlay(fish_lay.size, "Salmon")
    render_ms: list[float] = []
    total_ms: list[float] = []
    last: Sprite | None = None
    try:
        orca_win.show()
        prev = target = time.perf_counter()
        next_top = prev + 2.0
        n = 0
        while frames is None or n < frames:
            if not orca_win.pump():
                break
            t0 = time.perf_counter()
            dt = min(t0 - prev, 0.1)
            prev = t0
            for event in world.step(dt):
                print(event, flush=True)

            o, f = world.orca, world.fish
            sprite = render(world.orca_rig, pose_of(o.body, head_shake(o), o.jaw_open), o.bubbles, orca_lay, o.body.x, o.body.y)
            fish_sprite = None
            if f:
                fish_sprite = render(world.fish_rig, pose_of(f.body), Bubbles(), fish_lay, f.body.x, f.body.y)
            t1 = time.perf_counter()
            orca_win.present(sprite)
            if fish_sprite:
                fish_win.present(fish_sprite)
                if fish_win.show():
                    fish_win.place_below(orca_win)
            else:
                fish_win.hide()
            t2 = time.perf_counter()
            render_ms.append((t1 - t0) * 1000)
            total_ms.append((t2 - t0) * 1000)
            last = sprite
            n += 1

            if t2 > next_top:
                orca_win.keep_on_top()
                fish_win.place_below(orca_win)
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
        fish_win.close()
        orca_win.close()
        winmm.timeEndPeriod(1)

    if total_ms:
        print(f"frames={len(total_ms)} orca={orca_lay.length}px salmon={fish_lay.length}px "
              f"render avg={sum(render_ms) / len(render_ms):.2f}ms "
              f"render+present avg={sum(total_ms) / len(total_ms):.2f}ms max={max(total_ms):.2f}ms")
    if snapshot and last is not None:
        last.image.convert("RGBA").save(snapshot)
        print(f"snapshot saved to {snapshot}")


def main() -> None:
    ap = argparse.ArgumentParser(description="An orca on your desktop. Quit with Ctrl+Alt+O.")
    ap.add_argument("--frames", type=int, help="run N frames then exit and print frame times")
    ap.add_argument("--snapshot", help="after the run, save the last rendered orca frame (RGBA) to this PNG")
    ap.add_argument("--seed", type=int, help="seed the random number generator")
    ap.add_argument("--sheet", help="render the tail beats and the jaw to this PNG and exit (no window)")
    ap.add_argument("--film", help="render a contact sheet of one hunt to this PNG and exit (no window)")
    ap.add_argument("--sim", type=float, metavar="SECONDS",
                    help="run the simulation headless, print every transition and a summary, and exit")
    args = ap.parse_args()
    if args.sim:
        print(simulate(args.sim, args.seed if args.seed is not None else 0))
        return
    if args.film:
        make_film(args.seed if args.seed is not None else 0).save(args.film)
        print(f"film saved to {args.film}")
        return
    if args.sheet:
        make_sheet().save(args.sheet)
        print(f"sheet saved to {args.sheet}")
        return
    run(args.frames, args.snapshot, args.seed)


if __name__ == "__main__":
    main()
