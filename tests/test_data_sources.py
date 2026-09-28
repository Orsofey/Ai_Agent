"""Источники данных, разрешающие коммерческое использование: ЦБ РФ, MET Norway, Nominatim, Википедия."""
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from src.brain.tools import DataTools, parse_cbr_xml, summarize_met, met_condition, USER_AGENT

CBR_TODAY = '''<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="24.09.2026" name="Foreign Currency Market">
<Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>Dollar</Name><Value>81,5234</Value><VunitRate>81,5234</VunitRate></Valute>
<Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal><Name>Yen</Name><Value>55,0000</Value><VunitRate>0,55</VunitRate></Valute>
</ValCurs>'''.encode('cp1251')
CBR_PREV = CBR_TODAY.replace(b'24.09.2026', b'23.09.2026').replace(b'81,5234</Value>', b'81,2000</Value>')


def met_payload(start=date(2026, 9, 24)):
    """Прогноз на два дня, начиная с start (для «живого» теста — с сегодняшнего дня)."""
    day1, day2 = start.isoformat(), (start + timedelta(days=1)).isoformat()

    def entry(time, temp, symbol=None, rain=None, wind=2.0):
        time = time.replace('2026-09-24', day1).replace('2026-09-25', day2)
        data = {'instant': {'details': {'air_temperature': temp, 'wind_speed': wind, 'relative_humidity': 60}}}
        if symbol:
            data['next_1_hours'] = {'summary': {'symbol_code': symbol}}
            data['next_6_hours'] = {'summary': {'symbol_code': symbol}, 'details': {'precipitation_amount': rain or 0}}
        return {'time': time, 'data': data}
    return {'properties': {'timeseries': [
        entry('2026-09-24T12:00:00Z', 14.0, 'cloudy'), entry('2026-09-24T18:00:00Z', 9.0, 'cloudy'),
        entry('2026-09-25T00:00:00Z', 6.0, 'lightrain', 1.0), entry('2026-09-25T06:00:00Z', 7.0, 'lightrain', 2.5),
        entry('2026-09-25T12:00:00Z', 13.0, 'rainshowers_day', 0.7, wind=9.5),
        entry('2026-09-25T18:00:00Z', 10.0, 'cloudy'),
    ]}}


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for prefix, handler in self.routes.items():
            if url.startswith(prefix):
                body = handler(params or {})
                return SimpleNamespace(content=body if isinstance(body, bytes) else b'', json=lambda b=body: b,
                                       raise_for_status=lambda: None)
        raise AssertionError('unexpected url ' + url)


class CBRTests(unittest.TestCase):
    def test_parse_official_xml(self):
        day, values = parse_cbr_xml(CBR_TODAY)
        self.assertEqual(day, date(2026, 9, 24))
        self.assertEqual(values['USD'], (1.0, 81.5234))
        self.assertEqual(values['JPY'], (100.0, 55.0))

    def test_rates_with_previous_day(self):
        session = FakeSession({'https://www.cbr.ru/': lambda p: CBR_PREV if p.get('date_req') else CBR_TODAY})
        tools = DataTools(session=session)
        usd = tools.rate('USD')
        self.assertEqual((usd['value'], usd['previous'], usd['date']), (81.5234, 81.2, '2026-09-24'))
        self.assertAlmostEqual(tools.rate('JPY')['value'], 0.55)
        self.assertEqual(session.calls[1][1], {'date_req': '23/09/2026'})
        tools.rate('USD')
        self.assertEqual(len(session.calls), 2)  # кеш


class WeatherTests(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(met_condition('clearsky_day'), 'ясно')
        self.assertEqual(met_condition('lightrainshowersandthunder_night'), 'небольшой ливень с грозой')
        self.assertEqual(met_condition('lightssnowshowersandthunder_day'), 'небольшой снег с грозой')
        self.assertEqual(met_condition(None), 'осадки')

    def test_daily_summary(self):
        result = summarize_met(met_payload(), days=3, today=date(2026, 9, 24))
        self.assertEqual(result['current']['condition'], 'пасмурно')
        self.assertEqual(result['current']['temperature'], 14.0)
        days = {d['date']: d for d in result['daily']}
        self.assertIn('2026-09-25', days)
        self.assertEqual(days['2026-09-25']['t_max'], 13.0)
        self.assertGreaterEqual(days['2026-09-25']['wind'], 9.5)
        self.assertGreater(sum(d['precipitation'] for d in result['daily']), 4.0)

    def test_forecast_uses_nominatim_and_met(self):
        session = FakeSession({
            'https://nominatim.openstreetmap.org/': lambda p: [{'name': 'Казань', 'lat': '55.7887', 'lon': '49.1221'}],
            'https://api.met.no/': lambda p: met_payload(date.today()),
        })
        name, data = DataTools(session=session).forecast('Казань')
        self.assertEqual(name, 'Казань')
        self.assertEqual(session.calls[1][1], {'lat': 55.7887, 'lon': 49.1221})
        self.assertTrue(data['daily'])

    def test_user_agent_identifies_app(self):
        self.assertIn('LocalAIAgent', USER_AGENT)
        self.assertIn('github.com', USER_AGENT)


class SearchTests(unittest.TestCase):
    def wiki(self, params):
        self.assertEqual(params['gsrsearch'], 'Кто такой Гагарин')
        return {'query': {'pages': [
            {'index': 2, 'title': 'Гагарин (город)', 'fullurl': 'u2', 'extract': 'Город в Смоленской области.'},
            {'index': 1, 'title': 'Гагарин, Юрий Алексеевич', 'fullurl': 'u1', 'extract': 'Первый космонавт.'}]}}

    def test_wikipedia_by_default(self):
        session = FakeSession({'https://ru.wikipedia.org/': self.wiki})
        tools = DataTools(session=session)
        tools.duckduckgo = lambda *a, **k: self.fail('DuckDuckGo must be off by default')
        results = tools.web_search('Кто такой Гагарин')
        self.assertEqual([r['title'] for r in results], ['Гагарин, Юрий Алексеевич', 'Гагарин (город)'])
        self.assertEqual(results[0]['source'], 'Википедия')

    def test_duckduckgo_only_when_enabled(self):
        session = FakeSession({'https://ru.wikipedia.org/': self.wiki})
        tools = DataTools(session=session)
        tools.duckduckgo = lambda query, count: [{'title': 'Новость', 'snippet': 's', 'url': '', 'source': 'DuckDuckGo'}]
        results = tools.web_search('Кто такой Гагарин', duckduckgo=True)
        self.assertEqual(results[-1]['source'], 'DuckDuckGo')

    def test_english_query_uses_english_wikipedia(self):
        session = FakeSession({'https://en.wikipedia.org/': lambda p: {'query': {'pages': []}}})
        self.assertEqual(DataTools(session=session).wikipedia('who is Yuri Gagarin'), [])


if __name__ == '__main__':
    unittest.main()
