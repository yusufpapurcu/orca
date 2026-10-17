"""The animals: anatomy tables for each species."""

from __future__ import annotations

import math

from anatomy import Jaw, Part, Profile, Pt, Rim, Species, ellipse

EYE_U, EYE_V = 0.100, -0.008

ORCA_PROFILE = Profile((
    (0.000, 0.000, 0.000),
    (0.004, 0.014, 0.014),
    (0.015, 0.030, 0.030),
    (0.040, 0.050, 0.050),
    (0.080, 0.070, 0.068),
    (0.140, 0.088, 0.086),
    (0.220, 0.102, 0.100),
    (0.300, 0.109, 0.106),
    (0.400, 0.108, 0.104),
    (0.500, 0.097, 0.094),
    (0.600, 0.080, 0.080),
    (0.700, 0.062, 0.062),
    (0.800, 0.049, 0.048),
    (0.900, 0.037, 0.035),
        (1.000, 0.027, 0.027),
))

ORCA = Species(
    name="orca",
    profile=ORCA_PROFILE,
    palette={
        "black": "#111418",
        "white": "#f4f6f8",
        "grey": "#8a929b",
        "eye_ring": "#2b323a",
        "eye": "#020304",
        "mouth": "#8c3a4a",
    },
    parts=(
        Part("flukes", "black", 0, (
            Pt(-0.030, -0.026, True),
            Pt(0.020, -0.038),
            Pt(0.066, -0.080),
            Pt(0.128, -0.130, True),
            Pt(0.108, -0.066),
            Pt(0.078, -0.018, True),
            Pt(0.108, 0.066),
            Pt(0.128, 0.130, True),
            Pt(0.066, 0.080),
            Pt(0.020, 0.038),
            Pt(-0.030, 0.026, True),
        ), attach=1.0, outline=True, girth=0.034),
        Part("body", "black", 1, (
            Pt(0.0, Rim(-1), True),
            Pt(1.0, Rim(-1), True),
            Pt(1.0, Rim(1), True),
            Pt(0.0, Rim(1), True),
        ), outline=True),
        Part("belly", "white", 2, (
            Pt(0.005, Rim(1), True),
            Pt(0.300, Rim(1)),
            Pt(0.560, Rim(1)),
            Pt(0.790, Rim(1), True),
            Pt(0.730, 0.030),
            Pt(0.680, 0.000),
            Pt(0.664, -0.036, True),
            Pt(0.620, -0.044),
            Pt(0.578, -0.012),
            Pt(0.530, 0.034),
            Pt(0.440, 0.046),
            Pt(0.320, 0.044),
            Pt(0.200, 0.036),
            Pt(0.100, 0.028),
            Pt(0.016, 0.014, True),
        )),
        Part("eye_patch", "white", 3, ellipse(0.158, -0.046, 0.050, 0.0155, -24)),
        Part("saddle", "grey", 3, (
            Pt(0.470, Rim(-1), True),
            Pt(0.560, Rim(-1)),
            Pt(0.660, Rim(-1), True),
            Pt(0.610, -0.046),
            Pt(0.550, -0.050),
            Pt(0.500, -0.062),
        )),
        Part("flipper", "black", 4, (
            Pt(-0.030, 0.034, True),
            Pt(-0.008, 0.120),
            Pt(0.030, 0.185),
            Pt(0.070, 0.222),
            Pt(0.108, 0.228),
            Pt(0.106, 0.200),
            Pt(0.092, 0.150),
            Pt(0.076, 0.100),
            Pt(0.070, 0.034, True),
        ), attach=0.27, outline=True, paired=True, girth=0.075),
        Part("dorsal_fin", "black", 5, (
            Pt(-0.085, -0.070, True),
            Pt(-0.062, -0.128),
            Pt(-0.026, -0.196),
            Pt(0.022, -0.248),
            Pt(0.066, -0.274, True),
            Pt(0.056, -0.216),
            Pt(0.060, -0.160),
            Pt(0.078, -0.105),
            Pt(0.092, -0.070, True),
        ), attach=0.40, outline=True, girth=0.05),
        Part("eye_ring", "eye_ring", 6, ellipse(EYE_U, EYE_V, 0.0125, 0.0125, 0, 10)),
        Part("eye", "eye", 7, ellipse(EYE_U, EYE_V, 0.0075, 0.0075, 0, 10)),
    ),
    wave_amp=0.06,
    wave_cycles=0.85,
    beat_hz=1.15,
    length_frac=1.0,
    vents=((0.2, ORCA_PROFILE.rim_v(0.2, -1)), (0.012, 0.035)),
    bubble_room=0.18,
    # The near-black body vanishes against dark windows, so it gets a thin pale rim.
    outline_color="#6a7b8e",
    outline_px=4,
    jaw=Jaw(
        hinge=(0.170, 0.034),
        lip=((0.004, 0.008), (0.040, 0.014), (0.090, 0.022), (0.135, 0.029), (0.170, 0.034)),
        max_open=math.radians(42),
        teeth=5,
        order=2,
        mouth="mouth",
        chin="white",
        tooth="white",
    ),
)


SALMON_PROFILE = Profile((
    (0.000, 0.000, 0.000),
    (0.006, 0.014, 0.014),
    (0.020, 0.030, 0.028),
    (0.050, 0.052, 0.048),
    (0.100, 0.078, 0.074),
    (0.180, 0.098, 0.098),
    (0.280, 0.108, 0.112),
    (0.380, 0.110, 0.116),
    (0.500, 0.102, 0.108),
    (0.620, 0.086, 0.088),
    (0.740, 0.064, 0.064),
    (0.860, 0.044, 0.043),
    (0.950, 0.034, 0.033),
    (1.000, 0.030, 0.030),
))

