"""6.2: «Стекло» по умолчанию, автономный режим (без сети), проверка «Ваших предложений», подключение браузера одной
кнопкой, телевизоры Xiaomi / Android TV без кодов, несколько телевизоров."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

from src.storage import Store  # noqa: E402


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')

    def tearDown(self):
        self.temp.cleanup()


class Reply:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.ok = data, status, status < 400

    def json(self):
        return self.data


# ---------------- «Ваши предложения» ----------------
class SupportTests(Temp):
    def server(self, bot, **kw):
        import license_server
        from support import Support as ServerSupport
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        server = license_server.LicenseServer(self.root / 'lic.db', Ed25519PrivateKey.generate(), None)
        support = ServerSupport(server, bot_token='123:abc', session=bot, **kw)
        return license_server.create_app(server, support=support).test_client(), support

    def test_chat_found_automatically_and_check(self):
        bot = Mock()
        updates = {'ok': True, 'result': [
            {'message': {'chat': {'id': -5, 'type': 'group', 'title': 'x'}}},
            {'message': {'chat': {'id': 77, 'type': 'private', 'username': 'someone'}}},
            {'message': {'chat': {'id': 42, 'type': 'private', 'username': 'Orsofey'}}},
            {'message': {'chat': {'id': 99, 'type': 'private', 'username': 'late'}}}]}
        bot.get.side_effect = lambda url, **kw: Reply(updates if 'getUpdates' in url else
                                                       {'ok': True, 'result': {'username': 'andrey_ideas_bot'}})
        bot.post.return_value = Reply({'ok': True})
        web, support = self.server(bot, telegram='orsofey')          # TELEGRAM_CHAT_ID не задан
        check = web.get('/api/support/check').get_json()
        self.assertEqual((check['token'], check['bot_ok'], check['chat'], check['bot_name']),
                         (True, True, True, 'andrey_ideas_bot'))
        self.assertTrue(web.post('/api/support/feedback', json={'text': 'Добавьте кондиционер'}).get_json()['delivered'])
        self.assertEqual(str(bot.post.call_args.kwargs['json']['chat_id']), '42')   # чат владельца по нику
        self.assertNotIn('123:abc', json.dumps(check))                              # токен не раскрывается

    def test_check_explains_telegram_errors(self):
        bot = Mock()
        bot.get.side_effect = lambda url, **kw: Reply({'ok': True, 'result': []} if 'getUpdates' in url else
                                                       {'ok': True, 'result': {'username': 'b'}})
        web, support = self.server(bot)
        check = web.get('/api/support/check').get_json()
        self.assertFalse(check['chat'])
        self.assertIn('/start', check['error'])
        bot.get.side_effect = lambda url, **kw: Reply({'ok': False, 'description': 'Unauthorized'}, 401)
        self.assertIn('Unauthorized', web.get('/api/support/check').get_json()['error'])

    def test_client_check_detects_old_server(self):
        from src.support import Support
        session = Mock()
        session.request.return_value = Reply({}, 404)
        client = Support(self.store, Mock(server_url='https://lic.test', session=session), '6.2')
        result = client.check()
        self.assertFalse(result['ok'])
        self.assertIn('папки server/', result['steps'][-1]['text'])
        self.assertIn('Не задан адрес', Support(self.store, Mock(server_url=''), '6.2').check()['steps'][0]['text'])

    def test_client_check_all_good(self):
        from src.support import Support
        session = Mock()
        session.request.return_value = Reply({'success': True, 'token': True, 'bot_ok': True, 'bot_name': 'b',
                                              'chat': True, 'telegram': 'orsofey'})
        result = Support(self.store, Mock(server_url='https://lic.test', session=session), '6.2').check()
        self.assertTrue(result['ok'], result)


if __name__ == '__main__':
    unittest.main()
