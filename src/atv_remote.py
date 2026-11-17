"""Android TV Remote (протокол v2) — как пульт в приложении Google TV на телефоне. Без «Отладки по USB».

Один раз на телевизор: программа просит телевизор показать код (6 символов) — пользователь говорит
«Андрей, код 4F7A2C» или вводит его в окне. После этого доступны все кнопки пульта: питание, громкость, каналы,
стрелки/ОК/назад/домой, пауза, запуск приложений и ссылок (YouTube-видео). Сертификат этого ПК хранится в папке
данных; сопряжение запоминает сам телевизор.

Порты: 6467 — сопряжение, 6466 — пульт. Сообщения — protobuf с префиксом длины (varint) поверх TLS с сертификатом
клиента. Протокол описан в открытой библиотеке androidtvremote2 (Apache-2.0); здесь — своя минимальная реализация.
"""
import datetime
import hashlib
import logging
import re
import socket
import ssl
import time
from pathlib import Path

log = logging.getLogger(__name__)

PAIR_PORT, REMOTE_PORT = 6467, 6466
STATUS_OK = 200

# Коды клавиш Android (KeyEvent)
KEYS = {'power': 26, 'volume_up': 24, 'volume_down': 25, 'mute': 164, 'home': 3, 'back': 4, 'up': 19, 'down': 20,
        'left': 21, 'right': 22, 'ok': 23, 'menu': 82, 'play_pause': 85, 'play': 126, 'pause': 127,
        'channel_up': 166, 'channel_down': 167, 'sleep': 223, 'wakeup': 224, **{str(d): 7 + d for d in range(10)}}
SHORT = 3


class RemoteError(RuntimeError):
    pass


class NotPaired(RemoteError):
    pass


# ---------------- protobuf вручную ----------------
def varint(value):
    out = bytearray()
    while True:
        bits = value & 0x7F
        value >>= 7
        out.append(bits | (0x80 if value else 0))
        if not value:
            return bytes(out)


def f_int(number, value):
    return varint(number << 3) + varint(value)


def f_bytes(number, data):
    data = data.encode('utf-8') if isinstance(data, str) else data
    return varint(number << 3 | 2) + varint(len(data)) + data


def f_msg(number, *parts):
    return f_bytes(number, b''.join(parts))


def _read_varint(data, i):
    value = shift = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, i


def decode(data):
    """{номер поля: [значения]} — int для чисел, bytes для строк и вложенных сообщений."""
    fields, i = {}, 0
    while i < len(data):
        key, i = _read_varint(data, i)
        number, kind = key >> 3, key & 7
        if kind == 0:
            value, i = _read_varint(data, i)
        elif kind == 2:
            length, i = _read_varint(data, i)
            value, i = data[i:i + length], i + length
        elif kind == 5:
            value, i = data[i:i + 4], i + 4
        elif kind == 1:
            value, i = data[i:i + 8], i + 8
        else:
            break
        fields.setdefault(number, []).append(value)
    return fields


def first(fields, number, default=None):
    values = fields.get(number)
    return values[0] if values else default


# ---------------- сертификат этого ПК ----------------
def client_certificate(root):
    """(cert.pem, key.pem) — создаётся один раз и хранится в папке данных."""
    folder = Path(root) / 'tv'
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = folder / 'atv_client.pem', folder / 'atv_client.key'
    if cert.exists() and key.exists():
        return cert, key
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'atvremote'),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Andrey')])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
                   .not_valid_after(now + datetime.timedelta(days=3650)).sign(private, hashes.SHA256()))
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                          serialization.NoEncryption()))
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return cert, key


def own_cert_der(root):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    cert, _ = client_certificate(root)
    return x509.load_pem_x509_certificate(cert.read_bytes()).public_bytes(serialization.Encoding.DER)


def _hex_bytes(number):
    text = f'{number:X}'
    return bytes.fromhex(('0' if len(text) % 2 else '') + text)


