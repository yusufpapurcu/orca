# orca

An orca that hunts a salmon across your Windows 11 desktop, over every other window.
Both animals are click-through, have no taskbar button and never take focus, so you can keep working.

## Run

```
python orca.py
```

Needs Python 3.12 and Pillow. Nothing else is installed.

## What happens

The orca cruises and wanders. After three to six seconds, once a salmon has swum in from an edge, it notices the fish and stalks it.
The salmon is alarmed when the orca closes within three body lengths and bolts, dodging from side to side.
Within about one and a half lengths the orca lunges with its mouth open. If the mouth reaches the salmon the jaw snaps shut, the head shakes and a burst of bubbles marks the spot.
A missed lunge drops back to stalking, and a hunt can take several tries.
The orca then swims on slowly for about three seconds, a new salmon swims in, and it starts again.
A whole cycle takes roughly 8 to 30 seconds and averages about 15.

Both animals can face either way and are never drawn upside down. When one turns around it flips toward you, the way a fish does in an aquarium.

## Quit

Press `Ctrl+Alt+O`, or press `Ctrl+C` in the console that launched it.
The console prints every mode change with its time, for example `[  20.73s] orca STALK -> LUNGE`.

## Flags

- `--seed N` seeds the random number generator, so a run repeats exactly.
- `--frames N` runs N frames then exits and prints average and maximum frame time for rendering and presenting both animals.
- `--snapshot out.png` saves the last rendered orca frame (transparent RGBA) after a `--frames` run.
- `--sim SECONDS` runs the simulation headless at a fixed step, prints every transition with its time and a summary of catches, lunges, missed lunges and cycle times.
  It asserts that neither animal leaves the work area, except a salmon that is still swimming in.
- `--film out.png` writes a contact sheet of one hunt, twelve full-screen frames half a second apart, from just before the stalk to just after the catch. No window opens.
- `--sheet out.png` writes the orca and salmon tail beats and the orca's jaw at 0, 0.5 and 1 open. No window opens.

## Layout

- `anatomy.py` is the shape machinery: a `Species` is plain tables, baked once and bent along a travelling spine wave.
- `species.py` holds the `ORCA` and `SALMON` tables.
- `kinematics.py` has `Body`, `steer`, `accelerate`, edge avoidance and the facing and turning rules.
- `behavior.py` has the state machines and `World`, which is pure and never touches rendering or Win32.
- `bubbles.py`, `render.py` and `overlay.py` draw, rasterise and present. Each animal gets one layered window, and the salmon's sits just below the orca's.
- `sim.py` and `film.py` run the world without a window. `orca.py` is the entry point.
