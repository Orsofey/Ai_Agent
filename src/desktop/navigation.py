"""Навигация голосом: вкладки браузера («перейди на первую вкладку», «переключись на YouTube»)
и страницы Word («перейди на страницу 10», «перейди на страницу, где есть слово каша»).

parse_* — чистые функции (тестируются без Windows); остальное — выполнение.
"""
import base64
import re
import subprocess
import sys
import time

from ..brain.numbers import words_to_digits

# Порядковые числительные: «первую», «десятой», «двадцать первую».
ORDINALS = [
    ('одиннадцат', 11), ('двенадцат', 12), ('тринадцат', 13), ('четырнадцат', 14), ('пятнадцат', 15),
    ('шестнадцат', 16), ('семнадцат', 17), ('восемнадцат', 18), ('девятнадцат', 19), ('двадцат', 20),
    ('тридцат', 30), ('сороков', 40), ('пятидесят', 50), ('перв', 1), ('втор', 2), ('трет', 3),
    ('четверт', 4), ('пят', 5), ('шест', 6), ('седьм', 7), ('восьм', 8), ('девят', 9), ('десят', 10),
    ('сот', 100),
]
_ENDING = r'(?:ый|ий|ой|ая|ую|ое|ей|ья|ью|ье|ьей|ьего|ого|его|ом|ем|ым|им)'
_TENS = {'двадцать': 20, 'тридцать': 30, 'сорок': 40, 'пятьдесят': 50, 'шестьдесят': 60, 'семьдесят': 70,
         'восемьдесят': 80, 'девяносто': 90, 'сто': 100}


def ordinal_word(word):
    word = word.casefold().replace('ё', 'е')
    for stem, value in ORDINALS:
        if re.fullmatch(stem + _ENDING, word):
            return value
    return None


def number(text):
    """«10», «десять», «десятую», «двадцать первую», «номер три» → int или None."""
    value = re.sub(r'^(?:номер|под номером|№)\s*', '', str(text).strip().casefold().replace('ё', 'е'))
    value = value.strip(' .,!?«»"')
    if re.fullmatch(r'\d{1,5}', value):
        return int(value)
    words = value.split()
    if len(words) == 1 and ordinal_word(words[0]):
        return ordinal_word(words[0])
    if len(words) == 2 and words[0] in _TENS and ordinal_word(words[1]):
        return _TENS[words[0]] + ordinal_word(words[1])
    digits = words_to_digits(value).strip()
    return int(digits) if re.fullmatch(r'\d{1,5}', digits) else None


# ---------------- вкладки ----------------
_GO = r'(?:перейди|перейти|переключись|переключи|переключиться|открой|покажи|вернись|иди|зайди|активируй)'


def parse_tab(text):
    """('tab', n) | ('tab', 'last'|'next'|'prev') или None."""
    lower = re.sub(r'\s+', ' ', str(text)).strip().strip('.,!?').casefold().replace('ё', 'е')
    lower = re.sub(r'^' + _GO + r'\s+(?:на|в|во|к)?\s*', '', lower)
    lower = re.sub(r'^(?:на|в|во)\s+', '', lower)
    special = {'последн': 'last', 'следующ': 'next', 'предыдущ': 'prev', 'прошл': 'prev', 'соседн': 'next'}
    match = re.fullmatch(r'(.+?)\s+вкладк[уаеи]', lower) or re.fullmatch(r'вкладк[уаеи]\s+(.+)', lower)
    if not match:
        return None
    what = match[1].strip()
    for stem, value in special.items():
        if what.startswith(stem):
            return value
    if what in ('новую', 'новая', 'эту', 'текущую', 'пустую'):
        return None
    value = number(what)
    return value if value and 1 <= value <= 99 else None


