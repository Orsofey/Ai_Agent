"""Speech routes can be verified independently of missing application modules."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from flask import Flask, request

from src.local_tts_service import LocalTTSService
from src.tts_api import register_tts_routes


class AudioAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tts = LocalTTSService(self.temp.name)
        self.store = Mock()
        self.store.settings.return_value = {'voice_preset': 'jarvis', 'tts_voice': 'denis', 'tts_rate': 105}
        self.app = Flask(__name__)
        self.app.testing = True

        @self.app.before_request
        def auth():
            if request.headers.get('X-Agent-Token') != 'test-token':
                return 'Unauthorized', 401

        register_tts_routes(self.app, self.tts, self.store, lambda: 'test-owner')
        self.client = self.app.test_client()
        self.headers = {'X-Agent-Token': 'test-token'}

    def tearDown(self):
        self.temp.cleanup()

    def test_phone_returns_real_pack_wav_without_piper(self):
        response = self.client.post('/api/tts/phone', json={'text': 'Да, сэр.'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        audio = base64.b64decode(response.json['audio'])
        self.assertEqual(audio[:4], b'RIFF')
        self.assertEqual(audio[8:12], b'WAVE')

    def test_preview_and_phone_use_same_recording(self):
        response = self.client.post('/api/ai/synthesize_local', json={'text': 'Да, сэр.'}, headers=self.headers)
        self.assertTrue(response.json['success'])
        wav = self.client.get(response.json['audio_url'], headers=self.headers)
        self.assertEqual(wav.status_code, 200)
        self.assertTrue(wav.data.startswith(b'RIFF'))
        wav.close()

    def test_routes_remain_authenticated_and_reject_path_traversal(self):
        self.assertEqual(self.client.post('/api/tts/phone', json={'text': 'Да, сэр.'}).status_code, 401)
        response = self.client.get('/tts_audio/not-a-valid-name.wav', headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_invalid_input_and_missing_model_are_distinguishable(self):
        self.assertEqual(self.client.post('/api/tts/phone', json={'text': ''}, headers=self.headers).status_code, 400)
        self.tts.synthesize = Mock(return_value=None)
        self.assertEqual(self.client.post('/api/tts/phone', json={'text': 'Ответ'}, headers=self.headers).status_code, 503)


if __name__ == '__main__':
    unittest.main()
