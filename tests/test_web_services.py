"""Проверки открытия веб-сервисов и предложения установки."""
import unittest
from unittest.mock import Mock, patch
from src import web_services
from src.assistant_commands import handle


class WebServiceTests(unittest.TestCase):
    def setUp(self):
        # На Windows сервисы открываются в системном браузере; в тестах проверяем путь
        # через браузер агента и не открываем настоящие окна.
        patcher = patch.object(web_services, 'system_open', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.browser = Mock()
        self.browser.call.return_value = '[browser]'
        self.agent = Mock()
        self.agent.browser = self.browser

    # --- Музыка открывается в браузере агента: ею можно управлять голосом ---
    def test_music_opens_in_browser(self):
        answer = handle(self.agent, 'Открой яндекс музыку', {})
        self.assertIn('Яндекс Музыку', answer)
        self.browser.call.assert_called_once_with('open', 'https://music.yandex.ru')

    def test_spotify_opens_in_browser(self):
        handle(self.agent, 'Открой спотифай', {})
        self.browser.call.assert_called_once_with('open', 'https://open.spotify.com')

    def test_vk_music_opens_in_browser(self):
        handle(self.agent, 'Включи вк музыку', {})
        self.browser.call.assert_called_once_with('open', 'https://vk.com/music')

    # --- Приложение: нет системного — предложение скачать ---
    def test_app_not_installed_offers_download(self):
        with patch.object(web_services, 'find_installed', return_value=None):
            answer = handle(self.agent, 'Открой приложение Яндекс Музыка', {})
        self.assertIn('не установлено', answer)
        self.browser.call.assert_called_once_with('open', 'https://music.yandex.ru/download')

    def test_app_installed_launches_app(self):
        with patch.object(web_services, 'find_installed', return_value='C:/fake/Yandex Music.exe'), \
             patch.object(web_services.os, 'startfile', create=True) as starter, \
             patch.object(web_services.os, 'name', 'nt'):
            answer = handle(self.agent, 'Открой приложение Яндекс Музыка', {})
        self.assertIn('Открываю приложение', answer)
        starter.assert_called_once()
        self.browser.call.assert_not_called()

    # --- Открытие сервиса не зависит от установки приложения ---
    def test_service_opens_in_browser_even_if_app_installed(self):
        with patch.object(web_services, 'find_installed', return_value='C:/fake/Yandex Music.exe'):
            handle(self.agent, 'Открой Яндекс Музыку', {})
        self.browser.call.assert_called_once_with('open', 'https://music.yandex.ru')

    def test_music_uses_agent_browser_not_system(self):
        with patch.object(web_services, 'system_open', return_value=True) as system:
            handle(self.agent, 'Открой спотифай', {})
        system.assert_not_called()
        self.browser.call.assert_called_once_with('open', 'https://open.spotify.com')

    # --- Вспомогательные функции ---
    def test_open_service_unknown_returns_none(self):
        self.assertIsNone(web_services.open_service('несуществующий сервис', self.agent))

    def test_known_services_have_url(self):
        for name, info in web_services.WEB_SERVICES.items():
            self.assertTrue(info['url'].startswith('https://'), name)


if __name__ == '__main__':
    unittest.main()