def pairing_secret(client_cert_der, server_cert_der, code):
    """Секрет сопряжения: SHA-256(модуль и экспонента ПК и ТВ + код без первого байта)."""
    from cryptography import x509
    client = x509.load_der_x509_certificate(client_cert_der).public_key().public_numbers()
    server = x509.load_der_x509_certificate(server_cert_der).public_key().public_numbers()
    digest = hashlib.sha256()
    for part in (client.n, client.e, server.n, server.e):
        digest.update(_hex_bytes(part))
    digest.update(bytes.fromhex(code[2:]))
    secret = digest.digest()
    if secret[0] != int(code[:2], 16):
        raise RemoteError('Код не подошёл — проверьте символы на экране телевизора и скажите его ещё раз.')
    return secret


# ---------------- код голосом ----------------
SPOKEN_HEX = {
    'ноль': '0', 'нуль': '0', 'один': '1', 'одна': '1', 'два': '2', 'две': '2', 'три': '3', 'четыре': '4', 'пять': '5',
    'шесть': '6', 'семь': '7', 'восемь': '8', 'девять': '9', 'а': 'A', 'эй': 'A', 'бэ': 'B', 'бе': 'B', 'би': 'B',
    'б': 'B', 'цэ': 'C', 'це': 'C', 'си': 'C', 'ц': 'C', 'с': 'C', 'дэ': 'D', 'де': 'D', 'ди': 'D', 'д': 'D',
    'е': 'E', 'э': 'E', 'и': 'E', 'эф': 'F', 'ф': 'F', 'еф': 'F'}
CODE = re.compile(r'^(?:это\s+)?(?:пин-код|пинкод|пин|код)(?:\s+с\s+(?:экрана|телевизора))?\s*[:,—-]?\s*(?P<code>.+)$', re.I)


def normalize_code(raw):
    """'4f 7a-2c', 'четыре эф семь а два цэ' → '4F7A2C' или None."""
    raw = str(raw).casefold().replace('ё', 'е').strip()
    compact = re.sub(r'[\s-]', '', raw)
    if re.fullmatch(r'[0-9a-f]{6}', compact):
        return compact.upper()
    symbols = []
    for word in re.findall(r'[0-9a-f]+|[а-я]+', raw):
        if re.fullmatch(r'[0-9a-f]+', word):
            symbols.extend(word.upper())
        elif word in SPOKEN_HEX:
            symbols.append(SPOKEN_HEX[word])
        else:
            return None
    code = ''.join(symbols)
    return code if len(code) == 6 else None


def parse_code(text):
    """«код 4F7A2C», «код четыре эф семь а два цэ» → '4F7A2C' или None."""
    match = CODE.match(re.sub(r'\s+', ' ', str(text)).strip().strip('.!'))
    return normalize_code(match['code']) if match else None


