"""Умный дом голосом: телевизор, роутер, лампочки. Настройка — Настройки → «Умный дом».

Телевизор:  LG (webOS), Samsung (Tizen), Android TV / Google TV (Xiaomi, Sber, TCL, Haier… — «Отладка по сети»),
            а также телевизоры в «Доме с Алисой». «Включи телевизор», «громче на телевизоре», «громкость телевизора 20»,
            «выключи звук на телевизоре», «переключи на 5 канал», «следующий канал», «открой на телевизоре Кинопоиск»,
            «включи на телевизоре Интерстеллар на YouTube», «режим изображения кино» (LG), «пауза на телевизоре».
Роутер:     Keenetic (веб-API RCI), MikroTik (REST). «Кто подключён к Wi-Fi», «перезагрузи роутер» (с подтверждением),
            «отключи интернет у планшета», «открой настройки роутера», «проверь интернет».
Лампочки:   «Дом с Алисой» (все лампы, добавленные в приложение «Дом с Алисой»), Home Assistant, Philips Hue, Yeelight.
            «Включи свет в спальне», «выключи свет везде», «яркость 40 процентов», «сделай свет синим», «тёплый свет».

Пароли и токены хранятся только на этом ПК (папка данных) и не показываются в окне настроек.
"""
import base64
import hashlib
import json
import logging
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

log = logging.getLogger(__name__)

SECRET_FIELDS = {'password', 'token', 'client_key', 'username'}


def is_secret(key):
    """password, yandex_token, ha_token, hue_username, client_key…"""
    return key in SECRET_FIELDS or key.rsplit('_', 1)[-1] in SECRET_FIELDS
YANDEX_IOT = 'https://api.iot.yandex.net/v1.0'
CONFIRM_SECONDS = 30

COLORS = {
    'красн': (255, 0, 0), 'оранжев': (255, 120, 0), 'желт': (255, 220, 0), 'зелен': (0, 255, 60), 'голуб': (0, 190, 255),
    'син': (0, 60, 255), 'фиолетов': (150, 0, 255), 'сиренев': (190, 120, 255), 'розов': (255, 80, 170),
    'бирюзов': (0, 255, 200), 'бел': (255, 255, 255),
}
TEMPERATURES = {'тепл': 2700, 'уютн': 2700, 'нейтральн': 4000, 'дневн': 5000, 'холодн': 6500}
ORDINAL = {'перв': 1, 'втор': 2, 'трет': 3, 'четвер': 4, 'пят': 5, 'шест': 6, 'седьм': 7, 'восьм': 8, 'девят': 9,
           'десят': 10, 'одиннадцат': 11, 'двенадцат': 12, 'тринадцат': 13, 'четырнадцат': 14, 'пятнадцат': 15}
NUMBER_WORDS = {'ноль': 0, 'один': 1, 'два': 2, 'три': 3, 'четыре': 4, 'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8,
                'девять': 9, 'десять': 10, 'пятнадцать': 15, 'двадцать': 20, 'двадцать пять': 25, 'тридцать': 30,
                'сорок': 40, 'пятьдесят': 50, 'шестьдесят': 60, 'семьдесят': 70, 'восемьдесят': 80, 'девяносто': 90,
                'сто': 100}
TV_APPS = {
    'youtube': ('YouTube', ['ютуб', 'youtube', 'ютюб'], 'youtube.leanback.v4', 'com.google.android.youtube.tv', '111299001912'),
    'kinopoisk': ('Кинопоиск', ['кинопоиск', 'kinopoisk'], 'kinopoisk', 'kinopoisk', None),
    'ivi': ('Иви', ['иви', 'ivi'], 'ivi', 'ivi', None),
    'okko': ('Okko', ['окко', 'okko'], 'okko', 'okko', None),
    'wink': ('Wink', ['винк', 'wink'], 'wink', 'wink', None),
    'premier': ('PREMIER', ['премьер', 'premier'], 'premier', 'premier', None),
    'start': ('START', ['старт', 'start'], 'start', 'start', None),
    'rutube': ('RUTUBE', ['рутуб', 'rutube'], 'rutube', 'rutube', None),
    'vk': ('VK Видео', ['вк видео', 'vk видео', 'вконтакте'], 'vk', 'vk', None),
    'netflix': ('Netflix', ['нетфликс', 'netflix'], 'netflix', 'com.netflix', '3201907018807'),
}
SEARCH_LINKS = {'youtube': 'https://www.youtube.com/results?search_query={q}',
                'kinopoisk': 'https://hd.kinopoisk.ru/search?text={q}', 'ivi': 'https://www.ivi.ru/search/?q={q}'}

TV = r'(?:телевизор\w*|телик\w*|телек\w*|тв|ящик\w*|телевидени\w*)'
ON_TV = r'(?:\s+(?:на|в|у)\s+' + TV + r'|\s+' + TV + r')'
LIGHT = r'\b(?:свет|света|свету|светом|свете|ламп\w*|люстр\w*|подсветк\w*|торшер\w*|ночник\w*|светильник\w*|освещени\w*)\b'
ROUTER = r'(?:роутер\w*|маршрутизатор\w*)'


def number(text):
    text = text.casefold().strip()
    if text.isdigit():
        return int(text)
    if text in NUMBER_WORDS:
        return NUMBER_WORDS[text]
    for stem, value in sorted(ORDINAL.items(), key=lambda x: -len(x[0])):
        if text.startswith(stem):
            return value
    parts = text.split()
    if len(parts) == 2 and parts[0] in NUMBER_WORDS and parts[1] in NUMBER_WORDS:
        return NUMBER_WORDS[parts[0]] + NUMBER_WORDS[parts[1]]
    return None


def stem_words(text):
    words = re.findall(r'[\wё]+', str(text).casefold().replace('ё', 'е'))
    return [w[:max(4, len(w) - 2)] if len(w) > 5 else w for w in words]


def name_matches(query, name):
    """«в спальне» ≈ «Спальня», «у кровати» ≈ «Лампа у кровати»."""
    q, n = stem_words(query), stem_words(name)
    q = [w for w in q if w not in ('в', 'на', 'у', 'во', 'свет', 'ламп', 'лампу', 'люстр')]
    return bool(q) and all(any(a.startswith(b[:4]) or b.startswith(a[:4]) for b in n) for a in q)


