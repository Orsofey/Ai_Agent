"""5.6: свернуть приложение, быстрые ответы и «поболтать», напоминания, макросы, изучение файлов, узнавание голоса."""
import os
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from src import files, macros, reminders
from src.agent import LocalComputerAgent
from src.desktop.commands import DesktopCommands, parse as desktop_parse
from src.storage import Store


class MinimizeTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(desktop_parse('сверни телеграм'), ('minimize_app', {'name': 'телеграм'}))
        self.assertEqual(desktop_parse('Сверни приложение Discord'), ('minimize_app', {'name': 'discord'}))
        self.assertEqual(desktop_parse('разверни телеграм'), ('restore_app', {'name': 'телеграм'}))
        self.assertEqual(desktop_parse('сверни окно'), ('window', {'action': 'minimize'}))
        self.assertEqual(desktop_parse('сверни все'), ('keys', {'keys': ('win', 'd'), 'times': 1}))

    def test_execute(self):
        commands = DesktopCommands(Mock(available=True))
        with patch('src.app_control.minimize_application', return_value='Сворачиваю телеграм') as minimize:
            self.assertEqual(commands.handle('сверни телеграм', {}), 'Сворачиваю телеграм')
        minimize.assert_called_once_with('телеграм')

    def test_windows_minimize(self):
        from src import app_control
        user32 = Mock()
        with patch.object(app_control.sys, 'platform', 'win32'), \
                patch.object(app_control, '_pids_by_names', return_value={42}), \
                patch.object(app_control, '_find_windows', return_value=[101, 102]), \
                patch.object(app_control.ctypes, 'WinDLL', return_value=user32, create=True):
            self.assertEqual(app_control.minimize_application('telegram'), 'Сворачиваю telegram')
        self.assertEqual([c.args for c in user32.ShowWindow.call_args_list], [(101, 6), (102, 6)])


