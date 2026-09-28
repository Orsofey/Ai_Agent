"""5.5: вкладки по номеру и по сайту, страницы Word, чёрно-белый экран, сценарии и блокировки, Трекер онлайн."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

from src import display, scenarios, tracker
from src.agent import LocalComputerAgent
from src.desktop import navigation
from src.desktop.commands import DesktopCommands, parse as desktop_parse
from src.storage import Store


class NumberTests(unittest.TestCase):
    def test_numbers(self):
        for text, value in [('10', 10), ('десять', 10), ('десятую', 10), ('первую', 1), ('третью', 3),
                            ('двадцать первую', 21), ('номер 3', 3), ('пятнадцатой', 15), ('двадцать пять', 25)]:
            self.assertEqual(navigation.number(text), value, text)
        self.assertIsNone(navigation.number('новую'))


class TabParseTests(unittest.TestCase):
    def test_tab_numbers(self):
        cases = {
            'перейди на первую вкладку': 1, 'Перейди на вторую вкладку': 2, 'открой третью вкладку': 3,
            'переключись на вкладку 5': 5, 'на десятую вкладку': 10, 'вкладка номер 4': 4,
            'перейди на последнюю вкладку': 'last', 'следующая вкладка': 'next', 'предыдущая вкладка': 'prev',
        }
        for text, value in cases.items():
            self.assertEqual(navigation.parse_tab(text), value, text)
        self.assertIsNone(navigation.parse_tab('открой новую вкладку'))
        self.assertIsNone(navigation.parse_tab('закрой вкладку'))
        self.assertEqual(desktop_parse('перейди на первую вкладку'), ('tab', {'which': 1}))
        self.assertEqual(desktop_parse('открой новую вкладку'), ('keys', {'keys': ('ctrl', 't'), 'times': 1}))

    def test_site_phrases(self):
        self.assertEqual(navigation.parse_site('перейди в ютуб'), ('перейди', 'ютуб'))
        self.assertEqual(navigation.parse_site('Андрей переключись на вкладку YouTube'.split(' ', 1)[1]),
                         ('переключись', 'YouTube'))
        self.assertEqual(navigation.parse_site('открой ютуб'), ('открой', 'ютуб'))
        self.assertIsNone(navigation.parse_site('открой ютуб в хроме'))
        self.assertIsNone(navigation.parse_site('перейди на первую вкладку'))

    def test_title_markers(self):
        markers = navigation.title_markers('https://www.youtube.com', ['ютуб'])
        self.assertTrue(navigation.title_matches('Котики - YouTube - Google Chrome', markers))
        self.assertFalse(navigation.title_matches('Почта - Яндекс Браузер', markers))
        self.assertTrue(navigation.title_matches('Моя волна — Яндекс Музыка',
                                                 navigation.title_markers('https://music.yandex.ru')))


class TabExecuteTests(unittest.TestCase):
    def make(self, process='chrome.exe'):
        desktop = Mock(available=True)
        desktop.target_process.return_value = process
        return desktop, DesktopCommands(desktop)

    def test_hotkeys(self):
        desktop, commands = self.make()
        self.assertEqual(commands.handle('перейди на первую вкладку', {}), 'Вкладка 1.')
        desktop.hotkey.assert_called_with('ctrl', '1')
        commands.handle('последняя вкладка', {})
        desktop.hotkey.assert_called_with('ctrl', '9')
        desktop.hotkey.reset_mock()
        commands.handle('перейди на двенадцатую вкладку', {})
        self.assertEqual(desktop.hotkey.call_args_list[0].args, ('ctrl', '1'))
        self.assertEqual(desktop.hotkey.call_args_list[1].kwargs, {'times': 11})

    def test_not_in_browser(self):
        desktop, commands = self.make('winword.exe')
        self.assertIn('Переключитесь в окно браузера', commands.handle('перейди на вторую вкладку', {}))
        desktop.hotkey.assert_not_called()

    def test_extension_when_browser_not_active(self):
        desktop, commands = self.make('explorer.exe')
        commands.tabs.browser = Mock()
        commands.tabs.browser.bridge = Mock(connected=True)
        commands.tabs.browser.bridge.send.return_value = {'index': 2}
        self.assertEqual(commands.handle('перейди на вторую вкладку', {}), 'Вкладка 2.')
        commands.tabs.browser.bridge.send.assert_called_once_with('tab', index=2)

    def test_switch_to_open_tab_by_title(self):
        titles = iter(['Почта - Chrome', 'Хабр - Chrome', 'Котики - YouTube - Chrome'])
        state = {'title': next(titles)}

        def hotkey(*keys):
            state['title'] = next(titles)
        winapi = Mock(supported=lambda: True, foreground=lambda: 1, hotkey=hotkey,
                      window_title=lambda hwnd: state['title'], process_name=lambda hwnd: 'chrome.exe')
        with patch('src.desktop.winapi', winapi), patch('src.desktop.navigation.sys.platform', 'win32'), \
                patch('src.desktop.navigation.time.sleep'):
            result = navigation.TabNavigator(Mock()).switch_to_site('https://www.youtube.com', ['ютуб'])
        self.assertEqual(result, 'Переключаюсь на YouTube.')

    def test_no_open_tab_returns_to_start(self):
        titles = ['A - Chrome', 'B - Chrome', 'A - Chrome']
        state = {'i': 0}

        def hotkey(*keys):
            state['i'] += 1
        winapi = Mock(supported=lambda: True, foreground=lambda: 1, hotkey=hotkey,
                      window_title=lambda hwnd: titles[min(state['i'], 2)], process_name=lambda hwnd: 'chrome.exe')
        with patch('src.desktop.winapi', winapi), patch('src.desktop.navigation.sys.platform', 'win32'), \
                patch('src.desktop.navigation.time.sleep'):
            self.assertIsNone(navigation.TabNavigator(Mock()).switch_to_site('https://www.youtube.com'))
        self.assertEqual(state['i'], 2)


class AgentSiteTests(unittest.TestCase):
    def agent(self, connected=False):
        browser = Mock()
        browser.bridge = Mock(connected=connected)
        browser.call.return_value = 'Открываю YouTube'
        commands = DesktopCommands(Mock(available=True), browser=browser)
        return LocalComputerAgent(browser, desktop_commands=commands), browser, commands

    def test_go_to_youtube_switches_to_open_tab(self):
        agent, browser, commands = self.agent()
        commands.tabs.switch_to_site = Mock(return_value='Переключаюсь на YouTube.')
        self.assertIn('YouTube', agent.process_command('Андрей, перейди в ютуб', {'butler': False}))
        commands.tabs.switch_to_site.assert_called_once_with('https://www.youtube.com', ['ютуб'])
        browser.call.assert_not_called()

    def test_go_to_youtube_opens_when_not_open(self):
        agent, browser, commands = self.agent()
        commands.tabs.switch_to_site = Mock(return_value=None)
        agent.process_command('перейди в ютуб', {'butler': False})
        browser.call.assert_called_once_with('open', 'https://www.youtube.com')

    def test_open_youtube_uses_extension(self):
        agent, browser, _ = self.agent(connected=True)
        agent.process_command('открой ютуб', {'butler': False})
        browser.call.assert_called_once_with('open', 'https://www.youtube.com')


class WordTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(navigation.parse_word('перейди на страницу 10'), ('page', 10))
        self.assertEqual(navigation.parse_word('Перейди на страницу десять'), ('page', 10))
        self.assertEqual(navigation.parse_word('перейди на десятую страницу'), ('page', 10))
        self.assertEqual(navigation.parse_word('перейди на последнюю страницу'), ('page', -1))
        self.assertEqual(navigation.parse_word('перейди на страницу, где есть слово «Каша»'), ('find', 'Каша'))
        self.assertEqual(navigation.parse_word('перейди на страницу где написано каша'), ('find', 'каша'))
        self.assertEqual(navigation.parse_word('найди страницу со словом договор'), ('find', 'договор'))
        self.assertEqual(navigation.parse_word('перейди к слову итоги'), ('find', 'итоги'))
        self.assertEqual(navigation.parse_word('найди дальше'), ('next', None))
        self.assertIsNone(navigation.parse_word('перейди в ютуб'))

    def test_scripts(self):
        script = navigation.word_script('page', 10)
        self.assertIn('GetActiveObject', script)
        self.assertIn('$s.GoTo(1,1,10)', script)
        self.assertIn("Execute('it''s'", navigation.word_script('find', "it's"))
        self.assertIn('Collapse(0)', navigation.word_script('next', 'каша'))

    def test_only_in_word(self):
        desktop = Mock(available=True)
        desktop.target_process.return_value = 'chrome.exe'
        commands = DesktopCommands(desktop)
        self.assertIsNone(commands.handle('перейди на страницу 10', {}))
        desktop.target_process.return_value = 'WINWORD.EXE'.casefold()
        with patch('src.desktop.navigation._powershell', return_value=(0, '10', '')) as ps:
            self.assertEqual(commands.handle('перейди на страницу 10', {}), 'Страница 10.')
        ps.assert_called_once()
        with patch('src.desktop.navigation._powershell', return_value=(0, '7', '')):
            self.assertIn('на странице 7', commands.handle('перейди на страницу, где есть слово каша', {}))
        with patch('src.desktop.navigation._powershell', return_value=(0, 'NOTFOUND', '')):
            self.assertEqual(commands.handle('найди дальше', {}), 'Больше совпадений нет.')
        with patch('src.desktop.navigation._powershell', return_value=(0, 'TOTAL 5', '')):
            self.assertIn('всего 5', commands.handle('перейди на страницу 10', {}))

    def test_keyboard_fallback(self):
        desktop = Mock(available=True)
        desktop.target_process.return_value = 'winword.exe'
        commands = DesktopCommands(desktop)
        with patch('src.desktop.navigation._powershell', side_effect=OSError), \
                patch('src.desktop.navigation.time.sleep'):
            self.assertEqual(commands.handle('перейди на страницу 3', {}), 'Страница 3.')
        desktop.hotkey.assert_any_call('ctrl', 'g')
        desktop.type_text.assert_called_with('3', 'keys')


class DisplayTests(unittest.TestCase):
    def test_parse(self):
        for text in ('включи чёрно-белый режим', 'сделай экран черно белым', 'включи чб', 'переведи экран в чб',
                     'включи оттенки серого'):
            self.assertIs(display.parse(text), True, text)
        for text in ('верни цвета', 'выключи чб', 'выключи чёрно-белый режим', 'сделай цветной экран'):
            self.assertIs(display.parse(text), False, text)
        self.assertEqual(display.parse('переключи чб'), 'toggle')
        self.assertIsNone(display.parse('включи телеграм'))

    def test_windows_registry_and_toggle(self):
        state = {'active': 0, 'values': {}}

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        winreg = Mock(HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, REG_DWORD=4)
        winreg.OpenKey.return_value = Key()
        winreg.CreateKeyEx.return_value = Key()
        winreg.QueryValueEx.side_effect = lambda key, name: (state['active'], 4)
        winreg.SetValueEx.side_effect = lambda key, name, _, kind, value: state['values'].__setitem__(name, value)

        def atbroker(*a, **k):
            state['active'] = 1 - state['active']
        with patch.dict('sys.modules', {'winreg': winreg}), patch('src.display.sys.platform', 'win32'), \
                patch('src.display.subprocess.run', side_effect=atbroker) as run, patch('src.display.time.sleep'):
            self.assertEqual(display.set_grayscale(True), 'Экран чёрно-белый.')
            self.assertEqual(state['values'], {'FilterType': 0, 'HotkeyEnabled': 1})
            self.assertEqual(state['active'], 1)
            display.set_grayscale(True)  # уже включён — второй раз не переключаем
            self.assertEqual(run.call_count, 1)
            self.assertEqual(display.set_grayscale(False), 'Цвета вернул.')
            self.assertEqual(state['active'], 0)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(tempfile.mkdtemp())
        self.clock = Clock()
        self.notes = []
        self.browser = Mock()
        self.browser.bridge = Mock(connected=True)
        self.manager = scenarios.ScenarioManager(self.store, browser=self.browser, notify=self.notes.append,
                                                 clock=self.clock)
        self.manager.ensure_thread = Mock()
        self.manager._close_app = Mock()

    def test_minutes(self):
        for text, value in [('30 минут', 30), ('тридцать минут', 30), ('час', 60), ('полчаса', 30),
                            ('полтора часа', 90), ('2 часа', 120), ('2 часа 15 минут', 135), ('45', 45)]:
            self.assertEqual(scenarios.parse_minutes(text), value, text)
        self.assertIsNone(scenarios.parse_minutes('неделю'))
        self.assertEqual(scenarios.say_minutes(90), '1 час 30 минут')

    def test_parse(self):
        self.assertEqual(scenarios.parse('включи сценарий работа'), ('start', 'работа', None))
        self.assertEqual(scenarios.parse('Включи режим учёба на 45 минут'), ('start', 'учеба', 45))
        self.assertEqual(scenarios.parse('выключи сценарий'), ('stop', ''))
        self.assertEqual(scenarios.parse('заблокируй ютуб на 30 минут'), ('block', 'ютуб', 30))
        self.assertEqual(scenarios.parse('заблокируй стим'), ('block', 'стим', 60))
        self.assertEqual(scenarios.parse('разблокируй всё'), ('unblock', ''))
        self.assertEqual(scenarios.parse('сколько осталось'), ('status',))
        self.assertIsNone(scenarios.parse('заблокируй компьютер'))
        self.assertEqual(desktop_parse('заблокируй компьютер'), ('lock', {}))

    def test_start_blocks_sites_and_expires(self):
        reply = self.manager.handle('включи сценарий работа на 2 часа')
        self.assertIn('«Работа» включён на 2 часа', reply)
        self.browser.bridge.send.assert_called_with('block', timeout=5, domains=sorted(scenarios.DISTRACTING[:7]))
        self.assertIn('Работа', self.manager.status())
        self.manager._close_app.assert_any_call('steam')
        self.clock.now += 2 * 3600 + 1
        self.manager.enforce(force_sync=True)
        self.browser.bridge.send.assert_called_with('block', timeout=5, domains=[])
        self.assertIn('Сценарий «Работа» завершён.', self.notes)
        self.assertIn('ничего не заблокировано', self.manager.status())

    def test_block_and_unblock_single_site(self):
        self.assertEqual(self.manager.handle('заблокируй ютуб на 30 минут'), 'Заблокировал сайт youtube.com на 30 минут.')
        self.assertIn('youtube.com', self.manager.status())
        self.assertEqual(self.manager.handle('разблокируй ютуб'), 'Разблокировал youtube.com.')
        self.assertEqual(self.manager.handle('разблокируй всё'), 'Сейчас ничего не заблокировано.')

    def test_state_survives_restart(self):
        self.manager.handle('заблокируй вк на час')
        again = scenarios.ScenarioManager(self.store, clock=self.clock)
        self.assertEqual([b['value'] for b in again.active_blocks()], ['vk.com'])

    def test_unknown_scenario_and_editing(self):
        self.assertIn('Нет сценария', self.manager.handle('включи сценарий космос'))
        saved = self.manager.save([{'name': 'Космос', 'sites': ['https://www.YouTube.com/feed'], 'apps': 'steam, discord',
                                    'minutes': 15, 'grayscale': False}])
        self.assertEqual(saved[0]['sites'], ['youtube.com'])
        self.assertEqual(saved[0]['apps'], ['steam', 'discord'])
        self.assertIn('на 15 минут', self.manager.handle('включи сценарий космос'))
        with self.assertRaises(ValueError):
            self.manager.save([{'name': 'A', 'sites': ['не сайт']}])

    def test_grayscale_restored(self):
        self.manager.save([{'name': 'Учёба', 'grayscale': True, 'minutes': 10}])
        with patch('src.display.is_grayscale', return_value=False), \
                patch('src.display.set_grayscale', return_value='') as gray:
            self.manager.handle('включи сценарий учёба')
            gray.assert_called_with(True)
            self.manager.handle('выключи сценарий')
            gray.assert_called_with(False)

    def test_agent_routes(self):
        agent = LocalComputerAgent(Mock())
        agent.scenarios = self.manager
        self.assertIn('Заблокировал', agent.process_command('Андрей, заблокируй ютуб на 10 минут', {'butler': False}))


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self.data = data

    def json(self):
        return self.data


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(tempfile.mkdtemp())
        self.http = Mock()
        self.client = tracker.TrackerClient(self.store, session=self.http)

    def test_parse(self):
        self.assertEqual(tracker.parse('что в трекере на завтра'), ('tasks', date.today() + timedelta(days=1)))
        self.assertEqual(tracker.parse('мои задачи'), ('tasks', date.today()))
        self.assertEqual(tracker.parse('добавь в трекер задачу купить молоко на завтра'),
                         ('add', 'купить молоко', date.today() + timedelta(days=1)))
        self.assertEqual(tracker.parse('добавь в трекер позвонить маме'), ('add', 'позвонить маме', date.today()))
        self.assertEqual(tracker.parse('отметь задачу купить молоко выполненной'), ('done', 'купить молоко'))
        self.assertEqual(tracker.parse('отметь привычку зарядка'), ('habit', 'зарядка'))
        self.assertIsNone(tracker.parse('добавь в заметки хлеб'))

    def test_login_and_voice(self):
        self.http.request.return_value = FakeResponse(200, {'token': 'tok_' + 'x' * 30, 'user': {'name': 'Орсофей'}})
        status = self.client.login('https://tracker.example.ru/', 'me@example.ru', 'secret')
        self.assertEqual(status, {'connected': True, 'url': 'https://tracker.example.ru', 'user': 'Орсофей',
                                  'since': status['since']})
        self.assertNotIn('secret', self.store.meta('tracker'))  # пароль не сохраняется
        method, url = self.http.request.call_args.args
        self.assertEqual((method, url), ('POST', 'https://tracker.example.ru/api/agent/login'))

        self.http.request.return_value = FakeResponse(200, {'tasks': [{'title': 'Зарядка', 'done': True},
                                                                      {'title': 'Купить молоко', 'done': False}]})
        self.assertEqual(self.client.handle('что в трекере на сегодня'),
                         'На сегодня 1 из 2 задач не выполнено: Купить молоко.')
        headers = self.http.request.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer tok_' + 'x' * 30)

        self.http.request.return_value = FakeResponse(200, {'ok': True})
        self.assertIn('Добавил в трекер', self.client.handle('добавь в трекер задачу позвонить маме'))
        self.assertEqual(self.http.request.call_args.kwargs['json']['title'], 'позвонить маме')

        self.http.request.return_value = FakeResponse(200, {'text': 'ok', 'habits': [{'name': 'Зарядка', 'streak': 5}]})
        context = self.client.context('как у меня с привычками?')
        self.assertIn('Зарядка', context)
        self.assertIsNone(self.client.context('какая погода?'))

        self.http.request.return_value = FakeResponse(401, {'error': 'expired'})
        self.assertIn('подключите аккаунт заново', self.client.handle('мои задачи').casefold())
        self.assertFalse(self.client.connected)

    def test_requires_https_and_connection(self):
        with self.assertRaises(ValueError):
            self.client.login('http://tracker.example.ru', 'a', 'b')
        self.assertIn('не подключён', self.client.handle('что в трекере'))

    def test_agent_uses_tracker_context_for_llm(self):
        brain = Mock()
        brain.answer.return_value = 'Ответ'
        agent = LocalComputerAgent(Mock(), brain=brain)
        agent.tracker = Mock(handle=Mock(return_value=None), context=Mock(return_value='Данные из Трекера: 5 задач'))
        agent.process_command('как у меня с задачами на этой неделе?', {'butler': False})
        self.assertIn('Данные из Трекера', brain.answer.call_args.args[0])


class ApiTests(unittest.TestCase):
    def test_endpoints(self):
        from app import create_app
        store = Store(tempfile.mkdtemp())
        client = create_app(store, Mock(status=Mock(return_value={})), Mock(),
                            license=Mock(is_premium=lambda: True)).test_client()
        headers = {'X-Agent-Token': store.meta('pairing_token')}
        data = client.get('/api/scenarios', headers=headers).get_json()
        self.assertEqual([s['name'] for s in data['scenarios']][:3], ['Работа', 'Учёба', 'Игра'])
        body = {'scenarios': data['scenarios'][:1]}
        self.assertTrue(client.post('/api/scenarios', headers=headers, json=body).get_json()['success'])
        reply = client.post('/api/scenarios/start', headers=headers, json={'name': 'Работа', 'minutes': 5}).get_json()
        self.assertIn('включён на 5 минут', reply['message'])
        self.assertEqual(client.post('/api/scenarios/stop', headers=headers, json={'unblock': True}).get_json()['message'],
                         'Все блокировки сняты.')
        self.assertEqual(client.get('/api/tracker', headers=headers).get_json()['connected'], False)
        bad = client.post('/api/tracker/login', headers=headers, json={'url': 'ftp://x', 'email': 'a', 'password': 'b'})
        self.assertEqual(bad.status_code, 400)


if __name__ == '__main__':
    unittest.main()
