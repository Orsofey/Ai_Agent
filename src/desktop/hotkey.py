"""Global hotkey (works while any application is active) via RegisterHotKey."""
import logging
import sys
import threading

log = logging.getLogger(__name__)

MODS = {'alt': 0x0001, 'ctrl': 0x0002, 'shift': 0x0004, 'win': 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


def parse_hotkey(spec):
    """'ctrl+alt+space' → (modifiers, vk)."""
    from .winapi import VK
    parts = [p.strip().casefold() for p in str(spec).split('+') if p.strip()]
    if not parts:
        raise ValueError('Пустая горячая клавиша')
    mods = 0
    for part in parts[:-1]:
        if part not in MODS:
            raise ValueError('Неизвестный модификатор: ' + part)
        mods |= MODS[part]
    key = parts[-1]
    if key not in VK or key in MODS:
        raise ValueError('Неизвестная клавиша: ' + key)
    if not mods:
        raise ValueError('Нужен хотя бы один модификатор (Ctrl, Alt, Shift или Win)')
    return mods, VK[key]


class GlobalHotkey:
    def __init__(self, spec, callback):
        self.spec = spec
        self.callback = callback
        self.thread = None
        self.thread_id = None
        self.error = None

    def start(self):
        if sys.platform != 'win32':
            return False
        self.thread = threading.Thread(target=self._run, daemon=True, name='global-hotkey')
        self.thread.start()
        return True

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32')
        self.thread_id = kernel32.GetCurrentThreadId()
        try:
            mods, vk = parse_hotkey(self.spec)
        except ValueError as exc:
            self.error = str(exc)
            return
        if not user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk):
            self.error = 'Сочетание ' + self.spec + ' занято другой программой.'
            log.warning(self.error)
            return
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception:
                        log.exception('Hotkey callback failed')
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self.thread_id and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
