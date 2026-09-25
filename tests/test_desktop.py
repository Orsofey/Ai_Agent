"""Команды для любого приложения: разбор фраз и выполнение через подставной контроллер."""
import unittest
from unittest.mock import Mock, patch
from src.desktop.commands import parse, tidy_typed, apply_punctuation, DesktopCommands
from src.desktop import messengers
from src.desktop.hotkey import parse_hotkey
from src.agent import LocalComputerAgent


class ParseTests(unittest.TestCase):
    def test_user_example_type_text(self):
        self.assertEqual(parse('Напиши текст привет Милана'), ('type', {'text': 'привет Милана', 'send': False}))

    def test_recognizer_punctuation_is_kept_but_final_dot_dropped(self):
        self.assertEqual(parse('Напиши текст: привет, Милана.')[1]['text'], 'привет, Милана')

    def test_type_and_send(self):
        self.assertEqual(parse('напиши и отправь я уже еду'), ('type', {'text': 'я уже еду', 'send': True}))

    def test_messenger(self):
        action, request = parse('Напиши Милане в телеграме привет, как дела?')
        self.assertEqual(action, 'messenger')
        self.assertEqual((request['app'], request['who'], request['send']), ('telegram', 'Милане', False))
        self.assertEqual(request['text'], 'привет, как дела?')

    def test_messenger_send_and_order(self):
        self.assertTrue(parse('отправь Саше в ватсап ок')[1]['send'])
        self.assertEqual(parse('в телеграме напиши маме я буду поздно')[1]['who'], 'маме')

    def test_search_stem(self):
        self.assertEqual(messengers.search_stem('Милане'), 'Милан')
        self.assertEqual(messengers.search_stem('Андрею'), 'Андре')
        self.assertEqual(messengers.search_stem('Милане Ивановой'), 'Милан Иванов')

    def test_generation(self):
        self.assertEqual(parse('Сочини поздравление для Миланы')[0], 'generate')
        self.assertEqual(parse('Напиши письмо начальнику об отпуске')[0], 'generate')

    def test_hotkeys(self):
        self.assertEqual(parse('нажми ctrl+shift+t')[1]['keys'], ('ctrl', 'shift', 't'))
        self.assertEqual(parse('нажми контрол си')[1]['keys'], ('ctrl', 'c'))
        self.assertEqual(parse('нажми вниз 3 раза')[1], {'keys': ('down',), 'times': 3})
        self.assertEqual(parse('Отправь'), ('send_draft', {}))
        self.assertEqual(parse('громче')[1]['times'], 5)

    def test_windows_and_selection(self):
        self.assertEqual(parse('Сверни окно'), ('window', {'action': 'minimize'}))
        self.assertEqual(parse('переведи выделенное на английский')[1]['language'], 'English')
        self.assertEqual(parse('исправь ошибки')[1]['mode'], 'fix')
        self.assertEqual(parse('начни диктовку'), ('dictation', {'on': True}))

    def test_not_desktop_commands(self):
        for phrase in ('какой курс доллара', 'открой калькулятор', 'привет', 'включи видео котики'):
            self.assertIsNone(parse(phrase), phrase)

    def test_punctuation_words(self):
        self.assertEqual(apply_punctuation('привет запятая как дела вопросительный знак'), 'привет, как дела?')
        self.assertEqual(tidy_typed('первая строка новая строка вторая'), 'первая строка\nвторая')

    def test_hotkey_spec(self):
        self.assertEqual(parse_hotkey('ctrl+alt+space'), (0x0003, 0x20))
        with self.assertRaises(ValueError):
            parse_hotkey('space')


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.desktop = Mock()
        self.desktop.target_process.return_value = 'winword.exe'
        self.brain = Mock()
        self.commands = DesktopCommands(self.desktop, brain=self.brain)

    def test_types_into_active_window(self):
        answer = self.commands.handle('Напиши текст привет Милана', {'type_method': 'auto'})
        self.desktop.type_text.assert_called_once_with('привет Милана', 'auto')
        self.assertIn('привет Милана', answer)

    def test_type_and_send_presses_enter(self):
        self.commands.handle('напиши и отправь я еду', {})
        self.desktop.hotkey.assert_called_with('enter')

    def test_generate_uses_brain(self):
        self.brain.complete.return_value = 'С днём рождения, Милана!'
        self.commands.handle('Сочини поздравление для Миланы', {})
        self.desktop.type_text.assert_called_once()
        self.assertEqual(self.desktop.type_text.call_args.args[0], 'С днём рождения, Милана!')

    def test_fix_selection_pastes_result(self):
        self.desktop.copy_selection.return_value = 'превет мир'
        self.brain.complete.return_value = 'Привет, мир'
        self.assertIn('Исправил', self.commands.handle('Исправь ошибки', {}))
        self.desktop.paste.assert_called_once_with('Привет, мир')

    def test_read_selection(self):
        self.desktop.copy_selection.return_value = 'Текст для чтения'
        self.assertEqual(self.commands.handle('Прочитай выделенное', {}), 'Текст для чтения')

    def test_empty_selection(self):
        self.desktop.copy_selection.return_value = ''
        self.assertIn('выделите', self.commands.handle('Переведи выделенное', {}))

    def test_close_tab_only_in_browser(self):
        self.assertIsNone(self.commands.handle('Закрой вкладку', {}))
        self.desktop.target_process.return_value = 'chrome.exe'
        self.assertIn('закрыта', self.commands.handle('Закрой вкладку', {}))

    def test_dictation_flag(self):
        self.commands.handle('Начни диктовку', {})
        self.assertTrue(self.commands.dictation)
        self.commands.handle('Стоп диктовка', {})
        self.assertFalse(self.commands.dictation)

    def test_unavailable_on_other_os_is_explained(self):
        from src.desktop import DesktopController
        commands = DesktopCommands(DesktopController())
        with patch('src.desktop.winapi.IS_WINDOWS', False), patch('src.desktop.winapi.IS_MAC', False):
            self.assertIn('Windows', commands.handle('Напиши текст привет', {}))

    def test_agent_routes_desktop_first(self):
        agent = LocalComputerAgent(Mock(), desktop_commands=self.commands)
        agent.process_command('Андрей, напиши текст привет Милана', {'wake_word': 'Андрей'})
        self.desktop.type_text.assert_called_once_with('привет Милана', 'auto')


if __name__ == '__main__':
    unittest.main()