# ---------------- соединение ----------------
class Channel:
    def __init__(self, ip, port, root, timeout=6):
        cert, key = client_certificate(root)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.load_cert_chain(str(cert), str(key))
        try:
            raw = socket.create_connection((ip, port), timeout=4)
            self.sock = context.wrap_socket(raw)
        except ssl.SSLError as exc:
            raise NotPaired('Телевизор не узнал этот компьютер — нужно подтвердить код с экрана.') from exc
        except OSError as exc:
            raise RemoteError('Телевизор не отвечает — он включён и в той же Wi-Fi?') from exc
        self.sock.settimeout(timeout)

    def peer_der(self):
        return self.sock.getpeercert(binary_form=True)

    def send(self, payload):
        self.sock.sendall(varint(len(payload)) + payload)

    def recv(self):
        length = shift = 0
        while True:
            byte = self._exact(1)[0]
            length |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        return decode(self._exact(length))

    def _exact(self, size):
        data = b''
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise NotPaired('Телевизор закрыл соединение — нужно подтвердить код с экрана.')
            data += chunk
        return data

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Pairing:
    """Сопряжение: start() — телевизор показывает код; finish(code) — подтверждение."""

    def __init__(self, ip, root, channel_factory=Channel):
        self.ip, self.root = ip, root
        self.channel_factory = channel_factory
        self.channel = None
        self.started = 0.0

    @staticmethod
    def _outer(*parts):
        return f_int(1, 2) + f_int(2, STATUS_OK) + b''.join(parts)

    def _expect(self):
        reply = self.channel.recv()
        status = first(reply, 2, 0)
        if status != STATUS_OK:
            raise RemoteError('Код не подошёл — скажите его ещё раз.' if status == 402 else
                              'Телевизор отклонил подключение. Повторите команду и подтвердите код с экрана.')
        return reply

    def start(self):
        self.channel = self.channel_factory(self.ip, PAIR_PORT, self.root)
        encoding = f_int(1, 3) + f_int(2, 6)                 # шестнадцатеричный код из 6 символов
        self.channel.send(self._outer(f_msg(10, f_bytes(1, 'atvremote'), f_bytes(2, 'Андрей'))))
        self._expect()
        self.channel.send(self._outer(f_msg(20, f_msg(1, encoding), f_int(3, 1))))
        self._expect()
        self.channel.send(self._outer(f_msg(30, f_msg(1, encoding), f_int(2, 1))))
        self._expect()                                        # теперь на экране телевизора — код
        self.started = time.monotonic()

    def finish(self, code):
        code = normalize_code(code) or ''
        if not code:
            raise RemoteError('Код — это 6 символов с экрана телевизора: цифры и буквы A–F.')
        try:
            secret = pairing_secret(own_cert_der(self.root), self.channel.peer_der(), code)
            self.channel.send(self._outer(f_msg(40, f_bytes(1, secret))))
            self._expect()
        finally:
            self.channel.close()
        return True

    def cancel(self):
        if self.channel is not None:
            self.channel.close()


class Remote:
    """Пульт после сопряжения: кнопки, ссылки на приложения, состояние экрана."""

    def __init__(self, ip, root, channel_factory=Channel):
        self.ip, self.root = ip, root
        self.channel_factory = channel_factory
        self.channel = None
        self.screen_on = None

    def __enter__(self):
        self.channel = self.channel_factory(self.ip, REMOTE_PORT, self.root)
        try:
            self._handshake()
        except Exception:
            self.channel.close()
            raise
        return self

    def __exit__(self, *exc):
        if self.channel is not None:
            self.channel.close()

    def _handle(self, message):
        """Отвечаем на служебные сообщения телевизора; True — когда пришло состояние экрана."""
        if 8 in message:                                         # ping → pong
            ping = decode(first(message, 8, b''))
            self.channel.send(f_msg(9, f_int(1, first(ping, 1, 0))))
        if 1 in message:                                         # configure → наш configure
            info = (f_bytes(1, 'Andrey PC') + f_bytes(2, 'Andrey') + f_int(3, 1) + f_bytes(4, '1') +
                    f_bytes(5, 'atvremote') + f_bytes(6, '4.0.0'))
            self.channel.send(f_msg(1, f_int(1, 622), f_msg(2, info)))
        if 2 in message:                                         # set_active → наш set_active
            self.channel.send(f_msg(2, f_int(1, 622)))
        if 3 in message:
            raise NotPaired('Телевизор не принял пульт — нужно подтвердить код с экрана.')
        if 40 in message:                                        # remote_start: включён ли экран
            self.screen_on = bool(first(decode(first(message, 40, b'')), 1, 0))
            return True
        return False

    def _handshake(self, wait=4.0):
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                message = self.channel.recv()
            except (socket.timeout, TimeoutError):
                break
            except ssl.SSLError as exc:
                raise NotPaired('Телевизор не узнал этот компьютер — нужно подтвердить код с экрана.') from exc
            if self._handle(message):
                break

    def key(self, name, times=1):
        code = KEYS[name] if isinstance(name, str) else int(name)
        for _ in range(times):
            self.channel.send(f_msg(10, f_int(1, code), f_int(2, SHORT)))
            time.sleep(0.12)

    def link(self, url):
        """Открыть ссылку или приложение: https://www.youtube.com/watch?v=…, market://launch?id=пакет."""
        self.channel.send(f_msg(90, f_bytes(1, url)))

    def power(self, on):
        if self.screen_on is None or self.screen_on != bool(on):
            self.key('power')
            return True
        return False
