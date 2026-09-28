"""5.8: телефон через интернет (мост на сервере аккаунтов), все адреса ПК в ссылке подключения."""
import base64
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from relay import Relay, RelayError  # noqa: E402

from app import create_app  # noqa: E402
from src.relay_client import RelayClient, relay_key  # noqa: E402
from src.storage import Store  # noqa: E402


class FakeHttp:
    """requests.Session поверх тестового клиента сервера аккаунтов."""
    def __init__(self, client):
        self.client = client

    def post(self, url, json=None, timeout=None):
        response = self.client.post('/' + url.split('/', 3)[3], json=json)
        return Mock(status_code=response.status_code, json=lambda: response.get_json())


class RelayServerTests(unittest.TestCase):
    def test_round_trip_and_auth(self):
        relay = Relay()
        rid, key = 'A' * 20, 'k' * 64
        self.assertEqual(relay.poll(rid, key, wait=0), [])  # ПК подключился
        with self.assertRaises(RelayError):
            relay.poll(rid, 'x' * 64, wait=0)  # чужой ключ
        result = {}

        def phone():
            result['reply'] = relay.call(rid, key, {'path': '/api/chat', 'json': {'message': 'привет'}}, wait=5)
        thread = threading.Thread(target=phone)
        thread.start()
        items = []
        for _ in range(50):
            items = relay.poll(rid, key, wait=0.1)
            if items:
                break
        self.assertEqual(items[0]['json'], {'message': 'привет'})
        relay.reply(rid, key, items[0]['id'], 200, {'response': 'Здравствуйте'})
        thread.join(5)
        self.assertEqual(result['reply'], {'status': 200, 'body': {'response': 'Здравствуйте'}})

    def test_offline_and_forbidden_paths(self):
        relay = Relay()
        with self.assertRaises(RelayError) as error:
            relay.call('B' * 20, 'k' * 64, {'path': '/api/chat'})
        self.assertEqual(error.exception.code, 503)
        relay.poll('B' * 20, 'k' * 64, wait=0)
        with self.assertRaises(RelayError) as error:
            relay.call('B' * 20, 'k' * 64, {'path': '/api/settings'})
        self.assertEqual(error.exception.code, 403)


class EndToEndTests(unittest.TestCase):
    def test_phone_command_reaches_pc_through_server(self):
        import license_server
        server_app = license_server.create_app(Mock(owners=[]))
        server = server_app.test_client()
        store = Store(tempfile.mkdtemp())
        store.save_settings('device:desktop', {'remote_access': True})
        agent = Mock()
        agent.process_command.return_value = 'Открываю калькулятор.'
        speech = Mock(status=Mock(return_value={}))
        speech.transcribe.return_value = {'text': 'открой калькулятор', 'empty': False}
        license = Mock(is_premium=lambda: True, server_url='https://andrey.example')
        app = create_app(store, speech, agent, license=license)
        client = RelayClient(store, app, license, session=FakeHttp(server))
        self.assertTrue(client.enabled())
        key = relay_key(store.meta('pairing_token'))
        client.poll_once(wait=0)  # ПК на связи
        answers = {}

        def phone(name, body):
            answers[name] = server.post('/relay/phone', json=dict(body, rid=client.rid(), key=key)).get_json()
        audio = base64.b64encode(b'RIFF....WAVE').decode()
        threads = [threading.Thread(target=phone, args=('chat', {'path': '/api/chat', 'device': 'android-x',
                                                                  'json': {'message': 'открой калькулятор',
                                                                           'id': 'cmd-000000001'}})),
                   threading.Thread(target=phone, args=('voice', {'path': '/api/transcribe', 'audio': audio}))]
        for t in threads:
            t.start()
        deadline = time.time() + 10
        while len(answers) < 2 and time.time() < deadline:
            client.poll_once(wait=0.2)
            time.sleep(0.05)
        for t in threads:
            t.join(5)
        self.assertEqual(answers['chat']['body']['response'], 'Открываю калькулятор.')
        self.assertEqual(answers['voice']['body']['text'], 'открой калькулятор')
        self.assertEqual(speech.transcribe.call_args.args[0], b'RIFF....WAVE')
        bad = server.post('/relay/phone', json={'rid': client.rid(), 'key': 'z' * 64, 'path': '/api/chat'})
        self.assertEqual(bad.status_code, 403)

    def test_link_has_all_addresses_and_relay(self):
        store = Store(tempfile.mkdtemp())
        store.save_settings('device:desktop', {'remote_access': True})
        license = Mock(is_premium=lambda: True, server_url='https://andrey.example')
        app = create_app(store, Mock(status=Mock(return_value={})), Mock(), license=license)
        headers = {'X-Agent-Token': store.meta('pairing_token')}
        with patch('app.local_ips', return_value=['192.168.1.5', '10.0.0.7']):
            data = app.test_client().get('/api/connection', headers=headers).get_json()
            self.assertEqual(data['ips'], ['192.168.1.5', '10.0.0.7'])
        with patch('app.local_ips', return_value=['192.168.1.5', '10.0.0.7']), patch('segno.make') as make:
            app.test_client().get('/api/connection/qr', headers=headers, base_url='http://127.0.0.1:5000')
        link = make.call_args.args[0]
        self.assertTrue(link.startswith('http://192.168.1.5:5000/#token='))
        self.assertIn('&hosts=10.0.0.7', link)
        self.assertIn('&relay=', link)
        self.assertEqual(unquote(link.split('&relay=')[1].split('&')[0]), 'https://andrey.example')


class LocalIpTests(unittest.TestCase):
    def test_virtual_adapters_last(self):
        import app as app_module
        addr = lambda ip: Mock(family=app_module.socket.AF_INET, address=ip)  # noqa: E731
        with patch.object(app_module, 'local_ip', return_value='172.28.0.1'), \
                patch('psutil.net_if_addrs', return_value={'vEthernet (WSL)': [addr('172.28.0.1')],
                                                          'Wi-Fi': [addr('192.168.1.5')], 'Ethernet 2': [addr('10.0.0.7')]}), \
                patch('psutil.net_if_stats', return_value={}):
            self.assertEqual(app_module.local_ips(), ['192.168.1.5', '10.0.0.7', '172.28.0.1'])


if __name__ == '__main__':
    unittest.main()
