"""Тесты повседневного разговора: приветствия, small talk, время, дата."""
import unittest
from unittest.mock import Mock
from src.conversation import match_casual, is_casual, time_response, date_response
from src.agent import LocalComputerAgent


class ConversationTests(unittest.TestCase):
    def test_greeting(self):
        category, answer = match_casual('Привет')
        self.assertEqual(category, 'greeting')
        self.assertTrue(answer)

    def test_how_are_you(self):
        category, answer = match_casual('Как дела?')
        self.assertEqual(category, 'how_are_you')
        self.assertTrue(answer)

    def test_time_is_local(self):
        category, answer = match_casual('Который час?')
        self.assertEqual(category, 'time')
        self.assertTrue(answer.startswith('Сейчас'))

    def test_date_is_local(self):
        category, answer = match_casual('Какое сегодня число?')
        self.assertEqual(category, 'date')
        self.assertTrue(answer.startswith('Сегодня'))

    def test_joke(self):
        self.assertEqual(match_casual('Расскажи шутку')[0], 'joke')

    def test_unknown_is_not_casual(self):
        self.assertFalse(is_casual('случайный шум'))

    def test_commands_not_hijacked(self):
        # Реальные команды не должны попадать в разговорные шаблоны.
        for command in ['Открой калькулятор', 'Закрой приложение Chrome',
                        'Включи видео котики', 'Пауза видео', 'Найди погоду',
                        'Открой браузер', 'Напиши текст Привет']:
            self.assertFalse(is_casual(command), command)

    def test_agent_replies_to_casual_without_browser(self):
        browser = Mock()
        agent = LocalComputerAgent(browser)
        answer = agent.process_command('Привет')
        self.assertTrue(answer)
        browser.call.assert_not_called()

    def test_agent_still_runs_commands(self):
        browser = Mock()
        agent = LocalComputerAgent(browser)
        agent.process_command('Включи видео котики на Rutube')
        browser.call.assert_called_once_with('video', 'котики', 'rutube')


if __name__ == '__main__':
    unittest.main()
