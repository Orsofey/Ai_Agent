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
_GO = r'(?:открой|открыть|найди|найти|покажи|показать|перейди|перейти|зайди|зайти|переключись|переключиться|войди|войти)'
_OPEN_PATTERNS = [
    # «Открой чат с Арсением Крэком (в телеграме)», «перейди в группу Семья», «перейти в чат Избранное»
    re.compile(r'^' + _GO + r'\s+(?:в\s+|на\s+)?' + _CHAT + r'\s+(?:с\s+|со\s+)?(?P<who>.+?)(?:\s+(?:в|во)\s+(?P<app>' +
               _APP_WORDS + r'))?$', re.I),
    # «Открой телеграм и найди Арсения Крэка»
    re.compile(r'^(?:открой|запусти|включи)\s+(?P<app>' + _APP_WORDS + r')\s+и\s+' + _GO + r'\s+(?:в\s+)?(?:' +
               _CHAT + r'\s+)?(?:с\s+|со\s+)?(?P<who>.+)$', re.I),
    # «Открой в телеграм(е) (чат) Катя», «открой телеграм чат Катя», «найди в телеграме Арсения»
    re.compile(r'^' + _GO + r'\s+(?:(?:в|во)\s+)?(?P<app>' + _APP_WORDS + r')\s+(?:' + _CHAT +
               r'\s+)?(?:с\s+|со\s+)?(?P<who>.+)$', re.I),
    # «Перейди к Арсению в телеграме»
    re.compile(r'^' + _GO + r'\s+к\s+(?P<who>.+?)\s+(?:в|во)\s+(?P<app>' + _APP_WORDS + r')$', re.I),
]


def _tidy(text):
    """Распознавание пишет «Telegram-чат», «чат«Избранное»», «чат, Катя» — приводим к словам через пробел."""
    value = re.sub(r'[«»"“”„]', ' ', str(text))
    value = re.sub(r'(?<=\w)-(?=(?:чат|групп|канал))', ' ', value, flags=re.I)
    value = re.sub(r'(телеграм\w*?|telegram)(чат)', r'\1 \2', value, flags=re.I)
    value = re.sub(r'[,:;]', ' ', value)
    return re.sub(r'\s+', ' ', value).strip().strip('.!?')


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
    # Распознавание ошибается в редких фамилиях: «Арсений Краг» ≈ «Арсений Крэк».
    from difflib import SequenceMatcher
    best, score = None, 0.0
    for spoken, real in aliases.items():
        ratio = SequenceMatcher(None, ' '.join(words), search_stem(spoken).casefold()).ratio()
        if ratio > score:
            best, score = real, ratio
    return best if score >= 0.78 else None


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
    value = _tidy(text)
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


# ---------------- Discord: «Андрей, зайди на дискорд сервер Майнкрафт» ----------------
_DISCORD = r'(?:дискорд\w*|discord)'
_SERVER = r'(?:сервер\w*|серв)'
_ENTER = r'(?:зайди|зайти|перейди|перейти|войди|войти|открой|открыть|переключись|покажи)'
_DISCORD_PATTERNS = [
    # «Зайди на (дискорд) сервер Майнкрафт (в дискорде)», «открой дискорд сервер Друзья»
    re.compile(r'^' + _ENTER + r'\s+(?:(?:на|в)\s+)?(?:' + _DISCORD + r'\s+)?' + _SERVER + r'(?:\s+' + _DISCORD +
               r')?(?:\s+(?P<name>.+?))?(?:\s+(?:в|на)\s+' + _DISCORD + r')?$', re.I),
    # «Зайди в дискорд на сервер Майнкрафт», «зайди в дискорде на сервер …»
    re.compile(r'^' + _ENTER + r'\s+(?:в|на)\s+' + _DISCORD + r'\s+(?:(?:на|в)\s+)?' + _SERVER + r'(?:\s+(?P<name>.+))?$', re.I),
    # «Открой дискорд и зайди на сервер Майнкрафт»
    re.compile(r'^(?:открой|запусти|включи)\s+' + _DISCORD + r'\s+и\s+' + _ENTER + r'\s+(?:(?:на|в)\s+)?' + _SERVER +
               r'(?:\s+(?P<name>.+))?$', re.I),
]