class SpeedAndChatTests(unittest.TestCase):
    def test_search_deadline(self):
        from src.brain import llm
        tools = Mock()
        tools.web_search.side_effect = lambda *a, **k: time.sleep(3) or []
        provider = llm.OpenAICompatibleProvider('http://x/v1', 'm', '', tools)
        started = time.monotonic()
        with patch.object(llm, 'SEARCH_DEADLINE', 0.2):
            self.assertEqual(provider._context('какой курс доллара сегодня', {}), '')
        self.assertLess(time.monotonic() - started, 1.0)

    def test_chat_mode(self):
        brain = Mock()
        brain.answer.return_value = 'Отлично, а у вас?'
        agent = LocalComputerAgent(Mock(), brain=brain)
        settings = {'butler': False}
        self.assertIn('О чём поговорим', agent.process_command('Андрей, давай поболтаем', settings, owner='u'))
        self.assertTrue(agent.awaiting('u'))
        self.assertEqual(agent.process_command('как дела', settings, owner='u'), 'Отлично, а у вас?')
        self.assertEqual(brain.answer.call_args.kwargs['mode'], 'chat')
        agent.process_command('хватит болтать', settings, owner='u')
        self.assertFalse(agent.awaiting('u'))

    def test_chat_keeps_commands(self):
        brain = Mock()
        agent = LocalComputerAgent(Mock(), brain=brain, desktop_commands=DesktopCommands(Mock(available=True)))
        agent.process_command('давай поболтаем', {}, owner='u')
        with patch('src.app_control.minimize_application', return_value='Сворачиваю телеграм'):
            self.assertIn('Сворачиваю', agent.process_command('сверни телеграм', {'butler': False}, owner='u'))
        brain.answer.assert_not_called()

    def test_brain_chat_is_short_and_timed(self):
        from src.brain import Brain
        brain = Brain(Store(tempfile.mkdtemp()), tools=Mock(), local=Mock())
        brain.quick_answer = Mock(return_value=None)
        provider = Mock()
        provider.stream.side_effect = lambda history, settings, on_text=None, **kw: (on_text('Привет!'), 'Привет!')[1]
        brain.provider = Mock(return_value=provider)
        self.assertEqual(brain.answer('привет', {}, owner='u', mode='chat'), 'Привет!')
        kwargs = provider.stream.call_args.kwargs
        self.assertEqual(kwargs['max_tokens'], 120)
        self.assertIn('непринуждённая беседа', kwargs['system'])
        self.assertIsNotNone(brain.last_timing['first_token'])

    def test_filler_when_answer_is_slow(self):
        from src import service as service_module
        from src.events import EventBus
        agent = Mock()
        agent.process_command.side_effect = lambda *a, **k: time.sleep(0.5) or 'Ответ'
        player = Mock(available=True, token=1, speaking=False)
        player.new_utterance.return_value = 1
        svc = service_module.AssistantService(Store(tempfile.mkdtemp()), agent, EventBus(), player)
        with patch.object(service_module, 'FILLER_AFTER', 0.1):
            svc.run('вопрос', 'u', {'address': 'сэр'})
        phrases = [c.args[0] for c in player.acknowledge.call_args_list]
        self.assertTrue(any('сэр' in p for p in phrases), phrases)


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(tempfile.mkdtemp())
        self.now = datetime(2026, 9, 28, 14, 0).timestamp()
        self.said, self.shown = [], []
        self.idle = 0.0
        self.r = reminders.Reminders(self.store, notify=self.shown.append, speak=self.said.append,
                                     clock=lambda: self.now, idle=lambda: self.idle)

    def test_builtins_present(self):
        texts = [self.r.render(i['text'], {'address': 'сэр'}) for i in self.r.items]
        self.assertEqual(texts, ['Сэр, пора отдохнуть от ПК.', 'Сэр, пора размяться.'])

    def test_voice_create_and_fire(self):
        with patch('src.reminders.datetime') as dt:
            dt.now.return_value = datetime.fromtimestamp(self.now)
            dt.fromtimestamp = datetime.fromtimestamp
            reply = self.r.handle('создай напоминание через 20 минут позвонить маме', 'u', {})
        self.assertIn('позвонить маме', reply)
        self.now += 21 * 60
        fired = self.r.tick({'address': 'сэр'})
        self.assertIn('Сэр, напоминаю: позвонить маме.', fired)
        self.assertEqual(self.said, fired)
        self.assertFalse(any(i['text'] == 'позвонить маме' for i in self.r.items))  # разовое — удалено

    def test_asks_when(self):
        self.assertEqual(self.r.handle('напомни купить хлеб', 'u', {}), 'Когда напомнить?')
        self.assertTrue(self.r.awaiting('u'))
        self.assertIn('купить хлеб', self.r.handle('завтра в 9 утра', 'u', {}))
        self.assertFalse(self.r.awaiting('u'))

    def test_pc_reminder_skipped_when_away(self):
        self.now += 61 * 60
        self.idle = 10 * 60
        self.assertEqual(self.r.tick({'address': 'сэр'}), [])
        self.idle = 0
        self.now += 61 * 60
        self.assertIn('Сэр, пора отдохнуть от ПК.', self.r.tick({'address': 'сэр'}))

    def test_manage_by_voice(self):
        self.assertIn('Отключил', self.r.handle('отключи напоминание размяться', 'u', {}))
        self.assertIn('Удалил', self.r.handle('удали напоминание отдохнуть от ПК', 'u', {}))
        self.assertIn('Напоминаний нет', self.r.handle('какие у меня напоминания', 'u', {}))

    def test_interview(self):
        answers = ['в 7 утра', 'в 23', 'с 9 до 18', 'каждые 2 часа', 'витамины в 9 утра',
                   'по понедельникам и средам в 19:00', 'всё']
        reply = self.r.handle('настрой напоминания', 'u', {})
        for answer in answers:
            self.assertTrue(self.r.awaiting('u'))
            reply = self.r.handle(answer, 'u', {'address': 'сэр'})
        self.assertFalse(self.r.awaiting('u'))
        self.assertIn('Добавил напоминаний: 6', reply)
        kinds = sorted(i['kind'] for i in self.r.items if i.get('source') == 'interview')
        self.assertEqual(kinds, ['daily', 'daily', 'daily', 'interval', 'weekly', 'weekly'])
        rest = next(i for i in self.r.items if i['id'] == 'builtin-rest')
        self.assertEqual((rest['from'], rest['to']), ('09:00', '18:00'))

    def test_editor_validation(self):
        items = self.r.list()
        items[0]['enabled'] = False
        items.append({'text': 'Полить цветы', 'kind': 'weekly', 'days': [5], 'time': '10:00'})
        saved = self.r.replace(items)
        self.assertEqual(len(saved), 3)
        with self.assertRaises(ValueError):
            self.r.replace([{'text': 'x', 'kind': 'weekly', 'days': [], 'time': '10:00'}])

    def test_agent_routes_reminders_first(self):
        agent = LocalComputerAgent(Mock())
        agent.reminders = self.r
        self.assertEqual(agent.process_command('Андрей, напомни купить хлеб', {}, owner='u'), 'Когда напомнить?')
        self.assertTrue(agent.awaiting('u'))


class MacroTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(tempfile.mkdtemp())
        self.done = []
        self.m = macros.Macros(self.store, runner=lambda command, settings, owner: self.done.append(command) or 'Готово.')

    def test_create_and_run(self):
        reply = self.m.handle('создай макрос утро: открой почту, затем открой ютуб, потом включи музыку', 'u')
        self.assertIn('Макрос «утро» создан', reply)
        self.assertIn('выполнен: шагов 3', self.m.handle('запусти макрос утро', 'u'))
        self.assertEqual(self.done, ['открой почту', 'открой ютуб', 'включи музыку'])

    def test_record(self):
        agent = LocalComputerAgent(Mock())
        agent.macros = macros.Macros(self.store, runner=lambda c, s, o: agent.process_command(c, s, owner=o))
        agent.process_command('запиши макрос работа', {}, owner='u')
        with patch.object(agent, '_route', return_value=('Готово.', 'info')):
            agent.process_command('открой калькулятор', {}, owner='u')
            agent.process_command('сверни телеграм', {}, owner='u')
        self.assertIn('сохранён: 2', agent.process_command('сохрани макрос', {}, owner='u'))
        self.assertEqual(agent.macros.find('работа')['steps'], ['открой калькулятор', 'сверни телеграм'])

    def test_phrase_and_wait(self):
        self.m.save([{'name': 'вечер', 'phrase': 'добрый вечер', 'steps': ['подожди 0 секунд', 'включи музыку']}])
        self.assertIn('выполнен', self.m.handle('Добрый вечер', 'u'))
        self.assertEqual(self.done, ['включи музыку'])
        self.assertEqual(macros.wait_seconds('подожди пять секунд'), 5)

    def test_stop_between_steps(self):
        from src import abort
        self.m.save([{'name': 'долгий', 'steps': ['раз', 'два']}])
        self.m.runner = lambda c, s, o: abort.abort_all() or 'Готово.'
        abort.begin()
        with self.assertRaises(abort.Aborted):
            self.m.handle('запусти макрос долгий', 'u')
        abort.begin()


def make_docx(path, text):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>' + text +
                   '</w:t></w:r></w:p></w:body></w:document>')


