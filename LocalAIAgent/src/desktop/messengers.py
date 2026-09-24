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
_PATTERNS = [
    re.compile(_VERB + r'\s+(?:сообщение\s+)?(?P<who>[^,:]+?)\s+(?:в|во|на)\s+(?P<app>' + _APP_WORDS +
               r')\b\s*[,:\-—]?\s*(?:что\s+|текст\s+)?(?P<text>.+)$', re.I | re.S),
    re.compile(r'(?:в|во)\s+(?P<app>' + _APP_WORDS + r')\b\s*,?\s*' + _VERB +
               r'\s+(?P<who>\S+)\s*[,:\-—]?\s*(?:что\s+|текст\s+)?(?P<text>.+)$', re.I | re.S),
]


def app_key(word):
    for key, profile in PROFILES.items():
        if re.fullmatch(profile['words'], word, re.I):
            return key
    return None


def search_stem(who):
    """«Милане Ивановой» → «Милан Иванов»: префикс находит «Милана Иванова»."""
    words = []
    for word in re.findall(r'[\w\-]+', who):
        low = word.casefold()
        if len(low) > 4 and low.endswith(('ой', 'ей', 'ому', 'ему', 'ым', 'им')):
            word = word[:-3] if low.endswith(('ому', 'ему')) else word[:-2]
        elif len(low) > 3 and low[-1] in 'еиуюаяо':
            word = word[:-1]
        words.append(word)
    return ' '.join(words)


def parse(text):
    """Вернуть dict(app, who, text, send) или None."""
    value = re.sub(r'\s+', ' ', str(text)).strip()
    for pattern in _PATTERNS:
        match = pattern.match(value)
        if match:
            key = app_key(match['app'])
            who = match['who'].strip(' ,.')
            message = match['text'].strip()
            if not key or not who or not message:
                return None
            send = value.casefold().startswith(('отправь', 'отошли')) or \
                bool(re.search(r'\b(?:отправь|отошли)\b', value[:match.start('who')], re.I))
            return dict(app=key, who=who, text=message, send=send)
    return None


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


def send_message(desktop, request, autosend=False, root=None):
    """Выполнить макрос. desktop — DesktopController."""
    from . import winapi
    profile = load_profiles(root)[request['app']]
    if not desktop.activate_process({profile['process']}, launch_name=profile['launch']):
        return f"Не удалось открыть {profile['title']}. Запустите его и повторите."
    winapi.release_modifiers()
    for keys in profile['open_search']:
        winapi.hotkey(*keys)
        time.sleep(0.15)
    winapi.type_unicode(search_stem(request['who']))
    time.sleep(1.1)
    for keys in profile['open_result']:
        winapi.hotkey(*keys)
        time.sleep(0.25)
    time.sleep(0.5)
    winapi.type_unicode(request['text'], newline=('shift', 'enter'))
    if request['send'] or autosend:
        time.sleep(0.1)
        winapi.hotkey('enter')
        return f"Отправил в {profile['title']} для «{request['who']}»."
    return f"Написал в {profile['title']} для «{request['who']}». Скажите «отправь», чтобы отправить."