# ---------------- разбор фраз ----------------
def parse_tv(text):
    value = re.sub(r'\s+', ' ', str(text).casefold().replace('ё', 'е')).strip().strip('.!?')
    if re.fullmatch(r'(?:включи|вруби)\s+' + TV, value):
        return ('power', True)
    if re.fullmatch(r'(?:выключи|выруби|отключи)\s+' + TV, value):
        return ('power', False)
    if re.fullmatch(r'(?:выключи|отключи|убери)\s+звук' + ON_TV + r'|' + TV + r'\s+без звука', value):
        return ('mute', True)
    if re.fullmatch(r'(?:включи|верни)\s+звук' + ON_TV, value):
        return ('mute', False)
    match = re.fullmatch(r'(?:громкость|звук)(?:' + ON_TV + r')?\s+(?:на\s+)?(\S+(?:\s\S+)?)|'
                         r'(?:поставь|сделай)\s+громкость\s+(\S+(?:\s\S+)?)' + ON_TV, value)
    if match:
        level = number(match[1] or match[2])
        if level is not None:
            return ('volume', max(0, min(100, level)))
    if re.fullmatch(r'(?:(?:сделай|прибавь|добавь)\s+)?(?:громче|звук громче|прибавь звук)' + ON_TV + r'|' + TV + r'\s+громче', value):
        return ('volume_step', 1)
    if re.fullmatch(r'(?:(?:сделай|убавь)\s+)?(?:тише|звук тише|убавь звук)' + ON_TV + r'|' + TV + r'\s+тише', value):
        return ('volume_step', -1)
    match = re.fullmatch(r'(?:включи|переключи|поставь)(?:\s+на)?\s+(\S+)\s+канал(?:' + ON_TV + r')?|'
                         r'(?:включи|переключи на)?\s*канал\s+(\S+(?:\s\S+)?)(?:' + ON_TV + r')?', value)
    if match:
        channel = number(match[1] or match[2] or '')
        if channel:
            return ('channel', channel)
    if re.fullmatch(r'(?:следующий|дальше)\s+канал(?:' + ON_TV + r')?|канал\s+вперед', value):
        return ('channel_step', 1)
    if re.fullmatch(r'(?:предыдущий|прошлый)\s+канал(?:' + ON_TV + r')?|канал\s+назад', value):
        return ('channel_step', -1)
    if re.fullmatch(r'(?:пауза|останови|поставь на паузу)' + ON_TV, value):
        return ('pause', None)
    if re.fullmatch(r'(?:продолжи|воспроизведи|сними с паузы)' + ON_TV, value):
        return ('play', None)
    match = re.fullmatch(r'(?:режим (?:изображения|картинки))\s+(кино|спорт|игр\w*|ярк\w*|стандарт\w*|эко)' + '(?:' + ON_TV + ')?',
                         value)
    if match:
        return ('picture', match[1][:4])
    match = re.fullmatch(r'(?:включи|запусти|найди|покажи|поставь)' + ON_TV + r'\s+(?:фильм\w*|сериал\w*|видео|мультфильм\w*|'
                         r'мультик\w*)?\s*(.+?)(?:\s+(?:на|в)\s+(\S+))?', value)
    if match and not _app_key(match[1]):
        channel = re.fullmatch(r'(\S+(?:\s\S+)?)\s+канал', match[1].strip())
        if channel and number(channel[1]):
            return ('channel', number(channel[1]))
        return ('search', (match[1].strip(), _app_key(match[2] or '') or 'youtube'))
    match = re.fullmatch(r'(?:открой|запусти|включи)' + ON_TV + r'\s+(.+)|(?:открой|запусти|включи)\s+(.+?)' + ON_TV, value)
    if match:
        app = _app_key(match[1] or match[2] or '')
        if app:
            return ('app', app)
    return None


def _app_key(text):
    text = str(text).casefold().strip()
    for key, (title, words, *_rest) in TV_APPS.items():
        if any(text.startswith(w) for w in words):
            return key
    return None


def parse_lights(text):
    value = re.sub(r'\s+', ' ', str(text).casefold().replace('ё', 'е')).strip().strip('.!?')
    if not re.search(LIGHT, value):
        return None
    where = ''
    match = re.search(r'\s(?:в|во|на|у)\s+(?!\d)([\wё -]+?)(?:\s+(?:на|до)\s+\d.*)?$', value)
    if match and not re.fullmatch(r'\d+.*|процент\w*', match[1]):
        where = match[1].strip()
    if where:
        noise = '|'.join(list(COLORS) + list(TEMPERATURES) + ['ярче', 'темнее', 'поярче', 'потемнее', 'процент', 'яркост'])
        where = ' '.join(w for w in where.split() if not re.match(r'\d|(?:' + noise + ')', w) and number(w) is None).strip()
    if re.search(r'\bвезде\b|\bвесь свет\b|\bвсе\s+(?:ламп|свет)', value):
        where = '*'
    match = re.match(r'^(?:включи|зажги|вруби)\s+' + LIGHT, value)
    if match and not re.search(r'(?:ярк|%|процент|цвет|тепл|холодн|красн|син|зелен|желт|розов|фиолет|бел|голуб|оранж)', value):
        return ('on', where)
    if re.match(r'^(?:выключи|погаси|выруби|отключи)\s+(?:весь\s+|все\s+)?' + LIGHT, value):
        return ('off', where)
    match = re.search(r'(\d{1,3}|[а-я]+)\s*(?:%|процент\w*)', value) or re.search(r'яркост\w*\s+(?:на\s+)?(\d{1,3})', value)
    if match and number(match[1]) is not None:
        return ('brightness', (max(1, min(100, number(match[1]))), where))
    if re.search(r'\b(?:ярче|посветлее|поярче)\b', value):
        return ('brightness_step', (25, where))
    if re.search(r'\b(?:темнее|тусклее|приглуши|потемнее|поменьше)\b', value):
        return ('brightness_step', (-25, where))
    for stem, kelvin in TEMPERATURES.items():
        if re.search(r'\b' + stem + r'\w*\s+' + LIGHT + r'|' + LIGHT + r'\s+' + stem, value):
            return ('temperature', (kelvin, where))
    for stem, rgb in COLORS.items():
        if re.search(r'\b' + stem + r'\w*\b', value):
            return ('color', (rgb, where))
    return None


