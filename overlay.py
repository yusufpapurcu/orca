"""Win32 plumbing: click-through, always-on-top, per-pixel-alpha layered windows."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import numpy as np

from projection import Rect
from render import Sprite

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x08000000
WM_DESTROY, WM_HOTKEY = 0x2, 0x312
PM_REMOVE, WM_QUIT = 0x1, 0x12
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
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
    """Click-through, always-on-top, focus-less layered window with a DIB backbuffer.

    The window is resized to each sprite as it is presented. The backbuffer is
    `size` px square, the largest sprite the owner can produce.
    """

    _instances = 0
    _atom = 0
    _hinst = None

    def __init__(self, size: int, title: str, hotkey: bool = False):
        self.size = size
        self.hwnd = self.screen_dc = self.mem_dc = self.bitmap = self.old_bitmap = None
        self.hotkey = False
        self.visible = False
        if Overlay._instances == 0:
            Overlay._hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = _wndproc
            wc.hInstance = Overlay._hinst
            wc.lpszClassName = CLASS_NAME
            Overlay._atom = user32.RegisterClassExW(ctypes.byref(wc))
            if not Overlay._atom:
                raise ctypes.WinError(ctypes.get_last_error())
        Overlay._instances += 1
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            CLASS_NAME, title, WS_POPUP, 0, 0, size, size, None, None, Overlay._hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        self.bitmap = gdi32.CreateDIBSection(self.mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not self.bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        self.pixels = np.ctypeslib.as_array((ctypes.c_ubyte * (size * size * 4)).from_address(bits.value)).reshape(size, size, 4)
        self.old_bitmap = gdi32.SelectObject(self.mem_dc, self.bitmap)

        self.blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        self.src_origin = wintypes.POINT(0, 0)
        if hotkey:
            self.hotkey = bool(user32.RegisterHotKey(
                self.hwnd, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_O))
            if not self.hotkey:
                print("Ctrl+Alt+O is taken by another program; use Ctrl+C in the console to quit.", file=sys.stderr)
        self._msg = wintypes.MSG()

    def present(self, sprite: Sprite) -> None:
        w, h = sprite.image.size
        self.pixels[:h, :w] = np.frombuffer(sprite.image.tobytes("raw", "BGRa"), dtype=np.uint8).reshape(h, w, 4)
        pos, size = wintypes.POINT(sprite.x, sprite.y), wintypes.SIZE(w, h)
        self.blend.SourceConstantAlpha = round(255 * sprite.alpha)
        ok = user32.UpdateLayeredWindow(
            self.hwnd, self.screen_dc, ctypes.byref(pos), ctypes.byref(size), self.mem_dc,
            ctypes.byref(self.src_origin), 0, ctypes.byref(self.blend), ULW_ALPHA)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def show(self) -> bool:
        """Show the window. True if it was hidden, so the caller can fix the z-order."""
        if self.visible:
            return False
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.visible = True
        return True

    def hide(self) -> None:
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def keep_on_top(self) -> None:
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def place_below(self, other: "Overlay") -> None:
        """Put this window right under `other` in the z-order, both staying topmost."""
        user32.SetWindowPos(self.hwnd, other.hwnd, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

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
            self.pixels = None
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
            Overlay._instances -= 1
            if Overlay._instances == 0 and Overlay._atom:
                user32.UnregisterClassW(CLASS_NAME, Overlay._hinst)
                Overlay._atom = 0