def parse_discord(text):
    """dict(server=имя) или dict(server='') — сервер не назван; None — не про Discord."""
    value = _tidy(text)
    for pattern in _DISCORD_PATTERNS:
        match = pattern.match(value)
        if match:
            name = (match['name'] or '').strip(' ,.')
            name = re.sub(r'^(?:под названием|который называется|называется)\s+', '', name, flags=re.I)
            return dict(server=name)
    return None


def open_discord_server(desktop, name, settings=None, root=None):
    """Открыть Discord (запустить, если закрыт) и перейти на сервер через Ctrl+K «*имя»."""
    from . import winapi
    from ..app_control import activate_running
    fresh = not activate_running('дискорд')
    if fresh:
        # Discord после запуска проверяет обновления — ждём окно дольше обычного.
        if not desktop.activate_process({'discord.exe'}, launch_name='дискорд', timeout=60):
            return 'Не удалось открыть Discord. Запустите его и повторите.'
        time.sleep(7)
    else:
        time.sleep(0.4)
    winapi.release_modifiers()
    winapi.hotkey('esc')
    time.sleep(0.15)
    winapi.hotkey('ctrl', 'k')  # быстрый переход; «*» — искать только серверы
    time.sleep(0.6)
    winapi.type_unicode('*' + search_query(name, settings))
    time.sleep(1.0)
    winapi.hotkey('enter')
    return f'Захожу на сервер «{name}» в Discord.'


# ---------------- Голосовые каналы Discord ----------------
_VOICE = r'(?:голосов\w*|войс\w*|voice)(?:\s+(?:канал\w*|чат\w*|комнат\w*))?'
_VOICE_PATTERN = re.compile(r'^(?:зайди|зайти|войди|войти|подключись|подключиться|присоединись|перейди|перейти|залетай|залети)\s+'
                            r'(?:в|во|к|на)\s+' + _VOICE + r'(?:\s+(?P<name>.+?))?(?:\s+(?:в|на)\s+' + _DISCORD + r')?$', re.I)


def parse_voice_channel(text):
    """«Зайди в голосовой канал (Под столом)» → dict(channel=…); без названия — последний канал."""
    match = _VOICE_PATTERN.match(_tidy(text))
    if not match:
        return None
    name = (match['name'] or '').strip(' ,.')
    name = re.sub(r'^(?:под названием|который называется|называется)\s+', '', name, flags=re.I)
    return dict(channel=name)


def _open_discord(desktop):
    from ..app_control import activate_running
    if activate_running('дискорд'):
        time.sleep(0.4)
        return True
    if not desktop.activate_process({'discord.exe'}, launch_name='дискорд', timeout=60):
        return False
    time.sleep(7)  # проверка обновлений после запуска
    return True


def join_voice_channel(desktop, name, settings=None):
    """Ctrl+K «!название» — поиск только голосовых каналов; Enter подключает к каналу."""
    from . import winapi
    if not _open_discord(desktop):
        return 'Не удалось открыть Discord. Запустите его и повторите.'
    winapi.release_modifiers()
    winapi.hotkey('esc')
    time.sleep(0.15)
    winapi.hotkey('ctrl', 'k')
    time.sleep(0.6)
    winapi.type_unicode('!' + (search_query(name, settings) if name else ''))
    time.sleep(1.0)
    winapi.hotkey('enter')
    return f'Захожу в голосовой канал «{name}».' if name else 'Захожу в последний голосовой канал.'


_TOGGLES = [
    (re.compile(r'^(?:выключи|отключи|включи|замьють|замуть|размьють|размуть)\s*(?:мне\s+|мой\s+|себе\s+)?(?:микрофон|микро|мик|себя)'
                r'(?:\s+в\s+' + _DISCORD + r')?$', re.I), 'mute'),
    (re.compile(r'^(?:выключи|отключи|включи)\s+(?:звук|наушники)\s+в\s+' + _DISCORD + r'$', re.I), 'deafen'),
]