def parse_router(text):
    value = re.sub(r'\s+', ' ', str(text).casefold().replace('ё', 'е')).strip().strip('.!?')
    if re.fullmatch(r'(?:перезагрузи|перезапусти|рестартни)\s+(?:роутер\w*|маршрутизатор\w*|интернет|вай ?фай|wi-?fi)', value):
        return ('reboot', None)
    if re.fullmatch(r'(?:кто|какие устройства|что)\s+(?:сейчас\s+)?(?:подключен\w*|в сети|сидит)(?:\s+(?:к|в|на)\s+.+)?|'
                    r'сколько\s+устройств\s+.*|(?:покажи|список)\s+(?:устройств|подключенных устройств).*', value):
        return ('devices', None)
    if re.fullmatch(r'(?:открой|покажи)\s+(?:настройки|админк\w*|панель)\s+' + ROUTER, value):
        return ('open', None)
    match = re.fullmatch(r'(?:отключи|заблокируй|выключи)\s+интернет\s+(?:у|для|на)\s+(.+)', value)
    if match:
        return ('block', match[1])
    match = re.fullmatch(r'(?:включи|разблокируй|верни)\s+интернет\s+(?:у|для|на)\s+(.+)', value)
    if match:
        return ('unblock', match[1])
    if re.fullmatch(r'(?:проверь|есть ли|работает ли)\s+интернет|интернет работает', value):
        return ('check', None)
    return None


# ---------------- сеть: общее ----------------
def wake_on_lan(mac):
    raw = bytes.fromhex(re.sub(r'[^0-9a-fA-F]', '', mac))
    if len(raw) != 6:
        raise ValueError('MAC-адрес телевизора: 6 байт, например AA:BB:CC:DD:EE:FF')
    packet = b'\xff' * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            sock.sendto(packet, ('255.255.255.255', port))
    return True


def ssdp_search(targets=('urn:dial-multiscreen-org:service:dial:1', 'urn:schemas-upnp-org:device:MediaRenderer:1'),
                timeout=2.5, port=1900, address='239.255.255.250'):
    """Устройства в сети (телевизоры отвечают на DIAL/MediaRenderer): [{'ip', 'location', 'server'}]."""
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.3)
        for target in targets:
            message = (f'M-SEARCH * HTTP/1.1\r\nHOST: {address}:{port}\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
                       f'ST: {target}\r\n\r\n')
            sock.sendto(message.encode(), (address, port))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _) = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            headers = {k.strip().casefold(): v.strip() for k, _, v in
                       (line.partition(':') for line in data.decode('utf-8', 'replace').split('\r\n')[1:]) if k}
            found.setdefault(ip, {'ip': ip, 'location': headers.get('location', ''), 'server': headers.get('server', '')})
    return list(found.values())


def describe_tv(item, session):
    """Название и производитель из описания UPnP: определяем тип (LG/Samsung/Android)."""
    name, maker = item['ip'], ''
    try:
        xml = session.get(item['location'], timeout=3).text if item.get('location') else ''
        name = (re.search(r'<friendlyName>(.*?)</friendlyName>', xml) or [None, name])[1]
        maker = (re.search(r'<manufacturer>(.*?)</manufacturer>', xml) or [None, ''])[1]
    except Exception:
        pass
    text = f'{maker} {item.get("server", "")} {name}'.casefold()
    kind = 'lg' if 'lg' in text or 'webos' in text else 'samsung' if 'samsung' in text or 'tizen' in text else 'android'
    return {'ip': item['ip'], 'name': name, 'maker': maker, 'type': kind}


