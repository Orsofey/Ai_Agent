"""Оплата через Т-Банк (Т-Бизнес, интернет-эквайринг API v2): подпись, Init, уведомление, GetState."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import license_server  # noqa: E402
from license_server import TBankKassa  # noqa: E402
from test_subscription import keys  # noqa: E402


class FakeBank:
    """Имитация API Т-Банка: проверяет подпись каждого запроса, как настоящий сервер."""

    def __init__(self, password):
        self.password = password
        self.payments = {}
        self.requests = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit('/', 1)[1]
        self.requests.append((method, json))
        if json['Token'] != TBankKassa.token(json, self.password):
            return Mock(raise_for_status=lambda: None, json=lambda: {'Success': False, 'ErrorCode': '204', 'Message': 'Неверный токен'})
        if method == 'Init':
            pid = str(1000 + len(self.payments))
            self.payments[pid] = {'Status': 'NEW', 'Amount': json['Amount'], 'OrderId': json['OrderId']}
            body = {'Success': True, 'ErrorCode': '0', 'PaymentId': pid, 'Status': 'NEW',
                    'PaymentURL': f'https://securepay.tinkoff.ru/new/{pid}'}
        else:
            body = dict(self.payments[json['PaymentId']], Success=True, ErrorCode='0', PaymentId=json['PaymentId'])
        return Mock(raise_for_status=lambda: None, json=lambda: body)


class TBankTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bank = FakeBank('secret-pass')
        self.kassa = TBankKassa('1234567890DEMO', 'secret-pass', session=self.bank, notification_url='https://srv/tbank/webhook')
        key, _ = keys()
        self.server = license_server.LicenseServer(Path(self.temp.name) / 'l.db', key, self.kassa, 'https://srv')
        self.api = license_server.create_app(self.server).test_client()
        token = self.api.post('/api/register', json={'email': 'u@mail.ru', 'password': 'secret123'}).get_json()['token']
        self.auth = {'Authorization': 'Bearer ' + token}

    def tearDown(self):
        self.temp.cleanup()

    def test_token_algorithm(self):
        params = {'TerminalKey': 'T', 'Amount': 10000, 'OrderId': 'o1', 'Description': 'x',
                  'Receipt': {'Items': []}, 'DATA': {'Email': 'a@b.ru'}}
        # Вложенные объекты не участвуют; значения по алфавиту имён + Password.
        expected = hashlib.sha256(('10000' + 'x' + 'o1' + 'pw' + 'T').encode()).hexdigest()
        self.assertEqual(TBankKassa.token(params, 'pw'), expected)
        self.assertEqual(TBankKassa.token({'Success': True, 'TerminalKey': 'T'}, 'pw'),
                         hashlib.sha256(('pw' + 'true' + 'T').encode()).hexdigest())

    def test_checkout_then_notification_unlocks(self):
        checkout = self.api.post('/api/checkout', json={'plan': 'monthly'}, headers=self.auth).get_json()
        self.assertTrue(checkout['url'].startswith('https://securepay.tinkoff.ru/new/'))
        init = self.bank.requests[0][1]
        self.assertEqual(init['Amount'], 10000)  # 100 ₽ в копейках
        self.assertEqual(init['Receipt']['Items'][0]['Amount'], 10000)
        self.assertEqual(init['NotificationURL'], 'https://srv/tbank/webhook')
        pid = checkout['payment_id']

        # Пока не оплачено — ничего не меняется.
        self.assertEqual(self.api.get(f'/api/payments/{pid}', headers=self.auth).get_json()['plan'], 'free')

        self.bank.payments[pid]['Status'] = 'CONFIRMED'
        note = {'TerminalKey': '1234567890DEMO', 'OrderId': init['OrderId'], 'Success': True, 'Status': 'CONFIRMED',
                'PaymentId': int(pid), 'ErrorCode': '0', 'Amount': 10000}
        note['Token'] = TBankKassa.token(note, 'secret-pass')
        answer = self.api.post('/tbank/webhook', json=note)
        self.assertEqual(answer.get_data(as_text=True), 'OK')
        me = self.api.get('/api/me', headers=self.auth).get_json()
        self.assertEqual(me['plan'], 'monthly')
        self.assertEqual(me['license']['payload']['plan'], 'monthly')

    def test_forged_notification_rejected(self):
        checkout = self.api.post('/api/checkout', json={'plan': 'lifetime'}, headers=self.auth).get_json()
        note = {'TerminalKey': '1234567890DEMO', 'Status': 'CONFIRMED', 'PaymentId': int(checkout['payment_id']),
                'Success': True, 'Token': 'fake'}
        self.assertEqual(self.api.post('/tbank/webhook', json=note).status_code, 400)
        # Даже с верной подписью статус перепроверяется в банке: там платёж не оплачен.
        note['Token'] = TBankKassa.token(note, 'secret-pass')
        self.api.post('/tbank/webhook', json=note)
        self.assertEqual(self.api.get('/api/me', headers=self.auth).get_json()['plan'], 'free')

    def test_amount_is_checked(self):
        pid = self.api.post('/api/checkout', json={'plan': 'lifetime'}, headers=self.auth).get_json()['payment_id']
        self.bank.payments[pid].update(Status='CONFIRMED', Amount=100)  # 1 ₽ вместо 500
        self.assertEqual(self.server.apply(pid), 'mismatch')

    def test_env_selects_tbank(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {
                'DATA_DIR': data, 'TBANK_TERMINAL_KEY': 'T1', 'TBANK_PASSWORD': 'p', 'PUBLIC_URL': 'https://x.amvera.io'}):
            os.environ.pop('YOOKASSA_SHOP_ID', None)
            app = license_server.create_app()
            kassa = app.extensions['license_server'].kassa
            self.assertIsInstance(kassa, TBankKassa)
            self.assertEqual(kassa.notification_url, 'https://x.amvera.io/tbank/webhook')


if __name__ == '__main__':
    unittest.main()
