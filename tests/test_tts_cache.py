"""Regression checks for concurrent requests, bounded storage and recording routing."""
import json
import os
import tempfile
import threading
import time
import unittest
import wave
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.local_tts_service import LocalTTSService
import src.local_tts_service as service_module
from src.tts_cache import prune, write_wav
from src import voice_samples


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_parallel_requests_share_one_synthesis_across_service_instances(self):
        services = [LocalTTSService(self.root), LocalTTSService(self.root)]
        callers = threading.Barrier(8)
        count = []

        def synth(*args, **kwargs):
            count.append(1)
            time.sleep(0.02)
            return np.arange(200, dtype=np.int16), 22050

        for service in services:
            service.synthesize_array = synth

        def call(index):
            callers.wait(timeout=5)
            return services[index % 2].synthesize('Одинаковый ответ')

        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = list(pool.map(call, range(8)))
        self.assertEqual(len(count), 1)
        self.assertEqual(len(set(paths)), 1)
        with wave.open(paths[0]) as wav:
            self.assertEqual(wav.getnframes(), 200)
        self.assertEqual(list(services[0].cache.glob('*.tmp')), [])

    def test_failed_write_removes_temporary_file_and_preserves_previous_audio(self):
        path = self.root / 'answer.wav'
        path.write_bytes(b'previous audio')
        with patch('src.tts_cache.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                write_wav(path, np.zeros(10, dtype=np.int16), 22050)
        self.assertEqual(path.read_bytes(), b'previous audio')
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_cleanup_expires_old_audio_and_evicts_oldest_within_budget(self):
        for index, modified in enumerate((10, 80, 90, 95)):
            path = self.root / f'{index}.wav'
            path.write_bytes(b'x' * 20)
            os.utime(path, (modified, modified))
        protected = self.root / '3.wav'
        prune(self.root, keep=protected, max_age=50, max_bytes=40, now=100)
        self.assertEqual(sorted(p.name for p in self.root.glob('*.wav')), ['2.wav', '3.wav'])

    def test_model_replacement_changes_cache_key(self):
        folder = self.root / 'models' / 'voices'
        folder.mkdir(parents=True)
        onnx = folder / 'jarvis.onnx'
        onnx.write_bytes(b'model A')
        (folder / 'jarvis.onnx.json').write_text('{}')
        service = LocalTTSService(self.root)
        before = service.cache_identity('Текст', preset='jarvis')
        onnx.write_bytes(b'model B changed')
        self.assertNotEqual(before, service.cache_identity('Текст', preset='jarvis'))

    def test_character_model_reads_arbitrary_text_without_film_effects(self):
        folder = self.root / 'models' / 'voices'
        folder.mkdir(parents=True)
        (folder / 'friday.onnx').write_bytes(b'model')
        (folder / 'friday.onnx.json').write_text('{}')
        service = LocalTTSService(self.root)
        with patch('src.local_tts_service.get_piper_voice', return_value=object()) as load, \
             patch('src.local_tts_service._piper_pcm', return_value=(b'\x01\x00', 22050)), \
             patch('src.voice_fx.apply', side_effect=AssertionError('custom voice must remain unchanged')):
            audio, _ = service.synthesize_array('Произвольная новая фраза', preset='friday')
        load.assert_called_once_with('custom:friday', self.root)
        self.assertEqual(audio.tolist(), [1])

    def test_model_cache_distinguishes_roots_and_releases_old_models(self):
        paths = []
        for index in range(4):
            root = self.root / str(index)
            folder = root / 'models' / 'voices'
            folder.mkdir(parents=True)
            (folder / 'friday.onnx').write_bytes(b'model')
            (folder / 'friday.onnx.json').write_text('{}')
            paths.append(root)
        loader = MockLoader()
        service_module.clear_voice_cache()
        try:
            with patch.dict('sys.modules', {'piper': types.SimpleNamespace(PiperVoice=loader)}):
                first = service_module.get_piper_voice('custom:friday', paths[0])
                second = service_module.get_piper_voice('custom:friday', paths[1])
                self.assertIsNot(first, second)
                self.assertIs(second, service_module.get_piper_voice('custom:friday', paths[1]))
                for root in paths[2:]:
                    service_module.get_piper_voice('custom:friday', root)
                self.assertEqual(len(service_module._piper_voices), 3)
                service_module.get_piper_voice('custom:friday', paths[0])
                self.assertEqual(len(loader.loaded), 5)
        finally:
            service_module.clear_voice_cache()


class MockLoader:
    def __init__(self):
        self.loaded = []

    def load(self, *args, **kwargs):
        voice = object()
        self.loaded.append(voice)
        return voice


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pack = self.root / 'models' / 'voice_packs' / 'friday'
        self.pack.mkdir(parents=True)
        write_wav(self.pack / 'reply.wav', np.array([1, 2, 3], dtype=np.int16), 22050)
        self.manifest = {'phrases': [{'text': 'Да, сэр.', 'file': 'reply.wav'}]}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        (self.pack / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_recordings_work_without_neural_model_and_keep_original_timbre(self):
        service = LocalTTSService(self.root)
        with patch('src.local_tts_service.get_piper_voice', side_effect=AssertionError('must not load model')):
            audio, rate = service.synthesize_array('ДА, СЭР!', preset='friday', rate=1.8)
        self.assertEqual(audio.tolist(), [1, 2, 3])
        self.assertEqual(rate, 22050)

    def test_dynamic_response_is_not_replaced_by_short_recording(self):
        self.assertIsNone(voice_samples.find('Да, сэр, открыл Telegram.', 'friday', self.root))

    def test_pack_cannot_read_audio_outside_its_folder(self):
        self.manifest['phrases'][0]['file'] = '../outside.wav'
        self.save()
        self.assertIsNone(voice_samples.find('Да, сэр.', 'friday', self.root))

    def test_replacing_sample_changes_disk_and_ram_identity(self):
        service = LocalTTSService(self.root)
        before = service.cache_identity('Да, сэр.', preset='friday')
        write_wav(self.pack / 'reply.wav', np.zeros(20, dtype=np.int16), 22050)
        self.assertNotEqual(before, service.cache_identity('Да, сэр.', preset='friday'))

    def test_bundled_jarvis_pack_contains_readable_audio_for_every_phrase(self):
        pack = Path(__file__).resolve().parents[1] / 'models' / 'voice_packs' / 'jarvis'
        data = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['phrases']), 58)
        for phrase in data['phrases']:
            with self.subTest(phrase=phrase['text']):
                result = voice_samples.load(phrase['text'], 'jarvis', self.root)
                self.assertIsNotNone(result)
                self.assertGreater(len(result[0]), 0)


if __name__ == '__main__':
    unittest.main()
