"""Animated orca that swims across the Windows desktop in a click-through overlay.

Anatomy is declared once in body space, deformed by a travelling spine wave,
rasterised with Pillow at 3x supersampling and pushed to a layered window with
per-pixel alpha (UpdateLayeredWindow). Quit with Ctrl+Alt+O or Ctrl+C.
"""

from __future__ import annotations

import argparse
import bisect
import ctypes
import math
import random
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import NamedTuple

from PIL import Image, ImageColor, ImageDraw

# --------------------------------------------------------------------------
# Anatomy. Body space is (u, v): u runs nose (0) to tail stock (1) along the
# spine, v is the signed offset perpendicular to the spine in body lengths,
# negative toward the back (up on screen).
# --------------------------------------------------------------------------

BLACK = "#111418"
WHITE = "#f4f6f8"
GREY = "#8a929b"
EYE_RING = "#2b323a"
EYE = "#020304"

# (u, dorsal half-thickness, ventral half-thickness)
SPINE_PROFILE = (
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
)
_PROFILE_U = [row[0] for row in SPINE_PROFILE]


def _hermite(x: float, xs: list[float], ys: list[float]) -> float:
    i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
    h = xs[i + 1] - xs[i]

    def slope(k: int) -> float:
        lo, hi = max(k - 1, 0), min(k + 1, len(xs) - 1)
        return (ys[hi] - ys[lo]) / (xs[hi] - xs[lo])

    t = (x - xs[i]) / h
    t2, t3 = t * t, t * t * t
    return (
        (2 * t3 - 3 * t2 + 1) * ys[i]
        + (t3 - 2 * t2 + t) * h * slope(i)
        + (-2 * t3 + 3 * t2) * ys[i + 1]
        + (t3 - t2) * h * slope(i + 1)
    )


_DORSAL = [row[1] for row in SPINE_PROFILE]
_VENTRAL = [row[2] for row in SPINE_PROFILE]


def rim_v(u: float, f: float) -> float:
    """v of the point a fraction f of the way from the spine to the body edge.

    f = -1 is the dorsal outline, +1 the ventral outline. Markings that touch
    the outline use this so they share its exact vertices.
    """
    if f == 0:
        return 0.0
    if f < 0:
        return f * max(_hermite(u, _PROFILE_U, _DORSAL), 0.0)
    return f * max(_hermite(u, _PROFILE_U, _VENTRAL), 0.0)


class Rim(NamedTuple):
    f: float


class Pt(NamedTuple):
    u: float
    v: float | Rim
    corner: bool = False


@dataclass(frozen=True)
class Part:
    name: str
    color: str
    order: int
    points: tuple[Pt, ...]
    # None: points are (u, v) body coordinates bent along the spine.
    # u0: rigid appendage, points are (a, b) = (along, perpendicular) in the
    # spine frame at u0, so it inherits that point's position and rotation.
    attach: float | None = None


def ellipse(cu: float, cv: float, ru: float, rv: float, deg: float, n: int = 12) -> tuple[Pt, ...]:
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        x, y = ru * math.cos(t), rv * math.sin(t)
        pts.append(Pt(cu + x * ca - y * sa, cv + x * sa + y * ca))
    return tuple(pts)


EYE_U, EYE_V = 0.100, -0.008

