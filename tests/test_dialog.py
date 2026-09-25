"""Ответы «Да, сэр», уточняющие вопросы, YouTube в том же окне и кнопка «Пауза»."""
import random
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from app import create_app
from src.agent import LocalComputerAgent
from src.brain.llm import system_prompt
from src.dialog import Dialog, butler, incomplete_verb, misheard_command
from src.events import EventBus
from src.service import AssistantService
from src.storage import Store
from src.youtube import youtube_command


class ButlerTests(unittest.TestCase):
    def say(self, text, command, seed=0):
        return butler(text, command, 'сэр', random.Random(seed))

    def test_verb_follows_command(self):
        # «Включи Telegram» → «включаю», а не «открываю».
        for seed in range(6):
            answer = self.say('Открываю Telegram.', 'включи telegram', seed)
            self.assertIn('сэр', answer)
            self.assertIn('ключаю Telegram', answer)
            self.assertNotIn('Открываю', answer)

    def test_replies_vary(self):
        answers = {self.say('Запускаю Ютуб.', 'запусти ютуб', seed) for seed in range(30)}
        self.assertGreaterEqual(len(answers), 3)

    def test_error_is_apologetic(self):
        answer = self.say('Приложение не найдено: ворд', 'открой ворд')
        self.assertTrue(answer.startswith(('Прошу прощения, сэр', 'Увы, сэр')), answer)
        answer = self.say('Открытие приложений доступно только в Windows.', 'открой ворд')
        self.assertFalse(answer.startswith('Да, сэр'), answer)

    def test_done(self):
        self.assertIn(self.say('Готово.', 'нажми enter'), ('Готово, сэр.', 'Сделано, сэр.', 'Выполнено, сэр.'))

    def test_no_address(self):
        self.assertEqual(butler('Открываю Telegram.', 'открой telegram', ''), 'Открываю Telegram.')


class DialogHelpersTests(unittest.TestCase):
    def test_incomplete(self):
        self.assertEqual(incomplete_verb('открой'), 'открой')
        self.assertEqual(incomplete_verb('откройку'), 'открой')
        self.assertEqual(incomplete_verb('Запусти.'), 'запусти')
        self.assertIsNone(incomplete_verb('открой телеграм'))
        self.assertIsNone(incomplete_verb('привет'))

    def test_misheard(self):
        self.assertEqual(misheard_command('запустил Telegram', set()), 'запусти Telegram')
        self.assertEqual(misheard_command('открыл калькулятор', set()), 'открой калькулятор')
        self.assertIsNone(misheard_command('открой калькулятор', {'открой'}))
        self.assertIsNone(misheard_command('погода завтра', set()))

    def test_pending_expires(self):
        dialog = Dialog()
        dialog.set('u', 'confirm', 'запусти telegram')
        self.assertTrue(dialog.awaiting('u'))
        dialog.pending['u']['until'] = time.monotonic() - 1
        self.assertFalse(dialog.awaiting('u'))


@patch('src.agent.launch', side_effect=lambda name: f'Открываю {name}.')
class AgentDialogTests(unittest.TestCase):
    def setUp(self):
        self.browser = Mock()
        self.browser.call.side_effect = lambda method, *args: 'Открываю Ютуб.' if method == 'open' else 'ok'
        self.agent = LocalComputerAgent(self.browser)

    def run_command(self, text, **settings):
        return self.agent.process_command(text, settings, owner='u')

    def test_butler_launch(self, launch):
        answer = self.run_command('Андрей, включи Telegram')
        launch.assert_called_once_with('Telegram')
        self.assertIn('сэр', answer)
        self.assertIn('ключаю Telegram', answer)

    def test_butler_off(self, launch):
        self.assertEqual(self.run_command('включи Telegram', butler=False), 'Открываю Telegram.')

    def test_address_setting(self, launch):
        self.assertIn('мадам', self.run_command('открой Telegram', address='мадам'))
        self.assertEqual(self.run_command('открой Telegram', address='none'), 'Открываю Telegram.')

    def test_what_to_open(self, launch):
        self.assertEqual(self.run_command('Андрей, откройку'), 'Что открыть, сэр?')
        self.assertTrue(self.agent.awaiting('u'))
        answer = self.run_command('Андрей, телеграм')
        launch.assert_called_once_with('телеграм')
        self.assertIn('сэр', answer)
        self.assertFalse(self.agent.awaiting('u'))

    def test_confirm_misheard(self, launch):
        self.assertEqual(self.run_command('запустил Telegram'), 'Запустить Telegram, сэр?')
        launch.assert_not_called()
        answer = self.run_command('Андрей, да')
        launch.assert_called_once_with('Telegram')
        self.assertIn('апускаю Telegram', answer)

    def test_confirm_declined(self, launch):
        self.run_command('запустил Telegram')
        self.assertIn('отменяю', self.run_command('нет'))
        launch.assert_not_called()

    def test_other_command_after_question(self, launch):
        self.run_command('открой')
        self.run_command('закрой вкладку')
        self.browser.call.assert_called_with('close_tab')

    def test_youtube_flow(self, launch):
        self.assertIn('Ютуб', self.run_command('Запусти ютуб'))
        self.browser.call.assert_called_with('open', 'https://www.youtube.com')
        self.run_command('Андрей, открой первое видео')
        self.browser.call.assert_called_with('youtube', 'pick', 1)

    def test_llm_prompt_address(self, launch):
        self.assertIn('«сэр»', system_prompt({}))
        self.assertNotIn('сэр', system_prompt({'address': 'none'}))


