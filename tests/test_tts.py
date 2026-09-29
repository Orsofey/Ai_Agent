"""Проверки локального синтеза речи: список голосов и безопасный откат."""
import tempfile
import unittest
from pathlib import Path
from src.local_tts_service import (
    LocalTTSService, PIPER_VOICES, piper_models_dir, model_card,
)


class TTSServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = LocalTTSService(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_piper_voices_listed(self):
        ids = [v['id'] for v in self.service.available_voices()]
        for name in PIPER_VOICES:
            self.assertIn(name, ids)

    def test_no_non_commercial_voices(self):
        # Silero TTS (CC BY-NC) и lessac (датасет только для исследований) убраны.
        ids = [v['id'] for v in self.service.available_voices()]
        commercial = [i for i in ids if not PIPER_VOICES[i].get('trial')]
        self.assertEqual(sorted(commercial), ['amy', 'denis', 'irina'])
        # Голоса «для проверки» явно помечены — перед продажей их лицензию нужно проверить.
        self.assertEqual(sorted(i for i in ids if PIPER_VOICES[i].get('trial')), ['dmitri', 'ruslan'])

    def test_model_card_shown_when_present(self):
        folder = piper_models_dir(self.temp.name)
        folder.mkdir(parents=True, exist_ok=True)
        info = PIPER_VOICES['irina']
        (folder / info['file']).write_bytes(b'')
        (folder / (info['file'] + '.json')).write_text('{}')
        self.assertIsNone(model_card('irina', self.temp.name))
        (folder / (info['file'] + '.MODEL_CARD')).write_text('License: test', encoding='utf-8')
        self.assertEqual(model_card('irina', self.temp.name), 'License: test')

    def test_status_reports_installed_piper(self):
        # Без файлов .onnx Piper не готов — используется системный голос Windows.
        self.assertEqual(self.service.status()['piper_ready'], [])

    def test_piper_marked_installed_when_files_present(self):
        folder = piper_models_dir(self.temp.name)
        folder.mkdir(parents=True, exist_ok=True)
        for info in PIPER_VOICES.values():
            (folder / info['file']).write_bytes(b'')
            (folder / (info['file'] + '.json')).write_text('{}')
        ready = self.service.status()['piper_ready']
        self.assertEqual(sorted(ready), sorted(PIPER_VOICES))

    def test_unknown_voice_returns_none(self):
        # Неизвестный голос не должен ломать озвучку — только откат.
        self.assertIsNone(self.service.synthesize('Привет', 'неизвестный'))

    def test_empty_text_returns_none(self):
        self.assertIsNone(self.service.synthesize('   ', 'irina'))

    def test_cache_dir_created(self):
        self.assertTrue((Path(self.temp.name) / 'tts_cache').is_dir())


if __name__ == '__main__':
    unittest.main()
