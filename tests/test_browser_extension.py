"""Расширение «Андрей» в настоящем Chromium: подключение к агенту, переключение на уже открытую вкладку,
открытие ссылок в браузере пользователя, управление плеером, закрытие вкладок сайта."""
import http.server
import os
import socketserver
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from app import create_app
from src.browser_bridge import BridgeError, ExtensionBridge
from src.browser_control import BrowserController
from src.storage import Store

EXTENSION = Path(__file__).resolve().parents[1] / 'browser_extension'
CHROMIUM = '/opt/pw-browsers/chromium'


class BridgeUnitTests(unittest.TestCase):
    def test_round_trip(self):
        bridge = ExtensionBridge()
        self.assertFalse(bridge.connected)
        with self.assertRaises(BridgeError):
            bridge.send('url')
        self.assertIsNone(bridge.next_command(wait=0, browser='Yandex Browser'))
        self.assertTrue(bridge.connected)
        self.assertTrue(bridge.matches('yandex'))
        self.assertFalse(bridge.matches('chrome'))

        def extension():
            command = bridge.next_command(wait=2)
            bridge.complete(command['id'], True, {'focused': True, 'got': command['args']})
        threading.Thread(target=extension, daemon=True).start()
        self.assertEqual(bridge.send('open', url='https://a.ru'), {'focused': True, 'got': {'url': 'https://a.ru'}})

    def test_browser_controller_prefers_extension(self):
        controller = BrowserController(Path(tempfile.mkdtemp()))
        controller.bridge = Mock(connected=True)
        controller.bridge.send.return_value = {'focused': True}
        self.assertEqual(controller.call('open', 'https://www.youtube.com'), 'Переключаюсь на Ютуб')
        controller.bridge.send.assert_called_once_with('open', url='https://www.youtube.com')

    def test_extension_origin_allowed_only_for_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            agent = Mock()
            agent.browser.bridge = ExtensionBridge()
            client = create_app(store, Mock(status=Mock(return_value={})), agent,
                                license=Mock(is_premium=lambda: True)).test_client()
            headers = {'X-Agent-Token': store.meta('pairing_token'), 'Origin': 'chrome-extension://abcdef'}
            self.assertEqual(client.get('/api/ext/next?wait=0', headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/history', headers=headers).status_code, 403)
            self.assertEqual(client.get('/api/ext/next?wait=0', headers={'Origin': 'chrome-extension://abcdef'}).status_code, 401)


@unittest.skipUnless(os.path.exists(CHROMIUM), 'нужен Chromium для проверки расширения')
class ExtensionInChromiumTests(unittest.TestCase):
    def test_extension_end_to_end(self):
        from playwright.sync_api import sync_playwright
        from waitress import create_server
        site = tempfile.mkdtemp()
        Path(site, 'index.html').write_text('<title>A</title>')
        Path(site, 'video.html').write_text('<title>V</title><button aria-label="Play" onclick="window.played=1">▶</button>')
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=site, **k)  # noqa: E731
        httpd = socketserver.TCPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{httpd.server_address[1]}'
        store = Store(tempfile.mkdtemp())
        browser = BrowserController(store.root)
        browser.bridge = ExtensionBridge()
        agent = Mock()
        agent.browser = browser
        app = create_app(store, Mock(status=Mock(return_value={})), agent, license=Mock(is_premium=lambda: True))
        server = create_server(app, host='127.0.0.1', port=0, threads=8)
        threading.Thread(target=server.run, daemon=True).start()
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    tempfile.mkdtemp(), executable_path=CHROMIUM, headless=True,
                    args=[f'--disable-extensions-except={EXTENSION}', f'--load-extension={EXTENSION}', '--headless=new'])
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                worker.evaluate(f"chrome.storage.local.set({{port: {server.effective_port}, token: '{store.meta('pairing_token')}'}})")
                for _ in range(60):
                    if browser.bridge.connected:
                        break
                    time.sleep(0.25)
                self.assertTrue(browser.bridge.connected, 'расширение не подключилось')
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(base + '/index.html')
                context.new_page().goto('about:blank')
                count = len(context.pages)
                self.assertTrue(browser.call('open', base + '/index.html').startswith('Переключаюсь'))
                self.assertEqual(len(context.pages), count, 'уже открытый сайт не должен открываться второй раз')
                self.assertTrue(browser.call('open', base + '/video.html').startswith('Открываю'))
                self.assertEqual(browser.call('url'), base + '/video.html')
                self.assertTrue(browser.bridge.send('media', action='play'))
                self.assertIn('Закрываю', browser.call('close_site', base + '/video.html'))
                context.close()
        finally:
            server.close()
            httpd.shutdown()


if __name__ == '__main__':
    unittest.main()