# Как сайт подписан в заголовке вкладки (заголовок окна браузера = заголовок активной вкладки).
TITLE_MARKERS = {
    'https://www.youtube.com': ['YouTube'],
    'https://music.youtube.com': ['YouTube Music'],
    'https://vk.com': ['ВКонтакте', 'VK'],
    'https://vk.com/music': ['VK Музыка', 'Музыка ВКонтакте'],
    'https://music.yandex.ru': ['Яндекс Музыка', 'Яндекс.Музыка', 'Yandex Music'],
    'https://mail.google.com': ['Gmail'],
    'https://mail.yandex.ru': ['Яндекс Почта', 'Яндекс.Почта'],
    'https://ya.ru': ['Яндекс'],
    'https://www.google.com': ['Google'],
    'https://translate.google.com': ['Google Переводчик', 'Google Translate'],
    'https://translate.yandex.ru': ['Яндекс Переводчик'],
    'https://ru.wikipedia.org': ['Википедия', 'Wikipedia'],
    'https://www.kinopoisk.ru': ['Кинопоиск'],
    'https://www.gosuslugi.ru': ['Госуслуги'],
    'https://chatgpt.com': ['ChatGPT'],
    'https://claude.ai': ['Claude'],
    'https://claude.ai/code': ['Claude Code'],
    'https://web.telegram.org': ['Telegram'],
    'https://web.whatsapp.com': ['WhatsApp'],
    'https://www.twitch.tv': ['Twitch'],
    'https://rutube.ru': ['RUTUBE', 'Rutube'],
    'https://dzen.ru': ['Дзен'],
    'https://www.ozon.ru': ['OZON', 'Ozon'],
    'https://www.wildberries.ru': ['Wildberries'],
    'https://www.avito.ru': ['Авито', 'Avito'],
}


def title_markers(url, names=()):
    from ..sites import SITES
    markers = list(TITLE_MARKERS.get(url, []))
    for name in list(names) + SITES.get(url, []):
        if name.isascii() and len(name) >= 4:
            markers.append(name)
    host = re.sub(r'^https?://(?:www\.)?', '', url).split('/')[0].split('.')[0]
    if len(host) >= 4:
        markers.append(host)
    return list(dict.fromkeys(markers))


def title_matches(title, markers):
    text = str(title or '')
    return any(re.search(r'(?<![\w])' + re.escape(m) + r'(?![\w])', text, re.I) for m in markers)


def parse_site(text):
    """«перейди в ютуб», «переключись на вкладку YouTube», «открой ютуб» → (глагол, сайт) или None."""
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    match = re.match(r'^(?P<verb>перейди|перейти|переключись|вернись|зайди|открой|покажи|включи)\s+'
                     r'(?:(?:на|в|во|к)\s+)?(?:вкладку\s+|сайт\s+)?(?P<site>.+)$', value, re.I)
    from ..sites import parse as named_browser
    if not match or re.search(r'вкладк[уаи]$|страниц', value, re.I) or named_browser(value):
        return None  # «открой ютуб в хроме» — открывает именно этот браузер (sites.parse)
    return match['verb'].casefold(), match['site'].strip(' «»"\'.,')


# ---------------- Word ----------------
WORD_PROCESSES = {'winword.exe', 'microsoft word.exe', 'word.exe'}
_WORDS_QUOTE = '«»"\'„“”'