def parse_discord_toggle(text):
    value = _tidy(text)
    for pattern, what in _TOGGLES:
        if pattern.match(value):
            return dict(what=what)
    return None


def discord_toggle(desktop, what):
    """Горячие клавиши Discord: Ctrl+Shift+M — микрофон, Ctrl+Shift+D — звук."""
    from . import winapi
    if not _open_discord(desktop):
        return 'Discord не запущен.'
    winapi.release_modifiers()
    winapi.hotkey('ctrl', 'shift', 'm' if what == 'mute' else 'd')
    return 'Переключил микрофон в Discord.' if what == 'mute' else 'Переключил звук в Discord.'


# ---------------- Реакции: «поставь сердечко», «поставь смеющийся смайлик» ----------------
# (корень слова, эмодзи, имя в Discord)
EMOJI = [
    (r'серд|любов|лав|heart', '❤️', 'heart'),
    (r'сме[юх]|ржу|ржущ|хаха|угар|плачущ\w* от смеха|лол', '😂', 'joy'),
    (r'улыб', '😊', 'blush'),
    (r'лайк|палец вверх|класс|👍|like', '👍', 'thumbsup'),
    (r'дизлайк|палец вниз', '👎', 'thumbsdown'),
    (r'ог[он]н|fire', '🔥', 'fire'),
    (r'плач|груст|слез', '😢', 'cry'),
    (r'удивл|шок|вау', '😮', 'open_mouth'),
    (r'зл|бес|ярост', '😡', 'rage'),
    (r'праздн|хлопуш|конфетти|ура', '🎉', 'tada'),
    (r'сто\b|100', '💯', '100'),
    (r'ок\b|окей', '👌', 'ok_hand'),
    (r'глаз', '👀', 'eyes'),
    (r'череп|умер', '💀', 'skull'),
    (r'клоун', '🤡', 'clown'),
    (r'молитв|спасибо', '🙏', 'pray'),
    (r'думаю|задум', '🤔', 'thinking'),
    (r'галочк|готово', '✅', 'white_check_mark'),
]
_REACT = re.compile(r'^(?:поставь|поставить|ставь|отреагируй|кинь|добавь|лайкни)\s*(?:реакци\w+\s*)?(?P<what>.*?)'
                    r'(?:\s+(?:на|под)\s+(?:последнее\s+|это\s+)?сообщение)?$', re.I)


def parse_reaction(text):
    value = _tidy(text)
    if re.match(r'^лайкни', value, re.I):
        return dict(emoji='👍', name='thumbsup')
    match = _REACT.match(value)
    if not match:
        return None
    what = match['what']
    if not what and not re.search(r'реакци|отреагируй', value, re.I):
        return None
    if what and not re.search(r'смайл|эмодзи|реакц|серд|лайк|сме|огон|огн|плач|груст|удив|зл|праздн|палец|глаз|череп|клоун|'
                              r'молитв|задум|галочк|улыб|ржу|хаха|вау|сто\b|окей', value, re.I):
        return None  # «поставь будильник», «поставь музыку» — не реакции
    for stem, emoji, name in EMOJI:
        if re.search(stem, what or 'лайк', re.I):
            return dict(emoji=emoji, name=name)
    return dict(emoji='👍', name='thumbsup')


def react(desktop, request, chat=None):
    """Discord: «+:heart:» ставит реакцию на последнее сообщение. В остальных приложениях реакции
    голосом не поставить: эмодзи вставляется в поле сообщения, отправка — «отправь»."""
    from . import winapi
    process = desktop.target_process()
    if process == 'discord.exe':
        winapi.release_modifiers()
        winapi.type_unicode(f"+:{request['name']}:")
        time.sleep(0.1)
        winapi.hotkey('enter')
        return f"Поставил реакцию {request['emoji']}."
    desktop.type_text(request['emoji'])
    return (f"Здесь реакцию голосом поставить нельзя — вставил {request['emoji']} в поле сообщения. "
            'Скажите «отправь», чтобы отправить.')
