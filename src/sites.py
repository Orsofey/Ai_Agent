"""Сайты и сервисы по голосу: «Открой в браузере Claude Code», «открой в Яндекс Браузере YouTube».

Имя сервиса сравнивается по звучанию (распознавание пишет «Cloud Code», «клод код», «чат гпт»).
Неизвестное имя открывается первым результатом поиска DuckDuckGo (!ducky) — это обычная ссылка
в браузере пользователя, без API.
"""
import os
import re
import subprocess
import sys
from urllib.parse import quote

from .start_menu import phonetic

# Названия (как говорят и как пишут) → адрес.
SITES = {
    'https://claude.ai/code': ['claude code', 'клод код', 'клауд код', 'cloud code', 'клоуд код'],
    'https://claude.ai': ['claude', 'клод', 'клауд', 'claude ai', 'клод ай'],
    'https://chatgpt.com': ['chatgpt', 'чат гпт', 'чат джипити', 'чат gpt', 'чатгпт', 'gpt', 'джипити'],
    'https://gemini.google.com': ['gemini', 'джемини', 'гемини'],
    'https://chat.deepseek.com': ['deepseek', 'дипсик', 'дип сик'],
    'https://www.perplexity.ai': ['perplexity', 'перплексити'],
    'https://www.youtube.com': ['youtube', 'ютуб', 'ютюб', 'you tube'],
    'https://rutube.ru': ['rutube', 'рутуб'],
    'https://www.twitch.tv': ['twitch', 'твич'],
    'https://vk.com': ['вк', 'вконтакте', 'vk', 'в контакте'],
    'https://vk.com/music': ['вк музыка', 'vk музыка', 'вк музыку'],
    'https://music.yandex.ru': ['яндекс музыка', 'яндекс музыку', 'yandex music'],
    'https://open.spotify.com': ['spotify', 'спотифай'],
    'https://music.youtube.com': ['youtube music', 'ютуб музыка', 'ютуб мьюзик'],
    'https://zvuk.com': ['звук', 'zvuk', 'сбер звук'],
    'https://soundcloud.com': ['soundcloud', 'саундклауд'],
    'https://mail.google.com': ['gmail', 'гмейл', 'джимейл', 'гугл почта'],
    'https://mail.yandex.ru': ['яндекс почта', 'почта', 'яндекс почту'],
    'https://e.mail.ru': ['mail ru', 'мейл ру', 'мэйл ру'],
    'https://www.google.com': ['google', 'гугл'],
    'https://ya.ru': ['яндекс', 'yandex', 'я ру'],
    'https://translate.google.com': ['гугл переводчик', 'google translate', 'переводчик'],
    'https://translate.yandex.ru': ['яндекс переводчик'],
    'https://yandex.ru/maps': ['яндекс карты', 'карты'],
    'https://www.google.com/maps': ['гугл карты', 'google maps'],
    'https://yandex.ru/pogoda': ['яндекс погода'],
    'https://github.com': ['github', 'гитхаб', 'гит хаб'],
    'https://habr.com': ['habr', 'хабр'],
    'https://stackoverflow.com': ['stackoverflow', 'стак оверфлоу', 'стековерфлоу'],
    'https://www.kinopoisk.ru': ['кинопоиск', 'kinopoisk'],
    'https://ru.wikipedia.org': ['википедия', 'wikipedia', 'вики'],
    'https://www.gosuslugi.ru': ['госуслуги', 'гос услуги'],
    'https://www.ozon.ru': ['ozon', 'озон'],
    'https://www.wildberries.ru': ['wildberries', 'вайлдберриз', 'валберис', 'вб'],
    'https://www.avito.ru': ['avito', 'авито'],
    'https://market.yandex.ru': ['яндекс маркет', 'маркет'],
    'https://miro.com/app/dashboard': ['miro', 'миро'],
    'https://www.notion.so': ['notion', 'ноушн', 'ношн'],
    'https://www.figma.com': ['figma', 'фигма'],
    'https://www.canva.com': ['canva', 'канва'],
    'https://web.telegram.org': ['telegram web', 'телеграм веб'],
    'https://web.whatsapp.com': ['whatsapp web', 'ватсап веб'],
    'https://discord.com/app': ['discord web', 'дискорд веб'],
    'https://store.steampowered.com': ['steam', 'стим'],
    'https://drive.google.com': ['google drive', 'гугл диск'],
    'https://docs.google.com': ['google docs', 'гугл документы', 'гугл докс'],
    'https://disk.yandex.ru': ['яндекс диск'],
    'https://dzen.ru': ['дзен', 'яндекс дзен', 'dzen'],
    'https://hh.ru': ['hh', 'хедхантер', 'хх ру', 'эйч эйч'],
    'https://online.sberbank.ru': ['сбербанк', 'сбер', 'сбербанк онлайн'],
    'https://www.tbank.ru': ['тинькофф', 'т банк', 'тбанк'],
    'https://www.reddit.com': ['reddit', 'реддит'],
    'https://x.com': ['twitter', 'твиттер', 'икс'],
    'https://www.pinterest.com': ['pinterest', 'пинтерест'],
    'https://www.instagram.com': ['instagram', 'инстаграм'],
    'https://leetcode.com': ['leetcode', 'литкод'],
    'https://www.netflix.com': ['netflix', 'нетфликс'],
}
_INDEX = [(phonetic(name), url) for url, names in SITES.items() for name in names]