# (u, fraction of the way from the spine to the back outline)
SALMON_SPOTS = (
    (0.24, -0.78), (0.28, -0.52), (0.33, -0.86), (0.35, -0.62), (0.37, -0.40),
    (0.42, -0.78), (0.44, -0.52), (0.49, -0.84), (0.51, -0.60), (0.53, -0.38),
    (0.58, -0.72), (0.60, -0.48), (0.66, -0.76), (0.68, -0.52), (0.74, -0.62),
    (0.80, -0.55), (0.86, -0.50),
)


def _band(top: float, bottom: float, u0: float, u1: float) -> tuple[Pt, ...]:
    return (Pt(u0, Rim(top)), Pt(u1, Rim(top)), Pt(u1, Rim(bottom)), Pt(u0, Rim(bottom)))


SALMON = Species(
    name="salmon",
    profile=SALMON_PROFILE,
    palette={
        "back": "#3b6d78",
        "flank_hi": "#6f9aa6",
        "flank": "#bccfd5",
        "belly": "#eef3f4",
        "line": "#4e7a85",
        "gill": "#93aeb5",
        "spot": "#14262c",
        "fin": "#2f5a65",
        "fin_pale": "#8fb0b9",
        "iris": "#d3dde0",
        "pupil": "#0b1215",
        "mouth": "#1b3038",
    },
    parts=(
        Part("tail", "fin", 0, (
            Pt(-0.025, -0.030, True),
            Pt(0.030, -0.050),
            Pt(0.090, -0.105),
            Pt(0.150, -0.135, True),
            Pt(0.125, -0.070),
            Pt(0.095, 0.000, True),
            Pt(0.125, 0.070),
            Pt(0.150, 0.135, True),
            Pt(0.090, 0.105),
            Pt(0.030, 0.050),
            Pt(-0.025, 0.030, True),
        ), attach=1.0, outline=True, flutter=0.35, girth=0.03),
        Part("body", "back", 1, (
            Pt(0.0, Rim(-1), True),
            Pt(1.0, Rim(-1), True),
            Pt(1.0, Rim(1), True),
            Pt(0.0, Rim(1), True),
        ), outline=True),
        Part("flank_hi", "flank_hi", 2, _band(-0.30, 1, 0.03, 0.98)),
        Part("flank", "flank", 2, _band(-0.02, 1, 0.04, 0.97)),
        Part("belly", "belly", 2, _band(0.55, 1, 0.05, 0.90)),
        Part("lateral_line", "line", 3, (
            Pt(0.20, Rim(-0.17)), Pt(0.96, Rim(-0.10)), Pt(0.96, Rim(-0.04)), Pt(0.20, Rim(-0.11)),
        )),
        *(Part(f"spot{i}", "spot", 3, ellipse(u, SALMON_PROFILE.rim_v(u, f), 0.0085, 0.0085, 0, 6))
          for i, (u, f) in enumerate(SALMON_SPOTS)),
        Part("gill", "gill", 3, (
            Pt(0.160, -0.080, True), Pt(0.185, -0.040), Pt(0.192, 0.010), Pt(0.182, 0.060),
            Pt(0.158, 0.092, True), Pt(0.170, 0.058), Pt(0.181, 0.010), Pt(0.176, -0.040),
        )),
        Part("mouth", "mouth", 3, (
            Pt(0.004, 0.017, True), Pt(0.040, 0.020), Pt(0.072, 0.019, True), Pt(0.040, 0.024),
        )),
        Part("pectoral", "fin_pale", 4, (
            Pt(-0.015, 0.070, True), Pt(-0.005, 0.125), Pt(0.030, 0.155), Pt(0.065, 0.165),
            Pt(0.045, 0.130), Pt(0.035, 0.080, True),
        ), attach=0.20, outline=True, paired=True, girth=0.026),
        Part("pelvic", "fin_pale", 4, (
            Pt(-0.020, 0.090, True), Pt(0.000, 0.130), Pt(0.035, 0.145), Pt(0.040, 0.100, True),
        ), attach=0.52, outline=True, paired=True, girth=0.022),
        Part("anal", "fin_pale", 4, (
            Pt(-0.030, 0.055, True), Pt(0.000, 0.100), Pt(0.035, 0.095), Pt(0.045, 0.050, True),
        ), attach=0.74, outline=True, girth=0.02),
        Part("dorsal_fin", "fin", 4, (
            Pt(-0.040, -0.090, True), Pt(-0.015, -0.165), Pt(0.010, -0.160), Pt(0.045, -0.120),
            Pt(0.065, -0.090, True),
        ), attach=0.44, outline=True, girth=0.022),
        Part("adipose", "fin", 4, (
            Pt(-0.020, -0.045, True), Pt(0.000, -0.080), Pt(0.025, -0.045, True),
        ), attach=0.80, outline=True, girth=0.01),
        Part("eye", "iris", 6, ellipse(0.062, -0.012, 0.019, 0.019, 0, 10)),
        Part("pupil", "pupil", 7, ellipse(0.064, -0.012, 0.0115, 0.0115, 0, 8)),
    ),
    wave_amp=0.03,
    wave_cycles=0.9,
    beat_hz=3.0,
    length_frac=0.3,
    vents=(),
    bubble_room=0.0,
    outline_color="#14262c",
    outline_px=3,
)
