"""Запросы 5.2: стоп-фразы, «останови все команды», «выдели текст», чат Telegram из ослышек,
сервер Discord, программы из меню «Пуск» («Юнити» → Unity Hub)."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import abort, start_menu
from src.agent import LocalComputerAgent
from src.desktop import messengers
from src.desktop.commands import DesktopCommands, parse
from src.events import EventBus
from src.service import AssistantService, stop_kind
from src.storage import Store


class StopPhraseTests(unittest.TestCase):
    def test_kinds(self):
        for text in ('стоп', 'Стоп.', 'останови команду', 'хватит!', 'выключись', 'Остановись'):
            self.assertEqual(stop_kind(text), 'one', text)
        for text in ('останови все команды', 'Останови всё.', 'стоп все', 'отмени все команды'):
            self.assertEqual(stop_kind(text), 'all', text)
        # «Отмени» — это Ctrl+Z, «пауза» — видео: они остаются обычными командами.
        for text in ('отмени', 'пауза', 'останови видео', 'стоп диктовка', 'выключи свет'):
            self.assertIsNone(stop_kind(text), text)


class StopAllTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_typing_is_interrupted(self):
        typed = []
        started = threading.Event()

        def long_typing(text, settings, owner=None, on_text=None):
            started.set()
            for n in range(300):
                abort.check()  # так же проверяет каждая отправка клавиш в winapi/macapi
                typed.append(n)
                time.sleep(0.005)
            return 'Напечатал'

        agent = Mock()
        agent.process_command.side_effect = long_typing
        service = AssistantService(self.store, agent, EventBus())
        threading.Thread(target=lambda: (started.wait(2), time.sleep(0.05), service.control('Андрей, стоп', {})),
                         daemon=True).start()
        self.assertEqual(service.run('напиши длинный текст', 'u', {})[0], 'Остановлено.')
        count = len(typed)
        time.sleep(0.1)
        self.assertEqual(len(typed), count, 'печать должна остановиться')
        self.assertLess(count, 300)

    def test_stop_all_cancels_queued_commands_and_dictation(self):
        started = threading.Event()

        def slow(text, settings, owner=None, on_text=None):
            started.set()
            time.sleep(0.3)
            return 'готово'

        agent = Mock()
        agent.process_command.side_effect = slow
        agent.desktop_commands.dictation = True
        agent.dialog.pending = {'u': {}}
        service = AssistantService(self.store, agent, EventBus())
        results = []
        first = threading.Thread(target=lambda: results.append(service.run('первая', 'u', {})[0]))
        first.start()
        started.wait(2)
        second = threading.Thread(target=lambda: results.append(service.run('вторая', 'u', {})[0]))
        second.start()
        time.sleep(0.05)
        self.assertEqual(service.control('останови все команды', {}), 'Хорошо, сэр, все команды остановлены.')
        first.join(2)
        second.join(2)
        self.assertEqual(results, ['Остановлено.', 'Остановлено.'])
        self.assertEqual(agent.process_command.call_count, 1)
        self.assertFalse(agent.desktop_commands.dictation)
        self.assertEqual(agent.dialog.pending, {})

    def test_typed_stop_bypasses_busy_lock(self):
        from app import create_app
        agent = Mock()
        app = create_app(self.store, Mock(status=Mock(return_value={})), agent, license=Mock(is_premium=lambda: True))
        service = app.extensions['service']
        service.lock.acquire()
        try:
            response = app.test_client().post('/api/chat', json={'message': 'Андрей, хватит', 'id': 'stop-12345'},
                                              headers={'X-Agent-Token': self.store.meta('pairing_token')})
        finally:
            service.lock.release()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(service.cancel_event.is_set())

    def test_voice_stop_all_speaks(self):
        from src.speech.voice_loop import VoiceAssistant
        speech = Mock()
        speech.transcribe_array.return_value = {'text': 'Андрей, останови все команды'}
        service = Mock()
        service.cancel_all.return_value = 'Хорошо, сэр, все команды остановлены.'
        player = Mock(speaking=False, last_end=0.0, available=True)
        voice = VoiceAssistant(speech, service, EventBus(), lambda: {'wake_word': 'Андрей'}, player=player)
        voice.handle_segment(b'')
        service.cancel_all.assert_called_once()
        service.run.assert_not_called()
        player.acknowledge.assert_called_once_with('Хорошо, сэр, все команды остановлены.', {'wake_word': 'Андрей'})


class CommandTests(unittest.TestCase):
    def test_select_text(self):
        for text in ('Андрей, выдели текст', 'выдели текст', 'Выделить весь текст'):
            self.assertEqual(parse(text.replace('Андрей, ', '')), ('keys', {'keys': ('ctrl', 'a'), 'times': 1}))

    def test_telegram_misrecognized_forms(self):
        cases = {'открой в Telegram-чат Катя': 'Катя', 'открой чат, Катя': 'Катя',
                 'перейди в чат«избранное»': 'избранное', 'перейти в чат Арсений Краг': 'Арсений Краг',
                 'Открой в телеграм чат Катя': 'Катя', 'открой телеграм чат Катя': 'Катя'}
        for text, who in cases.items():
            self.assertEqual(parse(text), ('open_chat', {'app': 'telegram', 'who': who}), text)

    def test_fuzzy_alias(self):
        settings = {'contact_aliases': 'Арсений Крэк = Arseny Crack'}
        self.assertEqual(messengers.search_query('Арсений Краг', settings), 'Arseny Crack')
        self.assertEqual(messengers.search_query('Катя', settings), 'Кат')

    def test_discord_parse(self):
        self.assertEqual(parse('зайди на дискорд сервер Майнкрафт'), ('discord_server', {'server': 'Майнкрафт'}))
        self.assertEqual(parse('зайди на сервер Друзья в дискорде'), ('discord_server', {'server': 'Друзья'}))
        self.assertEqual(parse('зайди на дискорд сервер'), ('discord_server', {'server': ''}))
        self.assertIsNone(messengers.parse_discord('открой дискорд'))

    @patch('src.desktop.messengers.time.sleep')
    def test_discord_opens_closed_app_and_asks_for_server(self, sleep):
        desktop = Mock()
        desktop.activate_process.return_value = True
        agent = LocalComputerAgent(Mock(), desktop_commands=DesktopCommands(desktop))
        with patch('src.desktop.winapi') as winapi, patch('src.app_control.activate_running', return_value=False):
            self.assertEqual(agent.process_command('Андрей, зайди на дискорд сервер', {}, owner='u'),
                             'На какой сервер Discord зайти, сэр?')
            answer = agent.process_command('Андрей, Майнкрафт', {}, owner='u')
        self.assertIn('захожу на сервер «майнкрафт»', answer.casefold())
        desktop.activate_process.assert_called_once_with({'discord.exe'}, launch_name='дискорд', timeout=60)
        winapi.hotkey.assert_any_call('ctrl', 'k')
        winapi.type_unicode.assert_called_once_with('*Майнкрафт')


class StartMenuTests(unittest.TestCase):
    def test_find_by_sound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('Unity Hub', 'Unity 2022.3.10f1', 'Uninstall Unity Hub', 'OBS Studio', 'Adobe Photoshop 2024',
                         'Steam', 'Blender 4.2'):
                (root / (name + '.lnk')).write_text('')
            found = {spoken: start_menu.find(spoken, [root]) for spoken in
                     ('юнити', 'Юнити хаб', 'обс', 'фотошоп', 'стим', 'блендер', 'калькулятор')}
        names = {k: Path(v).stem if v else None for k, v in found.items()}
        self.assertEqual(names, {'юнити': 'Unity Hub', 'Юнити хаб': 'Unity Hub', 'обс': 'OBS Studio',
                                 'фотошоп': 'Adobe Photoshop 2024', 'стим': 'Steam', 'блендер': 'Blender 4.2',
                                 'калькулятор': None})

    def test_unity_alias(self):
        from src.app_control import resolve, targets
        self.assertEqual(resolve('Юнити'), 'Unity Hub')
        self.assertEqual(targets('юнити'), ['unity hub.exe'])


if __name__ == '__main__':
    unittest.main()