PARTS: tuple[Part, ...] = (
    Part("flukes", BLACK, 0, (
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
    ), attach=1.0),
    Part("body", BLACK, 1, (
        Pt(0.0, Rim(-1), True),
        Pt(1.0, Rim(-1), True),
        Pt(1.0, Rim(1), True),
        Pt(0.0, Rim(1), True),
    )),
    Part("belly", WHITE, 2, (
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
    Part("eye_patch", WHITE, 3, ellipse(0.158, -0.046, 0.050, 0.0155, -24)),
    Part("saddle", GREY, 3, (
        Pt(0.470, Rim(-1), True),
        Pt(0.560, Rim(-1)),
        Pt(0.660, Rim(-1), True),
        Pt(0.610, -0.046),
        Pt(0.550, -0.050),
        Pt(0.500, -0.062),
    )),
    Part("flipper", BLACK, 4, (
        Pt(-0.030, 0.034, True),
        Pt(-0.008, 0.120),
        Pt(0.030, 0.185),
        Pt(0.070, 0.222),
        Pt(0.108, 0.228),
        Pt(0.106, 0.200),
        Pt(0.092, 0.150),
        Pt(0.076, 0.100),
        Pt(0.070, 0.034, True),
    ), attach=0.27),
    Part("dorsal_fin", BLACK, 5, (
        Pt(-0.085, -0.070, True),
        Pt(-0.062, -0.128),
        Pt(-0.026, -0.196),
        Pt(0.022, -0.248),
        Pt(0.066, -0.274, True),
        Pt(0.056, -0.216),
        Pt(0.060, -0.160),
        Pt(0.078, -0.105),
        Pt(0.092, -0.070, True),
    ), attach=0.40),
    Part("eye_ring", EYE_RING, 6, ellipse(EYE_U, EYE_V, 0.0125, 0.0125, 0, 10)),
    Part("eye", EYE, 7, ellipse(EYE_U, EYE_V, 0.0075, 0.0075, 0, 10)),
)

MAX_STEP = 0.012


def bake(part: Part) -> list[tuple[float, float]]:
    """Resample a part densely so it bends smoothly under the spine wave."""
    pts = part.points
    n = len(pts)
    ev = [(p.u, rim_v(p.u, p.v.f) if isinstance(p.v, Rim) else p.v) for p in pts]
    out: list[tuple[float, float]] = []
    for i in range(n):
        j = (i + 1) % n
        a, b = pts[i], pts[j]
        (u0, v0), (u1, v1) = ev[i], ev[j]
        dist = math.hypot(u1 - u0, v1 - v0)
        steps = max(1, math.ceil(dist / MAX_STEP))
        if isinstance(a.v, Rim) and isinstance(b.v, Rim):
            for k in range(steps):
                t = k / steps
                u = u0 + (u1 - u0) * t
                out.append((u, rim_v(u, a.v.f + (b.v.f - a.v.f) * t)))
            continue
        pm, pn = ev[i - 1], ev[(j + 1) % n]
        m0 = (u1 - u0, v1 - v0) if a.corner else ((u1 - pm[0]) / 2, (v1 - pm[1]) / 2)
        m1 = (u1 - u0, v1 - v0) if b.corner else ((pn[0] - u0) / 2, (pn[1] - v0) / 2)
        for k in range(steps):
            t = k / steps
            t2, t3 = t * t, t * t * t
            h00, h10, h01, h11 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, -2 * t3 + 3 * t2, t3 - t2
            out.append((
                h00 * u0 + h10 * m0[0] + h01 * u1 + h11 * m1[0],
                h00 * v0 + h10 * m0[1] + h01 * v1 + h11 * m1[1],
            ))
    return out


@dataclass(frozen=True)
class BakedPart:
    color: tuple[int, int, int, int]
    attach: float | None
    points: tuple[tuple[float, float], ...]


RIM_TARGET = (*ImageColor.getrgb(BLACK), 255)
RIM_COLOR = (*ImageColor.getrgb("#6a7b8e"), 255)
RIM_OFFSETS = ((4, 0), (-4, 0), (0, 4), (0, -4))

BAKED: tuple[BakedPart, ...] = tuple(
    BakedPart((*ImageColor.getrgb(p.color), 255), p.attach, tuple(bake(p))) for p in sorted(PARTS, key=lambda p: p.order)
)

# --------------------------------------------------------------------------
# Spine deformation. Orcas swim with dorsoventral undulation, so the wave
# displaces y, growing from almost nothing at the head to the flukes.
# --------------------------------------------------------------------------

WAVE_AMP = 0.06
WAVE_CYCLES = 0.85
TAIL_BEAT_HZ = 1.15


def spine(u: float, phase: float) -> tuple[float, float, float, float]:
    """Spine point and unit tangent at u. Phase is in tail-beat cycles."""
    th = 2 * math.pi * (WAVE_CYCLES * u - phase)
    s, c = math.sin(th), math.cos(th)
    env = u * u
    y = WAVE_AMP * env * s
    slope = WAVE_AMP * (2 * u * s + env * 2 * math.pi * WAVE_CYCLES * c)
    inv = 1.0 / math.sqrt(1.0 + slope * slope)
    return u, y, inv, slope * inv


def bend(u: float, v: float, phase: float) -> tuple[float, float]:
    x, y, tx, ty = spine(u, phase)
    return x - v * ty, y + v * tx


# --------------------------------------------------------------------------
# Swim state and bubbles.
# --------------------------------------------------------------------------

BOB_PERIOD = 4.2
BOB_AMP_FRAC = 0.07


@dataclass
class SwimState:
    x: float
    base_y: float
    direction: int
    phase: float
    pass_index: int
    speed: float
    clock: float = 0.0

    @staticmethod
    def start(area: "Rect", half_w: float, rng: random.Random) -> "SwimState":
        s = SwimState(0.0, 0.0, rng.choice((-1, 1)), 0.0, 0, 0.0)
        s.begin_pass(area, half_w, rng, flip=False)
        return s

    def begin_pass(self, area: "Rect", half_w: float, rng: random.Random, flip: bool = True) -> None:
        if flip:
            self.direction = -self.direction
            self.pass_index += 1
        h = area.bottom - area.top
        self.base_y = area.top + h * rng.uniform(0.15, 0.85)
        self.speed = rng.uniform(200, 260)
        self.x = area.left - half_w if self.direction > 0 else area.right + half_w
        self.clock = 0.0

    def step(self, dt: float, area: "Rect", half_w: float, rng: random.Random) -> None:
        self.x += self.direction * self.speed * dt
        self.clock += dt
        self.phase += TAIL_BEAT_HZ * dt
        gone = self.x > area.right + half_w if self.direction > 0 else self.x < area.left - half_w
        if gone:
            self.begin_pass(area, half_w, rng)

    def bob(self, length: float) -> tuple[float, float]:
        """Vertical offset in px and body pitch in radians (nose up positive)."""
        w = 2 * math.pi / BOB_PERIOD
        amp = BOB_AMP_FRAC * length
        dy = amp * math.sin(w * self.clock)
        vy = amp * w * math.cos(w * self.clock)
        return dy, math.atan2(-vy, self.speed) * 0.7


@dataclass
class Bubble:
    x: float
    y: float
    vx: float
    vy: float
    r: float
    life: float
    age: float = 0.0
    wobble: float = 0.0


@dataclass
class Bubbles:
    items: list[Bubble] = field(default_factory=list)
    cooldown: float = 0.4

    def update(self, dt: float, sources: list[tuple[float, float]], drift: float, rng: random.Random) -> None:
        self.cooldown -= dt
        if self.cooldown <= 0 and len(self.items) < 14:
            self.cooldown = rng.uniform(0.25, 0.7)
            sx, sy = rng.choice(sources)
            for _ in range(rng.randint(1, 3)):
                self.items.append(Bubble(
                    sx + rng.uniform(-3, 3), sy + rng.uniform(-3, 3),
                    drift * rng.uniform(0.6, 1.0), -rng.uniform(35, 75),
                    rng.uniform(2.0, 5.5), rng.uniform(1.0, 1.8),
                    wobble=rng.uniform(0, 6.28),
                ))
        for b in self.items:
            b.age += dt
            b.wobble += dt * 5
            b.x += (b.vx + 10 * math.sin(b.wobble)) * dt
            b.y += b.vy * dt
        self.items = [b for b in self.items if b.age < b.life]


# --------------------------------------------------------------------------
# Rendering.
# --------------------------------------------------------------------------

SS = 3


@dataclass(frozen=True)
class Pose:
    phase: float
    pitch: float
    facing: int  # +1 swims right, -1 swims left


@dataclass(frozen=True)
class Layout:
    length: int
    width: int
    height: int
    cx: float
    cy: float

    @staticmethod
    def for_length(length: int) -> "Layout":
        w, h = round(length * 1.5), round(length * 1.0)
        return Layout(length, w, h, w / 2, h * 0.58)


def projector(pose: Pose, lay: Layout, scale: float):
    """Map spine-space (length units, nose at x=0) to canvas pixels."""
    k = lay.length * scale
    c, s = math.cos(pose.pitch), math.sin(pose.pitch)
    f, ox, oy = pose.facing, lay.cx * scale, lay.cy * scale

    def project(lx: float, ly: float) -> tuple[float, float]:
        x, y = (0.5 - lx) * k, ly * k
        return ox + f * (x * c + y * s), oy + (y * c - x * s)

    return project


def body_anchor(u: float, v: float, pose: Pose, lay: Layout) -> tuple[float, float]:
    return projector(pose, lay, 1)(*bend(u, v, pose.phase))


def draw_orca(draw: ImageDraw.ImageDraw, pose: Pose, lay: Layout) -> None:
    project = projector(pose, lay, SS)
    phase = pose.phase
    placed = []
    for part in BAKED:
        if part.attach is None:
            pts = [project(*bend(u, v, phase)) for u, v in part.points]
        else:
            fx, fy, tx, ty = spine(part.attach, phase)
            nx, ny = -ty, tx
            pts = [project(fx + a * tx + b * nx, fy + a * ty + b * ny) for a, b in part.points]
        placed.append((part, pts))
    # The near-black body vanishes against dark windows, so the black parts
    # get a thin pale rim, drawn underneath everything as offset copies (a wide
    # draw.line is several times slower).
    for part, pts in placed:
        if part.color == RIM_TARGET:
            for dx, dy in RIM_OFFSETS:
                draw.polygon([(x + dx, y + dy) for x, y in pts], fill=RIM_COLOR)
    for part, pts in placed:
        draw.polygon(pts, fill=part.color)


def draw_bubbles(draw: ImageDraw.ImageDraw, bubbles: Bubbles) -> None:
    for b in bubbles.items:
        fade = 1.0 - (b.age / b.life) ** 2
        x, y, r = b.x * SS, b.y * SS, b.r * SS
        fill, line = int(46 * fade), int(215 * fade)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(fill,) * 4, outline=(line,) * 4, width=max(1, SS - 1))


def render(pose: Pose, bubbles: Bubbles, lay: Layout) -> Image.Image:
    """Return the frame as a premultiplied "RGBa" image of the window size.

    The canvas is premultiplied from the start (opaque parts have alpha 255,
    bubbles use equal colour and alpha), so the box reduce is a correct
    premultiplied downsample with no per-frame RGBA/RGBa conversion.
    """
    big = Image.new("RGBa", (lay.width * SS, lay.height * SS))
    draw = ImageDraw.Draw(big)
    draw_bubbles(draw, bubbles)
    draw_orca(draw, pose, lay)
    return big.reduce(SS)


def make_sheet(lay: Layout, frames: int = 6) -> Image.Image:
    cols = 3
    rows = math.ceil(frames / cols)
    bg = Image.new("RGBA", (lay.width * cols, lay.height * rows), (96, 140, 176, 255))
    for k in range(frames):
        frame = render(Pose(k / frames, 0.0, 1), Bubbles(), lay).convert("RGBA")
        bg.alpha_composite(frame, ((k % cols) * lay.width, (k // cols) * lay.height))
    return bg


# --------------------------------------------------------------------------
# Win32 plumbing.
# --------------------------------------------------------------------------

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x08000000
WM_DESTROY, WM_HOTKEY = 0x2, 0x312
PM_REMOVE, WM_QUIT = 0x1, 0x12
SW_SHOWNOACTIVATE = 4
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_O = 0x4F
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
SPI_GETWORKAREA = 0x30
HOTKEY_ID = 1
CLASS_NAME = "OrcaOverlayWindow"

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")


class Rect(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


def _sig(fn, restype, *argtypes):
    fn.restype, fn.argtypes = restype, list(argtypes)


H, U, I, V = wintypes.HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_void_p
_sig(user32.SetProcessDpiAwarenessContext, wintypes.BOOL, V)
_sig(user32.RegisterClassExW, wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
_sig(user32.UnregisterClassW, wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE)
_sig(user32.CreateWindowExW, wintypes.HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
     I, I, I, I, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, V)
_sig(user32.DefWindowProcW, LRESULT, wintypes.HWND, U, WPARAM, LPARAM)
_sig(user32.DestroyWindow, wintypes.BOOL, wintypes.HWND)
_sig(user32.ShowWindow, wintypes.BOOL, wintypes.HWND, I)
_sig(user32.SetWindowPos, wintypes.BOOL, wintypes.HWND, wintypes.HWND, I, I, I, I, U)
_sig(user32.PostQuitMessage, None, I)
_sig(user32.PeekMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, U, U, U)
_sig(user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
_sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(wintypes.MSG))
_sig(user32.RegisterHotKey, wintypes.BOOL, wintypes.HWND, I, U, U)
_sig(user32.UnregisterHotKey, wintypes.BOOL, wintypes.HWND, I)
_sig(user32.GetDC, wintypes.HDC, wintypes.HWND)
_sig(user32.ReleaseDC, I, wintypes.HWND, wintypes.HDC)
_sig(user32.GetSystemMetrics, I, I)
_sig(user32.SystemParametersInfoW, wintypes.BOOL, U, U, V, U)
_sig(user32.UpdateLayeredWindow, wintypes.BOOL, wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
     ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
     ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD)
_sig(gdi32.CreateCompatibleDC, wintypes.HDC, wintypes.HDC)
_sig(gdi32.DeleteDC, wintypes.BOOL, wintypes.HDC)
_sig(gdi32.CreateDIBSection, wintypes.HBITMAP, wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), U,
     ctypes.POINTER(V), wintypes.HANDLE, wintypes.DWORD)
_sig(gdi32.SelectObject, wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
_sig(gdi32.DeleteObject, wintypes.BOOL, wintypes.HGDIOBJ)
_sig(kernel32.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)
_sig(winmm.timeBeginPeriod, U, U)
_sig(winmm.timeEndPeriod, U, U)


@WNDPROC
def _wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_HOTKEY or msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def primary_work_area() -> Rect:
    r = wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    return Rect(r.left, r.top, r.right, r.bottom)


class Overlay:
    """Click-through, always-on-top, focus-less layered window with a DIB backbuffer."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.hwnd = self.screen_dc = self.mem_dc = self.bitmap = self.old_bitmap = None
        self.hotkey = False
        self.class_atom = 0
        hinst = kernel32.GetModuleHandleW(None)
        self.hinst = hinst
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = _wndproc
        wc.hInstance = hinst
        wc.lpszClassName = CLASS_NAME
        self.class_atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not self.class_atom:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            CLASS_NAME, "Orca", WS_POPUP, 0, 0, width, height, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        self.bitmap = gdi32.CreateDIBSection(self.mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not self.bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        self.bits = bits.value
        self.old_bitmap = gdi32.SelectObject(self.mem_dc, self.bitmap)

        self.blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        self.size = wintypes.SIZE(width, height)
        self.src_origin = wintypes.POINT(0, 0)
        self.hotkey = bool(user32.RegisterHotKey(
            self.hwnd, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_O))
        if not self.hotkey:
            print("Ctrl+Alt+O is taken by another program; use Ctrl+C in the console to quit.", file=sys.stderr)
        self._msg = wintypes.MSG()

    def present(self, frame: Image.Image, x: int, y: int) -> None:
        data = frame.tobytes("raw", "BGRa")
        ctypes.memmove(self.bits, data, len(data))
        pos = wintypes.POINT(x, y)
        ok = user32.UpdateLayeredWindow(
            self.hwnd, self.screen_dc, ctypes.byref(pos), ctypes.byref(self.size), self.mem_dc,
            ctypes.byref(self.src_origin), 0, ctypes.byref(self.blend), ULW_ALPHA)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def show(self) -> None:
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def keep_on_top(self) -> None:
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def pump(self) -> bool:
        """Dispatch pending messages; False once a quit was requested."""
        msg = self._msg
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_QUIT:
                return False
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return True

    def close(self) -> None:
        if self.hotkey:
            user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
            self.hotkey = False
        if self.old_bitmap is not None:
            gdi32.SelectObject(self.mem_dc, self.old_bitmap)
            self.old_bitmap = None
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.mem_dc:
            gdi32.DeleteDC(self.mem_dc)
            self.mem_dc = None
        if self.screen_dc:
            user32.ReleaseDC(None, self.screen_dc)
            self.screen_dc = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.class_atom:
            user32.UnregisterClassW(CLASS_NAME, self.hinst)
            self.class_atom = 0


# --------------------------------------------------------------------------
# Main loop.
# --------------------------------------------------------------------------

FRAME_TIME = 1 / 60


def orca_length(screen_h: int) -> int:
    return max(200, min(520, round(screen_h * 0.296)))


def run(frames: int | None, snapshot: str | None) -> None:
    user32.SetProcessDpiAwarenessContext(-4)
    area = primary_work_area()
    lay = Layout.for_length(orca_length(area.bottom - area.top))
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
            state.step(dt, area, lay.width / 2, rng)

            dy, pitch = state.bob(lay.length)
            pose = Pose(state.phase, pitch, state.direction)
            sources = [body_anchor(0.2, rim_v(0.2, -1), pose, lay), body_anchor(0.012, 0.035, pose, lay)]
            bubbles.update(dt, sources, -state.direction * state.speed * 0.3, rng)

            frame = render(pose, bubbles, lay)
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
        make_sheet(Layout.for_length(320)).save(args.sheet)
        print(f"sheet saved to {args.sheet}")
        return
    run(args.frames, args.snapshot)


if __name__ == "__main__":
    main()