def make_xlsx(path, rows):
    shared, cells = [], []
    for r, row in enumerate(rows, start=1):
        line = []
        for c, value in enumerate(row):
            ref = chr(65 + c) + str(r)
            if isinstance(value, str):
                shared.append(value)
                line.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            else:
                line.append(f'<c r="{ref}"><v>{value}</v></c>')
        cells.append(f'<row r="{r}">' + ''.join(line) + '</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('xl/sharedStrings.xml', f'<sst {ns}>' + ''.join(f'<si><t>{s}</t></si>' for s in shared) + '</sst>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet {ns}><sheetData>' + ''.join(cells) + '</sheetData></worksheet>')


class FileTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.folder = self.home / 'Documents' / 'Отчёты'
        self.folder.mkdir(parents=True)
        (self.folder / 'заметка.txt').write_text('Договор поставки подписан 12 марта. Сумма договора 150000.', encoding='utf-8')
        make_docx(self.folder / 'план.docx', 'План проекта: запуск в апреле, бюджет утверждён.')
        make_xlsx(self.folder / 'продажи.xlsx', [['Товар', 'Сумма', 'Кол-во'], ['A', 1000, 2], ['B', 2500.5, 3]])
        (self.folder / 'расходы.csv').write_text('Статья;Сумма\nАренда;50 000\nСвязь;1 500,50\n', encoding='utf-8')
        self.events = []
        self.said = []
        self.patch = patch('src.files.Path.home', return_value=self.home)
        self.patch.start()
        self.study = files.FileStudy(Store(tempfile.mkdtemp()), events=Mock(emit=lambda t, **k: self.events.append(k)),
                                     brain=None, notify=self.said.append, open_path=Mock())

    def tearDown(self):
        self.patch.stop()

    def wait(self):
        self.study.running.join(10)

    def test_resolve_folder(self):
        self.assertEqual(files.resolve_folder('документах'), self.home / 'Documents')
        self.assertEqual(files.resolve_folder('отчеты'), self.folder)

    def test_study_with_progress(self):
        reply = self.study.handle('проштудируй папку отчёты')
        self.assertIn('Изучаю 4 файл', reply)
        self.wait()
        self.assertTrue(self.events[-1]['finished'])
        self.assertEqual(max(e['done'] for e in self.events), 4)
        self.assertIn('4 файл', self.said[0])
        report = Path(self.study.last_report).read_text(encoding='utf-8')
        self.assertIn('договор', report.casefold())
        self.assertIn('план.docx', report)

    def test_calc_tables(self):
        self.study.handle('посчитай сумму в таблицах в папке отчёты')
        self.wait()
        self.assertIn('«Сумма» — итого 55', self.said[0])  # 1000 + 2500,5 + 50000 + 1500,5 = 55 001
        report = Path(self.study.last_report).read_text(encoding='utf-8')
        self.assertIn('продажи.xlsx', report)
        self.assertIn('Кол-во: сумма 5', report)

    def test_grep(self):
        self.study.handle('найди в файлах слово бюджет в папке отчёты')
        self.wait()
        self.assertIn('план.docx', self.said[0])

    def test_unknown_folder(self):
        self.assertIn('Не нашёл папку', self.study.handle('изучи файлы в папке несуществующая'))


class SpeakerTests(unittest.TestCase):
    def test_fbank_shape(self):
        from src.speech.speaker import fbank
        feats = fbank(np.zeros(16000, dtype=np.float32) + 0.01)
        self.assertEqual(feats.shape, (98, 80))

    def test_password(self):
        from src.speech.speaker import SpeakerGate
        gate = SpeakerGate(Store(tempfile.mkdtemp()), model_path=Path('/nonexistent'))
        gate.set_password('Синий кит')
        self.assertTrue(gate.check_password('синий кит'))
        self.assertTrue(gate.check_password('Андрей, синий кит!'))
        self.assertFalse(gate.check_password('красный кит'))
        self.assertNotIn('синий', gate.store.meta('voice_password'))

    def make_loop(self, vectors):
        from src.speech.voice_loop import VoiceAssistant
        from src.speech.speaker import SpeakerGate
        store = Store(tempfile.mkdtemp())
        settings = dict(store.settings('device:desktop'), voice_id=True)
        gate = SpeakerGate(store, model_path=Path(__file__))  # «модель» есть
        gate.embed = Mock(side_effect=lambda audio: vectors.pop(0))
        speech = Mock()
        service = Mock(agent=None, cancel_event=threading.Event())
        service.run.return_value = ('Готово.', False)
        loop = VoiceAssistant(speech, service, Mock(), lambda: settings, player=None, gate=gate)
        loop.capture_thread = Mock(is_alive=lambda: True)  # микрофон в тесте не нужен
        return loop, speech, service, gate

    def test_known_and_unknown_voices(self):
        me, stranger = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
        loop, speech, service, gate = self.make_loop([me, me, me, me, stranger, stranger])
        audio = np.zeros(32000, dtype=np.float32)
        speech.transcribe_array.return_value = {'text': 'раз два три'}
        loop.start_enroll('Владелец')
        for _ in range(3):
            loop.handle_segment(audio)
        self.assertEqual([p['name'] for p in gate.profiles()], ['Владелец'])

        gate.set_password('синий кит')
        speech.transcribe_array.return_value = {'text': 'Андрей, открой калькулятор'}
        loop.handle_segment(audio)
        service.run.assert_called_once()

        loop.verified_until = 0
        speech.transcribe_array.return_value = {'text': 'Андрей, открой почту'}
        loop.handle_segment(audio)
        self.assertEqual(service.run.call_count, 1)  # чужой голос — команда не выполнена
        self.assertIsNotNone(loop.stranger)
        speech.transcribe_array.return_value = {'text': 'синий кит'}
        loop.handle_segment(audio)
        time.sleep(0.2)
        self.assertEqual(len(gate.profiles()), 2)  # познакомились
        self.assertEqual(service.run.call_args.args[0], 'открой почту')

    @unittest.skipUnless(os.getenv('LOCAL_AI_SPEAKER_MODEL'), 'нужна модель CAM++ (LOCAL_AI_SPEAKER_MODEL)')
    def test_real_model(self):
        from src.speech.speaker import SpeakerGate
        gate = SpeakerGate(Store(tempfile.mkdtemp()), model_path=Path(os.environ['LOCAL_AI_SPEAKER_MODEL']))

        def voice(f0, formants, seed):  # гармоники основного тона, окрашенные формантами «голоса»
            rng = np.random.default_rng(seed)
            t = np.arange(16000 * 2.5) / 16000
            phase = 2 * np.pi * np.cumsum(f0 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t + rng.random()))) / 16000
            x = sum(np.sin(k * phase) / k * sum(np.exp(-((k * f0 - f) / 150) ** 2) for f in formants) for k in range(1, 40))
            x = x * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t + rng.random() * 6))
            return (x / np.abs(x).max() * 0.5 + 0.005 * rng.standard_normal(t.size)).astype(np.float32)
        a1 = gate.embed(voice(110, [700, 1200, 2600], 1))
        a2 = gate.embed(voice(112, [700, 1200, 2600], 2))
        b = gate.embed(voice(220, [900, 1800, 3000], 3))
        self.assertAlmostEqual(float(np.linalg.norm(a1)), 1.0, places=4)
        self.assertGreater(float(a1 @ a2), float(a1 @ b) + 0.2)
        self.assertIsNone(gate.embed(np.zeros(4000, dtype=np.float32)))


if __name__ == '__main__':
    unittest.main()
