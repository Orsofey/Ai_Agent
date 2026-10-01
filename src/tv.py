"""Телевизоры: поиск в домашней сети без кодов и управление Xiaomi / Android TV / Google TV без режима разработчика.

Поиск (одной кнопкой «Найти телевизоры») идёт тремя путями сразу:
  1) mDNS — так о себе сообщают Android TV / Google TV / Xiaomi со встроенным Chromecast (_googlecast._tcp,
     _androidtvremote2._tcp) — запрос уходит с КАЖДОГО сетевого адаптера ПК (иначе на Windows с VPN/Hyper-V ответы
     теряются);
  2) SSDP/DIAL — LG, Samsung, Sony, Philips и многие Android TV;
  3) быстрый опрос всех адресов домашней сети по портам телевизоров (Cast 8009, Xiaomi 6095, LG 3000/3001,
     Samsung 8001/8002, ADB 5555) — находит телевизор, даже если роутер режет мультикаст.
MAC-адрес для включения (Wake-on-LAN) берётся из ARP-таблицы ПК автоматически.

Управление без кодов:
  - Xiaomi Mi TV (PatchWall): встроенный сервис на порту 6095 — питание, громкость, стрелки/ОК/назад/домой, запуск
    приложений; громкость числом и звук — через Cast.
  - Android TV / Google TV с Chromecast: протокол Google Cast (порт 8009) — громкость числом, звук, YouTube и
    приложения с Cast; конкретное видео YouTube — по DIAL. Включение — Wake-on-LAN. Если на ТВ включена
    «Отладка по сети», дополнительно работают ADB-команды (выключение, каналы, любые приложения).
"""
import concurrent.futures
import ipaddress
import json
import logging
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import quote

log = logging.getLogger(__name__)

TV_PORTS = {8009: 'cast', 6095: 'xiaomi', 3000: 'lg', 3001: 'lg', 8001: 'samsung', 8002: 'samsung', 5555: 'adb',
            6466: 'atv'}
SCAN_PORTS = (8009, 6095, 3000, 3001, 8001, 8002, 6466)
MDNS_SERVICES = ('_googlecast._tcp.local', '_androidtvremote2._tcp.local')
YOUTUBE_APP = '233637DE'
CAST_APPS = {'youtube': YOUTUBE_APP, 'netflix': 'CA5E8412'}


