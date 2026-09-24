"""Мгновенные ответы (курсы, погода, калькулятор) и потоковый ИИ с инструментами."""
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from src.brain import Brain, LLMError
from src.brain.numbers import words_to_digits, plural, say_number
from src.brain.quick import QuickAnswers, spoken_math, safe_eval, city_candidates, locative
from src.brain.llm import ClaudeProvider, OpenAICompatibleProvider, ThinkFilter, run_custom_tool
from src.storage import Store

CBR = {'Date': '2026-09-24T11:30:00+03:00', 'Valute': {
    'USD': {'Nominal': 1, 'Value': 81.5234, 'Previous': 81.2},
    'EUR': {'Nominal': 1, 'Value': 95.1, 'Previous': 95.3},
    'CNY': {'Nominal': 1, 'Value': 11.4, 'Previous': 11.4},
    'JPY': {'Nominal': 100, 'Value': 55.0, 'Previous': 55.0}}}
FORECAST = {'current': {'temperature_2m': 12.4, 'apparent_temperature': 10.1, 'weather_code': 3},
            'daily': {'time': ['2026-09-24', '2026-09-25', '2026-09-26'], 'weather_code': [3, 61, 0],
                      'temperature_2m_max': [15, 13, 18], 'temperature_2m_min': [7, 6, 9],
                      'precipitation_probability_max': [10, 80, 0], 'wind_speed_10m_max': [4, 9, 3]}}


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

    def test_weather_tomorrow_inflected_city(self):
        answer = self.ask('погода завтра в Казани')
        self.assertIn('Завтра в Казани: небольшой дождь', answer)
        self.assertIn('80 процентов', answer)
        self.assertIn('казань', self.tools.cities)

    def test_crypto(self):
        self.assertIn('Биткоин сейчас стоит 112 346 долларов', self.ask('Сколько стоит биткоин?'))

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


# ---------- Claude ----------
class FakeStream:
    def __init__(self, texts, message):
        self.texts, self.message = texts, message
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def __iter__(self):
        for text in self.texts:
            yield SimpleNamespace(type='text', text=text)
    def get_final_message(self):
        return self.message


class FakeMessages:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
    def stream(self, **params):
        self.calls.append(json.loads(json.dumps(params, default=lambda o: getattr(o, '__dict__', str(o)))))
        return self.turns.pop(0)


def claude_with(turns):
    provider = ClaudeProvider('test-key', FakeTools())
    messages = FakeMessages(turns)
    provider.client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return provider, messages


class ClaudeTests(unittest.TestCase):
    def test_streaming_and_params(self):
        final = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text='Привет!')])
        provider, messages = claude_with([FakeStream(['При', 'вет!'], final)])
        chunks = []
        text = provider.stream([{'role': 'user', 'content': 'Привет'}], {'llm_model': 'claude-opus-5'}, on_text=chunks.append)
        self.assertEqual(text, 'Привет!')
        self.assertEqual(chunks, ['При', 'вет!'])
        params = messages.calls[0]
        self.assertEqual(params['model'], 'claude-opus-5')
        self.assertEqual(params['output_config'], {'effort': 'low'})
        self.assertEqual(params['fallbacks'], 'default')
        self.assertEqual(params['betas'], ['server-side-fallback-2026-07-01'])
        types = [t.get('type') for t in params['tools']]
        self.assertIn('web_search_20260209', types)
        self.assertTrue(all(t['eager_input_streaming'] for t in params['tools'] if 'input_schema' in t))

    def test_haiku_has_no_effort(self):
        final = SimpleNamespace(stop_reason='end_turn', content=[])
        provider, messages = claude_with([FakeStream(['Ок'], final)])
        provider.stream([{'role': 'user', 'content': 'x'}], {'llm_model': 'claude-haiku-4-5'})
        params = messages.calls[0]
        self.assertNotIn('output_config', params)
        self.assertNotIn('fallbacks', params)
        self.assertIn('web_search_20250305', [t.get('type') for t in params['tools']])

    def test_custom_tool_loop(self):
        tool_use = SimpleNamespace(type='tool_use', id='toolu_1', name='get_exchange_rates', input={'currencies': ['USD']})
        first = SimpleNamespace(stop_reason='tool_use', content=[tool_use])
        second = SimpleNamespace(stop_reason='end_turn', content=[])
        provider, messages = claude_with([FakeStream([], first), FakeStream(['Доллар стоит 81,52 рубля.'], second)])
        text = provider.stream([{'role': 'user', 'content': 'курс доллара'}], {})
        self.assertEqual(text, 'Доллар стоит 81,52 рубля.')
        result = messages.calls[1]['messages'][-1]['content'][0]
        self.assertEqual(result['type'], 'tool_result')
        self.assertEqual(result['tool_use_id'], 'toolu_1')
        self.assertIn('81.5234', result['content'])
        self.assertFalse(result['is_error'])

    def test_pause_turn_is_resumed(self):
        paused = SimpleNamespace(stop_reason='pause_turn', content=[])
        done = SimpleNamespace(stop_reason='end_turn', content=[])
        provider, messages = claude_with([FakeStream(['Ищу. '], paused), FakeStream(['Нашёл.'], done)])
        self.assertEqual(provider.stream([{'role': 'user', 'content': 'новости'}], {}), 'Ищу. Нашёл.')
        self.assertEqual(len(messages.calls), 2)

    def test_invalid_tool_input_is_error_result(self):
        content, is_error = run_custom_tool(FakeTools(), 'get_exchange_rates', {'currencies': 'USD'})
        self.assertTrue(is_error)
        content, is_error = run_custom_tool(FakeTools(), 'get_weather', {'city': 'Москва'})
        self.assertFalse(is_error)


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

    def test_quick_answer_without_key(self):
        self.assertIn('рубля', self.brain.answer('курс доллара', {'llm_provider': 'claude'}))

    def test_missing_key_message(self):
        with self.assertRaises(LLMError) as ctx:
            self.brain.answer('Сколько белка нужно в день?', {'llm_provider': 'claude'})
        self.assertIn('ключ', str(ctx.exception))

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

    def test_key_from_store(self):
        self.store.set_secret('anthropic_api_key', 'sk-ant-test')
        self.assertIsInstance(self.brain.provider({'llm_provider': 'claude'}), ClaudeProvider)
        self.assertEqual(self.store.secrets_status()['anthropic_api_key'], True)


if __name__ == '__main__':
    unittest.main()
