"""High-level desktop actions used by voice commands.

Главное: команды работают в ЛЮБОМ приложении. Если команда пришла голосом,
активным остаётся окно пользователя (Word, Telegram, браузер...). Если команда
набрана в окне агента, текст уходит в последнее окно, где был пользователь.
"""
import logging
import threading
import time
from pathlib import Path

from . import winapi
from .winapi import DesktopUnavailable

log = logging.getLogger(__name__)

MESSENGER_PROCESSES = {'telegram.exe', 'whatsapp.exe', 'discord.exe', 'slack.exe',
                       'viber.exe', 'skype.exe', 'teams.exe', 'ms-teams.exe', 'vk messenger.exe',
                       'max.exe', 'element.exe', 'signal.exe'}
BROWSER_PROCESSES = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'browser.exe', 'opera.exe',
                     'brave.exe', 'vivaldi.exe', 'yandex.exe'}


class WindowTracker:
    """Запоминает последнее активное окно другого приложения."""

    def __init__(self, interval=0.25):
        self.last_external = None
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not winapi.IS_WINDOWS or self._thread:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name='window-tracker')
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        me = winapi.own_pid()
        while not self._stop.wait(self.interval):
            try:
                hwnd = winapi.foreground()
                if hwnd and winapi.window_pid(hwnd) != me and winapi.window_title(hwnd):
                    self.last_external = hwnd
            except Exception:
                pass


class DesktopController:
    def __init__(self, tracker=None):
        self.tracker = tracker or WindowTracker()
        self.lock = threading.RLock()

    @property
    def available(self):
        return winapi.IS_WINDOWS

    def start(self):
        self.tracker.start()

    # ---- целевое окно ----
    def target(self):
        """Окно, в которое нужно действовать. Возвращает HWND (уже активный)."""
        hwnd = winapi.foreground()
        if hwnd and winapi.window_pid(hwnd) == winapi.own_pid():
            external = self.tracker.last_external
            if not external or not winapi.is_window(external):
                raise DesktopUnavailable('Не знаю, в какое окно действовать. Переключитесь в нужное приложение и повторите команду голосом.')
            if not winapi.focus(external):
                raise DesktopUnavailable('Windows не дала переключиться в окно. Переключитесь вручную и повторите.')
            time.sleep(0.12)
            return external
        return hwnd

    def target_process(self):
        try:
            return winapi.process_name(self.target())
        except DesktopUnavailable:
            raise
        except Exception:
            return ''

    def target_title(self):
        hwnd = self.target()
        return winapi.window_title(hwnd), winapi.process_name(hwnd)

    # ---- ввод ----
    def type_text(self, text, method='auto'):
        with self.lock:
            hwnd = self.target()
            winapi.release_modifiers()
            process = winapi.process_name(hwnd)
            # В мессенджерах Enter отправляет сообщение — перенос строки через Shift+Enter.
            newline = ('shift', 'enter') if process in MESSENGER_PROCESSES else ('enter',)
            if method == 'paste' or (method == 'auto' and len(text) > 300):
                self.paste(text)
            else:
                winapi.type_unicode(text, newline=newline)
            return process

    def paste(self, text):
        import pyperclip
        previous = None
        try:
            previous = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(text)
        time.sleep(0.05)
        winapi.hotkey('ctrl', 'v')

        def restore():
            time.sleep(0.8)
            if previous is not None:
                try:
                    pyperclip.copy(previous)
                except Exception:
                    pass
        threading.Thread(target=restore, daemon=True).start()

    def hotkey(self, *keys, times=1):
        with self.lock:
            self.target()
            winapi.release_modifiers()
            for _ in range(max(1, min(int(times), 50))):
                winapi.hotkey(*keys)
                if times > 1:
                    time.sleep(0.03)

    def copy_selection(self):
        """Скопировать выделенный текст активного окна и вернуть его."""
        import pyperclip
        with self.lock:
            self.target()
            winapi.release_modifiers()
            marker = '⁣agent-empty⁣'
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = ''
            pyperclip.copy(marker)
            winapi.hotkey('ctrl', 'c')
            value = marker
            for _ in range(25):
                time.sleep(0.04)
                value = pyperclip.paste()
                if value != marker:
                    break
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
            return '' if value == marker else value

    # ---- окна ----
    def window(self, action):
        with self.lock:
            hwnd = self.target()
            if action == 'close':
                return winapi.close(hwnd)
            return winapi.show(hwnd, action)

    def activate_process(self, names, launch_name=None, timeout=8.0):
        """Активировать окно приложения; при необходимости запустить его."""
        from ..app_control import activate_running, launch
        if activate_running(launch_name or next(iter(names))):
            time.sleep(0.35)
            return True
        if launch_name:
            launch(launch_name)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.5)
                if activate_running(launch_name):
                    time.sleep(0.8)
                    return True
        return False

    def screenshot(self):
        from PIL import ImageGrab
        folder = Path.home() / 'Pictures' / 'LocalAIAgent'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / time.strftime('screenshot_%Y-%m-%d_%H-%M-%S.png')
        ImageGrab.grab(all_screens=True).save(path)
        return path

    def lock_workstation(self):
        return winapi.lock_workstation()
