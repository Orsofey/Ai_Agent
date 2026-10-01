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


# ---------------- автономный режим ----------------
class NetworkTests(Temp):
    def setUp(self):
        super().setUp()
        from src import network
        self.network = network
        self.addCleanup(lambda: network._state.update(online=True))

    def test_local_addresses(self):
        local = self.network.is_local
        for host in ('127.0.0.1', 'localhost', '192.168.1.40', '10.0.0.5', '172.20.1.1', 'tv.local', 'NAS', '::1',
                     'fe80::1', '239.255.255.250', None):
            self.assertTrue(local(host), host)
        for host in ('8.8.8.8', 'api.telegram.org', 'ya.ru', '2a00:1450::1', '172.32.0.1'):
            self.assertFalse(local(host), host)
        self.assertTrue(self.network.is_web_url('https://youtube.com/watch?v=1'))
        self.assertFalse(self.network.is_web_url('http://192.168.1.1/'))

    def test_guard_blocks_internet_but_not_home_network(self):
        import socket
        import webbrowser
        net = self.network.Network(self.store)
        net.set(False)
        with self.assertRaises(socket.gaierror):
            socket.getaddrinfo('example.com', 443)
        sock = socket.socket()
        with self.assertRaises(self.network.Offline):
            sock.connect(('93.184.216.34', 443))
        sock.close()
        self.assertFalse(webbrowser.open('https://ya.ru'))
        self.assertTrue(socket.getaddrinfo('127.0.0.1', 80))        # свой компьютер — можно
        server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(1)
        client = socket.socket(); client.connect(server.getsockname())  # локальное соединение работает
        client.close(); server.close()
        net.set(True)
        self.assertTrue(socket.getaddrinfo('127.0.0.1', 80))

    def test_voice_and_persistence(self):
        net = self.network.Network(self.store)
        self.assertIsNone(net.handle('отключи интернет у планшета'))     # это роутер, не агент
        self.assertIn('Отключился от сети', net.handle('Отключись от сети'))
        self.assertFalse(net.online)
        self.assertEqual(self.store.meta('network'), 'off')
        self.assertIn('уже работаю без сети', net.handle('перейди в офлайн режим'))
        self.assertFalse(self.network.Network(self.store).online)      # после перезапуска — тоже без сети
        self.assertIn('без сети', net.handle('ты в сети?'))
        self.assertIn('Подключился', net.handle('Андрей подключись к сети'.split(' ', 1)[1]))
        self.assertTrue(net.online)

    def test_settings_forced_local_and_browser(self):
        net = self.network.Network(self.store)
        net.set(False)
        settings = net.settings({'llm_web_search': True, 'llm_provider': 'openai',
                                 'openai_base_url': 'https://api.groq.com/openai/v1'})
        self.assertEqual((settings['llm_web_search'], settings['llm_provider']), (False, 'local'))
        local = net.settings({'llm_provider': 'openai', 'openai_base_url': 'http://127.0.0.1:11434/v1'})
        self.assertEqual(local['llm_provider'], 'openai')                # Ollama на этом ПК — можно
        browser = Mock()
        wrapped = self.network.OfflineBrowser(browser)
        self.assertIn('без сети', wrapped.call('open', 'https://youtube.com'))
        wrapped.call('tabs')
        browser.call.assert_called_once_with('tabs')

    def test_agent_and_api(self):
        from app import create_app
        from src import connectors
        app = create_app(self.store, Mock(status=Mock(return_value={})), Mock(),
                         license=Mock(is_premium=lambda: True))
        client = app.test_client()
        headers = {'X-Agent-Token': self.store.meta('pairing_token')}
        self.assertTrue(client.get('/api/network', headers=headers).get_json()['online'])
        self.assertFalse(client.post('/api/network', json={'online': False}, headers=headers).get_json()['online'])
        hub = connectors.Connectors(self.store, http=Mock())
        hub.get('todoist').save({'access_token': 't'})
        self.assertIn('без сети', hub.handle('Что в Todoist на сегодня?'))
        client.post('/api/network', json={'online': True}, headers=headers)

    def test_agent_voice_command(self):
        from src.agent import LocalComputerAgent
        agent = LocalComputerAgent(Mock(), brain=None)
        agent.network = self.network.Network(self.store)
        self.assertIn('Отключился', agent.process_command('Андрей, отключись от сети', {'wake_word': 'Андрей'}))
        self.assertIn('Подключился', agent.process_command('Андрей, подключись к сети', {'wake_word': 'Андрей'}))
