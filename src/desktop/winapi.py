"""Thin ctypes layer over user32 for keyboard input and windows.

Работает только на Windows. На других системах импорт безопасен, а вызовы
возвращают DesktopUnavailable — это позволяет тестировать логику на Linux.
"""
import ctypes
import os
import sys
import time

IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'


class DesktopUnavailable(RuntimeError):
    pass


VK = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'shift': 0x10, 'ctrl': 0x11,
    'alt': 0x12, 'pause': 0x13, 'capslock': 0x14, 'esc': 0x1B, 'space': 0x20,
    'pageup': 0x21, 'pagedown': 0x22, 'end': 0x23, 'home': 0x24, 'left': 0x25,
    'up': 0x26, 'right': 0x27, 'down': 0x28, 'printscreen': 0x2C, 'insert': 0x2D,
    'delete': 0x2E, 'win': 0x5B, 'apps': 0x5D,
    'volume_mute': 0xAD, 'volume_down': 0xAE, 'volume_up': 0xAF,
    'media_next': 0xB0, 'media_prev': 0xB1, 'media_stop': 0xB2, 'media_play_pause': 0xB3,
    'browser_back': 0xA6, 'browser_forward': 0xA7, 'browser_refresh': 0xA8,
}
VK.update({f'f{i}': 0x6F + i for i in range(1, 13)})
VK.update({chr(c): c for c in range(ord('0'), ord('9') + 1)})
VK.update({chr(c).lower(): c for c in range(ord('A'), ord('Z') + 1)})

EXTENDED = {'pageup', 'pagedown', 'end', 'home', 'left', 'up', 'right', 'down',
            'insert', 'delete', 'win', 'apps', 'printscreen'}
MODIFIERS = ('ctrl', 'shift', 'alt', 'win')

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    ULONG_PTR = wintypes.WPARAM

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ('u',)
        _fields_ = [('type', wintypes.DWORD), ('u', _U)]

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR]
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def supported():
    return IS_WINDOWS or IS_MAC


def _require():
    if not supported():
        raise DesktopUnavailable('Управление другими приложениями доступно на Windows и macOS.')


def _key_input(vk=0, scan=0, flags=0):
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


def _send(items):
    if not items:
        return
    array = (INPUT * len(items))(*items)
    sent = user32.SendInput(len(items), array, ctypes.sizeof(INPUT))
    if sent != len(items):
        raise RuntimeError('Windows заблокировала ввод (окно с правами администратора?).')


def vk_of(key):
    key = key.casefold()
    if key not in VK:
        raise ValueError('Неизвестная клавиша: ' + key)
    return VK[key]


def release_modifiers(wait=1.0):
    """Отпустить Ctrl/Alt/Shift/Win, которые пользователь мог держать (горячая клавиша)."""
    _require()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not any(user32.GetAsyncKeyState(VK[m]) & 0x8000 for m in MODIFIERS):
            return
        time.sleep(0.03)
    _send([_key_input(VK[m], 0, KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if m == 'win' else 0)) for m in MODIFIERS])


def hotkey(*keys):
    """Нажать сочетание клавиш: hotkey('ctrl', 'v')."""
    _require()
    codes = [(vk_of(k), KEYEVENTF_EXTENDEDKEY if k.casefold() in EXTENDED else 0) for k in keys]
    down = [_key_input(vk, 0, flags) for vk, flags in codes]
    up = [_key_input(vk, 0, flags | KEYEVENTF_KEYUP) for vk, flags in reversed(codes)]
    _send(down + up)


def press(key, times=1):
    for _ in range(max(1, min(int(times), 50))):
        hotkey(key)
        if times > 1:
            time.sleep(0.02)


def type_unicode(text, newline=('enter',)):
    """Набрать произвольный текст (любой язык, эмодзи) независимо от раскладки."""
    _require()
    batch = []
    for char in str(text):
        if char == '\r':
            continue
        if char == '\n':
            _send(batch)
            batch = []
            hotkey(*newline)
            continue
        raw = char.encode('utf-16-le')
        for n in range(0, len(raw), 2):
            unit = int.from_bytes(raw[n:n + 2], 'little')
            batch.append(_key_input(0, unit, KEYEVENTF_UNICODE))
            batch.append(_key_input(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if len(batch) >= 200:
            _send(batch)
            batch = []
            time.sleep(0.005)
    _send(batch)


# ---------------- окна ----------------

def foreground():
    _require()
    return user32.GetForegroundWindow()


def window_pid(hwnd):
    _require()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_title(hwnd):
    _require()
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def process_name(hwnd):
    import psutil
    try:
        return psutil.Process(window_pid(hwnd)).name().casefold()
    except Exception:
        return ''


def is_window(hwnd):
    return bool(hwnd) and IS_WINDOWS and bool(user32.IsWindow(hwnd))


def focus(hwnd):
    """Надёжно вывести окно на передний план (обход ограничений SetForegroundWindow)."""
    _require()
    if not is_window(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    current = user32.GetForegroundWindow()
    if current == hwnd:
        return True
    me = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(current, None) if current else 0
    attached = bool(other) and other != me and user32.AttachThreadInput(me, other, True)
    try:
        # Нажатие Alt снимает блокировку смены активного окна.
        user32.keybd_event(VK['alt'], 0, 0, 0)
        user32.keybd_event(VK['alt'], 0, KEYEVENTF_KEYUP, 0)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, other, False)
    for _ in range(20):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return user32.GetForegroundWindow() == hwnd


def show(hwnd, command):
    """command: 'minimize' | 'maximize' | 'restore'."""
    _require()
    codes = {'minimize': 6, 'maximize': 3, 'restore': 9}
    return bool(user32.ShowWindow(hwnd, codes[command]))


def close(hwnd):
    _require()
    return bool(user32.PostMessageW(hwnd, 0x0010, 0, 0))  # WM_CLOSE: приложение спросит о сохранении


def lock_workstation():
    _require()
    return bool(user32.LockWorkStation())


def own_pid():
    return os.getpid()


# ---------------- macOS ----------------
if IS_MAC:
    # Та же функциональность через Quartz и AppKit (см. macapi.py).
    from .macapi import (close, focus, foreground, hotkey, is_window, lock_workstation,  # noqa: F811
                         process_name, release_modifiers, show, type_unicode, window_pid, window_title)
