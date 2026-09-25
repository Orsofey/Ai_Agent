"""Встроенная нейросеть: запуск llama-server как отдельного процесса и потоковый ответ.

Вместо настоящего llama-server используется маленький Python-скрипт с тем же API
(/health и /v1/chat/completions со стримингом) — проверяется весь путь без модели.
"""
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from src.brain import Brain
from src.brain.local_llm import LocalLLMServer, find_binary, find_model, BINARY
from src.model_downloader import pick_asset
from src.storage import Store

FAKE_SERVER = textwrap.dedent('''
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = int(sys.argv[sys.argv.index('--port') + 1])
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            self.send_response(200 if self.path == '/health' else 404); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['cache_prompt'] is True
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            for word in ['Около ', '100 ', 'граммов.']:
                self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': word}}]}, ensure_ascii=False) + '\\n\\n').encode())
            self.wfile.write(b'data: [DONE]\\n\\n')
    HTTPServer(('127.0.0.1', port), H).serve_forever()
''')


@unittest.skipIf(sys.platform == 'win32', 'shell shim for the fake server is POSIX-only')
class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        runtime = root / 'models' / 'llama.cpp' / 'cpu'
        runtime.mkdir(parents=True)
        (runtime / 'fake_server.py').write_text(FAKE_SERVER)
        binary = runtime / BINARY
        binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{runtime / "fake_server.py"}" "$@"\n')
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        model_dir = root / 'models' / 'llm' / 'qwen3-4b'
        model_dir.mkdir(parents=True)
        (model_dir / 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf').write_bytes(b'GGUF')
        self.store = Store(root)
        self.server = LocalLLMServer(root)

    def tearDown(self):
        self.server.stop()
        self.temp.cleanup()

    def test_files_found(self):
        self.assertEqual(find_binary(self.store.root)[1], 'cpu')
        self.assertTrue(find_model(self.store.root, 'qwen3-4b').name.endswith('.gguf'))
        self.assertIsNone(find_model(self.store.root, 'qwen2.5-7b'))

    def test_brain_answers_through_local_server(self):
        brain = Brain(self.store, local=self.server)
        spoken = []
        settings = dict(self.store.settings('device:desktop'), llm_web_search=False)
        answer = brain.answer('Сколько белка нужно в день?', settings, on_text=spoken.append)
        self.assertEqual(answer, 'Около 100 граммов.')
        self.assertEqual(''.join(spoken), 'Около 100 граммов.')
        status = self.server.status(settings)
        self.assertTrue(status['ready'] and status['model_installed'] and status['runtime_installed'])
        args = self.server.process.args
        self.assertIn('--jinja', args)
        self.assertNotIn('-ngl', args)

    def test_missing_model_falls_back_to_installed_one(self):
        settings = {'local_model': 'qwen2.5-7b', 'llm_gpu': False}
        self.server.ensure(settings, wait=20)
        self.assertEqual(self.server.key, 'qwen3-4b')

    def test_stop_on_provider_change(self):
        self.server.ensure({'local_model': 'qwen3-4b'}, wait=20)
        self.server.apply_settings({'llm_provider': 'off'})
        self.assertFalse(self.server.running())


class ReleaseAssetTests(unittest.TestCase):
    ASSETS = [{'name': n} for n in ('llama-b7000-bin-macos-arm64.zip', 'llama-b7000-bin-win-cuda-12.4-x64.zip',
                                    'cudart-llama-bin-win-cuda-12.4-x64.zip', 'llama-b7000-bin-win-vulkan-x64.zip',
                                    'llama-b7000-bin-win-cpu-arm64.zip', 'llama-b7000-bin-win-cpu-x64.zip')]

    def test_pick_windows_builds(self):
        self.assertEqual(pick_asset(self.ASSETS, 'cpu')['name'], 'llama-b7000-bin-win-cpu-x64.zip')
        self.assertEqual(pick_asset(self.ASSETS, 'vulkan')['name'], 'llama-b7000-bin-win-vulkan-x64.zip')
        self.assertIsNone(pick_asset([{'name': 'llama-b7000-bin-ubuntu-x64.zip'}], 'cpu'))


if __name__ == '__main__':
    unittest.main()
