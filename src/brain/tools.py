"""Live data from sources that allow commercial use, no API keys.

- курсы валют: официальный XML-сервис Банка России (cbr.ru);
- погода: MET Norway Locationforecast (CC BY 4.0), города — OpenStreetMap Nominatim (ODbL);
- справка: Википедия (CC BY-SA 4.0);
- криптовалюты: CoinGecko (с указанием источника);
- DuckDuckGo — только если пользователь включил его в настройках (неофициальный доступ).

Каждый ответ кешируется, чтобы повторные вопросы отвечались мгновенно.
"""
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

CBR_URL = 'https://www.cbr.ru/scripts/XML_daily.asp'
GEO_URL = 'https://nominatim.openstreetmap.org/search'
WEATHER_URL = 'https://api.met.no/weatherapi/locationforecast/2.0/compact'
COIN_URL = 'https://api.coingecko.com/api/v3/simple/price'
WIKI_URL = 'https://{lang}.wikipedia.org/w/api.php'
# MET Norway и Wikimedia требуют представляться: название программы и адрес для связи.
USER_AGENT = 'LocalAIAgent/5.0 (+https://github.com/Orsofey/Ai_Agent)'

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

MET_SYMBOLS = {
    'clearsky': 'ясно', 'fair': 'малооблачно', 'partlycloudy': 'переменная облачность', 'cloudy': 'пасмурно',
    'fog': 'туман', 'lightrain': 'небольшой дождь', 'rain': 'дождь', 'heavyrain': 'сильный дождь',
    'lightrainshowers': 'небольшой ливень', 'rainshowers': 'ливни', 'heavyrainshowers': 'сильные ливни',
    'lightsleet': 'небольшой мокрый снег', 'sleet': 'мокрый снег', 'heavysleet': 'сильный мокрый снег',
    'lightsleetshowers': 'мокрый снег', 'sleetshowers': 'мокрый снег', 'heavysleetshowers': 'сильный мокрый снег',
    'lightsnow': 'небольшой снег', 'snow': 'снег', 'heavysnow': 'сильный снегопад',
    'lightsnowshowers': 'небольшой снег', 'snowshowers': 'снегопад', 'heavysnowshowers': 'сильный снегопад',
}


def met_condition(symbol):
    """'lightrainshowers_day' → 'небольшой ливень'; «…andthunder» → «… с грозой»."""
    base = re.sub(r'_(day|night|polartwilight)$', '', str(symbol or ''))
    thunder = base.endswith('andthunder')
    base = base[:-len('andthunder')] if thunder else base
    base = base.replace('lightss', 'lights')  # в API MET есть коды с опечаткой «lightss…»
    text = MET_SYMBOLS.get(base) or 'осадки'
    return text + ' с грозой' if thunder else text


def parse_cbr_xml(content):
    """XML_daily.asp → (дата ISO, {код: (номинал, курс)})."""
    root = ET.fromstring(content)
    day = datetime.strptime(root.attrib['Date'], '%d.%m.%Y').date()
    values = {}
    for valute in root.findall('Valute'):
        code = valute.findtext('CharCode')
        nominal = float(valute.findtext('Nominal').replace(',', '.'))
        value = float(valute.findtext('Value').replace(',', '.'))
        values[code] = (nominal, value)
    return day, values


