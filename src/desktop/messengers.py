"""Messenger macros: «Напиши Милане в телеграме привет».

Шаги поиска контакта для каждого мессенджера можно переопределить в файле
messenger_profiles.json в папке данных (%LOCALAPPDATA%\\LocalAIAgent).
"""
import json
import re
import time

PROFILES = {
    'telegram': {
        'title': 'Telegram', 'process': 'telegram.exe', 'launch': 'телеграм',
        'words': r'телеграм\w*|телеграмм\w*|телеге|телегу|telegram|тг',
        # Esc закрывает текущий чат, фокус переходит в поиск по чатам.
        'open_search': [['esc'], ['esc']], 'open_result': [['enter']],
    },
    'whatsapp': {
        'title': 'WhatsApp', 'process': 'whatsapp.exe', 'launch': 'ватсап',
        'words': r'ватсап\w*|вотсап\w*|вацап\w*|whatsapp',
        'open_search': [['esc'], ['ctrl', 'f']], 'open_result': [['down'], ['enter']],
    },
    'discord': {
        'title': 'Discord', 'process': 'discord.exe', 'launch': 'дискорд',
        'words': r'дискорд\w*|discord',
        'open_search': [['ctrl', 'k']], 'open_result': [['enter']],
    },
    'slack': {
        'title': 'Slack', 'process': 'slack.exe', 'launch': 'slack',
        'words': r'слак\w*|слэк\w*|slack',
        'open_search': [['ctrl', 'k']], 'open_result': [['enter']],
    },
    'viber': {
        'title': 'Viber', 'process': 'viber.exe', 'launch': 'viber',
        'words': r'вайбер\w*|viber',
        'open_search': [['ctrl', 'f']], 'open_result': [['enter']],
    },
}

_APP_WORDS = '|'.join(p['words'] for p in PROFILES.values())
_VERB = r'(?:напиши|отправь|отошли|скажи|передай|черкни)'
# Имя: первое слово и следующие за ним слова с заглавной буквы («Арсению Крэку», «Arseny Crack»).
_NAME = r'(?P<who>[\w-]+(?:\s+(?-i:[A-ZА-ЯЁ])[\w-]*)*)'
_TEXT = r'\s*[,:\-—]?\s*(?:что\s+|текст\s+)?(?P<text>.+)$'
_PATTERNS = [
    re.compile(_VERB + r'\s+(?:сообщение\s+)?(?P<who>[^,:]+?)\s+(?:в|во|на)\s+(?P<app>' + _APP_WORDS +
               r')\b' + _TEXT, re.I | re.S),
    re.compile(r'(?:в|во)\s+(?P<app>' + _APP_WORDS + r')\b\s*,?\s*' + _VERB + r'\s+' + _NAME + _TEXT, re.I | re.S),
    re.compile(_VERB + r'\s+(?:в|во)\s+(?P<app>' + _APP_WORDS + r')\b\s*,?\s*' + _NAME + _TEXT, re.I | re.S),
]
_CHAT = r'(?:чат|диалог|переписку|группу|канал|беседу|личку)'
_OPEN_PATTERNS = [
    # «Открой чат с Арсением Крэком (в телеграме)», «перейди в группу Семья»
    re.compile(r'^(?:открой|найди|покажи|перейди\s+в|зайди\s+в|переключись\s+на)\s+' + _CHAT +
               r'\s+(?:с\s+|со\s+)?(?P<who>.+?)(?:\s+(?:в|во)\s+(?P<app>' + _APP_WORDS + r'))?$', re.I),
    # «Открой в телеграме Арсения», «найди в телеграме чат Работа»
    re.compile(r'^(?:открой|найди|покажи)\s+(?:в|во)\s+(?P<app>' + _APP_WORDS + r')\s+(?:' + _CHAT +
               r'\s+)?(?:с\s+|со\s+)?(?P<who>.+)$', re.I),
    # «Открой телеграм и найди Арсения Крэка»
    re.compile(r'^(?:открой|запусти|включи)\s+(?P<app>' + _APP_WORDS + r')\s+и\s+(?:найди|открой|перейди\s+в)\s+(?:' +
               _CHAT + r'\s+)?(?:с\s+|со\s+)?(?P<who>.+)$', re.I),
    # «Перейди к Арсению в телеграме»
    re.compile(r'^(?:перейди|переключись|зайди)\s+к\s+(?P<who>.+?)\s+(?:в|во)\s+(?P<app>' + _APP_WORDS + r')$', re.I),
]
# Сообщение в уже открытый чат: «ответь привет», «напиши в чат я скоро буду».
_CURRENT = re.compile(r'^(?:(?P<send>ответь|отправь\s+в\s+(?:этот\s+)?чат)|(?:напиши|напечатай)\s+в\s+(?:этот\s+|текущий\s+)?чат)'
                      r'\s*[,:\-—]?\s*(?:что\s+|текст\s+)?(?P<text>.+)$', re.I | re.S)

_TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                     ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't',
                      'u', 'f', 'kh', 'ts', 'ch', 'sh', 'sch', '', 'y', '', 'e', 'yu', 'ya']))


def app_key(word):
    for key, profile in PROFILES.items():
        if re.fullmatch(profile['words'], word, re.I):
            return key
    return None


ENDINGS3 = ('ому', 'ему', 'ого', 'его', 'ами', 'ями')
ENDINGS2 = ('ой', 'ей', 'ым', 'им', 'ом', 'ем', 'ём', 'ую', 'юю', 'ая', 'яя')


def search_stem(who):
    """«Милане Ивановой» → «Милан Иванов», «Арсением Крэком» → «Арсени Крэк»: префикс находит полное имя."""
    words = []
    for word in re.findall(r'[\w\-]+', who):
        low = word.casefold()
        if not re.search('[а-яё]', low):
            words.append(word)  # латиницу не трогаем
            continue
        if len(low) > 5 and low.endswith(ENDINGS3):
            word = word[:-3]
        elif len(low) > 4 and low.endswith(ENDINGS2):
            word = word[:-2]
        elif len(low) > 3 and low[-1] in 'еиуюаяоы':
            word = word[:-1]
        words.append(word)
    return ' '.join(words)


def translit(text):
    return ''.join(_TRANSLIT.get(c, _TRANSLIT.get(c.lower(), c).capitalize() if c.isupper() else c) for c in text)


def latin_query(who):
    """«Арсению Крэку» → «Arsen»: латинский префикс имени находит «Arseny Crack», «Arseniy»…"""
    first = search_stem(who).split()[0] if who.split() else ''
    if not re.search('[а-яё]', first.casefold()):
        return first
    value = translit(first)
    trimmed = re.sub(r'[aeiouy]+$', '', value, flags=re.I)
    return trimmed if len(trimmed) >= 3 else value


def parse_aliases(text):
    """«Арсений Крэк = Arseny Crack; Мама = Мамуля» → {'арсений крэк': 'Arseny Crack', ...}."""
    aliases = {}
    for line in re.split(r'[\n;]+', str(text or '')):
        spoken, sep, real = line.partition('=')
        if sep and spoken.strip() and real.strip():
            aliases[' '.join(spoken.casefold().replace('ё', 'е').split())] = real.strip()
    return aliases


def find_alias(who, aliases):
    """Учитывает падежи: «Арсению Крэку» найдёт псевдоним «Арсений Крэк»."""
    key = ' '.join(who.casefold().replace('ё', 'е').split())
    if key in aliases:
        return aliases[key]
    words = search_stem(key).casefold().split()
    for spoken, real in aliases.items():
        other = search_stem(spoken).casefold().split()
        if len(other) == len(words) and all(a.startswith(b) or b.startswith(a) for a, b in zip(words, other)):
            return real
    return None


def search_query(who, settings=None):
    """Что напечатать в поиске чатов: псевдоним, латинский префикс или русская основа имени."""
    settings = settings or {}
    alias = find_alias(who, parse_aliases(settings.get('contact_aliases', '')))
    if alias:
        return alias
    if settings.get('contacts_latin', False):
        return latin_query(who)
    return search_stem(who)