# ---------------- сеть ПК ----------------
def local_ipv4s():
    """IPv4 этого ПК в домашних сетях (у каждого адаптера свой)."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    for probe in ('192.168.0.1', '192.168.1.1', '10.0.0.1', '172.16.0.1'):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((probe, 9))          # пакет не отправляется — только выбор маршрута
                found.add(sock.getsockname()[0])
        except OSError:
            pass
    result = []
    for ip in found:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if address.is_private and not address.is_loopback and not address.is_link_local:
            result.append(ip)
    return sorted(result)


def arp_table():
    """{ip: mac} из ARP-таблицы ПК."""
    table = {}
    try:
        if sys.platform.startswith('linux'):
            with open('/proc/net/arp', encoding='ascii') as fh:
                for line in fh.read().splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[3] != '00:00:00:00:00:00':
                        table[parts[0]] = parts[3].upper()
            return table
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        out = subprocess.run(['arp', '-a'], capture_output=True, timeout=8, creationflags=flags).stdout
        text = out.decode('cp866' if sys.platform == 'win32' else 'utf-8', 'replace')
        for ip, mac in re.findall(r'(\d+\.\d+\.\d+\.\d+)\)?\s+(?:at\s+)?([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})', text):
            parts = re.split(r'[:-]', mac)
            table[ip] = ':'.join(p.zfill(2) for p in parts).upper()
    except (OSError, subprocess.SubprocessError):
        pass
    return {ip: mac for ip, mac in table.items() if mac not in ('FF:FF:FF:FF:FF:FF',)}


# ---------------- mDNS ----------------
def _qname(name):
    return b''.join(bytes([len(p)]) + p.encode() for p in name.split('.') if p) + b'\x00'


def mdns_packet(services=MDNS_SERVICES):
    header = struct.pack('>HHHHHH', 0, 0, len(services), 0, 0, 0)
    return header + b''.join(_qname(s) + struct.pack('>HH', 12, 0x8001) for s in services)   # PTR, QU-бит


def _read_name(data, offset, depth=0):
    labels = []
    while offset < len(data) and depth < 20:
        length = data[offset]
        if length == 0:
            return '.'.join(labels), offset + 1
        if length & 0xC0 == 0xC0:
            pointer = struct.unpack('>H', data[offset:offset + 2])[0] & 0x3FFF
            name, _ = _read_name(data, pointer, depth + 1)
            labels.append(name)
            return '.'.join(x for x in labels if x), offset + 2
        labels.append(data[offset + 1:offset + 1 + length].decode('utf-8', 'replace'))
        offset += 1 + length
    return '.'.join(labels), offset


def parse_mdns(data):
    """Ответ mDNS → {'services': {...}, 'names': [...], 'txt': {...}, 'ips': [...]}."""
    result = {'services': set(), 'names': [], 'txt': {}, 'ips': []}
    try:
        _, flags, qd, an, ns, ar = struct.unpack('>HHHHHH', data[:12])
        offset = 12
        for _ in range(qd):
            _, offset = _read_name(data, offset)
            offset += 4
        for _ in range(an + ns + ar):
            name, offset = _read_name(data, offset)
            rtype, _, _, length = struct.unpack('>HHIH', data[offset:offset + 10])
            offset += 10
            body = data[offset:offset + length]
            if rtype == 12:                                  # PTR: сервис → экземпляр
                target, _ = _read_name(data, offset)
                for service in MDNS_SERVICES:
                    if name.casefold() == service.casefold():
                        result['services'].add(service)
                        result['names'].append(target[:-(len(service) + 1)] if target.endswith(service) else target)
            elif rtype == 16:                                # TXT
                i = 0
                while i < len(body):
                    size = body[i]
                    item = body[i + 1:i + 1 + size].decode('utf-8', 'replace')
                    key, _, value = item.partition('=')
                    result['txt'][key.casefold()] = value
                    i += 1 + size
            elif rtype == 1 and length == 4:                 # A
                result['ips'].append(socket.inet_ntoa(body))
            offset += length
    except (struct.error, IndexError):
        pass
    return result


def mdns_search(interfaces=None, timeout=2.0):
    """{ip: {'services', 'name', 'model', 'maker'}} по ответам mDNS со всех адаптеров."""
    found = {}
    sockets = []
    for ip in interfaces or local_ipv4s() or ['0.0.0.0']:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((ip, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            if ip != '0.0.0.0':
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            sock.setblocking(False)
            sock.sendto(mdns_packet(), ('224.0.0.251', 5353))
            sockets.append(sock)
        except OSError as exc:
            log.info('mDNS on %s: %s', ip, exc)
    deadline = time.monotonic() + timeout
    import select
    while sockets and time.monotonic() < deadline:
        ready, _, _ = select.select(sockets, [], [], max(0.05, deadline - time.monotonic()))
        for sock in ready:
            try:
                data, (sender, _) = sock.recvfrom(9000)
            except OSError:
                continue
            info = parse_mdns(data)
            if not info['services']:
                continue
            item = found.setdefault(sender, {'services': set(), 'name': '', 'model': '', 'maker': ''})
            item['services'] |= info['services']
            item['name'] = info['txt'].get('fn') or item['name'] or (info['names'][0] if info['names'] else '')
            item['model'] = info['txt'].get('md') or item['model']
    for sock in sockets:
        sock.close()
    return found


# ---------------- SSDP с каждого адаптера ----------------
def ssdp_search(interfaces=None, timeout=2.5,
                targets=('urn:dial-multiscreen-org:service:dial:1', 'urn:schemas-upnp-org:device:MediaRenderer:1',
                         'urn:schemas-upnp-org:device:tvdevice:1', 'urn:samsung.com:device:RemoteControlReceiver:1')):
    found = {}
    sockets = []
    for ip in interfaces or local_ipv4s() or ['0.0.0.0']:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.bind((ip, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if ip != '0.0.0.0':
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            sock.setblocking(False)
            for target in targets:
                sock.sendto((f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
                             f'ST: {target}\r\n\r\n').encode(), ('239.255.255.250', 1900))
            sockets.append(sock)
        except OSError as exc:
            log.info('SSDP on %s: %s', ip, exc)
    deadline = time.monotonic() + timeout
    import select
    while sockets and time.monotonic() < deadline:
        ready, _, _ = select.select(sockets, [], [], max(0.05, deadline - time.monotonic()))
        for sock in ready:
            try:
                data, (sender, _) = sock.recvfrom(4096)
            except OSError:
                continue
            headers = {k.strip().casefold(): v.strip() for k, _, v in
                       (line.partition(':') for line in data.decode('utf-8', 'replace').split('\r\n')[1:]) if k}
            found.setdefault(sender, {'ip': sender, 'location': headers.get('location', ''),
                                      'server': headers.get('server', '')})
    for sock in sockets:
        sock.close()
    return found


# ---------------- опрос портов ----------------
def port_open(ip, port, timeout=0.4):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((ip, port)) == 0


def port_scan(interfaces=None, ports=SCAN_PORTS, workers=160, timeout=0.4):
    """{ip: [порты]} по всем адресам /24 каждого адаптера ПК."""
    hosts = []
    own = set(interfaces or local_ipv4s())
    for ip in own:
        net = ipaddress.ip_network(ip + '/24', strict=False)
        hosts += [str(h) for h in net.hosts() if str(h) not in own]
    found = {}
    lock = threading.Lock()

    def probe(job):
        host, port = job
        if port_open(host, port, timeout):
            with lock:
                found.setdefault(host, []).append(port)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(probe, [(h, p) for h in hosts for p in ports]))
    return {ip: sorted(ports) for ip, ports in found.items()}


# ---------------- опознание ----------------
def eureka(ip, session):
    """Имя и производитель Cast-устройства (Android TV / Google TV)."""
    try:
        data = session.get(f'http://{ip}:8008/setup/eureka_info?params=name,device_info', timeout=2).json()
        info = data.get('device_info') or {}
        return {'name': data.get('name', ''), 'maker': info.get('manufacturer', ''), 'model': info.get('model_name', '')}
    except Exception:
        return {}


def xiaomi_alive(ip, session):
    try:
        response = session.get(f'http://{ip}:6095/request?action=isalive', timeout=2)
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            data = {}
        inner = data.get('data') if isinstance(data.get('data'), dict) else {}
        return {'name': inner.get('devicename') or inner.get('name') or '', 'model': inner.get('model', '')}
    except Exception:
        return None


def upnp_description(location, session):
    try:
        xml = session.get(location, timeout=3).text
    except Exception:
        return {}
    pick = lambda tag: (re.search(f'<{tag}>(.*?)</{tag}>', xml) or [None, ''])[1]  # noqa: E731
    return {'name': pick('friendlyName'), 'maker': pick('manufacturer'), 'model': pick('modelName')}


def classify(item):
    """Тип: xiaomi | android | lg | samsung | unknown."""
    text = f"{item.get('maker', '')} {item.get('model', '')} {item.get('name', '')} {item.get('server', '')}".casefold()
    ports = set(item.get('ports') or [])
    if 6095 in ports:
        return 'xiaomi'
    if re.search(r'\blg\b|webos|lge', text) or ports & {3000, 3001}:
        return 'lg'
    if re.search(r'samsung|tizen', text) or ports & {8001, 8002}:
        return 'samsung'
    if item.get('cast') or ports & {8009, 6466, 5555} or re.search(r'android|google|xiaomi|mitv|sony|philips|tcl|haier|'
                                                                    r'hisense|sber|kivi|bravia|nvidia|chromecast', text):
        return 'android'
    return 'unknown'


def discover(session, scan=True, timeout=2.5):
    """Все телевизоры в домашней сети: [{'ip', 'name', 'type', 'maker', 'model', 'mac', 'cast', 'ports'}]."""
    interfaces = local_ipv4s()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        mdns_job = pool.submit(mdns_search, interfaces, timeout)
        ssdp_job = pool.submit(ssdp_search, interfaces, timeout)
        scan_job = pool.submit(port_scan, interfaces) if scan and interfaces else None
        mdns, ssdp = mdns_job.result(), ssdp_job.result()
        ports = scan_job.result() if scan_job else {}
    items = {}
    for ip, info in mdns.items():
        items[ip] = {'ip': ip, 'name': info['name'], 'model': info['model'], 'maker': '', 'cast': True,
                     'ports': ports.get(ip, [])}
    for ip, info in ssdp.items():
        item = items.setdefault(ip, {'ip': ip, 'name': '', 'model': '', 'maker': '', 'cast': False, 'ports': ports.get(ip, [])})
        item['server'] = info.get('server', '')
        if info.get('location') and not item['name']:
            item.update({k: v for k, v in upnp_description(info['location'], session).items() if v})
    for ip, open_ports in ports.items():
        item = items.setdefault(ip, {'ip': ip, 'name': '', 'model': '', 'maker': '', 'cast': 8009 in open_ports,
                                     'ports': open_ports})
        item['ports'] = sorted(set(item['ports']) | set(open_ports))
        item['cast'] = item['cast'] or 8009 in open_ports
    for item in items.values():
        if 6095 in item['ports'] or (not item['ports'] and re.search(r'xiaomi|mitv', item.get('name', '') + item.get('model', ''), re.I)):
            alive = xiaomi_alive(item['ip'], session)
            if alive is not None:
                item['ports'] = sorted(set(item['ports']) | {6095})
                item['maker'] = item['maker'] or 'Xiaomi'
                item['name'] = item['name'] or alive['name']
                item['model'] = item['model'] or alive['model']
        if item['cast'] and not item['name']:
            item.update({k: v for k, v in eureka(item['ip'], session).items() if v})
        item['type'] = classify(item)
        if not item['name']:
            item['name'] = {'xiaomi': 'Xiaomi Mi TV', 'android': 'Android TV', 'lg': 'LG', 'samsung': 'Samsung'}.get(
                item['type'], 'Устройство') + f" ({item['ip']})"
    macs = arp_table()            # после опроса ARP-таблица заполнена адресами телевизоров
    result = []
    for item in items.values():
        if item['type'] == 'unknown':
            continue
        item['mac'] = macs.get(item['ip'], '')
        result.append(item)
    return sorted(result, key=lambda i: tuple(int(x) for x in i['ip'].split('.')))


# ---------------- Google Cast ----------------
def _varint(value):
    out = bytearray()
    while True:
        bits = value & 0x7F
        value >>= 7
        out.append(bits | (0x80 if value else 0))
        if not value:
            return bytes(out)


def cast_message(source, destination, namespace, payload):
    """CastMessage (protobuf) вручную: версия, отправитель, получатель, пространство, строка JSON."""
    def field(number, text):
        raw = text.encode('utf-8')
        return bytes([number << 3 | 2]) + _varint(len(raw)) + raw
    body = (b'\x08\x00' + field(2, source) + field(3, destination) + field(4, namespace) + b'\x28\x00' +
            field(6, json.dumps(payload)))
    return struct.pack('>I', len(body)) + body


def parse_cast(body):
    fields, i = {}, 0
    while i < len(body):
        key = body[i]
        i += 1
        number, kind = key >> 3, key & 7
        if kind == 0:
            value = 0
            shift = 0
            while True:
                byte = body[i]
                i += 1
                value |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            fields[number] = value
        elif kind == 2:
            length = shift = 0
            while True:
                byte = body[i]
                i += 1
                length |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            fields[number] = body[i:i + length]
            i += length
        else:
            break
    return {'source': fields.get(2, b'').decode(), 'namespace': fields.get(4, b'').decode(),
            'payload': fields.get(6, b'').decode('utf-8', 'replace')}


class Cast:
    """Минимальный клиент Google Cast: громкость, звук, запуск приложений. Без пар и кодов."""
    RECEIVER = 'urn:x-cast:com.google.cast.receiver'
    CONNECTION = 'urn:x-cast:com.google.cast.tp.connection'
    HEARTBEAT = 'urn:x-cast:com.google.cast.tp.heartbeat'

    def __init__(self, ip, port=8009, timeout=6, connector=None):
        self.ip, self.port, self.timeout = ip, port, timeout
        self.connector = connector
        self.sock = None
        self.request_id = 0

    def __enter__(self):
        if self.connector is not None:
            self.sock = self.connector(self.ip, self.port)
        else:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE          # у телевизора самоподписанный сертификат
            raw = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            self.sock = context.wrap_socket(raw)
        self._send(self.CONNECTION, {'type': 'CONNECT'})
        return self

    def __exit__(self, *exc):
        try:
            self._send(self.CONNECTION, {'type': 'CLOSE'})
            self.sock.close()
        except Exception:
            pass

    def _send(self, namespace, payload, destination='receiver-0'):
        self.sock.sendall(cast_message('sender-0', destination, namespace, payload))

    def _read(self):
        head = self._exact(4)
        return parse_cast(self._exact(struct.unpack('>I', head)[0]))

    def _exact(self, size):
        data = b''
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError('Телевизор закрыл соединение')
            data += chunk
        return data

    def request(self, payload):
        self.request_id += 1
        payload = dict(payload, requestId=self.request_id)
        self._send(self.RECEIVER, payload)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            message = self._read()
            try:
                data = json.loads(message['payload'] or '{}')
            except ValueError:
                continue
            if message['namespace'] == self.HEARTBEAT and data.get('type') == 'PING':
                self._send(self.HEARTBEAT, {'type': 'PONG'})
                continue
            if data.get('requestId') == self.request_id:
                return data
        raise TimeoutError('Телевизор не ответил')

    def status(self):
        return (self.request({'type': 'GET_STATUS'}).get('status') or {})

    def volume(self):
        return (self.status().get('volume') or {}).get('level', 0.0)

    def set_volume(self, level):
        return self.request({'type': 'SET_VOLUME', 'volume': {'level': max(0.0, min(1.0, level))}})

    def mute(self, muted):
        return self.request({'type': 'SET_VOLUME', 'volume': {'muted': bool(muted)}})

    def launch(self, app_id):
        return self.request({'type': 'LAUNCH', 'appId': app_id})

    def stop(self):
        for app in self.status().get('applications') or []:
            if not app.get('isIdleScreen'):
                self.request({'type': 'STOP', 'sessionId': app.get('sessionId')})


def youtube_video(query):
    """ID первого видео YouTube по запросу (yt-dlp, без ключей)."""
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'extract_flat': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info('ytsearch1:' + query, download=False)
        entries = info.get('entries') or []
        return entries[0].get('id') if entries else None
    except Exception as exc:
        log.info('YouTube search failed: %s', exc)
        return None


def dial_youtube(ip, session, video_id):
    """Запустить видео YouTube на телевизоре по DIAL (без пар и кодов)."""
    for url in (f'http://{ip}:8008/apps/YouTube', f'http://{ip}:8080/apps/YouTube'):
        try:
            response = session.post(url, data=f'v={video_id}', timeout=6,
                                    headers={'Content-Type': 'text/plain; charset=utf-8'})
            if response.status_code in (200, 201, 204):
                return True
        except Exception:
            continue
    return False


# ---------------- Xiaomi Mi TV ----------------
class XiaomiTV:
    """Xiaomi Mi TV / Redmi TV (PatchWall): сервис на порту 6095 — без пар и кодов."""
    KEYS = {'ok': 'enter', 'назад': 'back', 'домой': 'home', 'вверх': 'up', 'вниз': 'down', 'влево': 'left',
            'вправо': 'right', 'меню': 'menu'}

    def __init__(self, config, session, cast_factory=Cast):
        self.config = config
        self.session = session
        self.cast_factory = cast_factory

    @property
    def base(self):
        return f"http://{self.config['ip']}:6095"

    def key(self, code, times=1):
        for _ in range(times):
            response = self.session.get(f'{self.base}/controller', params={'action': 'keyevent', 'keycode': code}, timeout=4)
            if response.status_code != 200:
                raise RuntimeError('Телевизор Xiaomi не отвечает — он включён и в той же сети?')

    def apps(self):
        try:
            data = self.session.get(f'{self.base}/request', params={'action': 'getinstalledapp', 'count': 999,
                                                                    'changeIcon': 1}, timeout=5).json()
        except Exception:
            return []
        items = (data.get('data') or {}).get('AppInfo') or data.get('AppInfo') or []
        return [{'package': a.get('PackageName', ''), 'title': a.get('AppName', '')} for a in items]

    def open_app(self, package):
        self.session.get(f'{self.base}/controller', params={'action': 'startapp', 'type': 'packagename',
                                                            'packagename': package}, timeout=5)

    def pair(self):
        if xiaomi_alive(self.config['ip'], self.session) is None:
            raise RuntimeError('Телевизор Xiaomi не ответил. Он включён и подключён к той же Wi-Fi?')
        return 'Телевизор Xiaomi подключён — коды не нужны.'

    def _cast(self):
        return self.cast_factory(self.config['ip'])

    def run(self, action, value):
        from .smarthome import SEARCH_LINKS, TV_APPS
        if action == 'power':
            if value:
                return None            # включение — Wake-on-LAN (из SmartHome)
            self.key('power')
            return 'Выключаю телевизор.'
        if action == 'volume_step':
            self.key('volumeup' if value > 0 else 'volumedown', 2)
            return 'Громче.' if value > 0 else 'Тише.'
        if action in ('volume', 'mute'):
            try:
                with self._cast() as cast:
                    if action == 'volume':
                        cast.set_volume(value / 100)
                        return f'Громкость телевизора {value}.'
                    cast.mute(bool(value))
                    return 'Выключил звук.' if value else 'Включил звук.'
            except Exception:
                return 'Этот телевизор Xiaomi не даёт задать громкость числом — скажите «громче» или «тише».'
        if action == 'channel_step':
            self.key('up' if value > 0 else 'down')
            return 'Следующий канал.' if value > 0 else 'Предыдущий канал.'
        if action == 'channel':
            return 'На Xiaomi номер канала голосом не набрать — скажите «следующий канал» или «предыдущий канал».'
        if action in ('pause', 'play'):
            self.key('enter')
            return 'Пауза.' if action == 'pause' else 'Продолжаю.'
        if action == 'key':
            self.key(self.KEYS.get(value, value))
            return 'Готово.'
        if action == 'app':
            title, words, lg_id, hint, _ = TV_APPS[value]
            package = next((a['package'] for a in self.apps() if hint in a['package'].casefold()
                            or a['title'].casefold() in words), None)
            if package is None:
                return f'На телевизоре нет приложения {title}.'
            self.open_app(package)
            return f'Открываю {title} на телевизоре.'
        if action == 'search':
            query, app = value
            if app == 'youtube':
                video = youtube_video(query)
                if video and dial_youtube(self.config['ip'], self.session, video):
                    return f'Включаю «{query}» на YouTube на телевизоре.'
            title, words, lg_id, hint, _ = TV_APPS.get(app, TV_APPS['youtube'])
            package = next((a['package'] for a in self.apps() if hint in a['package'].casefold()), None)
            if package:
                self.open_app(package)
                return f'Открыл {title} на телевизоре — фильм «{query}» найдите в поиске приложения.'
            return f'Не получилось включить «{query}» — на телевизоре нет {title}.'
        if action == 'picture':
            return 'Режим изображения на Xiaomi переключается в настройках телевизора.'
        return None


# ---------------- Android TV / Google TV через Cast ----------------
class CastTV:
    """Android TV / Google TV со встроенным Chromecast — без «Отладки по сети» и без кодов.
    Если ADB настроен и разрешён (adb), выключение, каналы и любые приложения идут через него."""

    def __init__(self, config, session, adb=None, cast_factory=Cast):
        self.config = config
        self.session = session
        self.adb = adb
        self.cast_factory = cast_factory

    def pair(self):
        with self.cast_factory(self.config['ip']) as cast:
            cast.status()
        return 'Телевизор подключён — коды не нужны.'

    def _adb_run(self, action, value):
        if self.adb is None:
            return None
        try:
            return self.adb.run(action, value)
        except RuntimeError:
            return None

    def run(self, action, value):
        if action == 'power':
            if value:
                return None            # Wake-on-LAN
            return self._adb_run(action, value) or (
                'Выключить этот телевизор без кабеля управления нельзя: скажите «выключи телевизор» пульту или включите '
                'на ТВ «Отладку по сети» один раз (Настройки → Умный дом → подсказка).')
        if action in ('volume', 'volume_step', 'mute'):
            with self.cast_factory(self.config['ip']) as cast:
                if action == 'volume':
                    cast.set_volume(value / 100)
                    return f'Громкость телевизора {value}.'
                if action == 'volume_step':
                    cast.set_volume(cast.volume() + (0.06 if value > 0 else -0.06))
                    return 'Громче.' if value > 0 else 'Тише.'
                cast.mute(bool(value))
                return 'Выключил звук.' if value else 'Включил звук.'
        if action == 'search':
            query, app = value
            if app == 'youtube':
                video = youtube_video(query)
                if video and dial_youtube(self.config['ip'], self.session, video):
                    return f'Включаю «{query}» на YouTube на телевизоре.'
            done = self._adb_run(action, value)
            if done:
                return done
            if app in CAST_APPS:
                with self.cast_factory(self.config['ip']) as cast:
                    cast.launch(CAST_APPS[app])
                return f'Открыл {app.title()} на телевизоре.'
            return f'Чтобы включать фильмы в этом приложении, включите на ТВ «Отладку по сети». YouTube работает и так.'
        if action == 'app':
            if value in CAST_APPS:
                with self.cast_factory(self.config['ip']) as cast:
                    cast.launch(CAST_APPS[value])
                return 'Открываю на телевизоре.'
            return self._adb_run(action, value) or 'Это приложение на этом телевизоре открывается только с «Отладкой по сети».'
        if action in ('pause', 'play'):
            done = self._adb_run(action, value)
            if done:
                return done
            if action == 'pause':
                with self.cast_factory(self.config['ip']) as cast:
                    cast.stop()
                return 'Остановил.'
            return 'Продолжить можно пультом или с «Отладкой по сети».'
        return self._adb_run(action, value) or (
            'Эта команда для Android TV работает только с включённой «Отладкой по сети» (один раз в настройках ТВ). '
            'Громкость, звук и YouTube — работают и так.')


# ---------------- какой телевизор имелся в виду ----------------
TV_WORD = r'(?:телевизор\w*|телик\w*|телек\w*|тв)'
ORDINALS = {'перв': 1, 'втор': 2, 'трет': 3, 'четверт': 4, 'четвёрт': 4, 'пят': 5, 'шест': 6}
NUMBERS = {'один': 1, 'одном': 1, 'два': 2, 'двух': 2, 'три': 3, 'трех': 3, 'трёх': 3, 'четыре': 4, 'пять': 5, 'шесть': 6}


def pick_target(text, tvs):
    """(номер телевизора 1…N или None, фраза без уточнения): «на телевизоре 2», «на втором телевизоре»,
    «телевизор в спальне», «на всех телевизорах» → ('all', …)."""
    value = re.sub(r'\s+', ' ', str(text)).strip()
    numbers = {t.get('number') for t in tvs}
    match = re.search(r'(?<![\w])(на\s+)?(?:всех|все|оба|обоих|обои?х?)\s+' + TV_WORD + r'(?![\w])', value, re.I)
    if match:
        rest = (value[:match.start()] + ' ' + value[match.end():]).strip()
        cleaned = f'{rest} на телевизоре' if match[1] else value[:match.start()] + 'телевизор' + value[match.end():]
        return 'all', re.sub(r'\s+', ' ', cleaned).strip()
    match = re.search(r'(?<![\w])(перв|втор|трет|четв[её]рт|пят|шест)\w*\s+(' + TV_WORD + r')', value, re.I)
    if match:
        stem = match[1].casefold().replace('ё', 'е')
        number = next(v for k, v in ORDINALS.items() if stem.startswith(k.replace('ё', 'е')))
        return number, (value[:match.start()] + match[2] + value[match.end():]).strip()
    match = re.search(r'(?<![\w])(' + TV_WORD + r')(?:\s+(?:номер|№)\s*|\s+)(\d{1,2}|один|два|три|четыре|пять|шесть)(?![\w])',
                      value, re.I)
    if match:
        raw = match[2].casefold()
        number = int(raw) if raw.isdigit() else NUMBERS.get(raw)
        if number in numbers or 'номер' in match[0].casefold():   # «громкость на телевизоре 20» — это громкость
            return number, (value[:match.start()] + match[1] + value[match.end():]).strip()
    from .smarthome import name_matches
    match = re.search(r'(?<![\w])(' + TV_WORD + r')\s+(?:в|на|у)\s+([\wё-]+(?:\s[\wё-]+)?)', value, re.I)
    if match:
        for words in (match[2], match[2].split()[0]):
            for tv in tvs:
                if tv.get('name') and name_matches(words, tv['name']):
                    tail = value[match.start(2) + len(words):]
                    return tv['number'], (value[:match.start()] + match[1] + tail).strip()
    return None, value
