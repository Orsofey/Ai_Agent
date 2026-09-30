"""5.9: «Интеграции» с кнопкой «Подключить», «Все команды», настройки ПК с телефона, голос ПК на телефоне, дикторы."""
import base64
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from app import create_app
from src import connectors
from src.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def make_app(store=None, agent=None):
    store = store or Store(tempfile.mkdtemp())
    app = create_app(store, Mock(status=Mock(return_value={})), agent or Mock(), license=Mock(is_premium=lambda: True))
    return app, store, {'X-Agent-Token': store.meta('pairing_token')}


def blank_keys(case):
    """Тесты не должны зависеть от ключей, которые разработчик вписал в connector_config.py или переменные окружения."""
    from src import connectors_apps
    for name in dir(connectors.cfg):
        if name.isupper():
            patcher = patch.object(connectors.cfg, name, '')
            patcher.start()
            case.addCleanup(patcher.stop)
    classes = [v for m in (connectors, connectors_apps) for v in vars(m).values()
               if isinstance(v, type) and issubclass(v, connectors.OAuthConnector) and v is not connectors.TrackerConnector]
    for cls in classes:
        for attr in ('client_id', 'client_secret'):
            if attr in vars(cls):
                patcher = patch.object(cls, attr, '')
                patcher.start()
                case.addCleanup(patcher.stop)


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class SettingsLayoutTests(unittest.TestCase):
    def test_navigation_order_and_pages(self):
        html = (ROOT / 'templates/settings.html').read_text(encoding='utf-8')
        pages = re.findall(r'nav-item[^>]*data-page="(\w+)"', html)
        self.assertEqual(pages[:3], ['account', 'general', 'commands'])
        self.assertIn('integrations', pages)
        self.assertNotIn('tracker', pages)
        self.assertNotIn('profile', pages)
        general = html.split('id="page-general"')[1].split('</section>')[0]
        self.assertIn('id="export"', general)  # «Данные» — внизу «Общих»


class CatalogTests(unittest.TestCase):
    def test_commands_endpoint(self):
        app, _, headers = make_app()
        data = app.test_client().get('/api/commands', headers=headers).get_json()
        titles = [c['title'] for c in data['categories']]
        self.assertIn('Браузер и сайты', titles)
        self.assertIn('Интеграции', titles)
        self.assertGreater(sum(len(c['items']) for c in data['categories']), 80)


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        blank_keys(self)
        self.store = Store(tempfile.mkdtemp())
        self.http = Mock()
        self.opened = []
        self.hub = connectors.Connectors(self.store, http=self.http, opener=self.opened.append)

    def test_status_lists_all_apps(self):
        ids = [c['id'] for c in self.hub.status()]
        self.assertEqual(ids[:5], ['tracker', 'github', 'google_docs', 'google_sheets', 'miro'])

    def test_google_oauth_flow_and_docs(self):
        docs = self.hub.get('google_docs')
        with patch.object(connectors.GoogleDocsConnector, 'client_id', 'cid'), \
                patch.object(connectors.GoogleDocsConnector, 'client_secret', 'sec'):
            start = docs.start('http://127.0.0.1:5000/')
            query = parse_qs(urlparse(start['url']).query)
            self.assertEqual(query['redirect_uri'], ['http://127.0.0.1:5000/oauth/google_docs/callback'])
            self.assertEqual(query['code_challenge_method'], ['S256'])
            self.http.post.return_value = Response({'access_token': 'AT', 'refresh_token': 'RT', 'expires_in': 3600})
            self.http.get.return_value = Response({'email': 'me@gmail.com'})
            self.assertEqual(self.hub.callback('google_docs', 'CODE', query['state'][0]), 'me@gmail.com')
            sent = self.http.post.call_args.kwargs['data']
            self.assertEqual((sent['code'], sent['client_secret']), ('CODE', 'sec'))
            self.assertIn('code_verifier', sent)
        self.assertTrue(self.hub.get('google_sheets').connected())  # один вход Google на оба приложения
        with self.assertRaises(connectors.ConnectorError):
            self.hub.callback('google_docs', 'CODE', 'wrong-state')
        self.http.request.side_effect = [Response({'documentId': 'D1'})]
        self.assertIn('Создал документ «план поездки»', self.hub.handle('создай документ план поездки'))
        self.assertEqual(self.opened, ['https://docs.google.com/document/d/D1/edit'])

    def test_sheets_append(self):
        self.store.set_meta('connector:google', '{"access_token": "AT"}')
        self.http.request.side_effect = [Response({'files': [{'id': 'S1', 'name': 'Расходы'}]}), Response({})]
        reply = self.hub.handle('добавь в таблицу расходы строку: кофе, 250')
        self.assertEqual(reply, 'Добавил в «Расходы»: кофе, 250.0.')
        self.assertEqual(self.http.request.call_args.kwargs['json'], {'values': [['кофе', 250.0]]})

    def test_github_token_and_commands(self):
        self.http.get.return_value = Response({'login': 'orsofey'})
        self.assertEqual(self.hub.get('github').use_token('ghp_x'), 'orsofey')
        self.http.request.side_effect = [Response([{'name': 'ai_agent', 'full_name': 'orsofey/ai_agent'}]),
                                         Response([{'name': 'ai_agent', 'full_name': 'orsofey/ai_agent'}]),
                                         Response({'number': 7})]
        self.assertEqual(self.hub.handle('мои репозитории'), 'Последние репозитории: ai_agent.')
        self.assertIn('№7', self.hub.handle('создай issue в репозитории ai_agent: не работает звук'))
        self.assertEqual(self.http.request.call_args.kwargs['json'], {'title': 'не работает звук'})

    def test_github_device_flow(self):
        github = self.hub.get('github')
        with patch.object(connectors.cfg, 'GITHUB_CLIENT_ID', 'gh'):
            self.http.post.return_value = Response({'device_code': 'DC', 'user_code': 'ABCD-1234',
                                                    'verification_uri': 'https://github.com/login/device'})
            self.assertEqual(github.start('http://x')['device']['code'], 'ABCD-1234')
            self.http.post.return_value = Response({'error': 'authorization_pending'})
            self.assertEqual(github.poll(), {'done': False})
            self.http.post.return_value = Response({'access_token': 'T'})
            self.http.get.return_value = Response({'login': 'orsofey'})
            self.assertEqual(github.poll(), {'done': True})
        self.assertEqual(github.status()['user'], 'orsofey')

    def test_not_configured_has_clear_message(self):
        with self.assertRaises(connectors.ConnectorError) as error:
            self.hub.get('miro').start('http://x')
        self.assertIn('INTEGRATIONS_OAUTH', str(error.exception))
        self.assertIsNone(self.hub.handle('создай доску идеи'))  # не подключено — команда идёт дальше

    def test_tracker_connect_saves_login(self):
        from src.tracker import TrackerClient
        tracker = TrackerClient(self.store, session=Mock())
        hub = connectors.Connectors(self.store, tracker=tracker, http=self.http)
        self.store.set_meta('tracker_url', 'https://tracker.example')
        start = hub.get('tracker').start('http://127.0.0.1:5000')
        self.assertTrue(start['url'].startswith('https://tracker.example/connect?'))
        state = parse_qs(urlparse(start['url']).query)['state'][0]
        self.http.post.return_value = Response({'access_token': 'TT', 'user': {'name': 'Орсофей'}})
        self.assertEqual(hub.callback('tracker', 'C', state), 'Орсофей')
        self.assertTrue(tracker.connected)
        self.assertEqual(hub.get('tracker').status()['user'], 'Орсофей')