def default_gateway():
    try:
        if sys.platform == 'win32':
            out = subprocess.run(['ipconfig'], capture_output=True, timeout=10,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.decode('cp866', 'replace')
            match = re.search(r'(?:Default Gateway|Основной шлюз)[ .]*:\s*(\d+\.\d+\.\d+\.\d+)', out)
        elif sys.platform == 'darwin':
            out = subprocess.run(['route', '-n', 'get', 'default'], capture_output=True, text=True, timeout=10).stdout
            match = re.search(r'gateway:\s*(\d+\.\d+\.\d+\.\d+)', out)
        else:
            out = subprocess.run(['ip', 'route'], capture_output=True, text=True, timeout=10).stdout
            match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', out)
        if match:
            return match[1]
    except (OSError, subprocess.SubprocessError):
        pass
    return '192.168.1.1'


# ---------------- телевизоры ----------------
class LGTV:
    """webOS: WebSocket SSAP, порт 3000 (ws) или 3001 (wss). Первое подключение — «Разрешить» на экране ТВ."""
    PERMISSIONS = ['LAUNCH', 'LAUNCH_WEBAPP', 'APP_TO_APP', 'CONTROL_AUDIO', 'CONTROL_DISPLAY', 'CONTROL_INPUT_TV',
                   'CONTROL_POWER', 'CONTROL_TV_SCREEN', 'READ_APP_STATUS', 'READ_CURRENT_CHANNEL', 'READ_INSTALLED_APPS',
                   'READ_TV_CHANNEL_LIST', 'WRITE_NOTIFICATION_TOAST', 'CONTROL_INPUT_MEDIA_PLAYBACK',
                   'CONTROL_TV_STANBY', 'READ_SETTINGS', 'WRITE_SETTINGS']

    def __init__(self, config, save):
        self.config = config
        self.save = save   # (ключи) → сохранить client_key

    def _connect(self):
        import websocket  # websocket-client
        errors = []
        for url in (f"wss://{self.config['ip']}:3001", f"ws://{self.config['ip']}:3000"):
            try:
                return websocket.create_connection(url, timeout=6, sslopt={'cert_reqs': ssl.CERT_NONE})
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError('Телевизор LG не отвечает. Он включён и в той же сети? ' + '; '.join(errors)[:160])

    def _session(self, wait_pairing=60):
        ws = self._connect()
        payload = {'forcePairing': False, 'pairingType': 'PROMPT',
                   'manifest': {'manifestVersion': 1, 'appVersion': '1.1', 'permissions': self.PERMISSIONS,
                                'signed': {'appId': 'ru.andrey.assistant', 'vendorId': 'andrey', 'created': '20260101',
                                           'localizedAppNames': {'': 'Андрей'}, 'permissions': self.PERMISSIONS,
                                           'serial': 'andrey'}}}
        if self.config.get('client_key'):
            payload['client-key'] = self.config['client_key']
        ws.send(json.dumps({'type': 'register', 'id': 'register_0', 'payload': payload}))
        deadline = time.monotonic() + wait_pairing
        while time.monotonic() < deadline:
            message = json.loads(ws.recv())
            if message.get('type') == 'registered':
                key = message.get('payload', {}).get('client-key')
                if key and key != self.config.get('client_key'):
                    self.save({'client_key': key})
                return ws
            if message.get('type') == 'error':
                raise RuntimeError('Телевизор отклонил подключение: ' + str(message.get('error')))
        raise RuntimeError('Подтвердите подключение на экране телевизора и повторите.')

    def request(self, uri, payload=None):
        ws = self._session()
        try:
            ws.send(json.dumps({'type': 'request', 'id': 'req_1', 'uri': uri, 'payload': payload or {}}))
            for _ in range(10):
                message = json.loads(ws.recv())
                if message.get('id') == 'req_1':
                    if message.get('type') == 'error':
                        raise RuntimeError(str(message.get('error')))
                    return message.get('payload') or {}
        finally:
            ws.close()
        return {}

    def pair(self):
        ws = self._session(wait_pairing=60)
        ws.close()
        return 'Телевизор LG подключён.'

    def run(self, action, value):
        r = self.request
        if action == 'power':
            if value:
                return None  # включение — Wake-on-LAN (см. TVControl)
            r('ssap://system/turnOff')
            return 'Выключаю телевизор.'
        if action == 'volume':
            r('ssap://audio/setVolume', {'volume': value})
            return f'Громкость телевизора {value}.'
        if action == 'volume_step':
            r('ssap://audio/volumeUp' if value > 0 else 'ssap://audio/volumeDown')
            r('ssap://audio/volumeUp' if value > 0 else 'ssap://audio/volumeDown')
            return 'Громче.' if value > 0 else 'Тише.'
        if action == 'mute':
            r('ssap://audio/setMute', {'mute': bool(value)})
            return 'Звук выключен.' if value else 'Звук включён.'
        if action == 'channel':
            r('ssap://tv/openChannel', {'channelNumber': str(value)})
            return f'Включаю {value} канал.'
        if action == 'channel_step':
            r('ssap://tv/channelUp' if value > 0 else 'ssap://tv/channelDown')
            return 'Следующий канал.' if value > 0 else 'Предыдущий канал.'
        if action in ('pause', 'play'):
            r('ssap://media.controls/' + action)
            return 'Пауза.' if action == 'pause' else 'Продолжаю.'
        if action == 'picture':
            mode = {'кино': 'cinema', 'спор': 'sports', 'игра': 'game', 'игр': 'game', 'ярки': 'vivid', 'ярк': 'vivid',
                    'стан': 'standard', 'эко': 'eco'}.get(value, 'standard')
            r('ssap://com.webos.settingsservice/setSystemSettings', {'category': 'picture', 'settings': {'pictureMode': mode}})
            return 'Режим изображения переключён.'
        if action == 'app':
            apps = r('ssap://com.webos.applicationManager/listApps').get('apps', [])
            title, words, lg_id, *_ = TV_APPS[value]
            app = next((a for a in apps if lg_id in a.get('id', '').casefold() or
                        any(w in str(a.get('title', '')).casefold() for w in words + [title.casefold()])), None)
            if app is None:
                return f'На телевизоре нет приложения {title}.'
            r('ssap://system.launcher/launch', {'id': app['id']})
            return f'Открываю {title} на телевизоре.'
        if action == 'search':
            query, app = value
            url = SEARCH_LINKS.get(app, SEARCH_LINKS['youtube']).format(q=quote(query))
            if app == 'youtube':
                r('ssap://system.launcher/launch', {'id': 'youtube.leanback.v4', 'contentTarget': url})
            else:
                r('ssap://system.launcher/open', {'target': url})
            return f'Ищу «{query}» на телевизоре.'
        return None


class SamsungTV:
    """Tizen (2016+): WebSocket 8001/8002. Первое подключение — «Разрешить» на экране ТВ."""
    KEYS = {'volume_step': ('KEY_VOLUP', 'KEY_VOLDOWN'), 'channel_step': ('KEY_CHUP', 'KEY_CHDOWN')}

    def __init__(self, config, save):
        self.config = config
        self.save = save

    def _connect(self):
        import websocket
        name = base64.b64encode('Андрей'.encode()).decode()
        errors = []
        token = self.config.get('token')
        for url in (f"wss://{self.config['ip']}:8002/api/v2/channels/samsung.remote.control?name={name}" +
                    (f'&token={token}' if token else ''),
                    f"ws://{self.config['ip']}:8001/api/v2/channels/samsung.remote.control?name={name}"):
            try:
                ws = websocket.create_connection(url, timeout=8, sslopt={'cert_reqs': ssl.CERT_NONE})
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    message = json.loads(ws.recv())
                    if message.get('event') == 'ms.channel.connect':
                        new = (message.get('data') or {}).get('token')
                        if new and new != token:
                            self.save({'token': new})
                        return ws
                    if message.get('event') == 'ms.channel.unauthorized':
                        raise RuntimeError('Разрешите подключение на экране телевизора.')
            except RuntimeError:
                raise
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError('Телевизор Samsung не отвечает. ' + '; '.join(errors)[:160])

    def keys(self, *codes):
        ws = self._connect()
        try:
            for code in codes:
                ws.send(json.dumps({'method': 'ms.remote.control', 'params': {
                    'Cmd': 'Click', 'DataOfCmd': code, 'Option': 'false', 'TypeOfRemote': 'SendRemoteKey'}}))
                time.sleep(0.25)
        finally:
            ws.close()

    def pair(self):
        self._connect().close()
        return 'Телевизор Samsung подключён.'

    def run(self, action, value):
        if action == 'power':
            if value:
                return None
            self.keys('KEY_POWER')
            return 'Выключаю телевизор.'
        if action in self.KEYS:
            up, down = self.KEYS[action]
            self.keys(*([up if value > 0 else down] * (2 if action == 'volume_step' else 1)))
            return {'volume_step': 'Громче.' if value > 0 else 'Тише.',
                    'channel_step': 'Следующий канал.' if value > 0 else 'Предыдущий канал.'}[action]
        if action == 'mute':
            self.keys('KEY_MUTE')
            return 'Звук переключён.'
        if action == 'volume':
            self.keys(*(['KEY_VOLDOWN'] * 50 + ['KEY_VOLUP'] * value))
            return f'Громкость телевизора {value}.'
        if action == 'channel':
            self.keys(*[f'KEY_{d}' for d in str(value)] + ['KEY_ENTER'])
            return f'Включаю {value} канал.'
        if action in ('pause', 'play'):
            self.keys('KEY_PAUSE' if action == 'pause' else 'KEY_PLAY')
            return 'Пауза.' if action == 'pause' else 'Продолжаю.'
        if action in ('app', 'search'):
            app = value if action == 'app' else value[1]
            title, words, lg_id, android, samsung_id = TV_APPS.get(app, TV_APPS['youtube'])
            if not samsung_id:
                return f'Скажите «открой {title}» пультом: для Samsung я умею запускать YouTube и Netflix.'
            import requests
            requests.post(f"http://{self.config['ip']}:8001/api/v2/applications/{samsung_id}", timeout=8)
            return f'Открываю {title} на телевизоре.'
        if action == 'picture':
            return 'Режимы изображения Samsung переключаются пультом.'
        return None


class AndroidTV:
    """Android TV / Google TV через ADB по сети (Настройки ТВ → Для разработчиков → «Отладка по сети»)."""
    KEYCODES = {'mute': 'KEYCODE_VOLUME_MUTE', 'pause': 'KEYCODE_MEDIA_PAUSE', 'play': 'KEYCODE_MEDIA_PLAY'}

    def __init__(self, config, save, root=None):
        self.config = config
        self.save = save
        self.root = root

    def adb_path(self):
        name = 'adb.exe' if sys.platform == 'win32' else 'adb'
        if self.root:
            local = Path(self.root) / 'models' / 'platform-tools' / name
            if local.exists():
                return str(local)
        return shutil.which('adb')

    def adb(self, *args, timeout=15):
        adb = self.adb_path()
        if not adb:
            raise RuntimeError('Нужен ADB: Настройки → «Умный дом» → «Скачать ADB» (инструменты Android, бесплатно).')
        target = f"{self.config['ip']}:{self.config.get('port', 5555)}"
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        subprocess.run([adb, 'connect', target], capture_output=True, timeout=timeout, creationflags=flags)
        result = subprocess.run([adb, '-s', target, *args], capture_output=True, text=True, timeout=timeout,
                                creationflags=flags)
        if result.returncode != 0 or 'unauthorized' in (result.stderr + result.stdout):
            raise RuntimeError('Телевизор не разрешил подключение: подтвердите «Разрешить отладку» на экране ТВ.')
        return result.stdout

    def key(self, *codes):
        return self.adb('shell', 'input', 'keyevent', *codes)

    def pair(self):
        self.adb('shell', 'echo', 'ok')
        return 'Телевизор Android подключён.'

    def packages(self):
        return [line.split(':', 1)[1].strip() for line in self.adb('shell', 'pm', 'list', 'packages').splitlines()
                if line.startswith('package:')]

    def run(self, action, value):
        if action == 'power':
            if value:
                self.key('KEYCODE_WAKEUP')
                return 'Включаю телевизор.'
            self.key('KEYCODE_SLEEP')
            return 'Выключаю телевизор.'
        if action == 'volume_step':
            self.key(*(['KEYCODE_VOLUME_UP' if value > 0 else 'KEYCODE_VOLUME_DOWN'] * 2))
            return 'Громче.' if value > 0 else 'Тише.'
        if action == 'volume':
            for command in (['shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--set', str(value * 15 // 100)],
                            ['shell', 'media', 'volume', '--stream', '3', '--set', str(value * 15 // 100)]):
                try:
                    self.adb(*command)
                    return f'Громкость телевизора {value}.'
                except RuntimeError:
                    continue
            return 'Этот телевизор не даёт задать громкость числом — скажите «громче» или «тише».'
        if action == 'mute' or action in ('pause', 'play'):
            self.key(self.KEYCODES['mute' if action == 'mute' else action])
            return {'mute': 'Звук переключён.', 'pause': 'Пауза.', 'play': 'Продолжаю.'}[action]
        if action == 'channel':
            self.key(*[f'KEYCODE_{d}' for d in str(value)])
            return f'Включаю {value} канал.'
        if action == 'channel_step':
            self.key('KEYCODE_CHANNEL_UP' if value > 0 else 'KEYCODE_CHANNEL_DOWN')
            return 'Следующий канал.' if value > 0 else 'Предыдущий канал.'
        if action == 'app':
            title, words, lg_id, android_hint, _ = TV_APPS[value]
            package = next((p for p in self.packages() if android_hint in p.casefold()), None)
            if package is None:
                return f'На телевизоре нет приложения {title}.'
            self.adb('shell', 'monkey', '-p', package, '-c', 'android.intent.category.LEANBACK_LAUNCHER', '1')
            return f'Открываю {title} на телевизоре.'
        if action == 'search':
            query, app = value
            url = SEARCH_LINKS.get(app, SEARCH_LINKS['youtube']).format(q=quote(query))
            self.adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', url)
            return f'Ищу «{query}» на телевизоре.'
        if action == 'picture':
            return 'Режим изображения на Android TV переключается в настройках телевизора.'
        return None


# ---------------- лампочки и «Дом с Алисой» ----------------
class YandexHome:
    """«Дом с Алисой»: все устройства аккаунта Яндекса (лампы, розетки, телевизоры с Алисой)."""

    def __init__(self, token, session):
        self.token = token
        self.session = session

    def _headers(self):
        return {'Authorization': 'Bearer ' + self.token}

    def devices(self):
        response = self.session.get(YANDEX_IOT + '/user/info', headers=self._headers(), timeout=15)
        if response.status_code == 401:
            raise RuntimeError('Токен «Дома с Алисой» устарел — получите новый в Настройки → «Умный дом».')
        response.raise_for_status()
        data = response.json()
        rooms = {r['id']: r.get('name', '') for r in data.get('rooms', [])}
        return [{'id': d['id'], 'name': d.get('name', ''), 'room': rooms.get(d.get('room'), ''), 'type': d.get('type', ''),
                 'provider': 'yandex'} for d in data.get('devices', [])]

    def act(self, ids, action, value=None):
        if action in ('on', 'off'):
            capability = {'type': 'devices.capabilities.on_off', 'state': {'instance': 'on', 'value': action == 'on'}}
        elif action == 'brightness':
            capability = {'type': 'devices.capabilities.range', 'state': {'instance': 'brightness', 'value': value}}
        elif action == 'color':
            r, g, b = value
            capability = {'type': 'devices.capabilities.color_setting', 'state': {'instance': 'rgb', 'value': (r << 16) + (g << 8) + b}}
        elif action == 'temperature':
            capability = {'type': 'devices.capabilities.color_setting', 'state': {'instance': 'temperature_k', 'value': value}}
        elif action == 'volume':
            capability = {'type': 'devices.capabilities.range', 'state': {'instance': 'volume', 'value': value}}
        elif action == 'volume_step':
            capability = {'type': 'devices.capabilities.range', 'state': {'instance': 'volume', 'value': 5 * value, 'relative': True}}
        elif action == 'channel':
            capability = {'type': 'devices.capabilities.range', 'state': {'instance': 'channel', 'value': value}}
        elif action == 'channel_step':
            capability = {'type': 'devices.capabilities.range', 'state': {'instance': 'channel', 'value': value, 'relative': True}}
        elif action == 'mute':
            capability = {'type': 'devices.capabilities.toggle', 'state': {'instance': 'mute', 'value': bool(value)}}
        elif action in ('pause', 'play'):
            capability = {'type': 'devices.capabilities.toggle', 'state': {'instance': 'pause', 'value': action == 'pause'}}
        else:
            return False
        body = {'devices': [{'id': i, 'actions': [capability]} for i in ids]}
        response = self.session.post(YANDEX_IOT + '/devices/actions', headers=self._headers(), json=body, timeout=15)
        response.raise_for_status()
        return True


class HomeAssistant:
    def __init__(self, url, token, session):
        self.url = url.rstrip('/')
        self.token = token
        self.session = session

    def _headers(self):
        return {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}

    def devices(self):
        response = self.session.get(self.url + '/api/states', headers=self._headers(), timeout=15)
        response.raise_for_status()
        result = []
        for state in response.json():
            entity = state.get('entity_id', '')
            if entity.startswith(('light.', 'switch.')):
                attrs = state.get('attributes', {})
                result.append({'id': entity, 'name': attrs.get('friendly_name', entity), 'room': attrs.get('area', ''),
                               'type': 'devices.types.light', 'provider': 'homeassistant'})
        return result

    def act(self, ids, action, value=None):
        for entity in ids:
            domain = entity.split('.', 1)[0]
            service = 'turn_off' if action == 'off' else 'turn_on'
            data = {'entity_id': entity}
            if domain == 'light':
                if action == 'brightness':
                    data['brightness_pct'] = value
                elif action == 'color':
                    data['rgb_color'] = list(value)
                elif action == 'temperature':
                    data['color_temp_kelvin'] = value
            elif action not in ('on', 'off'):
                continue
            self.session.post(f'{self.url}/api/services/{domain}/{service}', headers=self._headers(), json=data,
                              timeout=15).raise_for_status()
        return True


def rgb_to_xy(rgb):
    r, g, b = [c / 255 for c in rgb]
    r, g, b = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in (r, g, b)]
    x = r * 0.664511 + g * 0.154324 + b * 0.162028
    y = r * 0.283881 + g * 0.668433 + b * 0.047685
    z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = x + y + z or 1
    return [round(x / total, 4), round(y / total, 4)]


class Hue:
    def __init__(self, bridge, username, session):
        self.bridge = bridge
        self.username = username
        self.session = session

    @staticmethod
    def discover(session):
        try:
            return [b['internalipaddress'] for b in session.get('https://discovery.meethue.com/', timeout=8).json()]
        except Exception:
            return []

    @staticmethod
    def pair(bridge, session):
        data = session.post(f'http://{bridge}/api', json={'devicetype': 'andrey#pc'}, timeout=8).json()
        item = data[0] if isinstance(data, list) and data else {}
        if 'success' in item:
            return item['success']['username']
        raise RuntimeError('Нажмите круглую кнопку на мосте Hue и в течение 30 секунд нажмите «Подключить».')

    def devices(self):
        base = f'http://{self.bridge}/api/{self.username}'
        lights = self.session.get(base + '/lights', timeout=8).json()
        groups = self.session.get(base + '/groups', timeout=8).json()
        room_of = {}
        for group in groups.values() if isinstance(groups, dict) else []:
            for light_id in group.get('lights', []):
                room_of[light_id] = group.get('name', '')
        return [{'id': k, 'name': v.get('name', k), 'room': room_of.get(k, ''), 'type': 'devices.types.light',
                 'provider': 'hue'} for k, v in (lights.items() if isinstance(lights, dict) else [])]

    def act(self, ids, action, value=None):
        state = {'on': action != 'off'}
        if action == 'brightness':
            state['bri'] = max(1, round(value * 254 / 100))
        elif action == 'color':
            state['xy'] = rgb_to_xy(value)
        elif action == 'temperature':
            state['ct'] = max(153, min(500, round(1_000_000 / value)))
        for light_id in ids:
            self.session.put(f'http://{self.bridge}/api/{self.username}/lights/{light_id}/state', json=state, timeout=8)
        return True


class Yeelight:
    """Лампы Yeelight: «Управление по локальной сети» в приложении Yeelight."""

    def __init__(self, bulbs):
        self.bulbs = bulbs   # [{'ip', 'name'}]

    @staticmethod
    def discover(timeout=2.0):
        message = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1982\r\nMAN: "ssdp:discover"\r\nST: wifi_bulb\r\n\r\n')
        found = {}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.settimeout(0.3)
            sock.sendto(message.encode(), ('239.255.255.250', 1982))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, (ip, _) = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                name = re.search(r'name: *(.*)', data.decode('utf-8', 'replace'))
                found[ip] = {'ip': ip, 'name': (name[1].strip() if name else '') or f'Yeelight {ip}'}
        return list(found.values())

    def devices(self):
        return [{'id': b['ip'], 'name': b.get('name') or b['ip'], 'room': b.get('room', ''), 'type': 'devices.types.light',
                 'provider': 'yeelight'} for b in self.bulbs]

    @staticmethod
    def command(ip, method, params):
        with socket.create_connection((ip, 55443), timeout=4) as sock:
            sock.sendall((json.dumps({'id': 1, 'method': method, 'params': params}) + '\r\n').encode())
            return sock.recv(1024)

    def act(self, ids, action, value=None):
        for ip in ids:
            if action in ('on', 'off'):
                self.command(ip, 'set_power', [action, 'smooth', 400])
            elif action == 'brightness':
                self.command(ip, 'set_bright', [value, 'smooth', 400])
            elif action == 'color':
                r, g, b = value
                self.command(ip, 'set_rgb', [(r << 16) + (g << 8) + b, 'smooth', 400])
            elif action == 'temperature':
                self.command(ip, 'set_ct_abx', [max(1700, min(6500, value)), 'smooth', 400])
        return True


# ---------------- роутеры ----------------
class Keenetic:
    def __init__(self, config, session):
        self.base = 'http://' + config['address'].replace('http://', '').rstrip('/')
        self.login = config.get('login', 'admin')
        self.password = config.get('password', '')
        self.session = session
        self.authorized = False

    def auth(self):
        response = self.session.get(self.base + '/auth', timeout=8)
        if response.status_code == 200:
            self.authorized = True
            return
        realm, challenge = response.headers.get('X-NDM-Realm', ''), response.headers.get('X-NDM-Challenge', '')
        md5 = hashlib.md5(f'{self.login}:{realm}:{self.password}'.encode()).hexdigest()
        digest = hashlib.sha256((challenge + md5).encode()).hexdigest()
        result = self.session.post(self.base + '/auth', json={'login': self.login, 'password': digest}, timeout=8)
        if result.status_code != 200:
            raise RuntimeError('Роутер Keenetic не принял логин или пароль.')
        self.authorized = True

    def rci(self, path, body=None):
        if not self.authorized:
            self.auth()
        url = self.base + '/rci/' + path.lstrip('/')
        response = self.session.post(url, json=body, timeout=15) if body is not None else self.session.get(url, timeout=15)
        response.raise_for_status()
        return response.json() if response.content else {}

    def devices(self):
        hosts = self.rci('show/ip/hotspot').get('host', [])
        return [{'name': h.get('name') or h.get('hostname') or h.get('mac'), 'ip': h.get('ip', ''), 'mac': h.get('mac', ''),
                 'active': bool(h.get('active'))} for h in hosts]

    def reboot(self):
        self.rci('system/reboot', {})

    def block(self, mac, deny=True):
        self.rci('', {'ip': {'hotspot': {'host': {'mac': mac, 'access': 'deny' if deny else 'permit'}}}})


class MikroTik:
    def __init__(self, config, session):
        address = config['address'].rstrip('/')
        self.base = address if address.startswith('http') else 'https://' + address
        self.auth = (config.get('login', 'admin'), config.get('password', ''))
        self.session = session

    def devices(self):
        response = self.session.get(self.base + '/rest/ip/dhcp-server/lease', auth=self.auth, timeout=15, verify=False)
        response.raise_for_status()
        return [{'name': l.get('host-name') or l.get('comment') or l.get('mac-address'), 'ip': l.get('address', ''),
                 'mac': l.get('mac-address', ''), 'active': l.get('status') == 'bound'} for l in response.json()]

    def reboot(self):
        self.session.post(self.base + '/rest/system/reboot', auth=self.auth, json={}, timeout=15, verify=False)

    def block(self, mac, deny=True):
        raise RuntimeError('Блокировка устройств на MikroTik настраивается в WinBox (Firewall).')


# ---------------- хаб ----------------
class SmartHome:
    def __init__(self, store, opener=None, session=None, clock=time.monotonic):
        self.store = store
        self.opener = opener
        self._session = session
        self.clock = clock
        self.pending = {}
        self.lock = threading.Lock()

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    # ---- настройки ----
    def config(self):
        try:
            return json.loads(self.store.meta('smarthome') or '{}')
        except ValueError:
            return {}

    def save(self, section, data):
        if section not in ('tv', 'router', 'lights'):
            raise ValueError('Неизвестный раздел')
        with self.lock:
            config = self.config()
            current = config.get(section, {})
            for key, value in (data or {}).items():
                if is_secret(key) and value in ('', None, '••••••'):
                    continue  # пустое поле пароля в форме — «не менять»
                current[key] = value
            config[section] = current
            self.store.set_meta('smarthome', json.dumps(config, ensure_ascii=False))
        return self.public()

    def public(self):
        """Для окна настроек: без паролей и токенов, только признак «задан»."""
        result = {}
        for section, values in self.config().items():
            result[section] = {k: ('••••••' if is_secret(k) and v else v) for k, v in values.items()}
        return result

    # ---- устройства ----
    def tv(self):
        config = self.config().get('tv') or {}
        kind = config.get('type')
        save = lambda data: self.save('tv', data)  # noqa: E731
        if kind == 'lg' and config.get('ip'):
            return LGTV(config, save)
        if kind == 'samsung' and config.get('ip'):
            return SamsungTV(config, save)
        if kind == 'android' and config.get('ip'):
            return AndroidTV(config, save, self.store.root)
        if kind == 'yandex':
            return _YandexTV(self, config)
        return None

    def light_providers(self):
        lights = self.config().get('lights') or {}
        providers = []
        if lights.get('yandex_token'):
            providers.append(YandexHome(lights['yandex_token'], self.session))
        if lights.get('ha_url') and lights.get('ha_token'):
            providers.append(HomeAssistant(lights['ha_url'], lights['ha_token'], self.session))
        if lights.get('hue_bridge') and lights.get('hue_username'):
            providers.append(Hue(lights['hue_bridge'], lights['hue_username'], self.session))
        if lights.get('yeelight'):
            providers.append(Yeelight(lights['yeelight']))
        return providers

    def router(self):
        config = self.config().get('router') or {}
        if not config.get('address'):
            return None
        if config.get('type') == 'mikrotik':
            return MikroTik(config, self.session)
        if config.get('type') == 'keenetic':
            return Keenetic(config, self.session)
        return None

    # ---- голос ----
    def awaiting(self, owner):
        item = self.pending.get(owner)
        return bool(item and item[1] > self.clock())

    def handle(self, text, owner='default'):
        lower = re.sub(r'[.!?,]+', '', str(text).casefold()).strip()
        pending = self.pending.get(owner)
        if pending and pending[1] > self.clock():
            self.pending.pop(owner)
            if re.match(r'^(?:да|давай|подтверждаю|перезагружай|отключай|конечно)\b', lower):
                return pending[0]()
            if re.match(r'^(?:нет|не надо|отмена|стоп)\b', lower):
                return 'Хорошо, не трогаю.'
        config = self.config()
        try:
            if config.get('tv'):
                request = parse_tv(text)
                if request is not None:
                    return self.tv_command(*request)
            if config.get('lights'):
                request = parse_lights(text)
                if request is not None:
                    return self.lights_command(*request)
            request = parse_router(text)
            if request is not None and (config.get('router') or request[0] in ('open', 'check')):
                return self.router_command(owner, *request)
        except RuntimeError as exc:
            return str(exc)
        except Exception as exc:
            log.exception('Smart home command failed')
            return f'Устройство не ответило: {str(exc)[:120]}'
        return None

    def tv_command(self, action, value):
        config = self.config().get('tv') or {}
        tv = self.tv()
        if action == 'power' and value:
            if config.get('mac'):
                wake_on_lan(config['mac'])
                if isinstance(tv, AndroidTV):
                    try:
                        tv.run('power', True)
                    except RuntimeError:
                        pass
                return 'Включаю телевизор.'
            if tv is not None and not isinstance(tv, (LGTV, SamsungTV)):
                return tv.run('power', True)
            return 'Чтобы включать телевизор, укажите его MAC-адрес: Настройки → «Умный дом».'
        if tv is None:
            return 'Телевизор не подключён: Настройки → «Умный дом» → «Телевизор».'
        return tv.run(action, value) or 'Готово.'

    def _lights(self, where):
        devices = []
        for provider in self.light_providers():
            for device in provider.devices():
                if device['type'] not in ('devices.types.light', 'devices.types.light.ceiling', 'devices.types.light.lamp',
                                          'devices.types.light.strip', 'devices.types.socket') and \
                        not device['type'].startswith('devices.types.light'):
                    continue
                if where in ('', '*') or name_matches(where, device['name']) or name_matches(where, device['room']):
                    devices.append((provider, device))
        return devices

    def lights_command(self, action, value):
        if action in ('on', 'off'):
            where, amount = value, None
        else:
            amount, where = value
        found = self._lights(where)
        if not found:
            return f'Не нашёл свет «{where}».' if where not in ('', '*') else \
                'Лампы не подключены: Настройки → «Умный дом» → «Освещение».'
        by_provider = {}
        for provider, device in found:
            by_provider.setdefault(id(provider), (provider, []))[1].append(device['id'])
        if action == 'brightness_step':
            action, amount = 'brightness', 80 if amount > 0 else 30
        for provider, ids in by_provider.values():
            provider.act(ids, action, amount)
        place = '' if where in ('', '*') else f' ({where})'
        return {'on': 'Включаю свет', 'off': 'Выключаю свет', 'brightness': f'Яркость {amount}%',
                'color': 'Меняю цвет', 'temperature': 'Меняю оттенок'}[action] + place + '.'

    def router_command(self, owner, action, value):
        router = self.router()
        if action == 'open':
            address = (self.config().get('router') or {}).get('address') or default_gateway()
            if self.opener:
                self.opener(address if address.startswith('http') else 'http://' + address)
            return 'Открываю настройки роутера.'
        if action == 'check':
            return _internet_check()
        if router is None:
            return 'Роутер не подключён: Настройки → «Умный дом» → «Роутер».'
        if action == 'devices':
            devices = router.devices()
            active = [d for d in devices if d['active']]
            names = ', '.join(d['name'] for d in active[:8])
            return f'Сейчас в сети {len(active)} устройств: {names}.' if active else 'Сейчас в сети нет активных устройств.'
        if action == 'reboot':
            self.pending[owner] = (lambda: (router.reboot(), 'Перезагружаю роутер — интернет пропадёт на пару минут.')[1],
                                   self.clock() + CONFIRM_SECONDS)
            return 'Перезагрузить роутер? Интернет пропадёт на 1–2 минуты. Скажите «да».'
        devices = router.devices()
        match = next((d for d in devices if name_matches(value, d['name'] or '')), None)
        if match is None:
            return f'Не нашёл устройство «{value}» в сети.'
        if action == 'block':
            self.pending[owner] = (lambda: (router.block(match['mac'], True), f'Отключил интернет у «{match["name"]}».')[1],
                                   self.clock() + CONFIRM_SECONDS)
            return f'Отключить интернет у «{match["name"]}»? Скажите «да».'
        router.block(match['mac'], False)
        return f'Вернул интернет «{match["name"]}».'

    # ---- настройка из окна ----
    def discover(self, what):
        if what == 'tv':
            return [describe_tv(item, self.session) for item in ssdp_search()]
        if what == 'hue':
            return [{'ip': ip, 'name': 'Мост Philips Hue'} for ip in Hue.discover(self.session)]
        if what == 'yeelight':
            return Yeelight.discover()
        if what == 'router':
            return [{'ip': default_gateway(), 'name': 'Роутер (основной шлюз)'}]
        raise ValueError('Неизвестное устройство')

    def pair(self, what):
        if what == 'tv':
            tv = self.tv()
            if tv is None or not hasattr(tv, 'pair'):
                raise ValueError('Сначала выберите тип телевизора и адрес.')
            return tv.pair()
        if what == 'hue':
            bridge = (self.config().get('lights') or {}).get('hue_bridge')
            if not bridge:
                raise ValueError('Укажите адрес моста Hue.')
            self.save('lights', {'hue_username': Hue.pair(bridge, self.session)})
            return 'Мост Philips Hue подключён.'
        raise ValueError('Неизвестное устройство')

    def test(self, what):
        if what == 'lights':
            names = [d['name'] for provider in self.light_providers() for d in provider.devices()]
            return f'Найдено устройств: {len(names)}. ' + ', '.join(names[:10])
        if what == 'router':
            router = self.router()
            if router is None:
                raise ValueError('Роутер не настроен.')
            return f'Устройств в сети: {len([d for d in router.devices() if d["active"]])}.'
        if what == 'tv':
            return self.pair('tv')
        raise ValueError('Неизвестное устройство')


class _YandexTV:
    """Телевизор из «Дома с Алисой» (Яндекс ТВ, телевизоры с Алисой)."""

    def __init__(self, hub, config):
        self.hub = hub
        self.config = config

    def run(self, action, value):
        token = (self.hub.config().get('lights') or {}).get('yandex_token') or self.config.get('token')
        if not token:
            raise RuntimeError('Подключите «Дом с Алисой»: Настройки → «Умный дом» → «Освещение».')
        home = YandexHome(token, self.hub.session)
        tvs = [d for d in home.devices() if 'media_device' in d['type'] or 'tv' in d['type']]
        if self.config.get('name'):
            tvs = [d for d in tvs if name_matches(self.config['name'], d['name'])] or tvs
        if not tvs:
            raise RuntimeError('В «Доме с Алисой» нет телевизора.')
        mapping = {'power': ('on' if value else 'off', None)}
        act, arg = mapping.get(action, (action, value))
        if not home.act([tvs[0]['id']], act, arg):
            return 'Этот телевизор через «Дом с Алисой» так не умеет.'
        return 'Готово.'


def _internet_check():
    started = time.monotonic()
    for host in ('ya.ru', '1.1.1.1'):
        try:
            socket.create_connection((host, 443), timeout=3).close()
            return f'Интернет работает, отклик {int((time.monotonic() - started) * 1000)} мс.'
        except OSError:
            continue
    return 'Интернета нет. Проверьте роутер — могу перезагрузить: «перезагрузи роутер».'


def download_adb(root, session=None, progress=None):
    """Инструменты Android (ADB) от Google — для Android TV. Скачиваются по кнопке, ≈10 МБ."""
    import io
    import zipfile
    from .model_downloader import _session
    platform = 'windows' if sys.platform == 'win32' else 'darwin' if sys.platform == 'darwin' else 'linux'
    url = f'https://dl.google.com/android/repository/platform-tools-latest-{platform}.zip'
    session = _session(session)
    response = session.get(url, timeout=120)
    response.raise_for_status()
    target = Path(root) / 'models'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(target)
    adb = target / 'platform-tools' / ('adb.exe' if platform == 'windows' else 'adb')
    if platform != 'windows' and adb.exists():
        adb.chmod(0o755)
    return adb
