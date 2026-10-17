# orca

An orca that hunts a salmon across your Windows 11 desktop, over every other window.
Both animals are click-through, have no taskbar button and never take focus, so you can keep working.

## Run

```
python orca.py
```

Needs Python 3.12, Pillow and numpy. Nothing else is installed.

## What happens

The orca cruises and wanders. After three to six seconds, once a salmon has swum in from an edge, it notices the fish and stalks it.
The salmon is alarmed when the orca closes within three body lengths and bolts, dodging from side to side.
Within about one and a half lengths the orca lunges with its mouth open. If the mouth reaches the salmon the jaw snaps shut, the head shakes and a burst of bubbles marks the spot.
A missed lunge drops back to stalking, and a hunt can take several tries.
The orca then swims on slowly for about three seconds, a new salmon swims in, and it starts again.
A whole cycle takes roughly 8 to 30 seconds and averages about 15.

Both animals can face either way and are never drawn upside down. To turn around, an animal swims a half circle through depth, alternately round the near side and the far side. The head swings round first and the body follows a moment later, so it curves as it goes, it banks into the turn, and the dorsal fin leans and the flippers spread. It looms about 15 percent larger passing close to you or shrinks about 12 percent and turns hazy passing far away, and is back to its usual size before the turn ends. Seen head on, the dorsal fin is a blade with real width and the flippers are paddles hanging down and out. The jaw, teeth and bubbles follow the turn too.

The orca only bites with its head settled in the swimming plane. A head swinging round mid-turn does not catch anything.

## Quit

Press `Ctrl+Alt+O`, or press `Ctrl+C` in the console that launched it.
The console prints every mode change with its time, for example `[  20.73s] orca STALK -> LUNGE`, and each time the orca starts turning round, for example `[   3.20s] orca TURN toward the viewer`.

## Flags

- `--seed N` seeds the random number generator, so a run repeats exactly.
- `--frames N` runs N frames then exits and prints average and maximum frame time for simulating, rendering and presenting both animals, and the same split into frames where the orca or salmon is turning and calm frames.
- `--snapshot out.png` saves the last rendered orca frame (transparent RGBA) after a `--frames` run.
- `--sim SECONDS` runs the simulation headless at a fixed step, prints every transition with its time and a summary of catches, lunges, missed lunges and cycle times.
  It asserts that neither animal leaves the work area, except a salmon that is still swimming in.
- `--film out.png` writes a contact sheet of one hunt, twelve full-screen frames half a second apart, from just before the stalk to just after the catch. No window opens.
- `--turns out.png` writes twelve frames across a turn toward you and twelve across a turn away from you, for the orca, the orca with its jaw open and the salmon, each with its head yaw, tail yaw, roll and depth. No window opens.
- `--turn-gif PREFIX` writes `PREFIX-orca.gif` and `PREFIX-salmon.gif`, a few turns at true screen motion. No window opens.
- `--sheet out.png` writes the orca and salmon tail beats and the orca's jaw at 0, 0.5 and 1 open. No window opens.

## Layout

- `anatomy.py` is the shape machinery: a `Species` is plain tables, baked once and bent along a travelling spine wave.
- `species.py` holds the `ORCA` and `SALMON` tables.
- `kinematics.py` has `Body`, steering and edge avoidance, and `Attitude`, the one owner of an animal's 3D pose: the yaw chain along its spine, roll and the depth arc a turn sweeps.
- `projection.py` is the one mapping from a pose to screen pixels. The drawing, the bubble vents and the nose that touches the salmon all go through it.
- `behavior.py` has the state machines and `World`, which is pure and never touches rendering or Win32.
- `bubbles.py`, `render.py` and `overlay.py` draw, rasterise and present. Each animal gets one layered window, and the salmon's sits just below the orca's.
- `sim.py`, `film.py` and `turns.py` run the world, or scripted turns, without a window. `orca.py` is the entry point.