def summarize_met(payload, days=3, today=None):
    """Ответ MET Norway → текущая погода и сводка по дням в местном времени."""
    series = payload['properties']['timeseries']
    first = series[0]['data']
    details = first['instant']['details']
    now_symbol = (first.get('next_1_hours') or first.get('next_6_hours') or {}).get('summary', {}).get('symbol_code')
    current = dict(temperature=details.get('air_temperature'), wind=details.get('wind_speed'),
                   humidity=details.get('relative_humidity'), condition=met_condition(now_symbol))
    by_day = OrderedDict()
    for item in series:
        utc = datetime.fromisoformat(item['time'].replace('Z', '+00:00'))
        moment = utc.astimezone()
        info = by_day.setdefault(moment.date(), dict(temps=[], winds=[], rain=0.0, symbols=[]))
        inst = item['data']['instant']['details']
        info['temps'].append(inst.get('air_temperature'))
        info['winds'].append(inst.get('wind_speed') or 0)
        six = item['data'].get('next_6_hours')
        if six and utc.hour % 6 == 0:  # шестичасовые блоки не перекрываются
            info['rain'] += six.get('details', {}).get('precipitation_amount') or 0
            symbol = six.get('summary', {}).get('symbol_code')
            if 9 <= moment.hour <= 15:
                info['symbols'].insert(0, symbol)  # дневная погода важнее ночной
            else:
                info['symbols'].append(symbol)
    start = today or datetime.now().astimezone().date()
    daily = []
    for day, info in by_day.items():
        if day < start or len(daily) >= days:
            continue
        temps = [t for t in info['temps'] if t is not None]
        if not temps:
            continue
        daily.append(dict(date=day.isoformat(), t_min=min(temps), t_max=max(temps), wind=max(info['winds']),
                          precipitation=round(info['rain'], 1),
                          condition=met_condition(info['symbols'][0] if info['symbols'] else None)))
    return dict(current=current, daily=daily)



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
            self._session.headers['User-Agent'] = USER_AGENT
        return self._session

    def _cached(self, key, ttl, loader):
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < ttl:
                return cached[1]
        data = loader()
        with self._lock:
            self._cache[key] = (now, data)
        return data

    def _get(self, key, ttl, url, params=None):
        def load():
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        return self._cached(key, ttl, load)

    # ---- валюты: официальный сервис Банка России ----
    def _cbr_xml(self, day=None):
        params = {'date_req': day.strftime('%d/%m/%Y')} if day else None
        response = self.session.get(CBR_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        return parse_cbr_xml(response.content)

    def cbr(self):
        """Курсы на сегодня и на предыдущую дату ЦБ (для изменения за день)."""
        def load():
            day, values = self._cbr_xml()
            _, previous = self._cbr_xml(day - timedelta(days=1))
            return {'Date': day.isoformat(), 'Valute': {
                code: {'Nominal': nominal, 'Value': value, 'Previous': previous.get(code, (nominal, value))[1]}
                for code, (nominal, value) in values.items()}}
        return self._cached('cbr', 1800, load)

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

    # ---- погода: MET Norway + OpenStreetMap Nominatim ----
    def geocode(self, city):
        data = self._get('geo:' + city.casefold(), 7 * 86400, GEO_URL,
                         {'q': city, 'format': 'jsonv2', 'limit': 1, 'accept-language': 'ru'})
        if not data:
            raise LookupError('Город не найден: ' + city)
        place = data[0]
        name = place.get('name') or place.get('display_name', city).split(',')[0]
        return name, float(place['lat']), float(place['lon'])

    def forecast(self, city, days=3):
        name, lat, lon = self.geocode(city)
        # MET Norway просит не больше 4 знаков после запятой в координатах.
        payload = self._get(f'wx:{lat:.2f}:{lon:.2f}', 900, WEATHER_URL, {'lat': round(lat, 4), 'lon': round(lon, 4)})
        return name, summarize_met(payload, max(1, min(int(days), 7)))

    # ---- криптовалюты ----
    def crypto(self, ids):
        ids = sorted(set(ids))
        return self._get('coin:' + ','.join(ids), 120, COIN_URL,
                         {'ids': ','.join(ids), 'vs_currencies': 'usd,rub', 'include_24hr_change': 'true'})

    # ---- справка: Википедия ----
    def wikipedia(self, query, count=3):
        lang = 'en' if re.search(r'[a-z]', query, re.I) and not re.search(r'[а-яё]', query, re.I) else 'ru'
        data = self._get(f'wiki:{lang}:{query.casefold()}', 3600, WIKI_URL.format(lang=lang), {
            'action': 'query', 'format': 'json', 'formatversion': 2, 'generator': 'search',
            'gsrsearch': query, 'gsrlimit': count, 'prop': 'extracts|info', 'inprop': 'url',
            'exintro': 1, 'explaintext': 1, 'exsentences': 4, 'redirects': 1})
        pages = sorted((data.get('query') or {}).get('pages', []), key=lambda p: p.get('index', 99))
        return [dict(title=p.get('title', ''), url=p.get('fullurl', ''), snippet=(p.get('extract') or '')[:700],
                     source='Википедия') for p in pages if p.get('extract')]

    # ---- DuckDuckGo: только по явному включению в настройках ----
    def duckduckgo(self, query, count=5):
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS(timeout=self.timeout) as ddgs:
            items = list(ddgs.text(query, region='ru-ru', max_results=count))
        return [dict(title=i.get('title', ''), url=i.get('href', ''), snippet=i.get('body', ''), source='DuckDuckGo')
                for i in items]

    def web_search(self, query, count=5, duckduckgo=False):
        results = []
        try:
            results += self.wikipedia(query, 3)
        except Exception as exc:
            log.info('Wikipedia search failed: %s', exc)
        if duckduckgo:
            try:
                results += self.duckduckgo(query, count)
            except Exception as exc:
                log.info('DuckDuckGo search failed: %s', exc)
        return results


def describe_day(daily, index):
    return daily[min(index, len(daily) - 1)]
