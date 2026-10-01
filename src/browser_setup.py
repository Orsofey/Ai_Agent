"""Подключение браузера одной кнопкой («Подключить браузер» в Настройки → «Управление ПК»).

Что делает кнопка:
  1. Кладёт расширение «Андрей» в папку данных программы и вписывает в него код подключения (pairing.json) —
     вставлять код вручную больше не нужно.
  2. Открывает страницу расширений именно в браузере по умолчанию (Chrome, Edge, Яндекс, Opera, Brave, Vivaldi)
     и рядом — окно с папкой расширения (путь ещё и в буфере обмена).
  Пользователю остаётся включить «Режим разработчика» и перетащить папку в окно браузера — это ограничение самих
  браузеров: установить расширение не из магазина за пользователя нельзя.

Когда расширение опубликовано в Chrome Web Store / Edge Add-ons (адреса — в connector_config.EXTENSION_STORE_*),
кнопка открывает страницу магазина: «Установить» — и расширение само просит ассистента подключиться
(в окне ассистента — «Разрешить»).
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

BROWSERS = {
    'chrome': ('Google Chrome', 'chrome://extensions/', [r'Google\Chrome\Application\chrome.exe'], 'chrome.exe',
               'Google Chrome'),
    'msedge': ('Microsoft Edge', 'edge://extensions/', [r'Microsoft\Edge\Application\msedge.exe'], 'msedge.exe',
               'Microsoft Edge'),
    'yandex': ('Яндекс Браузер', 'browser://extensions/', [r'Yandex\YandexBrowser\Application\browser.exe'], 'browser.exe',
               'Yandex'),
    'opera': ('Opera', 'opera://extensions', [r'Programs\Opera\opera.exe', r'Opera\opera.exe'], 'opera.exe', 'Opera'),
    'brave': ('Brave', 'brave://extensions/', [r'BraveSoftware\Brave-Browser\Application\brave.exe'], 'brave.exe',
              'Brave Browser'),
    'vivaldi': ('Vivaldi', 'vivaldi://extensions/', [r'Vivaldi\Application\vivaldi.exe'], 'vivaldi.exe', 'Vivaldi'),
}
ORDER = ('chrome', 'yandex', 'msedge', 'opera', 'brave', 'vivaldi')
STORE_KIND = {'chrome': 'chrome', 'yandex': 'chrome', 'brave': 'chrome', 'vivaldi': 'chrome', 'opera': 'chrome',
              'msedge': 'edge'}


def source_folder(app_root):
    base = Path(getattr(sys, '_MEIPASS', app_root))
    return base / 'browser_extension'


def find_browser(channel):
    """Путь к программе браузера (Windows: стандартные папки и App Paths; macOS: имя приложения)."""
    title, url, relatives, exe, mac_app = BROWSERS[channel]
    if sys.platform == 'darwin':
        return mac_app if Path(f'/Applications/{mac_app}.app').exists() else None
    if os.name != 'nt':
        return shutil.which(exe.replace('.exe', '')) or None
    for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        root = os.environ.get(env)
        for relative in relatives:
            if root and (Path(root) / relative).exists():
                return str(Path(root) / relative)
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, rf'Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}') as key:
                    value = winreg.QueryValue(key, None)
                    if value and Path(value).exists():
                        return value
            except OSError:
                continue
    except ImportError:
        pass
    return None


def pick_browser():
    """Браузер по умолчанию, если он на Chromium; иначе первый установленный."""
    try:
        from .browser_control import detect_default_browser
        default = detect_default_browser()
    except Exception:
        default = None
    for channel in ([default] if default in BROWSERS else []) + list(ORDER):
        path = find_browser(channel)
        if path:
            return channel, path
    return None, None


def prepare(data_root, app_root, port, token):
    """Копия расширения в папке данных + pairing.json с кодом (обновляется при каждом нажатии)."""
    target = Path(data_root) / 'browser_extension'
    source = source_folder(app_root)
    if not source.is_dir():
        raise RuntimeError('В установке нет папки расширения — переустановите программу.')
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    (target / 'pairing.json').write_text(json.dumps({'port': port, 'token': token}), encoding='utf-8')
    return target


def launch(channel, path, url):
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if sys.platform == 'darwin':
        subprocess.Popen(['open', '-a', path, url])
    else:
        subprocess.Popen([path, url], creationflags=flags)


def reveal(folder):
    try:
        if os.name == 'nt':
            subprocess.Popen(['explorer', '/select,', str(folder)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', str(folder)])
    except OSError:
        pass


def store_url(channel):
    from . import connector_config as cfg
    kind = STORE_KIND.get(channel, 'chrome')
    return (cfg.EXTENSION_STORE_EDGE if kind == 'edge' else '') or cfg.EXTENSION_STORE_CHROME


def connect(data_root, app_root, port, token, opener=None):
    """Кнопка «Подключить браузер». Возвращает, что показать пользователю."""
    channel, path = pick_browser()
    title = BROWSERS[channel][0] if channel else 'браузер'
    store = store_url(channel) if channel else ''
    if store:
        if opener is not None:
            opener(store)
        return {'mode': 'store', 'browser': title, 'url': store,
                'steps': [f'В открывшейся странице магазина нажмите «Установить» ({title}).',
                          'Вернитесь сюда и нажмите «Разрешить», когда расширение попросит подключиться.']}
    folder = prepare(data_root, app_root, port, token)
    try:
        import pyperclip
        pyperclip.copy(str(folder))
    except Exception:
        pass
    if channel:
        launch(channel, path, BROWSERS[channel][1])
    reveal(folder)
    return {'mode': 'folder', 'browser': title, 'folder': str(folder), 'opened': bool(channel),
            'steps': [f'В открывшейся вкладке {title} включите «Режим разработчика» (переключатель справа вверху).',
                      'Перетащите папку «browser_extension» из открывшегося окна в эту вкладку — готово, '
                      'расширение подключится само, код вводить не нужно.']}


class PairRequests:
    """Расширение из магазина просит подключиться: в окне ассистента — «Разрешить подключение браузера?»."""
    AUTO_SECONDS = 600     # после нажатия «Подключить браузер» разрешаем без лишнего вопроса

    def __init__(self, events=None):
        self.events = events
        self.lock = threading.Lock()
        self.pending = {}          # браузер → {'event', 'allowed', 'at'}
        self.wanted_until = 0.0

    def expect(self):
        self.wanted_until = time.monotonic() + self.AUTO_SECONDS

    def ask(self, browser, wait=20.0):
        browser = str(browser or 'Браузер')[:40]
        if time.monotonic() < self.wanted_until:
            return True
        with self.lock:
            item = self.pending.get(browser)
            if item is None or (item['allowed'] is not None and time.monotonic() - item['at'] > 60):
                item = {'event': threading.Event(), 'allowed': None, 'at': time.monotonic()}
                self.pending[browser] = item
                if self.events is not None:
                    self.events.emit('ext_pair', browser=browser)
        item['event'].wait(wait)
        return item['allowed']

    def answer(self, browser, allowed):
        with self.lock:
            item = self.pending.get(str(browser or 'Браузер')[:40])
            if item is None:
                return False
            item['allowed'] = bool(allowed)
            item['at'] = time.monotonic()
            item['event'].set()
        return True
