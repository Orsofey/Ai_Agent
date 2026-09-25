"""Мгновенные ответы (курсы, погода, калькулятор) и потоковый ИИ с инструментами."""
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from src.brain import Brain, LLMError
from src.brain.numbers import words_to_digits, plural, say_number
from src.brain.quick import QuickAnswers, spoken_math, safe_eval, city_candidates, locative
from src.brain.llm import OpenAICompatibleProvider, ThinkFilter
from src.storage import Store

CBR = {'Date': '2026-09-24T11:30:00+03:00', 'Valute': {
    'USD': {'Nominal': 1, 'Value': 81.5234, 'Previous': 81.2},
    'EUR': {'Nominal': 1, 'Value': 95.1, 'Previous': 95.3},
    'CNY': {'Nominal': 1, 'Value': 11.4, 'Previous': 11.4},
    'JPY': {'Nominal': 100, 'Value': 55.0, 'Previous': 55.0}}}
FORECAST = {'current': {'temperature': 12.4, 'wind': 3.0, 'humidity': 70, 'condition': 'пасмурно'},
            'daily': [dict(date='2026-09-24', condition='пасмурно', t_min=7, t_max=15, precipitation=0.0, wind=4),
                      dict(date='2026-09-25', condition='небольшой дождь', t_min=6, t_max=13, precipitation=4.2, wind=9),
                      dict(date='2026-09-26', condition='ясно', t_min=9, t_max=18, precipitation=0.0, wind=3)]}


class FakeTools:
    def __init__(self):
        self.cities = []
    def rate(self, code):
        if code == 'RUB':
            return dict(value=1.0, previous=1.0, date=None)
        item = CBR['Valute'][code]
        return dict(value=item['Value'] / item['Nominal'], previous=item['Previous'] / item['Nominal'], date=CBR['Date'][:10])
    def convert(self, amount, source, target):
        return amount * self.rate(source)['value'] / self.rate(target)['value']
    def rates(self, codes):
        return {c: self.rate(c) for c in codes}
    def forecast(self, city, days=3):
        self.cities.append(city)
        if city not in ('Москва', 'казань', 'Казань'):
            raise LookupError(city)
        return ('Казань' if city.casefold() == 'казань' else city), FORECAST
    def crypto(self, ids):
        return {'bitcoin': {'usd': 112345.6, 'rub': 9150000, 'usd_24h_change': 1.234}}


class NumberTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(words_to_digits('двадцать пять умножить на четыре'), '25 умножить на 4')
        self.assertEqual(words_to_digits('сто долларов в рублях'), '100 долларов в рублях')
        self.assertEqual(words_to_digits('5 тысяч рублей'), '5000 рублей')
        self.assertEqual(words_to_digits('три миллиона двести тысяч'), '3200000')

    def test_plural_and_format(self):
        self.assertEqual(plural(21, 'рубль', 'рубля', 'рублей'), 'рубль')
        self.assertEqual(plural(12, 'рубль', 'рубля', 'рублей'), 'рублей')
        self.assertEqual(plural(81.5, 'рубль', 'рубля', 'рублей'), 'рубля')
        self.assertEqual(say_number(81.5234), '81,52')


class QuickTests(unittest.TestCase):
    def setUp(self):
        self.tools = FakeTools()
        self.quick = QuickAnswers(self.tools)

    def ask(self, text, **settings):
        return self.quick.answer(text, settings)

    def test_rate(self):
        answer = self.ask('Какой курс доллара?')
        self.assertIn('81,52 рубля', answer)
        self.assertIn('24 сентября', answer)
        self.assertIn('плюс 0,32', answer)

    def test_nominal_100(self):
        self.assertIn('0,55', self.ask('курс иены'))

    def test_conversion_with_words(self):
        answer = self.ask('Сколько будет сто долларов в рублях')
        self.assertIn('100 долларов', answer)
        self.assertIn('8 152', answer)

    def test_cross_rate(self):
        self.assertIn('евро', self.ask('курс доллара к евро'))

    def test_calculator(self):
        self.assertEqual(self.ask('Сколько будет двадцать пять умножить на четыре'), 'Получается 100.')
        self.assertEqual(self.ask('Посчитай 15% от 2000'), 'Получается 300.')
        self.assertEqual(self.ask('корень из 144'), None)
        self.assertEqual(self.ask('сколько будет корень из 144'), 'Получается 12.')
        self.assertEqual(self.ask('сколько будет 10 разделить на 0'), 'На ноль делить нельзя.')

    def test_safe_eval_blocks_code(self):
        for bad in ('__import__("os")', '2**1000', 'open("x")'):
            with self.assertRaises(Exception):
                safe_eval(bad)
        self.assertIsNone(spoken_math('удали все файлы'))

    def test_weather_now_default_city(self):
        answer = self.ask('Какая погода?', city='Москва')
        self.assertTrue(answer.startswith('Сейчас в Москве пасмурно, плюс 12 градусов'), answer)
        self.assertTrue(answer.endswith('По данным MET Norway.'))

    def test_weather_tomorrow_inflected_city(self):
        answer = self.ask('погода завтра в Казани')
        self.assertIn('Завтра в Казани: небольшой дождь', answer)
        self.assertIn('осадки до 4,2 миллиметра', answer)
        self.assertIn('сильный ветер до 9 метров в секунду', answer)
        self.assertIn('казань', self.tools.cities)

    def test_crypto(self):
        answer = self.ask('Сколько стоит биткоин?')
        self.assertIn('Биткоин сейчас стоит 112 346 долларов', answer)
        self.assertTrue(answer.endswith('Данные CoinGecko.'))

    def test_not_quick(self):
        for text in ('Сколько белка нужно в день?', 'Открой калькулятор', 'Найди рецепт пиццы', 'включи песню про дождь'):
            self.assertIsNone(self.ask(text), text)

    def test_network_error_falls_through(self):
        tools = Mock()
        tools.rate.side_effect = OSError('offline')
        self.assertIsNone(QuickAnswers(tools).answer('Какой курс доллара?', {}))

    def test_city_forms(self):
        self.assertIn('казань', city_candidates('казани'))
        self.assertIn('москва', city_candidates('москве'))
        self.assertEqual(city_candidates('питере'), ['Санкт-Петербург'])
        self.assertEqual(locative('Новосибирск'), 'Новосибирске')
        self.assertEqual(locative('Сочи'), 'Сочи')


