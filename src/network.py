"""Автономный режим: «Андрей, отключись от сети» — агент перестаёт выходить в интернет вообще.

Включается голосом или ползунком «Подключение к сети» (Настройки → «Общие»); обратно — только ползунком или
голосом «Андрей, подключись к сети». Состояние хранится на ПК и действует после перезапуска.

Как это устроено. Пока сеть выключена, сетевые соединения самой программы проверяются на уровне сокетов:
разрешены только адреса этого компьютера и домашней сети (127.0.0.1, 192.168.x.x, 10.x, 172.16–31.x, *.local) —
телевизоры, роутер, лампы, телефон в той же Wi-Fi и локальная нейросеть продолжают работать. Любой выход в интернет
(облачные нейросети, поиск, погода, интеграции, сервер аккаунтов, загрузки моделей, мост для телефона) блокируется,
а ссылки на сайты не открываются в браузере. Подписка не пропадает: лицензия подписана и проверяется на месте.
"""
import ipaddress
import logging
import os
import re
import socket
import threading
import webbrowser

log = logging.getLogger(__name__)

MESSAGE = ('Я сейчас работаю без сети — это действие требует интернета. Чтобы подключиться, скажите '
           '«Андрей, подключись к сети» или включите «Подключение к сети» в настройках.')
LOCAL_SUFFIXES = ('.local', '.lan', '.home', '.home.arpa', '.internal', '.localdomain', '.localhost')

OFF = re.compile(r'^(?:отключись|отключайся|отсоединись|отключи\s+себя)\s+от\s+(?:сети|интернета)'
                 r'|^(?:перейди|переключись|уйди)\s+в\s+(?:офлайн|оффлайн|автономн\w+)(?:\s+режим)?'
                 r'|^(?:включи|включай|активируй)\s+(?:офлайн|оффлайн|автономн\w+)(?:\s+режим)?'
                 r'|^(?:работай|работать)\s+без\s+(?:сети|интернета)(?:\s+дальше)?'
                 r'|^отключи\s+(?:мне\s+)?(?:всю\s+)?(?:сеть|интернет)\s+(?:для\s+себя|у\s+себя|себе|агенту|андрею)$', re.I)
ON = re.compile(r'^(?:подключись|подключайся|вернись|переподключись)\s+(?:обратно\s+)?(?:к|в)\s+(?:сети|сеть|интернету|интернет)'
                r'|^(?:выключи|отключи)\s+(?:офлайн|оффлайн|автономн\w+)(?:\s+режим)?'
                r'|^(?:выйди|выходи)\s+из\s+(?:офлайн|оффлайн|автономн\w+)(?:\s+режима)?'
                r'|^(?:включи|верни)\s+(?:себе\s+)?(?:сеть|интернет)(?:\s+(?:для\s+себя|себе|агенту|андрею))?$', re.I)
STATUS = re.compile(r'^(?:ты\s+)?(?:сейчас\s+)?(?:в\s+сети|подключ[её]н\s+к\s+(?:сети|интернету)|без\s+сети|офлайн)\s*\??$'
                    r'|^(?:есть\s+ли\s+у\s+тебя|у\s+тебя\s+есть)\s+(?:сеть|интернет)', re.I)


class Offline(ConnectionRefusedError):
    """Соединение не выполнено: агент в автономном режиме."""

    def __init__(self, target=''):
        super().__init__(111, 'Андрей работает без сети' + (f' ({target})' if target else ''))


def is_local(host):
    """Адрес этого ПК или домашней сети — их можно и без интернета."""
    if host is None:
        return True
    host = str(host).strip('[]').casefold()
    if not host or host == 'localhost' or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host.split('%', 1)[0])
    except ValueError:
        return '.' not in host            # имя компьютера в сети (NetBIOS) без домена
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified


def is_web_url(value):
    return isinstance(value, str) and re.match(r'^(?:https?|ftp)://', value.strip(), re.I) is not None and \
        not is_local(re.sub(r'^\w+://([^/:?#]+).*$', r'\1', value.strip()))


# ---------------- охрана на уровне сокетов ----------------
_state = {'online': True}
_installed = threading.Lock()
_done = []


def online():
    return _state['online']


