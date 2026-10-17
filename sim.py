"""Headless run of the World: every transition with its time, a bounds check and a summary."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from behavior import FishMode, OrcaMode, World, orca_length
from kinematics import Rect

DEFAULT_AREA = Rect(0, 0, 1920, 1032)
DT = 1 / 60


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

    @property
    def cycles(self) -> list[float]:
        return [b - a for a, b in zip(self.catch_times, self.catch_times[1:])]

    def __str__(self) -> str:
        cyc = self.cycles
        mean = f"{sum(cyc) / len(cyc):.1f}s (min {min(cyc):.1f}s, max {max(cyc):.1f}s)" if cyc else "n/a"
        return (f"summary: {self.seconds:.0f}s simulated, catches={self.catches}, lunges={self.lunges}, "
                f"missed lunges={self.misses}, stalks given up={self.gave_up}, mean cycle (catch to catch)={mean}")


def simulate(seconds: float, seed: int, quiet: bool = False) -> Report:
    world = new_world(seed)
    report = Report(seconds)
    for _ in range(round(seconds / DT)):
        for e in world.step(DT):
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
        # Only a salmon that is swimming in is allowed off the work area.
        o, f = world.orca.body, world.fish
        assert world.area.contains(o.x, o.y), f"orca left the work area at t={world.t:.2f}: ({o.x:.0f}, {o.y:.0f})"
        if f and f.mode is not FishMode.ENTER:
            b = f.body
            assert world.area.contains(b.x, b.y), f"salmon left the work area at t={world.t:.2f}: ({b.x:.0f}, {b.y:.0f})"
    return report
