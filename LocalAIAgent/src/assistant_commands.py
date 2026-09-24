"""Explicit browser/service commands. Returns None when the phrase is not ours.

Раньше handle() всегда возвращал «Не понял команду», из-за чего разговорные
ответы, основной разбор команд и ИИ никогда не вызывались. Теперь модуль
отвечает только на свои фразы, а остальное передаёт дальше по цепочке.
"""
import os
import re
import webbrowser
from urllib.parse import quote
from . import web_services

HELP_EXTRA = '''
Сервисы: «Открой Яндекс Музыку», «Открой приложение Яндекс Музыка», «Открой Spotify».
Музыка: «Включи песню Кино в Яндекс Музыке», «Пауза музыки».'''

SERVICE_ALIASES = {
    'дискорд': 'discord', 'ютуве': 'youtube', 'телеграмм': 'telegram',
    'тг': 'telegram', 'яндекс музыки': 'яндекс музыка',
}

BROWSER_PHRASES = ('открой браузер', 'запусти браузер', 'включи браузер')


def normalize_service(text):
    value = re.sub(r'\s+', ' ', str(text)).strip(' «»".,!?').casefold()
    return SERVICE_ALIASES.get(value, value)


def system_browser(url):
    """Открыть ссылку в обычном браузере пользователя (браузер Windows по умолчанию)."""
    try:
        if os.name == 'nt':
            os.startfile(url)
            return True
        return bool(webbrowser.open(url))
    except Exception:
        return False


def default_browser_process():
    """Имя программы браузера по умолчанию для закрытия окон: chrome, msedge, browser (Яндекс)…"""
    from .browser_control import detect_default_browser
    try:
        channel = detect_default_browser()
    except Exception:
        channel = None
    return {'yandex': 'browser', 'chrome': 'chrome', 'msedge': 'msedge', 'opera': 'opera',
            'brave': 'brave', 'vivaldi': 'vivaldi'}.get(channel, 'msedge')


def default_browser(url, agent=None):
    """Открыть ссылку в браузере агента, при ошибке — в системном браузере."""
    if agent is not None and getattr(agent, 'browser', None) is not None:
        try:
            return agent.browser.call('open', url)
        except Exception:
            pass
    if os.name == 'nt':
        os.startfile(url)
        return 'Открываю браузер.'
    if webbrowser.open(url):
        return 'Открываю браузер.'
    return 'Не удалось открыть браузер.'


def handle(agent, command, settings):
    text = re.sub(r'\s+', ' ', str(command)).strip().rstrip('.,!?…')
    lower = text.casefold()

    if lower in BROWSER_PHRASES:
        if system_browser('https://ya.ru'):
            return 'Открываю браузер.'
        return default_browser('https://ya.ru', agent)

    if lower in ('закрой браузер', 'закрыть браузер', 'выключи браузер'):
        browser = getattr(agent, 'browser', None)
        if browser is not None and getattr(browser, 'context', None) is not None:
            return browser.call('close_browser')
        from .app_control import close_application
        answer = close_application(default_browser_process())
        return answer.replace(default_browser_process(), 'браузер')

    if lower in ('пауза музыки', 'останови музыку', 'поставь музыку на паузу'):
        return agent.browser.call('media', 'pause')
    if lower in ('продолжи музыку', 'включи музыку дальше'):
        return agent.browser.call('media', 'play')

    m = re.match(r'^(?:включи|найди|запусти|поставь)\s+(?:песню|музыку|трек|альбом)\s+(.+?)\s+(?:в|на)\s+яндекс\s*музык[еуи]$', text, re.I)
    if m:
        agent.browser.call('open', 'https://music.yandex.ru/search?text=' + quote(m[1]))
        return 'Ищу «' + m[1] + '» в Яндекс Музыке.'

    # «Открой приложение Яндекс Музыка» — именно системное приложение.
    m = re.match(r'^(?:открой|запусти|включи)\s+(?:приложение|программу)\s+(.+)$', lower)
    if m:
        name = normalize_service(m[1])
        if name in web_services.WEB_SERVICES:
            answer, launched = web_services.launch_app(name)
            if launched:
                return answer
            return web_services.open_download(name, agent) or answer
        return None

    # «Открой Яндекс Музыку» — сервис из интернета всегда в браузере.
    m = re.match(r'^(?:открой|запусти|включи)\s+(.+)$', lower)
    if m:
        name = normalize_service(m[1])
        if name in web_services.WEB_SERVICES and name not in ('telegram', 'телеграм'):
            return web_services.open_service(name, agent)
    return None
