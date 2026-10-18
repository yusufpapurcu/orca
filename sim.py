"""Headless run of the World: every transition with its time, a bounds check and a summary."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from behavior import FishMode, OrcaMode, Transition, World, orca_length
from projection import Rect

DEFAULT_AREA = Rect(0, 0, 1920, 1032)
DT = 1 / 60
BINS = 5  # depth histogram bins from the near limit to the far
SLACK = 0.1  # orca lengths an animal may overshoot a side of the frustum by: a chase along an edge skids a little
SOFT = 0.5  # ... and the near and far limits, which only make it look a little larger or smaller


def new_world(seed: int, area: Rect = DEFAULT_AREA) -> World:
    return World(area, orca_length(round(area.bottom - area.top)), random.Random(seed))


@dataclass
class Report:
    seconds: float
    catches: int = 0
    lunges: int = 0
    misses: int = 0
    gave_up: int = 0
    catch_times: list[float] = field(default_factory=list)
    depth: dict[str, list[int]] = field(default_factory=lambda: {"orca": [0] * BINS, "salmon": [0] * BINS})
    deep: dict[str, int] = field(default_factory=lambda: {"orca": 0, "salmon": 0})  # frames beyond the halfway depth

    @property
    def cycles(self) -> list[float]:
        return [b - a for a, b in zip(self.catch_times, self.catch_times[1:])]

    def _histogram(self, actor: str) -> str:
        n = sum(self.depth[actor]) or 1
        bins = " ".join(f"{100 * k / n:3.0f}%" for k in self.depth[actor])
        return f"  {actor} depth near->far [{bins}] beyond halfway {100 * self.deep[actor] / n:.0f}%"

    def __str__(self) -> str:
        cyc = self.cycles
        mean = f"{sum(cyc) / len(cyc):.1f}s (min {min(cyc):.1f}s, max {max(cyc):.1f}s)" if cyc else "n/a"
        return (f"summary: {self.seconds:.0f}s simulated, catches={self.catches}, lunges={self.lunges}, "
                f"missed lunges={self.misses}, stalks given up={self.gave_up}, mean cycle (catch to catch)={mean}\n"
                + self._histogram("orca") + "\n" + self._histogram("salmon"))


def simulate(seconds: float, seed: int, quiet: bool = False) -> Report:
    world = new_world(seed)
    cam = world.cam
    report = Report(seconds)

    def inside(b) -> bool:
        return all(d >= -(SOFT if abs(n[2]) == 1.0 else SLACK) * world.orca_length for d, n in cam.clearance(b.x, b.y, b.z))

    def tally(actor: str, z: float) -> None:
        k = int((z - cam.near) / (cam.far - cam.near) * BINS)
        report.depth[actor][max(0, min(BINS - 1, k))] += 1
        report.deep[actor] += z > cam.mid

    for _ in range(round(seconds / DT)):
        for e in world.step(DT):
            if not isinstance(e, Transition):
                continue
            if not quiet:
                print(e)
            if e.actor == "orca":
                if e.new is OrcaMode.LUNGE:
                    report.lunges += 1
                elif e.old is OrcaMode.LUNGE and e.new is OrcaMode.STALK:
                    report.misses += 1
                elif e.old is OrcaMode.STALK and e.new is OrcaMode.CRUISE:
                    report.gave_up += 1
                elif e.new is OrcaMode.CHOMP:
                    report.catches += 1
                    report.catch_times.append(e.t)
        # Only a salmon that is swimming in is allowed outside the frustum.
        o, f = world.orca.body, world.fish
        assert inside(o), f"orca left the frustum at t={world.t:.2f}: ({o.x:.0f}, {o.y:.0f}, {o.z:.0f})"
        tally("orca", o.z)
        if f and f.mode is not FishMode.ENTER:
            b = f.body
            assert inside(b), f"salmon left the frustum at t={world.t:.2f}: ({b.x:.0f}, {b.y:.0f}, {b.z:.0f})"
            tally("salmon", b.z)
    return report
