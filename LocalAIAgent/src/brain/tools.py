"""Live data sources without API keys: ЦБ РФ, Open-Meteo, CoinGecko, DuckDuckGo.

Каждый ответ кешируется, чтобы повторные вопросы отвечались мгновенно.
"""
import logging
import threading
import time
from datetime import date

log = logging.getLogger(__name__)

CBR_URL = 'https://www.cbr-xml-daily.ru/daily_json.js'
ER_URL = 'https://open.er-api.com/v6/latest/{base}'
GEO_URL = 'https://geocoding-api.open-meteo.com/v1/search'
WEATHER_URL = 'https://api.open-meteo.com/v1/forecast'
COIN_URL = 'https://api.coingecko.com/api/v3/simple/price'

CURRENCY_WORDS = {
    'USD': ('доллар', 'бакс', 'usd', 'dollar'),
    'EUR': ('евро', 'eur', 'euro'),
    'CNY': ('юан', 'cny', 'yuan'),
    'GBP': ('фунт', 'gbp', 'pound'),
    'JPY': ('иен', 'йен', 'jpy', 'yen'),
    'CHF': ('франк', 'chf'),
    'KZT': ('тенге', 'kzt'),
    'UAH': ('гривн', 'гривен', 'uah'),
    'BYN': ('белорусск', 'byn'),
    'TRY': ('лир', 'try'),
    'AED': ('дирхам', 'aed'),
    'INR': ('рупи', 'inr'),
    'KRW': ('вон', 'krw'),
    'AMD': ('драм', 'amd'),
    'GEL': ('лари', 'gel'),
    'UZS': ('сум', 'uzs'),
    'THB': ('бат', 'thb'),
    'RUB': ('рубл', 'руб', 'rub', 'ruble', 'rouble'),
}
CURRENCY_NAMES = {
    'USD': ('доллар', 'доллара', 'долларов'), 'EUR': ('евро', 'евро', 'евро'),
    'CNY': ('юань', 'юаня', 'юаней'), 'GBP': ('фунт', 'фунта', 'фунтов'),
    'JPY': ('иена', 'иены', 'иен'), 'CHF': ('франк', 'франка', 'франков'),
    'KZT': ('тенге', 'тенге', 'тенге'), 'UAH': ('гривна', 'гривны', 'гривен'),
    'BYN': ('белорусский рубль', 'белорусских рубля', 'белорусских рублей'),
    'TRY': ('лира', 'лиры', 'лир'), 'AED': ('дирхам', 'дирхама', 'дирхамов'),
    'INR': ('рупия', 'рупии', 'рупий'), 'KRW': ('вона', 'воны', 'вон'),
    'AMD': ('драм', 'драма', 'драмов'), 'GEL': ('лари', 'лари', 'лари'),
    'UZS': ('сум', 'сума', 'сумов'), 'THB': ('бат', 'бата', 'батов'),
    'RUB': ('рубль', 'рубля', 'рублей'),
}
CURRENCY_GENITIVE = {
    'USD': 'доллара', 'EUR': 'евро', 'CNY': 'юаня', 'GBP': 'фунта', 'JPY': 'иены', 'CHF': 'франка',
    'KZT': 'тенге', 'UAH': 'гривны', 'BYN': 'белорусского рубля', 'TRY': 'лиры', 'AED': 'дирхама',
    'INR': 'рупии', 'KRW': 'воны', 'AMD': 'драма', 'GEL': 'лари', 'UZS': 'сума', 'THB': 'бата',
    'RUB': 'рубля',
}
COINS = {
    'bitcoin': ('биткоин', 'биткойн', 'bitcoin', 'btc', 'биток'),
    'ethereum': ('эфир', 'эфириум', 'ethereum', 'eth'),
    'the-open-network': ('тон', 'toncoin', 'тонкоин', 'ton'),
    'tether': ('тезер', 'тетер', 'usdt', 'tether'),
    'solana': ('солана', 'solana', 'sol'),
    'binancecoin': ('bnb', 'бнб', 'бинанс'),
    'dogecoin': ('доги', 'догикоин', 'dogecoin', 'doge'),
    'ripple': ('рипл', 'xrp', 'ripple'),
}
COIN_TITLES = {'bitcoin': 'Биткоин', 'ethereum': 'Эфир', 'the-open-network': 'Toncoin', 'tether': 'USDT',
               'solana': 'Solana', 'binancecoin': 'BNB', 'dogecoin': 'Dogecoin', 'ripple': 'XRP'}