def _host_of(address):
    if isinstance(address, tuple) and address:
        return address[0]
    return None   # unix-сокеты и прочее локальное


def install():
    """Один раз подменить точки выхода в сеть. Пока сеть включена, всё работает как обычно."""
    with _installed:
        if _done:
            return
        _done.append(True)
        real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
        real_sendto, real_getaddrinfo = socket.socket.sendto, socket.getaddrinfo
        real_startfile = getattr(os, 'startfile', None)
        real_browser_open = webbrowser.open

        def connect(self, address):
            if not _state['online'] and not is_local(_host_of(address)):
                raise Offline(str(_host_of(address)))
            return real_connect(self, address)

        def connect_ex(self, address):
            if not _state['online'] and not is_local(_host_of(address)):
                return 111
            return real_connect_ex(self, address)

        def sendto(self, data, *args):
            address = args[-1] if args else None
            if not _state['online'] and not is_local(_host_of(address)):
                raise Offline(str(_host_of(address)))
            return real_sendto(self, data, *args)

        def getaddrinfo(host, *args, **kwargs):
            if not _state['online'] and not is_local(host.decode() if isinstance(host, bytes) else host):
                raise socket.gaierror(socket.EAI_NONAME, 'Андрей работает без сети')
            return real_getaddrinfo(host, *args, **kwargs)

        def browser_open(url, *args, **kwargs):
            if not _state['online'] and is_web_url(url):
                return False
            return real_browser_open(url, *args, **kwargs)

        socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto = connect, connect_ex, sendto
        socket.getaddrinfo = getaddrinfo
        webbrowser.open = browser_open
        if real_startfile is not None:
            def startfile(path, *args, **kwargs):
                if not _state['online'] and is_web_url(path):
                    raise Offline(str(path))
                return real_startfile(path, *args, **kwargs)
            os.startfile = startfile


# ---------------- переключатель ----------------
class Network:
    KEY = 'network'

    def __init__(self, store, events=None):
        self.store = store
        self.events = events
        install()
        _state['online'] = (store.meta(self.KEY) or 'on') != 'off'

    @property
    def online(self):
        return _state['online']

    def status(self):
        return {'online': self.online}

    def set(self, online, source='settings'):
        online = bool(online)
        changed = online != _state['online']
        _state['online'] = online
        self.store.set_meta(self.KEY, 'on' if online else 'off')
        if changed:
            log.info('Network %s (%s)', 'enabled' if online else 'disabled', source)
            if self.events is not None:
                self.events.emit('network', online=online, source=source)
        return self.status()

    def settings(self, settings):
        """Без сети нейросеть отвечает только локально и не ищет в интернете."""
        if self.online:
            return settings
        value = dict(settings, llm_web_search=False, ddg_search=False)
        if value.get('llm_provider') == 'openai' and not is_local(
                re.sub(r'^\w+://([^/:?#]+).*$', r'\1', str(value.get('openai_base_url', '')))):
            value['llm_provider'] = 'local'
        return value

    def handle(self, text):
        value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!')
        if OFF.match(value):
            if not self.online:
                return 'Я уже работаю без сети. Всё выполняется только на этом компьютере.'
            self.set(False, 'voice')
            return ('Отключился от сети. Теперь всё работает только на этом компьютере и в домашней сети: интернет, '
                    'облачные нейросети и интеграции выключены. Вернуть — «Андрей, подключись к сети» или ползунком '
                    'в настройках.')
        if ON.match(value):
            if self.online:
                return 'Я и так подключён к сети.'
            self.set(True, 'voice')
            return 'Подключился к сети. Интернет-функции снова работают.'
        if STATUS.match(value):
            return 'Я подключён к сети.' if self.online else 'Я работаю без сети — всё только на этом компьютере.'
        return None


class OfflineBrowser:
    """Браузер агента без сети не открывает сайты, но локальные страницы и управление вкладками доступны."""
    NETWORK = {'open', 'youtube', 'music', 'search', 'site', 'navigate', 'player'}

    def __init__(self, browser):
        self._browser = browser

    def call(self, method, *args):
        if not online() and (method in self.NETWORK or any(is_web_url(a) for a in args if isinstance(a, str))):
            return MESSAGE
        return self._browser.call(method, *args)

    def __getattr__(self, name):
        return getattr(self._browser, name)

