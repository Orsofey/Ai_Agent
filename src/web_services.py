"""Веб-сервисы: открытие в браузере по умолчанию + предложение установки.

Правило проекта: сервисы из интернета (Яндекс Музыка, Spotify, VK Музыка и т.д.)
всегда открываются в браузере. Системное приложение, если оно установлено,
используется только для команд вида «Открой приложение Яндекс Музыка».
Если системного приложения нет — агент предлагает скачать и открывает
страницу загрузки в браузере по умолчанию.
"""
import os
import sys
import webbrowser

# Сервис → (веб-адрес, страница загрузки приложения, имена .exe приложения)
WEB_SERVICES = {
    'яндекс музыку': {
        'url': 'https://music.yandex.ru',
        'download': 'https://music.yandex.ru/download',
        'exe': ['Яндекс Музыка.exe', 'Yandex Music.exe'],
        'path': [('LOCALAPPDATA', 'Programs', 'YandexMusic')],
        'title': 'Яндекс Музыка',
    },
    'яндекс музыка': {
        'url': 'https://music.yandex.ru',
        'download': 'https://music.yandex.ru/download',
        'exe': ['Яндекс Музыка.exe', 'Yandex Music.exe'],
        'path': [('LOCALAPPDATA', 'Programs', 'YandexMusic')],
        'title': 'Яндекс Музыка',
    },
    'spotify': {
        'url': 'https://open.spotify.com',
        'download': 'https://www.spotify.com/download/windows/',
        'exe': ['Spotify.exe'],
        'path': [('APPDATA', 'Spotify')],
        'title': 'Spotify',
    },
    'спотифай': {
        'url': 'https://open.spotify.com',
        'download': 'https://www.spotify.com/download/windows/',
        'exe': ['Spotify.exe'],
        'path': [('APPDATA', 'Spotify')],
        'title': 'Spotify',
    },
    'вк музыку': {
        'url': 'https://vk.com/music',
        'download': 'https://vk.com/apps',
        'exe': [],
        'path': [],
        'title': 'VK Музыка',
    },
    'вк музыка': {
        'url': 'https://vk.com/music',
        'download': 'https://vk.com/apps',
        'exe': [],
        'path': [],
        'title': 'VK Музыка',
    },
    'ютуб': {
        'url': 'https://www.youtube.com',
        'download': None,
        'exe': [],
        'path': [],
        'title': 'YouTube',
    },
    'youtube': {
        'url': 'https://www.youtube.com',
        'download': None,
        'exe': [],
        'path': [],
        'title': 'YouTube',
    },
    'рутуб': {
        'url': 'https://rutube.ru',
        'download': None,
        'exe': [],
        'path': [],
        'title': 'Rutube',
    },
    'rutube': {
        'url': 'https://rutube.ru',
        'download': None,
        'exe': [],
        'path': [],
        'title': 'Rutube',
    },
    'телеграм': {
        'url': 'https://web.telegram.org',
        'download': 'https://desktop.telegram.org',
        'exe': ['Telegram.exe'],
        'path': [('APPDATA', 'Telegram Desktop')],
        'title': 'Telegram',
    },
    'telegram': {
        'url': 'https://web.telegram.org',
        'download': 'https://desktop.telegram.org',
        'exe': ['Telegram.exe'],
        'path': [('APPDATA', 'Telegram Desktop')],
        'title': 'Telegram',
    },
}


def find_installed(name):
    """Путь к установленному приложению сервиса или None."""
    info = WEB_SERVICES.get(name)
    if not info:
        return None
    for parts in info['path']:
        base = os.getenv(parts[0], '')
        if not base:
            continue
        folder = os.path.join(base, *parts[1:])
        for exe in info['exe']:
            candidate = os.path.join(folder, exe)
            if os.path.isfile(candidate):
                return candidate
    return None


def system_open(url):
    """Открыть ссылку в браузере по умолчанию (Windows, macOS). На других системах — False."""
    from .network import is_web_url, online
    if not online() and is_web_url(url):
        return False   # автономный режим: сайты не открываем
    if sys.platform == 'darwin':
        import subprocess
        return subprocess.run(['open', url], timeout=10).returncode == 0
    if os.name != 'nt':
        return False
    try:
        os.startfile(url)
        return True
    except OSError:
        return False


def open_in_browser(url, agent=None):
    """Открыть адрес в браузере по умолчанию.

    Сначала пробуем системный браузер по умолчанию (Windows Shell), затем
    управляемый браузер агента — чтобы ссылка гарантированно открылась.
    """
    if system_open(url):
        return True
    if agent is not None and getattr(agent, 'browser', None) is not None:
        try:
            agent.browser.call('open', url)
            return True
        except Exception:
            pass
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def open_service(name, agent=None):
    """Открыть веб-сервис в браузере. Возвращает текст ответа для пользователя."""
    info = WEB_SERVICES.get(name)
    if not info:
        return None
    opened = open_in_browser(info['url'], agent)
    if opened:
        return f"Открываю {info['title']} в браузере."
    return f"Не удалось открыть браузер для {info['title']}."


def open_download(name, agent=None):
    """Открыть страницу загрузки приложения сервиса в браузере."""
    info = WEB_SERVICES.get(name)
    if not info or not info.get('download'):
        return None
    opened = open_in_browser(info['download'], agent)
    if opened:
        return (f"Приложение «{info['title']}» не установлено. "
                f"Открываю страницу загрузки в браузере.")
    return (f"Приложение «{info['title']}» не установлено, "
            f"и не удалось открыть страницу загрузки.")


def launch_app(name):
    """Запустить установленное системное приложение сервиса.
    Возвращает (текст, найден ли путь). Если не найдено — (текст-объяснение, False).
    """
    info = WEB_SERVICES.get(name)
    if not info:
        return None, False
    path = find_installed(name)
    if not path:
        return (f"Приложение «{info['title']}» не найдено на компьютере.", False)
    try:
        os.startfile(path)
        return f"Открываю приложение {info['title']}.", True
    except OSError as exc:
        return f"Не удалось запустить приложение: {exc}", False