def parse_word(text):
    """('page', n) | ('find', слово) | ('next', None) или None."""
    raw = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    lower = raw.casefold().replace('ё', 'е')
    if lower in ('следующее совпадение', 'найди дальше', 'ищи дальше', 'дальше по тексту', 'следующее вхождение',
                 'найди следующее', 'следующая страница со словом'):
        return 'next', None
    word = re.match(r'^(?:перейди|перейти|открой|покажи|найди)\s+(?:на\s+|к\s+)?(?:страниц[уаеы]|место)\s*,?\s*'
                    r'(?:где|в которой|на которой|со словом|с словом|с текстом|с фразой)\s*'
                    r'(?:есть|написано|встречается|упоминается|находится)?\s*(?:слово|фраза|текст|словосочетание)?\s*(.+)$',
                    raw, re.I) \
        or re.match(r'^(?:перейди|перейти)\s+(?:к|на)\s+(?:слову|фразе|тексту)\s+(.+)$', raw, re.I) \
        or re.match(r'^(?:где|найди в документе|найди в ворде)\s+(?:слово|фраза|фразу|текст)\s+(.+)$', raw, re.I)
    if word:
        phrase = word[1].strip(' ' + _WORDS_QUOTE + '.,')
        return ('find', phrase) if phrase else None
    page = re.match(r'^(?:(?:перейди|перейти|открой|покажи|листай|вернись|иди)\s+)?(?:на|к)?\s*(.+?)\s+страниц[уаеы]$', lower) \
        or re.match(r'^(?:(?:перейди|перейти|открой|покажи|листай|вернись|иди)\s+)?(?:на|к)?\s*страниц[уаеы]\s+(.+)$', lower)
    if page:
        what = page[1].strip()
        if what.startswith('последн'):
            return 'page', -1
        if what.startswith(('перв', 'начал')) and number(what) == 1:
            return 'page', 1
        value = number(what)
        if value and value >= 1:
            return 'page', value
    return None


def _powershell(script, timeout=20):
    """Windows PowerShell 5.1 (в нём есть GetActiveObject для запущенного Word)."""
    code = '[Console]::OutputEncoding=[Text.Encoding]::UTF8\n' + script
    encoded = base64.b64encode(code.encode('utf-16-le')).decode()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-EncodedCommand', encoded], capture_output=True, timeout=timeout,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.returncode, result.stdout.decode('utf-8', 'replace').strip(), result.stderr.decode('utf-8', 'replace')


def _ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


WORD_HEAD = ("$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application')\n"
             "if(-not $w.Documents.Count){'NODOC';exit}\n$s=$w.Selection\n")


def word_script(action, arg=None):
    """Скрипт COM для активного документа Word. Печатает номер страницы или NOTFOUND/NODOC."""
    if action == 'page':
        if arg == -1:
            return WORD_HEAD + "$null=$s.EndKey(6)\n$s.Information(3)"
        return WORD_HEAD + (f"$total=$w.ActiveDocument.ComputeStatistics(2)\n"
                            f"if({int(arg)} -gt $total){{'TOTAL '+$total;exit}}\n"
                            f"$null=$s.GoTo(1,1,{int(arg)})\n$s.Information(3)")
    head = WORD_HEAD + "$f=$s.Find\n$f.ClearFormatting()\n"
    if action == 'find':
        head += "$null=$s.HomeKey(6)\n"  # с начала документа
    else:
        head += "$null=$s.Collapse(0)\n"  # дальше от текущего места
    text = _ps_string(arg or '')
    return head + (f"if($f.Execute({text},$false,$false,$false,$false,$false,$true,0)){{$s.Information(3)}}"
                   "else{'NOTFOUND'}")


class WordNavigator:
    """«Перейди на страницу 10» и поиск слова в открытом документе Word."""

    def __init__(self, desktop):
        self.desktop = desktop
        self.last = None

    def run(self, action, arg):
        if sys.platform == 'darwin':
            return self._keyboard(action, arg)
        try:
            code, out, _ = _powershell(word_script(action, arg if action != 'next' else self.last))
        except Exception:
            code, out = 1, ''
        if code != 0 or not out:
            return self._keyboard(action, arg)
        return self._answer(action, arg, out.splitlines()[-1].strip())

    def _answer(self, action, arg, out):
        if out == 'NODOC':
            return 'В Word не открыт документ.'
        if out.startswith('TOTAL'):
            return f'В документе всего {out.split()[-1]} стр. — перейти на {arg} нельзя.'
        if action == 'page':
            return f'Страница {out}.' if arg != -1 else f'Последняя страница — {out}.'
        if out == 'NOTFOUND':
            return (f'Слово «{arg}» в документе не найдено.' if action == 'find'
                    else 'Больше совпадений нет.')
        if action == 'find':
            self.last = arg
        return f'Нашёл «{self.last}» на странице {out}. Скажите «найди дальше» для следующего.'

    def _keyboard(self, action, arg):
        """Без COM (или на Mac): окно «Перейти» / поиск через горячие клавиши Word."""
        d = self.desktop
        mac = sys.platform == 'darwin'
        if action == 'page':
            if arg == -1:
                d.hotkey('ctrl', 'end')
                return 'Последняя страница.'
            d.hotkey(*(('cmd', 'alt', 'g') if mac else ('ctrl', 'g')))
            time.sleep(0.5)
            d.type_text(str(arg), 'keys')
            d.hotkey('enter')
            time.sleep(0.3)
            d.hotkey('esc')
            return f'Страница {arg}.'
        if action == 'next' and not self.last:
            return 'Сначала скажите, какое слово найти.'
        if action == 'find':
            self.last = arg
            d.hotkey('ctrl', 'f')
            time.sleep(0.5)
            d.hotkey('ctrl', 'a')
            d.type_text(arg, 'keys')
        d.hotkey('enter')
        return f'Ищу «{self.last}».'


