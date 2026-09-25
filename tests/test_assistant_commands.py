import unittest
from unittest.mock import Mock, patch
from src.assistant_commands import handle


class ServiceCommands(unittest.TestCase):
    def test_open_browser_uses_system_default(self):
        with patch('src.assistant_commands.system_browser', return_value=True) as system:
            self.assertEqual(handle(Mock(), 'Открой браузер', {}), 'Открываю браузер.')
            system.assert_called_once_with('https://ya.ru')

    def test_open_browser_falls_back_to_agent_browser(self):
        agent = Mock()
        with patch('src.assistant_commands.system_browser', return_value=False), \
             patch('src.assistant_commands.default_browser', return_value='ok') as b:
            self.assertEqual(handle(agent, 'Открой браузер', {}), 'ok')
            b.assert_called_once_with('https://ya.ru', agent)

    def test_close_browser(self):
        agent = Mock()
        handle(agent, 'Закрой браузер', {})
        agent.browser.call.assert_called_once_with('close_browser')
        agent.browser.context = None
        with patch('src.app_control.close_application', return_value='Закрываю chrome') as close, \
             patch('src.assistant_commands.default_browser_process', return_value='chrome'):
            self.assertEqual(handle(agent, 'Закрой браузер', {}), 'Закрываю браузер')
            close.assert_called_once_with('chrome')

    def test_service_fallback_downloads(self):
        a = Mock()
        with patch('src.web_services.find_installed', return_value=None), \
             patch('src.web_services.system_open', return_value=False):
            handle(a, 'Запусти приложение Яндекс Музыка', {})
        a.browser.call.assert_called_once_with('open', 'https://music.yandex.ru/download')

    def test_yandex_music_search(self):
        a = Mock()
        answer = handle(a, 'Включи песню Кино в Яндекс Музыке', {})
        self.assertIn('Кино', answer)
        self.assertIn('music.yandex.ru/search', a.browser.call.call_args.args[1])

    def test_unrelated_returns_none(self):
        # Раньше модуль отвечал «Не понял команду» на всё подряд и блокировал остальные обработчики.
        for phrase in ('Открой калькулятор', 'Какой курс доллара', 'Привет', 'Запусти телеграм'):
            self.assertIsNone(handle(Mock(), phrase, {}), phrase)


if __name__ == '__main__':
    unittest.main()
