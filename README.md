# orca

An orca that hunts a salmon in 3D across your Windows 11 desktop, over every other window.
Both animals are click-through, have no taskbar button and never take focus, so you can keep working.

## Run

```
python orca.py
```

Needs Python 3.12, Pillow and numpy. Nothing else is installed.

## What happens

The orca cruises and wanders. After three to six seconds, once a salmon has swum in, it notices the fish and stalks it.
The salmon is alarmed when the orca closes within three body lengths and bolts, dodging from side to side, and it may dive away from you or dart toward you.
Within about one and a half lengths the orca lunges with its mouth open. If the mouth reaches the salmon the jaw snaps shut, the head shakes and a burst of bubbles marks the spot.
A missed lunge drops back to stalking, and a hunt can take several tries.
After a catch the orca swims off into the deep for three to four seconds, getting smaller, paler and slower, while the next salmon swims in from an edge or emerges tiny out of the haze. The orca comes back up for it, or stalks it from the distance.
A whole cycle takes roughly 9 to 30 seconds and averages about 15. The orca spends about a third of its time beyond the halfway depth, and the salmon keeps to the front, so most hunts happen near you.

The water is a real volume. Depth runs from slightly in front of the screen plane, where an animal is about 15 percent larger than its usual size, to a far limit where it is about a third of its size, hazed toward blue-grey and at about half opacity. One camera, with its vanishing point in the middle of the work area, maps the world to the screen, so what the screen sees is a frustum: there is much more room to swim in the deep than at the front. Speeds are in world units, so a deep animal crosses the screen slowly. Whichever animal is nearer you is drawn on top.

Both animals head wherever they like in 3D and are never drawn upside down. The head swings round first and the body follows a moment later, so a turn is a curve through depth, the animal banks into it, the dorsal fin leans and the flippers spread. Whether a turn round goes through your side or the far side falls out of where the animal is going. Seen head on, the dorsal fin is a blade with real width and the flippers are paddles hanging down and out. The jaw, teeth and bubbles follow the turn too.

The orca only bites with its head pointing at the salmon and its spine straight behind it. A head swinging round mid-turn does not catch anything.

## Quit

Press `Ctrl+Alt+O`, or press `Ctrl+C` in the console that launched it.
The console prints every mode change with its time, for example `[  20.73s] orca STALK -> LUNGE`, each time the orca turns round, for example `[   3.20s] orca TURN toward the viewer`, each time an animal crosses the halfway depth with its screen position and scale, for example `[  15.55s] orca DEEP at (1748, 649) 0.54x`, and each time the two animals swap places in depth, for example `[   1.58s] salmon in front`.

## Flags

- `--seed N` seeds the random number generator, so a run repeats exactly.
- `--frames N` runs N frames then exits and prints average and maximum frame time for simulating, rendering and presenting both animals, and the same split into frames where the orca is turning, deep, or calm.
- `--snapshot out.png` saves the last rendered orca frame (transparent RGBA) after a `--frames` run.
- `--sim SECONDS` runs the simulation headless at a fixed step, prints every transition with its time and a summary of catches, lunges, missed lunges, cycle times and a depth histogram for each animal.
  It asserts that neither animal leaves the frustum by more than a tenth of an orca length at the sides, or half a length at the near and far limits, except a salmon that is still swimming in.
- `--film out.png` writes a contact sheet of one hunt, twelve full-screen frames half a second apart, from just before the stalk to just after the catch. No window opens.
- `--dive out.png` writes a contact sheet of twelve frames a second apart from a catch: the orca swims off into the deep and comes back for the next salmon. No window opens.
- `--turns out.png` writes twelve frames across a turn toward you and twelve across a turn away from you, for the orca, the orca with its jaw open and the salmon, each with its head yaw, tail yaw, roll, depth and scale. No window opens.
- `--turn-gif PREFIX` writes `PREFIX-orca.gif` and `PREFIX-salmon.gif`, a few turns at true screen motion. No window opens.
- `--depth-gif PATH` writes a GIF of the orca diving away into the deep and returning, eight seconds on a dark sea at true screen motion, scaled down to fit. No window opens.
- `--sheet out.png` writes the orca and salmon tail beats and the orca's jaw at 0, 0.5 and 1 open. No window opens.

## Layout

- `anatomy.py` is the shape machinery: a `Species` is plain tables, baked once and bent along a travelling spine wave.
- `species.py` holds the `ORCA` and `SALMON` tables.
- `kinematics.py` has `Body`, a swimmer with a position in the world and a yaw and pitch, steering toward a 3D direction, edge avoidance against the frustum's walls, and `Attitude`, the yaw chain along its spine and its roll.
- `projection.py` has the `Camera`, the one mapping from the world to the screen and the walls of what it sees, and the `Placement`, the one mapping from a pose to pixels. The drawing, the bubble vents and the nose that touches the salmon all go through it.
- `behavior.py` has the state machines and `World`, which is pure and never touches rendering or Win32. Modes that roam pick waypoints from shallow and deep bands, and the band the next one comes from is a weighted coin, so a trip into the deep lingers.
- `bubbles.py`, `render.py` and `overlay.py` draw, rasterise and present. Each animal gets one layered window, and the nearer animal's window is put above the other's when they swap.
- `sim.py`, `film.py` and `turns.py` run the world, or scripted swims, without a window. `orca.py` is the entry point.
