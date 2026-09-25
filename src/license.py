"""Аккаунт и подписка на стороне приложения.

Вход и оплата идут через сервер лицензий (server/license_server.py). Сервер выдаёт лицензию,
подписанную Ed25519; приложение проверяет подпись открытым ключом без интернета, так что
подписка работает офлайн, а подделать её без закрытого ключа нельзя.

Адрес сервера и открытый ключ: src/license_config.py, файл license.json в папке данных
или переменные AGENT_LICENSE_SERVER / AGENT_LICENSE_PUBLIC_KEY.
"""
import base64
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from . import license_config

log = logging.getLogger(__name__)
GRACE = timedelta(days=3)          # месячная подписка работает ещё 3 дня, если нет интернета для продления
REFRESH_SECONDS = 6 * 3600
PLAN_NAMES = {'free': 'Бесплатный', 'monthly': 'Подписка на месяц', 'lifetime': 'Навсегда'}


class AccountError(RuntimeError):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def verify(document, public_key):
    """Проверить подпись лицензии. Вернуть payload или None."""
    if not public_key or not isinstance(document, dict):
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key))
        key.verify(base64.b64decode(document['signature']), canonical(document['payload']))
        return document['payload']
    except Exception:
        return None


def parse_time(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) if value else None


class LicenseClient:
    def __init__(self, store, server_url=None, public_key=None, session=None):
        self.store = store
        config = self._config()
        self.server_url = (server_url if server_url is not None else config.get('server_url', '')).rstrip('/')
        self.public_key = public_key if public_key is not None else config.get('public_key', '')
        self.session = session or requests.Session()
        self.lock = threading.Lock()
        self._cache = None

    def _config(self):
        config = {'server_url': license_config.SERVER_URL, 'public_key': license_config.PUBLIC_KEY}
        try:
            config.update(json.loads((self.store.root / 'license.json').read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
        config['server_url'] = os.environ.get('AGENT_LICENSE_SERVER', config['server_url'])
        config['public_key'] = os.environ.get('AGENT_LICENSE_PUBLIC_KEY', config['public_key'])
        return config

    @property
    def configured(self):
        return bool(self.server_url)

    def key(self):
        """Открытый ключ: из сборки, либо запомненный при первом подключении к серверу (по HTTPS)."""
        if self.public_key:
            return self.public_key
        pinned = self.store.meta('license_public_key')
        if pinned:
            return pinned
        if not self.server_url.startswith(('https://', 'http://127.0.0.1', 'http://localhost')):
            return ''
        try:
            response = self.session.request('GET', self.server_url + '/api/public-key', json=None, headers={}, timeout=15)
            value = response.json().get('public_key', '') if response.ok else ''
        except Exception:
            value = ''
        if value:
            self.store.set_meta('license_public_key', value)
        return value

    # ---- состояние ----
    def _load(self):
        if self._cache is None:
            try:
                self._cache = json.loads(self.store.meta('license') or 'null')
            except ValueError:
                self._cache = None
        return self._cache

    def _save(self, token=None, document=None, email=None):
        if token is not None:
            self.store.set_meta('account_token', token or None)
        if email is not None:
            self.store.set_meta('account_email', email or None)
        if document is not None:
            self.store.set_meta('license', json.dumps(document, ensure_ascii=False) if document else None)
            self._cache = document or None

    def payload(self):
        document = self._load()
        if not document:
            return None
        key = self.public_key or self.store.meta('license_public_key')
        return verify(document, key)

    def is_premium(self):
        payload = self.payload()
        if not payload or payload.get('email') != self.store.meta('account_email'):
            return False
        if payload.get('plan') == 'lifetime':
            return True
        if payload.get('plan') == 'monthly':
            expires = parse_time(payload.get('expires'))
            return bool(expires and datetime.now(timezone.utc) < expires + GRACE)
        return False

    def status(self):
        payload = self.payload() or {}
        email = self.store.meta('account_email')
        plan = payload.get('plan', 'free') if payload.get('email') == email else 'free'
        return {'configured': self.configured, 'logged_in': bool(self.store.meta('account_token')), 'email': email,
                'owner': bool(self.store.meta('account_owner')),
                'plan': plan, 'plan_name': PLAN_NAMES.get(plan, plan), 'expires': payload.get('expires'),
                'premium': self.is_premium(), 'prices': {'monthly': 100, 'lifetime': 500},
                'pending_payment': self.store.meta('pending_payment')}

    # ---- сервер ----
    def _request(self, method, path, body=None, auth=True):
        if not self.configured:
            raise AccountError('Сервер подписки не настроен в этой сборке (см. docs/AMVERA.md).', 503)
        headers = {}
        if auth:
            token = self.store.meta('account_token')
            if not token:
                raise AccountError('Войдите в аккаунт', 401)
            headers['Authorization'] = 'Bearer ' + token
        try:
            response = self.session.request(method, self.server_url + path, json=body, headers=headers, timeout=20)
        except requests.RequestException:
            raise AccountError('Нет связи с сервером подписки. Проверьте интернет.', 502)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code == 401 and auth:
            self._save(token='')
        if not response.ok or not data.get('success', False):
            raise AccountError(data.get('message') or f'Ошибка сервера подписки ({response.status_code})',
                               response.status_code if response.status_code in (400, 401, 404) else 502)
        return data

    def _accept(self, data):
        if data.get('license') and not verify(data['license'], self.key()):
            raise AccountError('Сервер вернул лицензию с неверной подписью.', 502)
        self._save(token=data.get('token'), document=data.get('license'), email=data.get('email'))
        if 'owner' in data:
            self.store.set_meta('account_owner', '1' if data.get('owner') else None)
        return self.status()

    def register(self, email, password):
        with self.lock:
            return self._accept(self._request('POST', '/api/register', {'email': email, 'password': password}, auth=False))

    def login(self, email, password):
        with self.lock:
            return self._accept(self._request('POST', '/api/login', {'email': email, 'password': password}, auth=False))

    def logout(self):
        with self.lock:
            try:
                self._request('POST', '/api/logout')
            except AccountError:
                pass
            self._save(token='', document={}, email='')
            self.store.set_meta('account_owner', None)
            self.store.set_meta('pending_payment', None)
            return self.status()

    def promo(self, code):
        """Активировать промокод: подписка навсегда бесплатно."""
        code = str(code or '').strip()
        if not 3 <= len(code) <= 64:
            raise AccountError('Введите промокод')
        with self.lock:
            return self._accept(self._request('POST', '/api/promo', {'code': code}))

    def refresh(self):
        """Обновить лицензию с сервера (продление, окончание месяца)."""
        with self.lock:
            return self._accept(self._request('GET', '/api/me'))

    def checkout(self, plan):
        if plan not in ('monthly', 'lifetime'):
            raise AccountError('Неизвестный тариф')
        with self.lock:
            data = self._request('POST', '/api/checkout', {'plan': plan})
            self.store.set_meta('pending_payment', data['payment_id'])
            return {'url': data['url'], 'payment_id': data['payment_id']}

    def check_payment(self):
        payment_id = self.store.meta('pending_payment')
        if not payment_id:
            return self.refresh()
        with self.lock:
            data = self._request('GET', '/api/payments/' + payment_id)
            if data.get('status') in ('succeeded', 'canceled', 'mismatch'):
                self.store.set_meta('pending_payment', None)
            status = self._accept(data)
            status['payment_status'] = data.get('status')
            return status

    def start_background_refresh(self, on_change=None):
        """Раз в 6 часов (и сразу после запуска) обновлять лицензию, если есть интернет."""
        def loop():
            while True:
                if self.configured and self.store.meta('account_token'):
                    before = self.is_premium()
                    try:
                        self.check_payment()
                    except AccountError as exc:
                        log.info('License refresh skipped: %s', exc)
                    if on_change and self.is_premium() != before:
                        on_change(self.status())
                time.sleep(REFRESH_SECONDS)
        threading.Thread(target=loop, daemon=True, name='license-refresh').start()
