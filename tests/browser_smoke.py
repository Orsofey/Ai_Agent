"""UI smoke test in a real Chromium (run explicitly, not part of unittest discovery).

    python tests/browser_smoke.py            # после `python -m playwright install chromium`
    PLAYWRIGHT_CHROMIUM=/path/to/chrome python tests/browser_smoke.py

Проверяет: потоковый ответ в чате, отдельное окно настроек, смену темы с
синхронизацией между окнами, автосохранение настроек. STT и агент — заглушки.
"""
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waitress import create_server
from playwright.sync_api import sync_playwright
from app import create_app
from src.storage import Store


def main():
    with tempfile.TemporaryDirectory() as folder:
        store = Store(folder)
        agent = Mock()
        agent.brain = None

        def run(text, settings, owner=None, on_text=None):
            for word in ('Курс ', 'доллара ', '81,52 ', 'рубля.'):
                if on_text:
                    on_text(word)
            return 'Курс доллара 81,52 рубля.'
        agent.process_command.side_effect = run
        speech = Mock()
        speech.status.return_value = {'ready': True, 'engine': 'Parakeet v3', 'loading': False, 'error': None}
        app = create_app(store, speech, agent)
        server = create_server(app, host='127.0.0.1', port=0, threads=8)
        threading.Thread(target=server.run, daemon=True).start()
        base = f'http://127.0.0.1:{server.effective_port}'
        token = store.meta('pairing_token')
        errors = []
        try:
            with sync_playwright() as pw:
                executable = os.getenv('PLAYWRIGHT_CHROMIUM')
                browser = pw.chromium.launch(**({'executable_path': executable} if executable else {}))
                context = browser.new_context()
                main_page = context.new_page()
                main_page.on('pageerror', lambda e: errors.append(str(e)))
                main_page.goto(base + '/#token=' + token)
                main_page.wait_for_function("document.getElementById('engine').textContent.includes('готов')")
                main_page.fill('#chat-input', 'Какой курс доллара?')
                main_page.click('#send')
                main_page.wait_for_function("[...document.querySelectorAll('.msg.agent')].some(m => m.textContent.includes('81,52 рубля'))")
                assert agent.process_command.call_count == 1

                settings_page = context.new_page()
                settings_page.on('pageerror', lambda e: errors.append(str(e)))
                settings_page.goto(base + '/settings')
                settings_page.click('[data-page="appearance"]')
                settings_page.click('.theme-card[data-value="cyberpunk"]')
                settings_page.wait_for_function("document.documentElement.dataset.theme === 'cyberpunk'")
                main_page.wait_for_function("document.documentElement.dataset.theme === 'cyberpunk'")
                settings_page.click('[data-page="general"]')
                settings_page.fill('[data-setting="wake_word"]', 'Джарвис')
                settings_page.press('[data-setting="wake_word"]', 'Enter')
                settings_page.wait_for_function("document.getElementById('save-state').textContent.includes('Сохранено')")
                assert store.settings('device:desktop')['wake_word'] == 'Джарвис'
                assert store.settings('device:desktop')['theme'] == 'cyberpunk'
                main_page.wait_for_function("document.getElementById('agent-name').textContent === 'Джарвис'")
                browser.close()
        finally:
            server.close()
        assert not errors, errors
        print('Browser smoke test: OK')


if __name__ == '__main__':
    main()