def _clean_who(who):
    return re.sub(r'^(?:в\s+|во\s+)?(?:чат|группу|канал|беседу)\s+(?:с\s+|со\s+)?', '', who.strip(' ,.'), flags=re.I).strip()


def parse(text):
    """Вернуть dict(app, who, text, send) или None."""
    value = re.sub(r'\s+', ' ', str(text)).strip()
    for pattern in _PATTERNS:
        match = pattern.match(value)
        if match:
            key = app_key(match['app'])
            who = _clean_who(match['who'])
            message = match['text'].strip()
            if not key or not who or not message:
                return None
            send = value.casefold().startswith(('отправь', 'отошли')) or \
                bool(re.search(r'\b(?:отправь|отошли)\b', value[:match.start('who')], re.I))
            return dict(app=key, who=who, text=message, send=send)
    return None


def parse_open(text, default_app='telegram'):
    """«Открой чат с Арсением Крэком» → dict(app, who) или None."""
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    for pattern in _OPEN_PATTERNS:
        match = pattern.match(value)
        if match:
            who = _clean_who(match['who'])
            key = app_key(match['app']) if match['app'] else default_app
            if who and key and not app_key(who):
                return dict(app=key, who=who)
    return None


def parse_current(text):
    """«Ответь привет» → dict(text, send) для открытого чата или None."""
    match = _CURRENT.match(re.sub(r'\s+', ' ', str(text)).strip())
    if not match or not match['text'].strip():
        return None
    return dict(text=match['text'].strip(), send=bool(match['send']))


def load_profiles(root=None):
    profiles = {k: dict(v) for k, v in PROFILES.items()}
    if root:
        try:
            custom = json.loads((root / 'messenger_profiles.json').read_text(encoding='utf-8'))
            for key, value in custom.items():
                if key in profiles and isinstance(value, dict):
                    profiles[key].update({k: v for k, v in value.items() if k in ('open_search', 'open_result')})
        except (OSError, ValueError):
            pass
    return profiles


def open_chat(desktop, request, settings=None, root=None):
    """Открыть чат или группу через поиск мессенджера. Вернуть None или текст ошибки."""
    from . import winapi
    profile = load_profiles(root)[request['app']]
    if not desktop.activate_process({profile['process']}, launch_name=profile['launch']):
        return f"Не удалось открыть {profile['title']}. Запустите его и повторите."
    winapi.release_modifiers()
    for keys in profile['open_search']:
        winapi.hotkey(*keys)
        time.sleep(0.15)
    winapi.type_unicode(search_query(request['who'], settings))
    time.sleep(1.1)
    for keys in profile['open_result']:
        winapi.hotkey(*keys)
        time.sleep(0.25)
    time.sleep(0.5)
    return None


def type_in_chat(desktop, app, text, send, root=None):
    """Напечатать в уже открытый чат (мессенджер выводится на передний план)."""
    from . import winapi
    profile = load_profiles(root)[app]
    if desktop.target_process() != profile['process'] and not desktop.activate_process({profile['process']}):
        return f"{profile['title']} не запущен. Скажите «Открой чат с …»."
    winapi.release_modifiers()
    winapi.type_unicode(text, newline=('shift', 'enter'))
    if send:
        time.sleep(0.1)
        winapi.hotkey('enter')
        return 'Отправил: ' + text
    return 'Напечатал: ' + text + '. Скажите «отправь», чтобы отправить.'


def send_message(desktop, request, autosend=False, root=None, settings=None):
    """Выполнить макрос. desktop — DesktopController."""
    from . import winapi
    profile = load_profiles(root)[request['app']]
    error = open_chat(desktop, request, settings, root)
    if error:
        return error
    winapi.type_unicode(request['text'], newline=('shift', 'enter'))
    if request['send'] or autosend:
        time.sleep(0.1)
        winapi.hotkey('enter')
        return f"Отправил в {profile['title']} для «{request['who']}»."
    return f"Написал в {profile['title']} для «{request['who']}». Скажите «отправь», чтобы отправить."
