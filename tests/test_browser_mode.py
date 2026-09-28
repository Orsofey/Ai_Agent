"""Сайты и музыка открываются в том же браузере, что и «Открой браузер» (браузер по умолчанию)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.browser_control import BrowserController
from src.storage import Store


class BrowserModeTests(unittest.TestCase):
    def setUp(self):
        self.controller = BrowserController(Path(tempfile.mkdtemp()))

    def test_open_goes_to_default_browser(self):
        with patch('src.web_services.system_open', return_value=True) as opened:
            answer = self.controller.call('open', 'https://music.yandex.ru')
        opened.assert_called_once_with('https://music.yandex.ru')
        self.assertTrue(answer.startswith('Открываю'))
        self.assertIsNone(self.controller.context)  # отдельный браузер агента не запускался

    def test_music_search_in_default_browser(self):
        with patch('src.web_services.system_open', return_value=True) as opened:
            answer = self.controller.call('music', 'Imagine Dragons', None)
        self.assertIn('music.yandex.ru', opened.call_args[0][0])
        self.assertIn('Imagine Dragons', answer)

    def test_player_uses_media_key(self):
        with patch('src.desktop.winapi.hotkey') as hotkey:
            self.assertEqual(self.controller.call('player'), 'Готово.')
        hotkey.assert_called_once_with('media_play_pause')

    def test_extension_preferred_when_connected(self):
        self.controller.bridge = Mock(connected=True)
        self.controller.bridge.send.return_value = {'focused': False}
        with patch('src.web_services.system_open') as opened:
            self.controller.call('open', 'https://music.yandex.ru')
        opened.assert_not_called()
        self.controller.bridge.send.assert_called_once()

    def test_agent_mode_uses_worker(self):
        self.controller.mode = 'agent'
        self.controller._focus_or_open = Mock(return_value='агент')
        with patch('src.web_services.system_open') as opened:
            self.assertEqual(self.controller.call('open', 'https://ya.ru'), 'агент')
        opened.assert_not_called()

    def test_setting(self):
        store = Store(tempfile.mkdtemp())
        self.assertEqual(store.settings('u')['browser_mode'], 'user')
        store.save_settings('u', {'browser_mode': 'agent'})
        with self.assertRaises(ValueError):
            store.save_settings('u', {'browser_mode': 'other'})


if __name__ == '__main__':
    unittest.main()