# ---------------- выполнение: вкладки ----------------
MAC_BROWSER_APPS = {'Google Chrome': 'chrome', 'Yandex': 'chrome', 'Microsoft Edge': 'chrome', 'Brave Browser': 'chrome',
                    'Vivaldi': 'chrome', 'Opera': 'chrome', 'Arc': 'chrome', 'Safari': 'safari'}


def mac_tab_script(app, kind, host):
    """AppleScript: найти вкладку с адресом host в запущенном браузере и сделать её активной."""
    host = host.replace('"', '')
    if kind == 'safari':
        body = (f'repeat with w in windows\nrepeat with t in tabs of w\nif URL of t contains "{host}" then\n'
                'set current tab of w to t\nset index of w to 1\nactivate\nreturn name of t\nend if\n'
                'end repeat\nend repeat')
    else:
        body = (f'repeat with w in windows\nset i to 0\nrepeat with t in tabs of w\nset i to i + 1\n'
                f'if URL of t contains "{host}" then\nset active tab index of w to i\nset index of w to 1\n'
                'activate\nreturn title of t\nend if\nend repeat\nend repeat')
    return f'tell application "{app}"\n{body}\nreturn ""\nend tell'


class TabNavigator:
    """Вкладки в браузере пользователя: по номеру (Ctrl+1…9) и по сайту (перебор Ctrl+Tab с проверкой заголовка)."""

    MAX_TABS = 60

    def __init__(self, desktop, browser=None):
        self.desktop = desktop
        self.browser = browser

    def _bridge(self):
        bridge = getattr(self.browser, 'bridge', None)
        return bridge if bridge is not None and getattr(bridge, 'connected', False) is True else None

    def go(self, which):
        from .controller import BROWSER_PROCESSES
        bridge = self._bridge()
        try:
            in_browser = self.desktop.target_process() in BROWSER_PROCESSES
        except Exception:
            in_browser = False
        if not in_browser and bridge is not None:
            result = bridge.send('tab', index=which)
            return f"Вкладка {result.get('index', which)}." if result else 'Такой вкладки нет.'
        if not in_browser:
            return 'Переключитесь в окно браузера и повторите: «перейди на первую вкладку».'
        mac = sys.platform == 'darwin'
        next_tab = ('control', 'tab') if mac else ('ctrl', 'tab')  # на Mac «ctrl» стал бы ⌘ — нужен настоящий Control
        if which == 'next':
            self.desktop.hotkey(*next_tab)
            return 'Следующая вкладка.'
        if which == 'prev':
            self.desktop.hotkey(*(('control', 'shift', 'tab') if mac else ('ctrl', 'shift', 'tab')))
            return 'Предыдущая вкладка.'
        if which == 'last':
            self.desktop.hotkey('ctrl', '9')  # Ctrl+9 (⌘9) — последняя вкладка
            return 'Последняя вкладка.'
        if which <= 8:
            self.desktop.hotkey('ctrl', str(which))
        else:
            self.desktop.hotkey('ctrl', '1')
            time.sleep(0.05)
            self.desktop.hotkey(*next_tab, times=which - 1)
        return f'Вкладка {which}.'

    def switch_to_site(self, url, names=()):
        """Переключиться на уже открытую вкладку сайта. Вернуть ответ или None, если такой вкладки нет."""
        if self._bridge() is not None:
            return None  # с расширением вкладку по адресу найдёт browser.call('open')
        if sys.platform == 'darwin':
            return self._mac_switch(url)
        from . import winapi
        if not winapi.supported():
            return None
        markers = title_markers(url, names)
        if not markers or not self._browser_window():
            return None

        def title():
            return winapi.window_title(winapi.foreground())

        start = title()
        if title_matches(start, markers):
            return f'{markers[0]} уже на экране.'
        for _ in range(self.MAX_TABS):
            winapi.hotkey('ctrl', 'tab')
            time.sleep(0.12)
            current = title()
            if title_matches(current, markers):
                return f'Переключаюсь на {markers[0]}.'
            if current == start:
                break  # прошли все вкладки и вернулись на исходную
        return None

    def _browser_window(self):
        """Окно браузера: активное, если это браузер, иначе — первое окно запущенного браузера."""
        import psutil
        from . import winapi
        from .controller import BROWSER_PROCESSES
        hwnd = winapi.foreground()
        if hwnd and winapi.process_name(hwnd) in BROWSER_PROCESSES:
            return hwnd
        from ..app_control import _find_windows
        pids = set()
        for process in psutil.process_iter(['pid', 'name']):
            try:
                if (process.info['name'] or '').casefold() in BROWSER_PROCESSES:
                    pids.add(process.pid)
            except psutil.Error:
                pass
        windows = [w for w in (_find_windows(pids) if pids else []) if winapi.window_title(w)]
        if not windows or not winapi.focus(windows[0]):
            return None
        time.sleep(0.2)
        return windows[0]

    @staticmethod
    def _mac_switch(url):
        from .. import macos
        host = re.sub(r'^https?://(?:www\.)?', '', url).split('/')[0]
        for app, kind in MAC_BROWSER_APPS.items():
            if not macos.is_running(app):
                continue
            result = subprocess.run(['osascript', '-e', mac_tab_script(app, kind, host)],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return 'Переключаюсь на ' + result.stdout.strip()[:60] + '.'
        return None


# ---------------- свернуть сайт ----------------
def mac_minimize_script(app, kind, host):
    host = host.replace('"', '')
    prop = 'miniaturized' if kind == 'safari' else 'minimized'
    return (f'tell application "{app}"\nset n to 0\nrepeat with w in windows\nrepeat with t in tabs of w\n'
            f'if URL of t contains "{host}" then\nset {prop} of w to true\nset n to n + 1\nexit repeat\nend if\n'
            'end repeat\nend repeat\nreturn n\nend tell')


def minimize_site(url, names=(), bridge=None):
    """«Сверни ютуб»: свернуть окно браузера, где открыт сайт. Вернуть число свёрнутых окон или None, если не умеем."""
    if bridge is not None and getattr(bridge, 'connected', False) is True:
        return int(bridge.send('minimize', url=url) or 0)
    host = re.sub(r'^https?://(?:www\.)?', '', url).split('/')[0]
    if sys.platform == 'darwin':
        from .. import macos
        count = 0
        for app, kind in MAC_BROWSER_APPS.items():
            if macos.is_running(app):
                out = subprocess.run(['osascript', '-e', mac_minimize_script(app, kind, host)], capture_output=True,
                                     text=True, timeout=10).stdout.strip()
                count += int(out) if out.isdigit() else 0
        return count
    if sys.platform != 'win32':
        return None
    from ..app_control import _pids_by_names, minimize_windows, window_titles
    from .controller import BROWSER_PROCESSES
    markers = title_markers(url, names)
    windows = [hwnd for hwnd, title in window_titles(_pids_by_names(BROWSER_PROCESSES)) if title_matches(title, markers)]
    return minimize_windows(windows)
