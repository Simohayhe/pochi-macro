# -*- coding: utf-8 -*-
"""マウス/キーボード入力を送ったり、対象ウィンドウを探したりする最小限のWinAPIラッパー。

追加ライブラリなし（ctypesのみ）で完結させる。SendInputは仮想キーコードではなく
スキャンコードで送る。生入力(RawInput/DirectInput)しか見ないゲームでも届きやすいため。
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


# 拡張キー（E0が付くもの）。矢印やInsert系、右Ctrl/Alt、テンキーEnterなど。
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
                0x2D, 0x2E, 0x2C, 0x90, 0x6F, 0x0D, 0xA3, 0xA5, 0x5B, 0x5C, 0x5D}
MAPVK_VK_TO_VSC = 0


def scancode_of(vk):
    return user32.MapVirtualKeyW(int(vk), MAPVK_VK_TO_VSC)


def _make_key(scan, extended, up):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    if up:
        flags |= KEYEVENTF_KEYUP
    return INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTUNION(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags,
                                             time=0, dwExtraInfo=0)))


def sleep(sec):
    # threading.Event().wait は精度がそこそこ良く、GILも離す
    import threading
    threading.Event().wait(sec)


WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101


# ------------------------------------------------------------ ウィンドウ探し
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _exe_of_hwnd(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def foreground_exe():
    """いま最前面のウィンドウのexe名（例 'notepad.exe'）。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    return _exe_of_hwnd(hwnd)


def matches(target):
    """対象アプリが最前面か。targetが空なら常にTrue。"""
    if not target:
        return True
    return foreground_exe().lower() == target.strip().lower()


def find_window(target):
    """exe名から、そのアプリの表に出ているウィンドウを1つ探す。"""
    if not target:
        return 0
    want = target.strip().lower()
    found = []

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        if _exe_of_hwnd(hwnd).lower() == want:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(_EnumProc(cb), 0)
    return found[0] if found else 0


_win_cache = {}


def find_window_cached(target, ttl=1.0):
    """画面の表示用。毎回の全ウィンドウ走査は重いので少しキャッシュする。"""
    now = time.time()
    hit = _win_cache.get(target)
    if hit and now - hit[0] < ttl:
        return hit[1]
    hwnd = find_window(target)
    _win_cache[target] = (now, hwnd)
    return hwnd


# ------------------------------------------------------------ swapモード
SW_RESTORE = 9


def force_foreground(hwnd):
    """他プロセスの窓を前に出す。素のSetForegroundWindowは弾かれるので、
    前面スレッドに入力キューをくっつけてから呼ぶ。"""
    if not hwnd:
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True
    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.BringWindowToTop(hwnd)
    if attached:
        user32.AttachThreadInput(cur_tid, fg_tid, False)
    return ok


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def set_cursor_pos(x, y):
    return bool(user32.SetCursorPos(int(x), int(y)))
