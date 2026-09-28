"""Интеграции: JSON (HTTP API и локальный файл), Python-плагины, данные для вопросов нейросети."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.agent import LocalComputerAgent
from src.integrations import Integrations, folder, say


class FakeHTTP:
    def __init__(self):
        self.requests = []
        self.tasks = [{'title': 'Купить молоко'}, {'title': 'Позвонить маме'}]

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.requests.append((method, url, headers, json))
        if method == 'POST':
            self.tasks.append({'title': json['title']})
            body = {'ok': True}
        else:
            body = {'items': self.tasks, 'day': 'today'}
        return Mock(raise_for_status=lambda: None, json=lambda: body)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        folder(self.root).mkdir()
        self.http = FakeHTTP()
        self.export = self.root / 'export.json'
        self.export.write_text(json.dumps([{'habit': 'Бег', 'done': True}, {'habit': 'Чтение', 'done': False}],
                                          ensure_ascii=False), encoding='utf-8')
        (folder(self.root) / 'tracker.json').write_text(json.dumps({
            'name': 'Трекер',
            'commands': [
                {'phrases': ['что в трекере( на (?P<day>сегодня|завтра))?'], 'method': 'GET',
                 'url': 'https://tracker.example/api/tasks?day={day}',
                 'headers': {'Authorization': 'Bearer {secret:TRACKER_TOKEN}'}, 'say': 'Задач: {count}. {items[*].title}'},
                {'phrases': ['добавь в трекер (?P<text>.+)'], 'method': 'POST', 'url': 'https://tracker.example/api/tasks',
                 'json': {'title': '{text}'}, 'say': 'Добавил в трекер: {text}'},
            ],
            'context': {'phrases': ['привычк'], 'file': str(self.export)},
        }, ensure_ascii=False), encoding='utf-8')
        (folder(self.root) / 'secrets.json').write_text('{"TRACKER_TOKEN": "abc123"}', encoding='utf-8')
        self.integrations = Integrations(self.root, session=self.http)

    def tearDown(self):
        self.temp.cleanup()

    def test_read_data_by_voice(self):
        answer = self.integrations.handle('Что в трекере на сегодня?')
        self.assertEqual(answer, 'Задач: 2. Купить молоко, Позвонить маме')
        method, url, headers, _ = self.http.requests[0]
        self.assertEqual(url, 'https://tracker.example/api/tasks?day=сегодня')
        self.assertEqual(headers['Authorization'], 'Bearer abc123')

    def test_action_in_app(self):
        self.assertEqual(self.integrations.handle('добавь в трекер тренировка в 7'), 'Добавил в трекер: тренировка в 7')
        self.assertEqual(self.http.requests[-1][3], {'title': 'тренировка в 7'})

    def test_not_ours(self):
        self.assertIsNone(self.integrations.handle('открой калькулятор'))

    def test_context_for_llm(self):
        context = self.integrations.context('как мои привычки на этой неделе?')
        self.assertIn('Данные из «Трекер»', context)
        self.assertIn('Бег', context)
        self.assertIsNone(self.integrations.context('какая погода?'))

    def test_agent_uses_integrations(self):
        brain = Mock()
        brain.answer.return_value = 'Бег выполнен, чтение — нет.'
        agent = LocalComputerAgent(Mock(), brain=brain, integrations=self.integrations)
        self.assertEqual(agent.process_command('Андрей, что в трекере', {}), 'Задач: 2. Купить молоко, Позвонить маме')
        agent.process_command('Андрей, как мои привычки?', {})
        self.assertIn('Чтение', brain.answer.call_args.args[0])

    def test_python_plugin_and_hot_reload(self):
        self.integrations.load()
        (folder(self.root) / 'steps.py').write_text(
            "NAME = 'Шаги'\n"
            "def steps(match, settings):\n    return 'Сегодня 8 000 шагов.'\n"
            "COMMANDS = [(r'сколько шагов( сегодня)?', steps)]\n", encoding='utf-8')
        os.utime(folder(self.root) / 'steps.py', (1, 1))  # другое время изменения — папка перечитывается
        self.assertEqual(self.integrations.handle('сколько шагов сегодня'), 'Сегодня 8 000 шагов.')
        names = [i['name'] for i in self.integrations.status()['items']]
        self.assertEqual(sorted(names), ['Трекер', 'Шаги'])

    def test_broken_file_reported(self):
        (folder(self.root) / 'bad.json').write_text('{oops', encoding='utf-8')
        status = Integrations(self.root, session=self.http).status()
        self.assertTrue(any('bad.json' in e for e in status['errors']))
        self.assertEqual(len(status['items']), 1)

    def test_only_http_urls(self):
        (folder(self.root) / 'evil.json').write_text(json.dumps({'commands': [
            {'phrases': ['прочитай файл'], 'url': 'file:///etc/passwd'}]}), encoding='utf-8')
        self.assertIn('только адреса http', Integrations(self.root, session=self.http).handle('прочитай файл'))

    def test_say_template(self):
        self.assertEqual(say('{a.b} и {list[*].x}', {'a': {'b': 5}, 'list': [{'x': 1}, {'x': 2}]}), '5 и 1, 2')

    def test_open_folder_creates_example(self):
        from app import create_app
        from src.storage import Store
        with tempfile.TemporaryDirectory() as data:
            store = Store(data)
            app = create_app(store, Mock(status=Mock(return_value={})), Mock(integrations=None),
                             license=Mock(is_premium=lambda: True))
            with patch('src.web_services.system_open', return_value=True):
                result = app.test_client().post('/api/integrations/open-folder',
                                                headers={'X-Agent-Token': store.meta('pairing_token')}).get_json()
            self.assertTrue((Path(result['path']) / 'example.json.txt').exists())


if __name__ == '__main__':
    unittest.main()
