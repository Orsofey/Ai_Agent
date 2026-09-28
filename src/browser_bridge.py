"""Мост к браузеру пользователя через расширение «Андрей» (Chrome, Edge, Яндекс Браузер, Opera, Brave).

Расширение раз в несколько секунд спрашивает у агента «есть ли команда» (долгий опрос /api/ext/next),
выполняет её в браузере пользователя — переключает вкладки, открывает ссылки, управляет плеерами —
и возвращает результат (/api/ext/result). Пока расширение на связи, агент работает в открытом браузере
пользователя; без него — в своём управляемом браузере, как раньше.
"""
import itertools
import queue
import threading
import time

ONLINE_SECONDS = 45     # расширение считается подключённым, если опрашивало агента недавно
WAIT_SECONDS = 20       # долгий опрос: сколько ждать команду, прежде чем ответить «нет команд»


class BridgeError(RuntimeError):
    pass


class ExtensionBridge:
    def __init__(self):
        self.commands = queue.Queue()
        self.results = {}
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self.last_seen = 0.0
        self.browser = ''     # «Google Chrome», «Yandex», «Microsoft Edge»… — сообщает расширение

    # ---- сторона агента ----
    @property
    def connected(self):
        return time.monotonic() - self.last_seen < ONLINE_SECONDS

    def matches(self, browser_key):
        """Подходит ли подключённый браузер к «в Яндекс Браузере», «в хроме»… ('default' — любой)."""
        if browser_key in (None, 'default'):
            return True
        name = self.browser.casefold()
        return {'yandex': 'yandex', 'chrome': 'chrome', 'msedge': 'edge', 'opera': 'opera',
                'firefox': 'firefox'}.get(browser_key, browser_key) in name

    def send(self, _command, timeout=20, **args):
        """Отправить команду расширению и дождаться ответа."""
        if not self.connected:
            raise BridgeError('Расширение браузера не подключено')
        ident = next(self.ids)
        event = threading.Event()
        with self.lock:
            self.results[ident] = {'event': event}
        self.commands.put({'id': ident, 'action': _command, 'args': args})
        if not event.wait(timeout):
            with self.lock:
                self.results.pop(ident, None)
            raise BridgeError('Браузер не ответил вовремя')
        with self.lock:
            result = self.results.pop(ident)
        if not result.get('ok'):
            raise BridgeError(result.get('error') or 'Браузер не смог выполнить команду')
        return result.get('result')

    # ---- сторона расширения (HTTP) ----
    def next_command(self, wait=WAIT_SECONDS, browser=''):
        self.last_seen = time.monotonic()
        if browser:
            self.browser = str(browser)[:80]
        try:
            command = self.commands.get(timeout=max(0.0, min(float(wait), 25.0)))
        except queue.Empty:
            return None
        finally:
            self.last_seen = time.monotonic()
        return command

    def complete(self, ident, ok, result=None, error=None):
        self.last_seen = time.monotonic()
        with self.lock:
            slot = self.results.get(ident)
            if slot is None:
                return False
            slot.update(ok=bool(ok), result=result, error=error)
            slot['event'].set()
        return True

    def status(self):
        return {'connected': self.connected, 'browser': self.browser if self.connected else '',
                'seconds_ago': round(time.monotonic() - self.last_seen, 1) if self.last_seen else None}
