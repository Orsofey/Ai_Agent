"""Telegram: поиск любого чата голосом, псевдонимы, группы и сообщения в открытый чат."""
import unittest
from unittest.mock import Mock, patch

from src.desktop import messengers
from src.desktop.commands import DesktopCommands, parse

ALIASES = {'contact_aliases': 'Арсений Крэк = Arseny Crack\nМама = Мамуля'}


class ParseTests(unittest.TestCase):
    def test_multiword_names(self):
        self.assertEqual(messengers.parse('Напиши в Telegram Арсению Крэку привет как дела'),
                         dict(app='telegram', who='Арсению Крэку', text='привет как дела', send=False))
        self.assertEqual(messengers.parse('в телеграме напиши Арсению Крэку привет')['who'], 'Арсению Крэку')
        self.assertEqual(messengers.parse('Напиши Arseny Crack в Telegram привет')['who'], 'Arseny Crack')

    def test_group(self):
        request = messengers.parse('напиши в группу Семья в телеграме я еду')
        self.assertEqual((request['who'], request['text']), ('Семья', 'я еду'))

    def test_open_chat(self):
        cases = {'Открой чат с Арсением Крэком': 'Арсением Крэком',
                 'открой чат с Арсением Крэком в телеграме': 'Арсением Крэком',
                 'Открой в телеграме Арсения': 'Арсения',
                 'Открой телеграм и найди группу Работа': 'Работа',
                 'Перейди в группу Семья': 'Семья',
                 'перейди к Милане в телеграме': 'Милане'}
        for text, who in cases.items():
            self.assertEqual(parse(text), ('open_chat', dict(app='telegram', who=who)), text)
        self.assertIsNone(messengers.parse_open('открой телеграм'))
        self.assertIsNone(messengers.parse_open('открой калькулятор'))

    def test_current_chat(self):
        self.assertEqual(parse('ответь привет'), ('chat_type', dict(text='привет', send=True)))
        self.assertEqual(parse('напиши в чат я скоро буду'), ('chat_type', dict(text='я скоро буду', send=False)))


class SearchTests(unittest.TestCase):
    def test_stems(self):
        self.assertEqual(messengers.search_stem('Арсением Крэком'), 'Арсени Крэк')
        self.assertEqual(messengers.search_stem('Арсению Крэку'), 'Арсени Крэк')
        self.assertEqual(messengers.search_stem('Arseny Crack'), 'Arseny Crack')

    def test_alias_any_case(self):
        for who in ('Арсений Крэк', 'Арсению Крэку', 'Арсением Крэком', 'арсения крэка'):
            self.assertEqual(messengers.search_query(who, ALIASES), 'Arseny Crack', who)
        self.assertEqual(messengers.search_query('маме', ALIASES), 'Мамуля')
        self.assertEqual(messengers.search_query('Милане', ALIASES), 'Милан')

    def test_latin(self):
        self.assertEqual(messengers.search_query('Арсению', {'contacts_latin': True}), 'Arsen')
        self.assertTrue('Arseny'.startswith(messengers.latin_query('Арсений Крэк')))
        self.assertTrue('Milana'.startswith(messengers.latin_query('Милане')))


@patch('src.desktop.messengers.time.sleep')
class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.desktop = Mock()
        self.desktop.target_process.return_value = 'telegram.exe'
        self.commands = DesktopCommands(self.desktop)
        self.winapi = patch('src.desktop.winapi').start()
        self.addCleanup(patch.stopall)

    def typed(self):
        return [c.args[0] for c in self.winapi.type_unicode.call_args_list]

    def test_open_chat_then_write(self, sleep):
        answer = self.commands.handle('Открой чат с Арсением Крэком', ALIASES)
        self.assertIn('Арсением Крэком', answer)
        self.assertEqual(self.typed(), ['Arseny Crack'])
        self.assertEqual(self.commands.chat, dict(app='telegram', who='Арсением Крэком'))
        # Дальше «напиши …» печатает в открытый чат (Telegram на переднем плане).
        self.commands.handle('Напиши привет, как дела?', {})
        self.desktop.type_text.assert_called_once_with('привет, как дела?', 'auto')

    def test_reply_to_current_chat(self, sleep):
        self.commands.chat = dict(app='telegram', who='Семья')
        self.desktop.target_process.return_value = 'winword.exe'
        self.desktop.activate_process.return_value = True
        self.assertIn('Отправил', self.commands.handle('ответь буду в семь', {}))
        self.desktop.activate_process.assert_called_once_with({'telegram.exe'})
        self.assertEqual(self.typed(), ['буду в семь'])
        self.winapi.hotkey.assert_called_with('enter')

    def test_message_remembers_chat(self, sleep):
        self.commands.handle('Напиши в Telegram Арсению Крэку привет', ALIASES)
        self.assertEqual(self.typed(), ['Arseny Crack', 'привет'])
        self.assertEqual(self.commands.chat['who'], 'Арсению Крэку')

    def test_messenger_not_running(self, sleep):
        self.desktop.activate_process.return_value = False
        self.assertIn('Не удалось открыть Telegram', self.commands.handle('Открой чат с Миланой', {}))
        self.assertIsNone(self.commands.chat)


if __name__ == '__main__':
    unittest.main()
