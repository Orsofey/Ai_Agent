"""ПК ↔ мост на сервере аккаунтов: телефон управляет компьютером через интернет, из любой сети.

ПК сам опрашивает сервер (исходящее соединение), поэтому не нужны белый IP и проброс портов.
Запросы выполняются тем же локальным API, что и в домашней сети, с тем же кодом подключения.
"""
import base64
import hashlib
import hmac
import io
import logging
import re
import secrets
import threading
import time

log = logging.getLogger(__name__)

RELAY_SALT = b'andrey-relay'


def relay_key(token):
    """Ключ моста: HMAC от кода подключения. Сам код подключения на сервер не передаётся."""
    return hmac.new(str(token).encode(), RELAY_SALT, hashlib.sha256).hexdigest()


class RelayClient:
    def __init__(self, store, app, license, session=None):
        self.store = store
        self.app = app
        self.license = license
        self._session = session
        self.thread = None
        self.state = {'online': False, 'error': None, 'last': None}

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def rid(self):
        value = self.store.meta('relay_id')
        if not value:
            value = secrets.token_urlsafe(18)
            self.store.set_meta('relay_id', value)
        return value

    def key(self):
        return relay_key(self.store.meta('pairing_token'))

    def server(self):
        return (getattr(self.license, 'server_url', '') or '').rstrip('/')

    def enabled(self):
        return bool(self.store.settings('device:desktop').get('remote_access')) and bool(self.server())

    def status(self):
        return dict(self.state, enabled=self.enabled(), server=self.server())

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, daemon=True, name='relay')
            self.thread.start()

    def _run(self):
        delay = 2
        while True:
            if not self.enabled():
                self.state.update(online=False)
                time.sleep(5)
                continue
            try:
                self.poll_once()
                delay = 2
            except Exception as exc:
                self.state.update(online=False, error=str(exc)[:200])
                log.info('Relay unavailable: %s', exc)
                time.sleep(delay)
                delay = min(delay * 2, 60)

    def poll_once(self, wait=25):
        response = self.session.post(self.server() + '/relay/pc/poll',
                                     json={'rid': self.rid(), 'key': self.key(), 'wait': wait}, timeout=wait + 15)
        if response.status_code != 200:
            raise RuntimeError(f'мост ответил {response.status_code}')
        self.state.update(online=True, error=None, last=time.strftime('%H:%M:%S'))
        for request in response.json().get('requests') or []:
            threading.Thread(target=self._serve, args=(request,), daemon=True, name='relay-request').start()

    def _serve(self, request):
        try:
            status, body = self.execute(request)
        except Exception as exc:
            log.exception('Relay request failed')
            status, body = 500, {'success': False, 'message': str(exc)[:200]}
        try:
            self.session.post(self.server() + '/relay/pc/reply', timeout=30,
                              json={'rid': self.rid(), 'key': self.key(), 'id': request.get('id'),
                                    'status': status, 'body': body})
        except Exception as exc:
            log.info('Relay reply failed: %s', exc)

    def execute(self, request):
        """Выполнить запрос телефона через локальный API (в том же процессе)."""
        path = str(request.get('path', ''))
        device = re.sub(r'[^\w-]', '', str(request.get('device') or 'phone'))[:80] or 'phone'
        headers = {'X-Agent-Token': self.store.meta('pairing_token'), 'X-Device-ID': device}
        client = self.app.test_client()
        if path == '/api/transcribe':
            audio = base64.b64decode(request.get('audio') or '')
            response = client.post(path, headers=headers, content_type='multipart/form-data',
                                   data={'audio': (io.BytesIO(audio), 'voice.wav'),
                                         'language': str(request.get('language') or 'auto')})
        elif str(request.get('method', 'POST')).upper() == 'GET':
            response = client.get(path, headers=headers)
        else:
            response = client.post(path, headers=headers, json=request.get('json') or {})
        return response.status_code, response.get_json(silent=True)
