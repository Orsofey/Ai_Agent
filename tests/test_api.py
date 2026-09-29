"""Новые API: потоковый чат, ключи, темы, голосовой статус, окно настроек."""
import json
import tempfile
import unittest
from unittest.mock import Mock
from app import create_app
from src.storage import Store


class APIv5Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.agent = Mock()
        self.agent.brain = None
        self.agent.process_command.side_effect = lambda text, settings, owner=None, on_text=None: (on_text and on_text('Ответ '), 'Ответ готов')[1]
        self.speech = Mock()
        self.speech.status.return_value = {'ready': True, 'engine': 'Parakeet v3'}
        self.app = create_app(self.store, self.speech, self.agent, license=Mock(is_premium=lambda: True))
        self.client = self.app.test_client()
        self.headers = {'X-Agent-Token': self.store.meta('pairing_token'), 'X-Device-ID': 'desktop'}

    def tearDown(self):
        self.temp.cleanup()

    def post(self, route, body):
        return self.client.post('/api/' + route, json=body, headers=self.headers)

    def test_defaults(self):
        settings = self.client.get('/api/settings', headers=self.headers).json['settings']
        self.assertEqual(settings['wake_word'], 'Андрей')
        self.assertEqual(settings['theme'], 'aurora')
        self.assertEqual(settings['llm_provider'], 'local')

    def test_old_claude_setting_falls_back_to_local(self):
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('device:desktop', json.dumps({'llm_provider': 'claude'})))
        self.assertEqual(self.store.settings('device:desktop')['llm_provider'], 'local')

    def test_old_wake_word_migrates(self):
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('device:desktop', json.dumps({'wake_word': 'Орсофей', 'theme': 'dark'})))
        settings = self.store.settings('device:desktop')
        self.assertEqual((settings['wake_word'], settings['theme']), ('Андрей', 'dark'))

    def test_themes_validated(self):
        for theme in ('aurora', 'cyberpunk', 'sakura', 'ocean', 'luxe', 'dark', 'light'):
            self.assertEqual(self.post('settings', {'theme': theme}).status_code, 200)
        self.assertEqual(self.post('settings', {'theme': 'matrix'}).status_code, 400)
        self.assertEqual(self.post('settings', {'silence_ms': 100}).status_code, 400)
        self.assertEqual(self.post('settings', {'wake_word': '  '}).status_code, 400)

    def test_settings_callbacks(self):
        seen = []
        self.app.extensions['on_settings'].append(seen.append)
        self.post('settings', {'hotkey': 'ctrl+shift+a'})
        self.assertEqual(seen[-1]['hotkey'], 'ctrl+shift+a')
        self.speech.configure.assert_called()

    def test_secrets_never_returned(self):
        self.assertEqual(self.post('secrets', {'name': 'openai_api_key', 'value': 'gsk-secret'}).status_code, 200)
        body = self.client.get('/api/settings', headers=self.headers).get_data(as_text=True)
        self.assertNotIn('gsk-secret', body)
        self.assertTrue(json.loads(body)['secrets']['openai_api_key'])
        self.assertEqual(self.post('secrets', {'name': 'anthropic_api_key', 'value': 'x'}).status_code, 400)
        self.assertEqual(self.post('secrets', {'name': 'other', 'value': 'x'}).status_code, 400)

    def test_chat_stream(self):
        response = self.post('chat/stream', {'message': 'Привет', 'id': 'stream-00000001'})
        events = [json.loads(line[5:]) for line in response.get_data(as_text=True).split('\n\n') if line.startswith('data:')]
        self.assertEqual(events[0], {'type': 'delta', 'text': 'Ответ '})
        self.assertEqual(events[-1]['type'], 'done')
        self.assertEqual(events[-1]['response'], 'Ответ готов')
        again = self.post('chat/stream', {'message': 'Привет', 'id': 'stream-00000001'}).get_data(as_text=True)
        self.assertIn('"duplicate": true', again)
        self.assertEqual(self.agent.process_command.call_count, 1)

    def test_events_token_in_query(self):
        self.assertEqual(self.client.get('/api/events').status_code, 401)
        response = self.client.get('/api/events?token=' + self.store.meta('pairing_token'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.mimetype.startswith('text/event-stream'))
        response.close()

    def test_voice_without_native(self):
        self.assertFalse(self.client.get('/api/voice/status', headers=self.headers).json['native'])
        self.assertEqual(self.post('voice/listen', {}).status_code, 409)

    def test_open_settings_fallback(self):
        self.assertEqual(self.post('ui/open-settings', {}).json, {'success': True, 'opened': False})
        ui = Mock()
        self.app.extensions['ui'] = ui
        self.assertTrue(self.post('ui/open-settings', {}).json['opened'])
        ui.open_settings.assert_called_once()

    def test_tts_audio_path_traversal(self):
        self.assertEqual(self.client.get('/tts_audio/..%2Fagent.sqlite3').status_code, 404)

    def test_licenses(self):
        data = self.client.get('/api/licenses', headers=self.headers).json
        names = ' '.join(item['name'] + item['license'] for section in data['sections'] for item in section['items'])
        for required in ('Банк', 'MET Norway', 'OpenStreetMap', 'Википедия', 'CoinGecko', 'Parakeet', 'Qwen3 1.7B',
                         'llama.cpp', 'piper-tts', 'GPL-3.0'):
            self.assertIn(required, names + ' '.join(i['author'] for s in data['sections'] for i in s['items']))
        self.assertNotIn('Silero TTS', names)
        self.assertNotIn('2.5 3B', names)
        self.assertEqual([v['voice'] for v in data['voices'] if not v['trial']], ['irina', 'denis', 'amy'])
        self.assertEqual([v['voice'] for v in data['voices'] if v['trial']], ['dmitri', 'ruslan'])
        self.assertIn('page-licenses', self.client.get('/settings').get_data(as_text=True))

    def test_removed_components_rejected(self):
        self.assertEqual(self.post('settings', {'local_model': 'qwen2.5-3b'}).status_code, 400)
        self.assertEqual(self.post('settings', {'tts_voice_en': 'lessac'}).status_code, 400)
        self.assertEqual(self.post('settings', {'tts_voice': 'baya'}).status_code, 400)
        self.assertEqual(self.post('settings', {'local_model': 'qwen3-1.7b'}).status_code, 200)
        self.assertFalse(self.client.get('/api/settings', headers=self.headers).json['settings']['ddg_search'])

    def test_settings_page(self):
        html = self.client.get('/settings').get_data(as_text=True)
        for section in ('page-general', 'page-voice', 'page-recognition', 'page-ai', 'page-control', 'page-appearance'):
            self.assertIn(section, html)


if __name__ == '__main__':
    unittest.main()
