"""Запросы 5.3: сайты в браузере, аккаунт владельца, промокоды, Amvera, Discord (голосовые каналы, реакции),
«Отправь сообщение», музыка, «Секунду, сэр», «Хорошо, сэр», стили голоса."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import license_server  # noqa: E402

from app import create_app  # noqa: E402
from src import music, sites, voice_fx  # noqa: E402
from src.agent import LocalComputerAgent  # noqa: E402
from src.desktop import messengers  # noqa: E402
from src.desktop.commands import DesktopCommands, parse  # noqa: E402
from src.dialog import ack_phrases, stop_reply  # noqa: E402
from src.license import LicenseClient  # noqa: E402
from src.storage import Store  # noqa: E402
from test_subscription import FakeKassa, ServerSession, keys  # noqa: E402


class SitesTests(unittest.TestCase):
    def test_parse_and_resolve(self):
        cases = {
            'Открой в браузере Claude Code': ('Claude Code', 'default', 'https://claude.ai/code'),
            'открой в браузере Cloud Code': ('Cloud Code', 'default', 'https://claude.ai/code'),
            'открой в Яндекс Браузере YouTube': ('YouTube', 'yandex', 'https://www.youtube.com'),
            'открой хабр в хроме': ('хабр', 'chrome', 'https://habr.com'),
            'зайди на сайт хабр точка ком': ('хабр точка ком', 'default', 'https://habr.com'),
            'открой сайт чат гпт': ('чат гпт', 'default', 'https://chatgpt.com'),
        }
        for text, (site, browser, url) in cases.items():
            self.assertEqual(sites.parse(text), dict(site=site, browser=browser), text)
            self.assertEqual(sites.resolve(site), url, text)
        self.assertTrue(sites.resolve('мой блог про котов').startswith('https://duckduckgo.com/?q=%21ducky'))
        for text in ('открой браузер', 'открой калькулятор', 'открой в телеграм чат Катя'):
            self.assertIsNone(sites.parse(text), text)

    def test_agent_opens_in_named_browser(self):
        agent = LocalComputerAgent(Mock())
        with patch('src.sites.open_url', return_value=True) as opened:
            answer = agent.process_command('Андрей, открой в Яндекс Браузере YouTube', {})
        opened.assert_called_once_with('https://www.youtube.com', 'yandex')
        self.assertIn('YouTube в Яндекс Браузере', answer)

    def test_unknown_app_that_is_a_site(self):
        agent = LocalComputerAgent(Mock())
        with patch('src.agent.launch', return_value='Приложение не найдено: Claude Code.'), \
                patch('src.sites.open_url', return_value=True) as opened:
            agent.process_command('открой Claude Code', {})
        opened.assert_called_once_with('https://claude.ai/code', 'default')

    def test_close_site_tab(self):
        browser = Mock()
        browser.call.side_effect = lambda method, *args: None
        desktop = Mock()
        desktop.target_title.return_value = ('Главная — YouTube - Google Chrome', 'chrome.exe')
        agent = LocalComputerAgent(browser, desktop_commands=DesktopCommands(desktop))
        with patch('src.agent.close_application', return_value='Закрываю YouTube: приложение не запущено'):
            answer = agent.process_command('закрой YouTube', {})
        desktop.hotkey.assert_called_once_with('ctrl', 'w')
        self.assertIn('вкладку YouTube', answer)

    def test_app_name_cases(self):
        from src.app_control import targets
        self.assertEqual(targets('эджу'), ['msedge.exe'])
        self.assertEqual(targets('хрома'), ['chrome.exe'])


class ServerAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        key, self.public = keys()
        self.server = license_server.LicenseServer(root / 'l.db', key, FakeKassa(), 'https://license.test',
                                                   owners=['orsofey@gmail.com'], owner_password='owner-pass-1',
                                                   promo_codes='ANDREY2026, FRIENDS:1')
        self.api = license_server.create_app(self.server).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def client(self, name, public=None):
        return LicenseClient(Store(Path(self.temp.name) / name), 'https://license.test', public,
                             ServerSession(self.api))

    def test_owner_has_everything(self):
        client = self.client('owner', self.public)
        status = client.login('Orsofey@gmail.com', 'owner-pass-1')
        self.assertTrue(status['premium'])
        self.assertTrue(status['owner'])
        self.assertEqual(status['plan'], 'lifetime')

    def test_owner_email_cannot_be_taken(self):
        with self.assertRaises(Exception) as ctx:
            self.client('thief').register('orsofey@gmail.com', 'hacker123')
        self.assertIn('зарезервирован', str(ctx.exception))
        with self.assertRaises(Exception):
            self.client('thief2').login('orsofey@gmail.com', 'wrong-pass')

    def test_promo_gives_lifetime(self):
        client = self.client('user', self.public)
        client.register('user@mail.ru', 'secret123')
        self.assertFalse(client.is_premium())
        status = client.promo('andrey2026')
        self.assertEqual((status['plan'], status['premium']), ('lifetime', True))

    def test_promo_rules(self):
        first = self.client('a', self.public)
        first.register('a@mail.ru', 'secret123')
        with self.assertRaises(Exception) as ctx:
            first.promo('NOPE')
        self.assertIn('не найден', str(ctx.exception))
        first.promo('FRIENDS')
        second = self.client('b', self.public)
        second.register('b@mail.ru', 'secret123')
        with self.assertRaises(Exception) as ctx:
            second.promo('FRIENDS')  # лимит — 1 активация
        self.assertIn('максимальное', str(ctx.exception))

    def test_public_key_pinned_on_first_contact(self):
        client = self.client('pin', public='')
        status = client.register('pin@mail.ru', 'secret123')
        self.assertFalse(status['premium'])
        self.assertEqual(client.store.meta('license_public_key'), license_server.public_key_text(self.server.key))
        client.promo('ANDREY2026')
        self.assertTrue(client.is_premium())

    def test_payments_disabled_without_yookassa(self):
        self.server.kassa = None
        client = self.client('c', self.public)
        client.register('c@mail.ru', 'secret123')
        with self.assertRaises(Exception) as ctx:
            client.checkout('monthly')
        self.assertIn('Оплата пока не подключена', str(ctx.exception))

    def test_amvera_env_config(self):
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {
                'DATA_DIR': data, 'OWNER_PASSWORD': 'owner-pass-1', 'PROMO_CODES': 'X1'}, clear=False):
            for name in ('LICENSE_PRIVATE_KEY', 'YOOKASSA_SHOP_ID', 'LICENSE_TEST_MODE', 'LICENSE_DB', 'OWNER_EMAILS'):
                os.environ.pop(name, None)
            app = license_server.create_app()
            key_file = Path(data) / 'license_signing_key'
            self.assertTrue(key_file.exists())
            health = app.test_client().get('/health').get_json()
            self.assertFalse(health['payments'])
            login = app.test_client().post('/api/login', json={'email': 'orsofey@gmail.com', 'password': 'owner-pass-1'})
            self.assertEqual(login.get_json()['plan'], 'lifetime')
            # Ключ сохраняется между перезапусками контейнера.
            again = license_server.create_app()
            self.assertEqual(license_server.public_key_text(again.extensions['license_server'].key),
                             license_server.public_key_text(app.extensions['license_server'].key))

    def test_amvera_files(self):
        """Папка server/ самодостаточна: её содержимое загружается в Amvera как есть."""
        server = Path(__file__).resolve().parents[1] / 'server'
        config = (server / 'amvera.yml').read_text(encoding='utf-8')
        self.assertIn('dockerfile: Dockerfile', config)
        self.assertIn('persistenceMount: /data', config)
        docker = (server / 'Dockerfile').read_text(encoding='utf-8')
        self.assertNotIn('server/', docker.split('\n', 2)[-1].replace('папки server/', ''))
        for line in docker.splitlines():
            if line.startswith('COPY ') and not line.startswith('COPY . '):
                self.assertTrue((server / line.split()[1]).exists(), line)
        self.assertIn('CMD ["python", "run.py"]', docker)

    def test_app_promo_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            client = LicenseClient(store, 'https://license.test', self.public, ServerSession(self.api))
            app = create_app(store, Mock(status=Mock(return_value={})), Mock(), license=client)
            web = app.test_client()
            headers = {'X-Agent-Token': store.meta('pairing_token')}
            web.post('/api/account/register', json={'email': 'z@mail.ru', 'password': 'secret123'}, headers=headers)
            data = web.post('/api/account/promo', json={'code': 'ANDREY2026'}, headers=headers).get_json()
            self.assertTrue(data['account']['premium'])
            self.assertEqual(web.post('/api/settings', json={'theme': 'luxe'}, headers=headers).status_code, 200)


class DiscordTests(unittest.TestCase):
    def test_voice_channel_parse(self):
        self.assertEqual(parse('зайди в голосовой канал'), ('discord_voice', {'channel': ''}))
        self.assertEqual(parse('зайди в голосовой канал под столом'), ('discord_voice', {'channel': 'под столом'}))
        self.assertEqual(parse('Зайди в голосовой чат'), ('discord_voice', {'channel': ''}))
        self.assertEqual(parse('выключи микрофон в дискорде'), ('discord_toggle', {'what': 'mute'}))

    def test_voice_channel_not_misheard_as_find(self):
        agent = LocalComputerAgent(Mock(), desktop_commands=DesktopCommands(Mock()))
        with patch('src.desktop.messengers.join_voice_channel', return_value='Захожу в голосовой канал «Под столом».') as join:
            answer = agent.process_command('зайди в голосовой канал под столом', {})
        join.assert_called_once()
        self.assertIn('Под столом', answer)
        self.assertNotIn('Найти', answer)

    @patch('src.desktop.messengers.time.sleep')
    def test_join_types_exclamation_search(self, sleep):
        desktop = Mock()
        with patch('src.desktop.winapi') as winapi, patch('src.app_control.activate_running', return_value=True):
            messengers.join_voice_channel(desktop, 'Под столом', {})
        winapi.hotkey.assert_any_call('ctrl', 'k')
        winapi.type_unicode.assert_called_once_with('!Под стол')

    def test_reactions(self):
        self.assertEqual(parse('поставь сердечко'), ('reaction', {'emoji': '❤️', 'name': 'heart'}))
        self.assertEqual(parse('поставь смеющийся смайлик'), ('reaction', {'emoji': '😂', 'name': 'joy'}))
        self.assertEqual(parse('лайкни'), ('reaction', {'emoji': '👍', 'name': 'thumbsup'}))
        self.assertIsNone(messengers.parse_reaction('поставь будильник на 7'))

    def test_reaction_in_discord_and_elsewhere(self):
        desktop = Mock()
        desktop.target_process.return_value = 'discord.exe'
        with patch('src.desktop.winapi') as winapi:
            self.assertIn('❤️', messengers.react(desktop, {'emoji': '❤️', 'name': 'heart'}))
        winapi.type_unicode.assert_called_once_with('+:heart:')
        winapi.hotkey.assert_called_with('enter')
        desktop.target_process.return_value = 'telegram.exe'
        answer = messengers.react(desktop, {'emoji': '❤️', 'name': 'heart'})
        desktop.type_text.assert_called_once_with('❤️')
        self.assertIn('отправь', answer)


class SendDraftTests(unittest.TestCase):
    def test_send_draft(self):
        desktop = Mock()
        desktop.target_process.return_value = 'telegram.exe'
        commands = DesktopCommands(desktop)
        self.assertEqual(commands.handle('Отправь сообщение', {}), 'Отправил сообщение.')
        desktop.hotkey.assert_called_once_with('enter')

    def test_send_draft_returns_to_chat(self):
        desktop = Mock()
        desktop.target_process.return_value = 'winword.exe'
        desktop.activate_process.return_value = True
        commands = DesktopCommands(desktop)
        commands.chat = dict(app='telegram', who='Катя')
        commands.handle('отправь', {})
        desktop.activate_process.assert_called_once_with({'telegram.exe'})
        desktop.hotkey.assert_called_once_with('enter')


class MusicTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(music.parse('Включи Imagine Dragons', True), ('play', 'Imagine Dragons', None))
        self.assertIsNone(music.parse('Включи Imagine Dragons', False))
        self.assertEqual(music.parse('включи песню Believer на яндекс музыке'), ('play', 'Believer', 'music.yandex'))
        self.assertEqual(music.parse('Запусти плеер'), ('player',))
        self.assertIsNone(music.parse('включи видео котики', True))

    def test_agent_plays_on_music_page(self):
        browser = Mock()
        browser.call.side_effect = lambda method, *args: {'url': 'https://music.yandex.ru/home',
                                                          'music': 'Включаю «Кино» в Яндекс Музыке.'}.get(method)
        agent = LocalComputerAgent(browser)
        # На реальном ПК в меню «Пуск» есть «Кино и ТВ» — это не должно перехватить песню.
        with patch('src.start_menu.shortcuts', return_value=[('Кино и ТВ', 'C:/menu/Кино и ТВ.lnk')]):
            answer = agent.process_command('Андрей, включи Кино', {})
        browser.call.assert_called_with('music', 'Кино', None)
        self.assertIn('Кино', answer)

    def test_app_names_are_not_songs(self):
        browser = Mock()
        browser.call.side_effect = lambda method, *args: 'https://music.yandex.ru/home' if method == 'url' else None
        agent = LocalComputerAgent(browser)
        with patch('src.agent.launch', return_value='Открываю Telegram.') as launch:
            agent.process_command('включи Telegram', {})
        launch.assert_called_once()

    def test_player_falls_back_to_media_key(self):
        browser = Mock()
        browser.call.return_value = None
        desktop = Mock()
        agent = LocalComputerAgent(browser, desktop_commands=DesktopCommands(desktop))
        self.assertIn('плеер', agent.process_command('запусти плеер', {}))
        desktop.hotkey.assert_called_once_with('media_play_pause')

    def test_play_first_script(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright не установлен')
        from src.browser_control import BrowserController
        html = ('<header><button aria-label="Play">шапка</button></header><footer><button aria-label="Воспроизведение">'
                'плеер</button></footer><main><button aria-label="Пауза">п</button><button aria-label="Воспроизведение '
                'Believer" onclick="window.clicked=1">▶</button></main>')
        try:
            with sync_playwright() as p:
                path = '/opt/pw-browsers/chromium'
                browser = p.chromium.launch(executable_path=path) if os.path.exists(path) else p.chromium.launch()
                page = browser.new_page()
                page.set_content(html)
                label = page.evaluate(BrowserController.PLAY_FIRST)
                clicked = page.evaluate('window.clicked')
                browser.close()
        except Exception as exc:
            self.skipTest(f'Браузер недоступен: {exc}')
        self.assertIn('believer', label)
        self.assertEqual(clicked, 1)


class SpeechTests(unittest.TestCase):
    def test_phrases(self):
        self.assertIn('Секунду, сэр.', ack_phrases('сэр'))
        self.assertEqual(stop_reply('one', 'сэр'), 'Хорошо, сэр.')
        self.assertEqual(stop_reply('all', 'сэр'), 'Хорошо, сэр, все команды остановлены.')
        self.assertEqual(stop_reply('one', ''), 'Хорошо.')

    def test_typed_stop_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            app = create_app(store, Mock(status=Mock(return_value={})), Mock(), license=Mock(is_premium=lambda: True))
            response = app.test_client().post('/api/chat', json={'message': 'Андрей, стоп', 'id': 'stop-00001'},
                                              headers={'X-Agent-Token': store.meta('pairing_token')})
        self.assertEqual(response.get_json()['response'], 'Хорошо, сэр.')

    def test_voice_command_is_acknowledged_first(self):
        from src.speech.voice_loop import VoiceAssistant
        from src.events import EventBus
        order = []
        speech = Mock()
        speech.transcribe_array.return_value = {'text': 'Андрей, открой калькулятор'}
        service = Mock()
        service.run.side_effect = lambda *a, **k: (order.append('run'), ('Открываю калькулятор.', True))[1]
        player = Mock(speaking=False, last_end=0.0, available=True)
        player.acknowledge.side_effect = lambda text, settings: order.append(text)
        voice = VoiceAssistant(speech, service, EventBus(), lambda: {'wake_word': 'Андрей'}, player=player)
        voice.handle_segment(b'')
        self.assertEqual(len(order), 2)
        self.assertIn(order[0], ack_phrases('сэр'))
        self.assertEqual(order[1], 'run')

    def test_ack_is_not_cut_by_answer(self):
        from src.tts_player import TTSPlayer
        tts = Mock()
        tts.pick_voice.return_value = 'denis'
        tts.synthesize_array.return_value = (np.zeros(1600, dtype=np.int16), 16000)
        with patch.object(TTSPlayer, '_check_audio', return_value=True), \
                patch.object(TTSPlayer, '_play_loop'), patch.object(TTSPlayer, '_synth_loop'):
            player = TTSPlayer(tts)
        player.acknowledge('Секунду, сэр.', {})
        player.new_utterance()  # начало ответа
        queued = list(player.play_queue.queue)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][3], 'ack')
        player.stop()  # «стоп» обрывает и подтверждение
        self.assertTrue(player.play_queue.empty())

    def test_prewarm_makes_ack_instant(self):
        from src.tts_player import TTSPlayer
        tts = Mock()
        tts.pick_voice.return_value = 'denis'
        tts.synthesize_array.return_value = (np.zeros(10, dtype=np.int16), 16000)
        with patch.object(TTSPlayer, '_check_audio', return_value=True), \
                patch.object(TTSPlayer, '_play_loop'), patch.object(TTSPlayer, '_synth_loop'):
            player = TTSPlayer(tts)
        player.prewarm(['Секунду, сэр.'], {})
        for _ in range(50):
            if player.ack_cache:
                break
            time.sleep(0.02)
        tts.synthesize_array.reset_mock()
        player.acknowledge('Секунду, сэр.', {})
        tts.synthesize_array.assert_not_called()


class VoiceStyleTests(unittest.TestCase):
    def test_presets_process_audio(self):
        audio = (np.sin(np.arange(22050) / 22050 * 2 * np.pi * 180) * 12000).astype(np.int16)
        for name in voice_fx.PRESETS:
            out = voice_fx.apply(audio, 22050, name)
            self.assertEqual(out.dtype, np.int16, name)
            self.assertGreater(np.abs(out).max(), 1000, name)
        self.assertGreater(len(voice_fx.apply(audio, 22050, 'jarvis')), len(audio))  # тон ниже — звук длиннее

    def test_jarvis_default_and_premium(self):
        from src.storage import DEFAULTS, PREMIUM_KEYS
        self.assertEqual(DEFAULTS['voice_preset'], 'jarvis')
        self.assertIn('voice_preset', PREMIUM_KEYS)

    def test_service_uses_preset_voice(self):
        from src.local_tts_service import LocalTTSService
        with tempfile.TemporaryDirectory() as folder:
            service = LocalTTSService(folder)
            voice = Mock()
            with patch('src.local_tts_service.get_piper_voice', return_value=voice) as get, \
                    patch('src.local_tts_service.voice_files', return_value=('x', 'y')), \
                    patch('src.local_tts_service._piper_pcm', return_value=(np.zeros(2205, dtype=np.int16).tobytes(), 22050)) as pcm:
                audio, rate = service.synthesize_array('Добрый вечер, сэр', 'irina', 1.0, preset='jarvis')
        get.assert_called_with('denis', service.root)
        self.assertAlmostEqual(pcm.call_args.args[2], 0.93)  # говорит быстрее, чтобы после понижения тона темп остался
        self.assertGreater(len(audio), 2205)


if __name__ == '__main__':
    unittest.main()
