"""QPhoneMirror Windows 開啟中程式視窗列舉、多螢幕邊界查詢與視窗訊息工具。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


@dataclass
class WindowInfo:
    """代表一個正在執行的桌面應用程式視窗。"""

    hwnd: int
    title: str
    rect: Tuple[int, int, int, int]  # (x, y, width, height) 實體像素（支援多螢幕負座標）

    @property
    def display_label(self) -> str:
        short = self.title if len(self.title) <= 44 else self.title[:41] + "..."
        return f"{short}  ({self.rect[2]}x{self.rect[3]})"


DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
SW_RESTORE = 9
WM_CLOSE = 0x0010

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.EnumWindows.argtypes = [_ENUM_PROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL

    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL

    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL

    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL

    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL

    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL

    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int

    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int

    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL

    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int

    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL

    _dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _dwmapi.DwmGetWindowAttribute.restype = ctypes.HRESULT


def get_primary_monitor_bounds() -> Tuple[int, int, int, int]:
    """回傳主螢幕實體像素範圍 (0, 0, width, height)。"""
    if sys.platform != "win32":
        return (0, 0, 1920, 1080)
    try:
        w = int(_user32.GetSystemMetrics(SM_CXSCREEN))
        h = int(_user32.GetSystemMetrics(SM_CYSCREEN))
        if w > 0 and h > 0:
            return (0, 0, w, h)
    except Exception:
        pass
    return (0, 0, 1920, 1080)


def get_virtual_screen_bounds() -> Tuple[int, int, int, int]:
    """回傳涵蓋所有外接螢幕的 Windows 虛擬桌面實體像素範圍 (x, y, width, height)。"""
    if sys.platform != "win32":
        return (0, 0, 1920, 1080)
    try:
        vx = int(_user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        vy = int(_user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        vw = int(_user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        vh = int(_user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        if vw > 0 and vh > 0:
            return (vx, vy, vw, vh)
    except Exception:
        pass
    return get_primary_monitor_bounds()


def send_wm_close_to_pids(pids: Iterable[int]) -> int:
    """對屬於指定 PID 集合的頂層視窗傳送 WM_CLOSE，讓程式（如 Scrcpy）優雅結束並完整寫入 MP4 檔尾。"""
    if sys.platform != "win32":
        return 0
    target_pids = {int(p) for p in pids if p}
    if not target_pids:
        return 0

    sent = 0

    def _cb(hwnd: int, _lparam: int) -> bool:
        nonlocal sent
        try:
            pid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in target_pids:
                if _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
                    sent += 1
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(_ENUM_PROC(_cb), 0)
    except Exception:
        pass
    return sent


def is_window_alive_and_minimized(hwnd: int) -> Tuple[bool, bool]:
    """檢查視窗是否仍存在及是否處於最小化狀態。"""
    if sys.platform != "win32":
        return (False, False)
    try:
        alive = bool(_user32.IsWindow(hwnd))
        if not alive:
            return (False, False)
        return (True, bool(_user32.IsIconic(hwnd)))
    except Exception:
        return (False, False)


def _get_accurate_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """優先使用 DWM API 取得不含陰影邊框的視窗實際實體像素座標 (x, y, w, h)，保留多螢幕負座標。"""
    if sys.platform != "win32":
        return None
    rect = wintypes.RECT()
    try:
        hr = _dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if hr != 0:
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    except Exception:
        try:
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        except Exception:
            return None

    w = int(rect.right - rect.left)
    h = int(rect.bottom - rect.top)
    if w < 64 or h < 64:
        return None
    return (int(rect.left), int(rect.top), w, h)


def list_open_windows(exclude_own_process: bool = True) -> List[WindowInfo]:
    """列出 Windows 桌面上所有可見且具標題的運作中程式視窗（排除本程式自身視窗，保留手機投影視窗可選）。"""
    if sys.platform != "win32":
        return []

    own_pid = os.getpid() if exclude_own_process else -1
    results: List[WindowInfo] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            if exclude_own_process:
                pid = wintypes.DWORD(0)
                _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if int(pid.value) == own_pid:
                    return True

            length = _user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True

            # 排除系統隱藏／背景 UWP Cloaked 視窗
            cloaked = wintypes.DWORD(0)
            try:
                if (
                    _dwmapi.DwmGetWindowAttribute(
                        hwnd,
                        DWMWA_CLOAKED,
                        ctypes.byref(cloaked),
                        ctypes.sizeof(cloaked),
                    )
                    == 0
                    and cloaked.value != 0
                ):
                    return True
            except Exception:
                pass

            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title or title in ("Program Manager", "Windows Input Experience"):
                return True

            rect = _get_accurate_rect(hwnd)
            if not rect:
                return True

            results.append(WindowInfo(hwnd=int(hwnd), title=title, rect=rect))
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(_ENUM_PROC(_callback), 0)
    except Exception:
        return []
    return results


def focus_and_get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """將指定的程式視窗從最小化還原並帶至前景，回傳其最新精準實體像素座標。"""
    if sys.platform != "win32":
        return None
    if not _user32.IsWindow(hwnd):
        return None
    try:
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.18)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
    except Exception:
        pass
    return _get_accurate_rect(hwnd)
