# orca

An animated orca that swims across your Windows 11 desktop, over every other window.
The overlay is click-through, has no taskbar button and never takes focus, so you can keep working.

## Run

```
python orca.py
```

Needs Python 3.12 and Pillow. Nothing else is installed.

Each pass the orca crosses the primary monitor's work area at a random depth, leaves the far edge,
then returns the other way. Occasional bubbles rise from its blowhole and mouth.

## Quit

Press `Ctrl+Alt+O`, or press `Ctrl+C` in the console that launched it.

## Other flags

- `--frames N` runs N frames then exits and prints average and max frame time.
- `--snapshot out.png` saves the last rendered frame (transparent RGBA) after the run.
- `--sheet out.png` writes six frames of one tail beat to a PNG and exits, with no window.