WMO = {
    0: 'ясно', 1: 'преимущественно ясно', 2: 'переменная облачность', 3: 'пасмурно',
    45: 'туман', 48: 'изморозь и туман', 51: 'лёгкая морось', 53: 'морось', 55: 'сильная морось',
    56: 'ледяная морось', 57: 'сильная ледяная морось', 61: 'небольшой дождь', 63: 'дождь',
    65: 'сильный дождь', 66: 'ледяной дождь', 67: 'сильный ледяной дождь', 71: 'небольшой снег',
    73: 'снег', 75: 'сильный снегопад', 77: 'снежные зёрна', 80: 'ливень', 81: 'ливни',
    82: 'сильный ливень', 85: 'снегопад', 86: 'сильный снегопад', 95: 'гроза',
    96: 'гроза с градом', 99: 'сильная гроза с градом',
}


def currency_code(word):
    value = str(word or '').casefold().strip()
    if len(value) == 3 and value.upper() in CURRENCY_NAMES:
        return value.upper()
    for code, stems in CURRENCY_WORDS.items():
        if any(value.startswith(stem) for stem in stems):
            # «рубли» — рубль, но «белорусский рубль» — BYN
            return code
    return None


def coin_id(word):
    value = str(word or '').casefold().strip()
    for cid, names in COINS.items():
        if any(value == n or (len(n) > 3 and value.startswith(n)) for n in names):
            return cid
    return None


class DataTools:
    def __init__(self, timeout=6.0, session=None):
        self.timeout = timeout
        self._session = session
        self._cache = {}
        self._lock = threading.Lock()

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers['User-Agent'] = 'LocalAIAgent/5.0'
        return self._session

    def _get(self, key, ttl, url, params=None):
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < ttl:
                return cached[1]
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        with self._lock:
            self._cache[key] = (now, data)
        return data

    # ---- валюты ----
    def cbr(self):
        return self._get('cbr', 1800, CBR_URL)

    def rate(self, code):
        """Курс валюты к рублю по ЦБ: dict(value, previous, date) за 1 единицу."""
        code = code.upper()
        if code == 'RUB':
            return dict(value=1.0, previous=1.0, date=None)
        data = self.cbr()
        item = data.get('Valute', {}).get(code)
        if not item:
            raise KeyError(code)
        nominal = float(item.get('Nominal') or 1)
        return dict(value=float(item['Value']) / nominal, previous=float(item['Previous']) / nominal,
                    date=str(data.get('Date', ''))[:10])

    def convert(self, amount, source, target):
        return amount * self.rate(source)['value'] / self.rate(target)['value']

    def rates(self, codes):
        result = {}
        for code in codes:
            try:
                result[code.upper()] = self.rate(code)
            except Exception as exc:
                result[code.upper()] = {'error': str(exc)}
        return result

    # ---- погода ----
    def geocode(self, city):
        data = self._get('geo:' + city.casefold(), 86400, GEO_URL,
                         {'name': city, 'count': 1, 'language': 'ru', 'format': 'json'})
        results = data.get('results') or []
        if not results:
            raise LookupError('Город не найден: ' + city)
        place = results[0]
        return place.get('name', city), float(place['latitude']), float(place['longitude'])

    def forecast(self, city, days=3):
        name, lat, lon = self.geocode(city)
        data = self._get(f'wx:{lat:.2f}:{lon:.2f}', 600, WEATHER_URL, {
            'latitude': lat, 'longitude': lon, 'timezone': 'auto', 'forecast_days': max(1, min(int(days), 7)),
            'current': 'temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m,precipitation',
            'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max',
            'wind_speed_unit': 'ms',
        })
        return name, data

    # ---- криптовалюты ----
    def crypto(self, ids):
        ids = sorted(set(ids))
        return self._get('coin:' + ','.join(ids), 120, COIN_URL,
                         {'ids': ','.join(ids), 'vs_currencies': 'usd,rub', 'include_24hr_change': 'true'})

    # ---- поиск в интернете (для провайдеров без встроенного веб-поиска) ----
    def web_search(self, query, count=5):
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS(timeout=self.timeout) as ddgs:
            items = list(ddgs.text(query, region='ru-ru', max_results=count))
        return [dict(title=i.get('title', ''), url=i.get('href', ''), snippet=i.get('body', '')) for i in items]


def describe_day(daily, index):
    code = daily['weather_code'][index]
    return dict(
        condition=WMO.get(code, 'осадки'), t_max=daily['temperature_2m_max'][index],
        t_min=daily['temperature_2m_min'][index],
        rain=(daily.get('precipitation_probability_max') or [None] * 8)[index],
        wind=(daily.get('wind_speed_10m_max') or [None] * 8)[index],
        date=daily['time'][index] if 'time' in daily else str(date.today()),
    )
