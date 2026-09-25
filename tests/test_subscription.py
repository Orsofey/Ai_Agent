"""Аккаунт и подписка: сервер лицензий, ЮKassa, подпись Ed25519, замки на платных разделах."""
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import license_server  # noqa: E402

from app import create_app  # noqa: E402
from src.license import LicenseClient, verify  # noqa: E402
from src.storage import PremiumRequired, Store  # noqa: E402


class FakeKassa:
    """ЮKassa: платёж создаётся «в ожидании», затем тест помечает его оплаченным."""

    def __init__(self):
        self.payments = {}

    def create(self, plan, email, user_id, return_url):
        payment = {'id': f'pay-{len(self.payments) + 1:04d}-abcdef', 'status': 'pending', 'paid': False,
                   'amount': {'value': license_server.PLANS[plan]['price'], 'currency': 'RUB'},
                   'metadata': {'user_id': str(user_id), 'plan': plan},
                   'confirmation': {'confirmation_url': 'https://yoomoney.ru/checkout/' + str(len(self.payments))}}
        self.payments[payment['id']] = payment
        return payment

    def pay(self, payment_id):
        self.payments[payment_id].update(status='succeeded', paid=True)

    def get(self, payment_id):
        return dict(self.payments[payment_id])


class ServerSession:
    """requests.Session, который ходит во Flask-приложение сервера лицензий."""

    def __init__(self, client):
        self.client = client

    def request(self, method, url, json=None, headers=None, timeout=None):
        path = url.split('://', 1)[1].split('/', 1)[1]
        response = self.client.open('/' + path, method=method, json=json, headers=headers or {})
        return Mock(status_code=response.status_code, ok=response.status_code < 400,
                    json=lambda: response.get_json())