# «в Яндекс Браузере», «в хроме» → ключ браузера.
BROWSERS = {
    'yandex': r'яндекс\s*браузер\w*|яндексе|yandex(?:\s*browser)?',
    'chrome': r'(?:гугл\s+)?хром\w*|(?:google\s+)?chrome',
    'msedge': r'эдж\w*|edge|майкрософт\s+эдж\w*',
    'firefox': r'фаерфокс\w*|файрфокс\w*|firefox|мозилл\w*',
    'opera': r'опер[ае]\w*|opera',
    'safari': r'сафари|safari',
    'default': r'браузер\w*',
}
_BROWSER_RE = '|'.join(f'(?P<{k}>{v})' for k, v in BROWSERS.items())
_OPEN = r'(?:открой|открыть|зайди|зайти|перейди|перейти|запусти|включи|покажи)'
PATTERNS = [
    # «Открой в браузере Claude Code», «открой в Яндекс Браузере YouTube», «зайди через хром на хабр»
    re.compile(r'^' + _OPEN + r'\s+(?:в|во|через)\s+(?:' + _BROWSER_RE + r')\s+(?:(?:на|в)\s+)?(?:сайт\s+)?(?P<site>.+)$', re.I),
    # «Открой Claude Code в браузере», «зайди на хабр в хроме»
    re.compile(r'^' + _OPEN + r'\s+(?:(?:на|в)\s+)?(?:сайт\s+)?(?P<site>.+?)\s+(?:в|во|через)\s+(?:' + _BROWSER_RE + r')$', re.I),
    # «Открой сайт Claude», «зайди на сайт хабр»
    re.compile(r'^' + _OPEN + r'\s+(?:(?:на|в)\s+)?сайт\s+(?P<site>.+)$', re.I),
]
DOMAIN = re.compile(r'^(?:https?://)?([\w-]+(?:\.[\w-]+)+)(/\S*)?$', re.I)


TLD = {'ком': 'com', 'ру': 'ru', 'орг': 'org', 'нет': 'net', 'ио': 'io', 'ай': 'ai', 'дев': 'dev', 'ми': 'me'}
_LATIN = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                  ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't',
                   'u', 'f', 'h', 'ts', 'ch', 'sh', 'sch', '', 'y', '', 'e', 'yu', 'ya']))


def spoken_domain(text):
    """«хабр точка ком» → «habr.com», «сайт.рф» остаётся как есть."""
    value = re.sub(r'\s*(?:точка|dot)\s*', '.', text.strip(), flags=re.I).casefold()
    if not DOMAIN.match(value):
        return None
    parts = value.split('.')
    if parts[-1] != 'рф':
        parts[-1] = TLD.get(parts[-1], parts[-1])
        parts = [''.join(_LATIN.get(c, c) for c in part) for part in parts]
    return '.'.join(parts)


def find(name, threshold=0.8):
    """Адрес сайта по названию или None."""
    value = name.strip(' «»"\'.,!?')
    domain = spoken_domain(value)
    if domain:
        return domain if domain.startswith('http') else 'https://' + domain
    key = phonetic(value)
    if not key:
        return None
    best, score = None, 0.0
    from difflib import SequenceMatcher
    for spoken, url in _INDEX:
        ratio = 1.0 if spoken == key else SequenceMatcher(None, key, spoken).ratio()
        if ratio > score:
            best, score = url, ratio
    return best if score >= threshold else None


def resolve(name):
    """Адрес сайта: из каталога, по домену или «мне повезёт» DuckDuckGo."""
    return find(name) or 'https://duckduckgo.com/?q=' + quote('!ducky ' + name.strip())


def parse(text):
    """dict(site, browser) для «открой в браузере …» или None."""
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    for pattern in PATTERNS:
        match = pattern.match(value)
        if match:
            browser = next((k for k in BROWSERS if match.groupdict().get(k)), 'default')
            site = match['site'].strip(' «»"\'.,')
            if site:
                return dict(site=site, browser=browser)
    return None


BROWSER_TITLES = {'yandex': 'Яндекс Браузере', 'chrome': 'Chrome', 'msedge': 'Edge', 'firefox': 'Firefox',
                  'opera': 'Opera', 'safari': 'Safari', 'default': 'браузере'}
MAC_BROWSERS = {'yandex': 'Yandex', 'chrome': 'Google Chrome', 'msedge': 'Microsoft Edge', 'firefox': 'Firefox',
                'opera': 'Opera', 'safari': 'Safari'}


def browser_exe(key):
    from .app_aliases import KNOWN_PATHS
    paths = list(KNOWN_PATHS.get(key, []))
    if key == 'yandex':
        paths.append(os.path.expandvars(r'%LocalAppData%\Yandex\YandexBrowser\Application\browser.exe'))
    return next((p for p in paths if os.path.isfile(p)), None)


def open_url(url, browser='default'):
    """Открыть адрес в указанном браузере пользователя. Вернуть True при успехе."""
    from .web_services import system_open
    if browser == 'default':
        return system_open(url)
    if sys.platform == 'darwin':
        return subprocess.run(['open', '-a', MAC_BROWSERS.get(browser, 'Safari'), url], timeout=15).returncode == 0
    exe = browser_exe(browser)
    if not exe:
        return False
    subprocess.Popen([exe, url], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return True


def open_site(site, browser='default'):
    url = resolve(site)
    name = site if 'duckduckgo.com' in url else _pretty(site, url)
    if open_url(url, browser):
        return f'Открываю {name} в {BROWSER_TITLES[browser]}.'
    if browser != 'default' and open_url(url, 'default'):
        return f'Этот браузер не найден — открываю {name} в браузере по умолчанию.'
    return f'Не удалось открыть браузер для {name}.'


def _pretty(site, url):
    if site.isascii():
        return site  # как сказано: «YouTube», «Claude Code»
    known = next((names for address, names in SITES.items() if address == url), None)
    if known:
        latin = next((n for n in known if n.isascii()), known[0])
        return ' '.join(w[:1].upper() + w[1:] for w in latin.split()) if latin.isascii() else site
    return site