class YouTubeParseTests(unittest.TestCase):
    def test_pick(self):
        cases = {'Открой первое видео': 1, 'включи третий ролик': 3, 'открой видео номер 5': 5,
                 'второе видео': 2, 'запусти последнее видео': -1, 'открой 4-е видео на ютубе': 4}
        for text, n in cases.items():
            self.assertEqual(youtube_command(text), ('pick', n), text)

    def test_search_and_controls(self):
        self.assertEqual(youtube_command('найди на ютубе рецепт борща'), ('search', 'рецепт борща'))
        self.assertEqual(youtube_command('найди котиков на youtube'), ('search', 'котиков'))
        self.assertEqual(youtube_command('следующее видео'), ('next',))
        self.assertEqual(youtube_command('перемотай на 30 секунд'), ('seek', 30))
        self.assertEqual(youtube_command('отмотай на 2 минуты'), ('seek', -120))
        self.assertIsNone(youtube_command('открой калькулятор'))

    def test_pick_script_in_browser(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright не установлен')
        from src.browser_control import BrowserController
        html = ('<div id="masthead"><a href="https://www.youtube.com/watch?v=MASTHEAD000">logo</a></div>'
                '<a href="https://www.youtube.com/watch?v=AAAAAAAAAAA">1</a>'
                '<a href="https://www.youtube.com/watch?v=AAAAAAAAAAA&t=5">1 дубль</a>'
                '<a href="https://www.youtube.com/watch?v=CURRENT0000">текущее</a>'
                '<a href="https://www.youtube.com/shorts/BBBBBBBBBBB">2</a>'
                '<a hidden href="https://www.youtube.com/watch?v=HIDDEN00000">скрыто</a>'
                '<a href="https://example.com">не видео</a>')
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path='/opt/pw-browsers/chromium') \
                    if __import__('os').path.exists('/opt/pw-browsers/chromium') else p.chromium.launch()
                page = browser.new_page()
                page.set_content(html)
                links = page.evaluate(BrowserController.PICK_SCRIPT, 'CURRENT0000')
                browser.close()
        except Exception as exc:
            self.skipTest(f'Браузер недоступен: {exc}')
        self.assertEqual(links, ['https://www.youtube.com/watch?v=AAAAAAAAAAA',
                                 'https://www.youtube.com/shorts/BBBBBBBBBBB'])


class CancelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_cancel_stops_long_command(self):
        started = threading.Event()

        def slow(text, settings, owner=None, on_text=None):
            started.set()
            for _ in range(200):
                on_text('слово ')
                time.sleep(0.01)
            return 'полный ответ'

        agent = Mock()
        agent.process_command.side_effect = slow
        service = AssistantService(self.store, agent, EventBus())
        threading.Thread(target=lambda: (started.wait(2), time.sleep(0.05), service.cancel()), daemon=True).start()
        began = time.monotonic()
        result, spoken = service.run('расскажи длинную историю', 'u', {})
        self.assertEqual(result, 'Остановлено.')
        self.assertLess(time.monotonic() - began, 1.5)
        self.assertFalse(service.lock.locked())
        # Следующая команда выполняется как обычно.
        agent.process_command.side_effect = None
        agent.process_command.return_value = 'ок'
        self.assertEqual(service.run('привет', 'u', {})[0], 'ок')

    def test_cancel_api(self):
        agent = Mock()
        agent.process_command.return_value = 'ok'
        speech = Mock()
        speech.status.return_value = {'ready': True}
        player = Mock()
        player.is_busy.return_value = True
        app = create_app(self.store, speech, agent, player=player)
        client = app.test_client()
        headers = {'X-Agent-Token': self.store.meta('pairing_token'), 'X-Device-ID': 'desktop'}
        response = client.post('/api/cancel', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['cancelled'])
        player.stop.assert_called()
        self.assertEqual(client.post('/api/cancel').status_code, 401)


if __name__ == '__main__':
    unittest.main()