def keys():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(public).decode()


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        key, self.public = keys()
        self.kassa = FakeKassa()
        self.server = license_server.LicenseServer(root / 'licenses.db', key, self.kassa, 'https://license.test')
        self.server_client = license_server.create_app(self.server).test_client()
        self.store = Store(root / 'app')
        self.license = LicenseClient(self.store, 'https://license.test', self.public, ServerSession(self.server_client))
        self.app = create_app(self.store, Mock(status=Mock(return_value={})), Mock(), license=self.license)
        self.client = self.app.test_client()
        self.headers = {'X-Agent-Token': self.store.meta('pairing_token'), 'X-Device-ID': 'phone1'}

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, body=None):
        return self.client.post('/api/' + path, json=body or {}, headers=self.headers)

    def buy(self, plan):
        self.assertEqual(self.post('account/checkout', {'plan': plan}).status_code, 200)
        payment_id = self.store.meta('pending_payment')
        self.kassa.pay(payment_id)
        return payment_id

    def test_premium_sections_locked_until_paid(self):
        response = self.post('settings', {'theme': 'cyberpunk'})
        self.assertEqual(response.status_code, 402)
        self.assertTrue(response.get_json()['premium_required'])
        self.assertEqual(self.post('settings', {'tts_rate': 150}).status_code, 402)
        self.assertEqual(self.post('settings', {'stt_engine': 'gigaam'}).status_code, 402)
        # Бесплатные настройки работают.
        self.assertEqual(self.post('settings', {'wake_word': 'Джарвис'}).status_code, 200)
        self.assertFalse(self.client.get('/api/settings', headers=self.headers).get_json()['premium'])

    def test_register_pay_monthly_unlocks(self):
        response = self.post('account/register', {'email': 'User@Mail.ru', 'password': 'secret123'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['account']['email'], 'user@mail.ru')
        self.assertFalse(self.license.is_premium())
        self.buy('monthly')
        account = self.post('account/check').get_json()['account']
        self.assertTrue(account['premium'])
        self.assertEqual(account['plan'], 'monthly')
        self.assertIsNone(self.store.meta('pending_payment'))
        self.assertEqual(self.post('settings', {'theme': 'cyberpunk'}).status_code, 200)
        self.assertEqual(self.store.settings('device:phone1')['theme'], 'cyberpunk')

    def test_lifetime_and_login_on_second_pc(self):
        self.post('account/register', {'email': 'a@b.ru', 'password': 'secret123'})
        self.buy('lifetime')
        self.post('account/check')
        other = LicenseClient(Store(Path(self.temp.name) / 'pc2'), 'https://license.test', self.public,
                              ServerSession(self.server_client))
        self.assertFalse(other.is_premium())
        status = other.login('a@b.ru', 'secret123')
        self.assertEqual((status['plan'], status['premium']), ('lifetime', True))
        with self.assertRaises(Exception):
            other.login('a@b.ru', 'wrong-password')

    def test_unpaid_payment_changes_nothing(self):
        self.post('account/register', {'email': 'a@b.ru', 'password': 'secret123'})
        self.post('account/checkout', {'plan': 'monthly'})
        account = self.post('account/check').get_json()['account']
        self.assertFalse(account['premium'])
        self.assertTrue(account['pending_payment'])

    def test_webhook_is_verified_and_applied_once(self):
        self.post('account/register', {'email': 'a@b.ru', 'password': 'secret123'})
        payment_id = self.buy('monthly')
        # Поддельное уведомление о неоплаченном платеже ничего не даёт; настоящее — ровно 30 дней.
        for _ in range(3):
            self.server_client.post('/yookassa/webhook', json={'event': 'payment.succeeded', 'object': {'id': payment_id}})
        with self.server.connect() as db:
            expires = db.execute('SELECT expires FROM users').fetchone()[0]
        days = (license_server.parse_iso(expires) - license_server.now()).days
        self.assertIn(days, (29, 30))

    def test_amount_mismatch_rejected(self):
        self.post('account/register', {'email': 'a@b.ru', 'password': 'secret123'})
        payment_id = self.buy('lifetime')
        self.kassa.payments[payment_id]['amount'] = {'value': '1.00', 'currency': 'RUB'}
        self.assertEqual(self.server.apply(payment_id), 'mismatch')
        self.assertFalse(self.post('account/check').get_json()['account']['premium'])

    def test_forged_license_rejected(self):
        self.post('account/register', {'email': 'a@b.ru', 'password': 'secret123'})
        document = json.loads(self.store.meta('license'))
        document['payload']['plan'] = 'lifetime'
        self.store.set_meta('license', json.dumps(document))
        self.license._cache = None
        self.assertIsNone(verify(document, self.public))
        self.assertFalse(self.license.is_premium())

    def test_expired_month_locks_again(self):
        self.post('account/register', {'email': 'a@b.ru', 'password': 'secret123'})
        self.buy('monthly')
        self.post('account/check')
        self.assertTrue(self.license.is_premium())
        self.post('settings', {'theme': 'luxe'})
        with self.server.connect() as db:
            db.execute("UPDATE users SET expires='2020-01-01T00:00:00Z'")
        self.license.refresh()
        self.assertFalse(self.license.is_premium())
        # Платные значения не стираются, но не действуют до продления.
        self.assertEqual(self.store.settings('device:phone1')['theme'], 'aurora')
        self.assertEqual(self.store.settings('device:phone1', raw=True)['theme'], 'luxe')
        with self.assertRaises(PremiumRequired):
            self.store.save_settings('device:phone1', {'theme': 'sakura'})

    def test_logout(self):
        self.post('account/register', {'email': 'a@b.ru', 'password': 'secret123'})
        self.buy('lifetime')
        self.post('account/check')
        account = self.post('account/logout').get_json()['account']
        self.assertFalse(account['logged_in'])
        self.assertFalse(account['premium'])

    def test_not_configured(self):
        client = LicenseClient(Store(Path(self.temp.name) / 'pc3'), '', '')
        self.assertFalse(client.is_premium())
        self.assertFalse(client.status()['configured'])
        with self.assertRaises(Exception) as ctx:
            client.login('a@b.ru', 'secret123')
        self.assertEqual(ctx.exception.code, 503)

    def test_server_validation(self):
        bad = self.server_client.post('/api/register', json={'email': 'нет', 'password': 'secret123'})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.server_client.get('/api/me').status_code, 401)
        for _ in range(10):
            self.server_client.post('/api/login', json={'email': 'x@y.ru', 'password': 'wrongpass'})
        blocked = self.server_client.post('/api/login', json={'email': 'x@y.ru', 'password': 'wrongpass'})
        self.assertIn('Слишком много', blocked.get_json()['message'])


if __name__ == '__main__':
    unittest.main()