class OpenAICompatTests(unittest.TestCase):
    def test_stream_and_think_filter(self):
        lines = [b'data: {"choices":[{"delta":{"content":"<think>hmm</think>"}}]}',
                 b'data: {"choices":[{"delta":{"content":"\xd0\x9f\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82"}}]}',
                 b'data: [DONE]']
        response = SimpleNamespace(status_code=200, iter_lines=lambda decode_unicode=False: iter(lines), text='')
        session = Mock()
        session.post.return_value = response
        provider = OpenAICompatibleProvider('http://127.0.0.1:11434/v1', 'qwen', '', FakeTools(), session=session)
        spoken = []
        text = provider.stream([{'role': 'user', 'content': 'Привет'}], {'llm_web_search': False}, on_text=spoken.append)
        self.assertEqual(text, 'Привет')
        self.assertEqual(''.join(spoken), 'Привет')
        self.assertEqual(session.post.call_args.kwargs['json']['model'], 'qwen')
        self.assertNotIn('cache_prompt', session.post.call_args.kwargs['json'])

    def test_fresh_question_gets_search_context(self):
        tools = FakeTools()
        tools.web_search = Mock(return_value=[{'title': 'ЦБ', 'snippet': 'Ключевая ставка 16%', 'url': ''}])
        response = SimpleNamespace(status_code=200, iter_lines=lambda decode_unicode=False: iter([b'data: [DONE]']), text='')
        session = Mock()
        session.post.return_value = response
        provider = OpenAICompatibleProvider('http://127.0.0.1:1/v1', 'local', '', tools, session=session, local=True)
        provider.stream([{'role': 'user', 'content': 'Какая сейчас ключевая ставка?'}], {'llm_web_search': True})
        body = session.post.call_args.kwargs['json']
        self.assertTrue(body['cache_prompt'])
        self.assertEqual(body['chat_template_kwargs'], {'enable_thinking': False})
        tools.web_search.assert_called_once_with('Какая сейчас ключевая ставка?', 5, duckduckgo=False)
        self.assertIn('Ключевая ставка 16%', body['messages'][-1]['content'])
        self.assertIn('голосовой ассистент', body['messages'][0]['content'])

    def test_think_filter_split_tags(self):
        f = ThinkFilter()
        self.assertEqual(f.feed('<thi') + f.feed('nk>скрыто</th') + f.feed('ink>Видно'), 'Видно')


class BrainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.brain = Brain(self.store, tools=FakeTools())

    def tearDown(self):
        self.temp.cleanup()

    def test_quick_answer_without_model(self):
        self.assertIn('рубля', self.brain.answer('курс доллара', {'llm_provider': 'local'}))

    def test_missing_local_model_message(self):
        with self.assertRaises(LLMError) as ctx:
            self.brain.answer('Сколько белка нужно в день?', {'llm_provider': 'local'})
        self.assertIn('Скачать нейросеть', str(ctx.exception))

    def test_memory_and_context(self):
        provider = Mock()
        provider.stream.side_effect = ['Около 100 граммов.', 'Примерно 400 калорий.']
        self.brain.provider = lambda settings: provider
        self.brain.answer('Сколько белка нужно в день?', {}, owner='o')
        self.brain.answer('А сколько это калорий?', {}, owner='o')
        history = provider.stream.call_args.args[0]
        self.assertEqual(history[0], {'role': 'user', 'content': 'Сколько белка нужно в день?'})
        self.assertEqual(history[1]['content'], 'Около 100 граммов.')
        self.assertIn('А сколько это калорий?', history[-1]['content'])
        self.assertIn('Сейчас', history[-1]['content'])

    def test_provider_off(self):
        self.assertIsNone(self.brain.answer('Сколько белка нужно?', {'llm_provider': 'off'}))

    def test_openai_provider_uses_saved_key(self):
        self.store.set_secret('openai_api_key', 'free-key')
        provider = self.brain.provider({'llm_provider': 'openai', 'openai_base_url': 'https://api.groq.com/openai/v1',
                                        'openai_model': 'llama-3.3-70b-versatile'})
        self.assertEqual(provider.api_key, 'free-key')
        self.assertFalse(provider.local)


if __name__ == '__main__':
    unittest.main()