class ConnectorApiTests(unittest.TestCase):
    def setUp(self):
        blank_keys(self)

    def test_endpoints_and_callback_page(self):
        app, store, headers = make_app()
        client = app.test_client()
        items = client.get('/api/connectors', headers=headers).get_json()['items']
        self.assertGreaterEqual(len(items), 5)
        with patch.object(connectors.GoogleDocsConnector, 'client_id', 'cid'):
            data = client.post('/api/connectors/google_docs/connect', headers=headers, json={}).get_json()
        self.assertIn('accounts.google.com', data['url'])
        page = client.get('/oauth/google_docs/callback?code=x&state=bad')
        self.assertEqual(page.status_code, 200)
        self.assertIn('устарела', page.get_data(as_text=True))
        bad = client.post('/api/connectors/miro/connect', headers=headers, json={})
        self.assertEqual(bad.status_code, 400)


class PhoneApiTests(unittest.TestCase):
    def test_remote_settings_roundtrip(self):
        app, store, headers = make_app()
        client = app.test_client()
        data = client.get('/api/remote/settings', headers=dict(headers, **{'X-Device-ID': 'android-x'})).get_json()
        self.assertEqual([s['id'] for s in data['sections']][0], 'general')
        voices = next(f for s in data['sections'] for f in s['fields'] if f['key'] == 'voice_preset')['options']
        self.assertEqual([v['value'] for v in voices][:3], ['jarvis', 'friday', 'narrator'])
        saved = client.post('/api/remote/settings', headers=headers, json={'values': {'theme': 'luxe'}}).get_json()
        self.assertEqual(saved['values']['theme'], 'luxe')
        self.assertEqual(store.settings('device:desktop')['theme'], 'luxe')

    def test_phone_voice_is_wav_base64(self):
        app, store, headers = make_app()
        wav = Path(tempfile.mkdtemp()) / 'a.wav'
        wav.write_bytes(b'RIFFxxxxWAVE')
        with patch.object(app.extensions['local_tts'], 'synthesize', return_value=str(wav)) as synth:
            data = app.test_client().post('/api/tts/phone', headers=headers, json={'text': 'Привет'}).get_json()
        self.assertEqual(base64.b64decode(data['audio']), b'RIFFxxxxWAVE')
        self.assertEqual(synth.call_args.kwargs['preset'], 'jarvis')


class VoiceTests(unittest.TestCase):
    def test_narrators_available(self):
        from src.local_tts_service import LocalTTSService, PIPER_VOICES
        self.assertIn('dmitri', PIPER_VOICES)
        self.assertIn('ruslan', PIPER_VOICES)
        voices = LocalTTSService(tempfile.mkdtemp()).assistant_voices()
        self.assertEqual([v['id'] for v in voices][:7], ['jarvis', 'friday', 'narrator', 'irina', 'denis', 'dmitri', 'ruslan'])
        store = Store(tempfile.mkdtemp())
        store.save_settings('u', {'voice_preset': 'dmitri'})
        self.assertEqual(store.settings('u')['voice_preset'], 'dmitri')

    def test_download_item(self):
        from src import model_downloader
        with patch('src.local_tts_service.ensure_piper_voice', return_value=('x', 'y')) as ensure:
            self.assertTrue(model_downloader.download(Path(tempfile.mkdtemp()), ['piper:ruslan'], report=lambda *a: None))
        ensure.assert_called_once()
        self.assertEqual(ensure.call_args.args[0], 'ruslan')


if __name__ == '__main__':
    unittest.main()
