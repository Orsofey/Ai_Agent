"""Исправления по отзыву: вежливые/ослышанные команды, закрытый браузер, загрузка моделей."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.agent import LocalComputerAgent, normalize_command, looks_like_question
from src.brain import LLMError
from src.browser_control import BrowserController
from src import model_downloader as md


class CommandTests(unittest.TestCase):
    def test_polite_and_misheard(self):
        self.assertEqual(normalize_command('Закройте браузер').casefold(), 'закрой браузер')
        self.assertEqual(normalize_command('забудьте браузер'), 'закрой браузер')
        self.assertEqual(normalize_command('Откройте калькулятор').casefold(), 'открой калькулятор')
        self.assertEqual(normalize_command('Напишите текст привет').casefold(), 'напиши текст привет')
        self.assertEqual(normalize_command('Включите музыку, пожалуйста'), 'Включи музыку')
        self.assertEqual(normalize_command('забудь это'), 'забудь это')
        self.assertEqual(normalize_command('хотите чаю'), 'хотите чаю')

    def test_misheard_close_reaches_browser(self):
        browser = Mock()
        LocalComputerAgent(browser).process_command('Андрей, забудьте браузер', {'wake_word': 'Андрей'})
        browser.call.assert_called_once_with('close_browser')

    def test_no_technical_error_for_commands(self):
        brain = Mock()
        brain.answer.side_effect = LLMError('Не найден llama-server.')
        agent = LocalComputerAgent(Mock(), brain=brain)
        self.assertIn('Не понял команду', agent.process_command('сделай что-нибудь странное', {}))
        self.assertIn('llama-server', agent.process_command('Куда лучше вложить 100 тысяч рублей на год?', {}))

    def test_question_detection(self):
        self.assertTrue(looks_like_question('Сколько белка нужно в день'))
        self.assertTrue(looks_like_question('погода?'))
        self.assertFalse(looks_like_question('забудь это'))


class BrowserRecoveryTests(unittest.TestCase):
    def test_reopen_after_user_closed_window(self):
        browser = BrowserController.__new__(BrowserController)
        browser.context, browser.current, browser.pw = object(), None, None
        calls = []

        def fake_open(url):
            calls.append(browser.context)
            if len(calls) == 1:
                raise RuntimeError('Page.goto: Target page, context or browser has been closed')
            return 'Открываю Яндекс'
        browser._open = fake_open
        self.assertEqual(browser._run('open', ('https://ya.ru',)), 'Открываю Яндекс')
        self.assertIsNone(calls[1])  # контекст сброшен → будет запущен заново

    def test_close_when_already_closed(self):
        browser = BrowserController.__new__(BrowserController)
        browser.context, browser.current, browser.pw = object(), None, None
        browser._close_browser = Mock(side_effect=RuntimeError('Target closed'))
        self.assertEqual(browser._run('close_browser', ()), 'Браузер агента уже закрыт.')


class Response:
    def __init__(self, status=200, body=b'', headers=None, json_data=None):
        self.status_code, self.body, self.headers, self.json_data = status, body, headers or {}, json_data
        self.ok = status < 400
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')
    def iter_content(self, size):
        yield self.body
    def json(self):
        return self.json_data


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_resume_and_progress(self):
        target = self.root / 'model.gguf'
        (self.root / 'model.gguf.part').write_bytes(b'GGUF')
        session = Mock()
        session.get.return_value = Response(206, b'-rest', {'Content-Length': '5'})
        progress = []
        md.http_download('https://x/model.gguf', target, session, lambda d, t: progress.append((d, t)))
        self.assertEqual(target.read_bytes(), b'GGUF-rest')
        self.assertEqual(session.get.call_args.kwargs['headers'], {'Range': 'bytes=4-'})
        self.assertFalse((self.root / 'model.gguf.part').exists())

    def test_interrupted_download_keeps_part(self):
        session = Mock()
        session.get.return_value = Response(200, b'abc', {'Content-Length': '10'})
        with self.assertRaises(md.DownloadError):
            md.http_download('https://x/f', self.root / 'f', session)
        self.assertEqual((self.root / 'f.part').read_bytes(), b'abc')

    def test_llama_skips_non_build_releases(self):
        # Реальный случай: «последний» релиз — v0.5.0 (другой пакет) без архивов для Windows.
        releases = [
            {'tag_name': 'v0.5.0', 'assets': [{'name': 'gguf-0.5.0.tar.gz', 'browser_download_url': 'x'}]},
            {'tag_name': 'b11165', 'draft': False, 'assets': [
                {'name': 'llama-b11165-bin-win-cuda-12.4-x64.zip', 'browser_download_url': 'cuda'},
                {'name': 'llama-b11165-bin-win-cpu-x64.zip', 'browser_download_url': 'https://gh/b11165-cpu.zip'}]},
            {'tag_name': 'b11163', 'assets': [
                {'name': 'llama-b11163-bin-win-cpu-x64.zip', 'browser_download_url': 'https://gh/b11163-cpu.zip'}]},
        ]
        session = Mock()
        session.get.return_value = Response(json_data=releases)
        self.assertEqual(md.llama_asset_urls(session, 'cpu'), ['https://gh/b11165-cpu.zip', 'https://gh/b11163-cpu.zip'])

    def test_llama_url_from_releases_page_when_api_limited(self):
        session = Mock()
        page = SimpleNamespace(text='<a href="/ggml-org/llama.cpp/releases/tag/v0.5.0"></a>'
                                    '<a href="/ggml-org/llama.cpp/releases/tag/b11163"></a>'
                                    '<a href="/ggml-org/llama.cpp/releases/tag/b11165"></a>')
        session.get.side_effect = [Response(403, json_data={'message': 'rate limit'}), page]
        urls = md.llama_asset_urls(session, 'cpu')
        self.assertEqual(urls[0], 'https://github.com/ggml-org/llama.cpp/releases/download/b11165/llama-b11165-bin-win-cpu-x64.zip')
        self.assertEqual(len(urls), 2)

    def test_runtime_tries_previous_build_when_newest_missing(self):
        import io
        import zipfile
        from src.brain.local_llm import BINARY
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as zf:
            zf.writestr(BINARY, 'exe')
        session = Mock()

        def get(url, **kwargs):
            if 'api.github.com' in url:
                return Response(json_data=[
                    {'tag_name': 'b2', 'assets': [{'name': 'llama-b2-bin-win-cpu-x64.zip', 'browser_download_url': 'https://gh/b2.zip'}]},
                    {'tag_name': 'b1', 'assets': [{'name': 'llama-b1-bin-win-cpu-x64.zip', 'browser_download_url': 'https://gh/b1.zip'}]}])
            if url.endswith('b2.zip'):
                return Response(404)
            return Response(200, data.getvalue(), {'Content-Length': str(len(data.getvalue()))})
        session.get.side_effect = get
        with patch('src.model_downloader.sys.platform', 'win32'):
            target = md.download_llama_runtime(self.root, 'cpu', session)
        self.assertTrue((target / BINARY).exists())
        self.assertFalse(target.with_name('cpu.zip').exists())

    def test_llm_uses_backup_repo(self):
        from src.brain.local_llm import find_model
        session = Mock()

        def get(url, **kwargs):
            if 'api/models/bartowski' in url:
                return Response(404)
            if 'api/models/unsloth' in url:
                return Response(json_data={'siblings': [{'rfilename': 'Qwen3-1.7B-Q8_0.gguf'},
                                                        {'rfilename': 'Qwen3-1.7B-Q4_K_M.gguf'}]})
            self.assertIn('unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf', url)
            return Response(200, b'GGUF', {'Content-Length': '4'})
        session.get.side_effect = get
        md.download_llm(self.root, 'qwen3-1.7b', session)
        self.assertEqual(find_model(self.root, 'qwen3-1.7b').name, 'Qwen3-1.7B-Q4_K_M.gguf')

    def test_missing_items_on_first_run(self):
        with patch('src.model_downloader.find_model', return_value=None), \
             patch('src.speech.engines.bundled_models_dir', return_value=self.root / 'none'):
            items = md.missing_items(self.root, {'llm_provider': 'local', 'local_model': 'qwen3-4b', 'voice_language': 'auto'})
        self.assertEqual(items[:3], ['vad', 'parakeet', 'piper'])
        self.assertIn('llm:qwen3-4b', items)

    def test_nothing_missing_when_ai_off_and_models_present(self):
        with patch('src.model_downloader.find_model', return_value=self.root), \
             patch('src.local_tts_service.voice_files', return_value=(self.root, self.root)):
            self.assertEqual(md.missing_items(self.root, {'llm_provider': 'off'}), [])


if __name__ == '__main__':
    unittest.main()
