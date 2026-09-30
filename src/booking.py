"""Заказ еды, авиабилеты, бронирование столиков — «Андрей» открывает сервис с уже заполненным поиском.

«Закажи пиццу» → Яндекс Еда с поиском «пицца» (или Маркет Деливери, Самокат, Купер — Настройки → «Управление ПК»);
«купи билет на самолёт из Москвы в Сочи на 5 октября на двоих», «билеты в Казань на завтра и обратно 12 октября»
→ Авиасейлс с найденными рейсами; «забронируй столик в Пушкине на 19:00 на троих» → ресторан на Яндекс Картах
с кнопкой брони.

Оплату и подтверждение брони вы делаете сами на сайте: ассистент никогда не платит и не вводит данные карты.
"""
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote

FOOD_SERVICES = {
    'yandex_eda': ('Яндекс Еда', 'https://eda.yandex.ru/search?query={q}'),
    'market_delivery': ('Маркет Деливери', 'https://market-delivery.yandex.ru/search?query={q}'),
    'samokat': ('Самокат', 'https://samokat.ru/search?value={q}'),
    'kuper': ('Купер', 'https://kuper.ru/multisearch?q={q}'),
}
FOOD_WORDS = {'яндекс ед': 'yandex_eda', 'яндекс.ед': 'yandex_eda', 'деливери': 'market_delivery',
              'маркет деливери': 'market_delivery', 'самокат': 'samokat', 'купер': 'kuper', 'сбермаркет': 'kuper'}
# Коды городов IATA для Авиасейлс (город, а не аэропорт: MOW — все аэропорты Москвы).
CITIES = {
    'москв': 'MOW', 'санкт-петербург': 'LED', 'петербург': 'LED', 'питер': 'LED', 'спб': 'LED', 'сочи': 'AER',
    'адлер': 'AER', 'казан': 'KZN', 'екатеринбург': 'SVX', 'новосибирск': 'OVB', 'краснодар': 'KRR',
    'калининград': 'KGD', 'минеральные воды': 'MRV', 'минвод': 'MRV', 'самар': 'KUF', 'уф': 'UFA',
    'ростов': 'ROV', 'нижн': 'GOJ', 'пермь': 'PEE', 'перм': 'PEE', 'волгоград': 'VOG', 'владивосток': 'VVO',
    'хабаровск': 'KHV', 'иркутск': 'IKT', 'красноярск': 'KJA', 'омск': 'OMS', 'тюмен': 'TJM', 'челябинск': 'CEK',
    'махачкал': 'MCX', 'мурманск': 'MMK', 'архангельск': 'ARH', 'симферопол': 'SIP', 'анап': 'AAQ', 'геленджик': 'GDZ',
    'стамбул': 'IST', 'анталь': 'AYT', 'дуба': 'DXB', 'ереван': 'EVN', 'тбилиси': 'TBS', 'баку': 'BAK',
    'минск': 'MSQ', 'алмат': 'ALA', 'астан': 'NQZ', 'ташкент': 'TAS', 'бишкек': 'FRU', 'пекин': 'BJS',
    'бангкок': 'BKK', 'пхукет': 'HKT', 'шарм': 'SSH', 'хургад': 'HRG', 'мале': 'MLE', 'гоа': 'GOI',
    'белград': 'BEG', 'рим': 'ROM', 'париж': 'PAR', 'барселон': 'BCN', 'калининград ': 'KGD',
}
MONTHS = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма': 5, 'июн': 6, 'июл': 7, 'август': 8, 'сентябр': 9,
          'октябр': 10, 'ноябр': 11, 'декабр': 12}
WEEKDAYS = {'понедельник': 0, 'вторник': 1, 'сред': 2, 'четверг': 3, 'пятниц': 4, 'суббот': 5, 'воскресень': 6}
COUNT = {'одного': 1, 'одну': 1, 'двоих': 2, 'двух': 2, 'двое': 2, 'троих': 3, 'трех': 3, 'трёх': 3, 'трое': 3,
         'четверых': 4, 'четырех': 4, 'четырёх': 4, 'пятерых': 5, 'пяти': 5, 'шестерых': 6}

FOOD = re.compile(r'^(?:закажи|заказать|хочу заказать|доставь|привези)\s+(?:мне\s+)?(?:еду\s*)?(?P<what>.*?)'
                  r'(?:\s+(?:в|через|на)\s+(?P<service>яндекс[\s.]?ед\w*|маркет деливери|деливери|самокат\w*|купер\w*|сбермаркет\w*))?$',
                  re.I)
FLIGHT = re.compile(r'^(?:купи|найди|забронируй|посмотри|подбери|хочу)\s+(?:мне\s+)?(?:авиа)?билет\w*\s*(?:на самол[её]т\s*)?'
                    r'(?P<rest>.*)$|^(?:авиабилет\w*|перел[её]т|рейс\w*)\s+(?P<rest2>.+)$', re.I)
TABLE = re.compile(r'^(?:забронируй|закажи|зарезервируй|бронь)\s+(?:мне\s+)?столик\w*\s*(?P<rest>.*)$', re.I)


def parse_date(text, today=None):
    """«5 октября», «завтра», «послезавтра», «в пятницу», «через 3 дня», «05.10» → date или None."""
    today = today or date.today()
    low = text.casefold()
    if 'послезавтра' in low:
        return today + timedelta(days=2)
    if 'завтра' in low:
        return today + timedelta(days=1)
    if re.search(r'\bсегодня\b', low):
        return today
    match = re.search(r'через\s+(\d+|один|два|три|четыре|пять|неделю)\s*(дн\w*|день|недел\w*)?', low)
    if match:
        word = match[1]
        n = {'один': 1, 'два': 2, 'три': 3, 'четыре': 4, 'пять': 5, 'неделю': 7}.get(word) or int(word)
        return today + timedelta(days=n * (7 if (match[2] or '').startswith('недел') and word != 'неделю' else 1))
    match = re.search(r'\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b', low)
    if match:
        year = int(match[3]) + (2000 if match[3] and len(match[3]) == 2 else 0) if match[3] else today.year
        value = date(year, int(match[2]), int(match[1]))
        return value if value >= today or match[3] else date(year + 1, value.month, value.day)
    match = re.search(r'\b(\d{1,2})\s+(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]\w*|июн\w*|июл\w*|август\w*|сентябр\w*|'
                      r'октябр\w*|ноябр\w*|декабр\w*)', low)
    if match:
        month = next(v for k, v in MONTHS.items() if match[2].startswith(k))
        value = date(today.year, month, int(match[1]))
        return value if value >= today else date(today.year + 1, month, int(match[1]))
    match = re.search(r'\bв\s+(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)', low)
    if match:
        target = next(v for k, v in WEEKDAYS.items() if match[1].startswith(k))
        delta = (target - today.weekday()) % 7 or 7
        return today + timedelta(days=delta)
    return None


def people(text, default=1):
    low = text.casefold()
    match = re.search(r'на\s+(\d{1,2})\s*(?:человек|персон|гост|взросл|пассажир)?', low)
    if match:
        return max(1, min(9, int(match[1])))
    match = re.search(r'на\s+(' + '|'.join(COUNT) + r')\b', low)
    if match:
        return COUNT[match[1]]
    return default


def city_code(name):
    low = name.casefold().replace('ё', 'е').strip()
    for stem, code in sorted(CITIES.items(), key=lambda x: -len(x[0])):
        if low.startswith(stem.strip()):
            return code
    return None


def parse_flight(rest, home='Москва', today=None):
    """{'origin', 'dest', 'there', 'back', 'people'} или None."""
    low = ' ' + rest.casefold().replace('ё', 'е') + ' '
    origin = re.search(r'\sиз\s+([а-яa-z-]+(?:\s[а-я-]+)?)', low)
    dest = re.search(r'\s(?:в|во|до|на)\s+(?!самол)([а-яa-z-]+(?:\s(?:воды|новгород|дону))?)', low)
    if not dest:
        return None
    dest_code = city_code(dest[1])
    origin_code = city_code(origin[1]) if origin else city_code(home or 'москва')
    if not dest_code or not origin_code:
        return None
    back_part = re.split(r'\s(?:и\s+)?обратно\s*', low, maxsplit=1)
    there = parse_date(back_part[0], today)
    back = parse_date(back_part[1], today) if len(back_part) > 1 else None
    return {'origin': origin_code, 'dest': dest_code, 'there': there, 'back': back, 'people': people(low)}


def aviasales_url(flight, today=None):
    there = flight['there'] or (today or date.today()) + timedelta(days=1)
    code = f"{flight['origin']}{there:%d%m}{flight['dest']}"
    if flight['back']:
        code += f"{flight['back']:%d%m}"
    return f'https://www.aviasales.ru/search/{code}{flight["people"]}'


def parse(text):
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!')
    match = TABLE.match(value)
    if match:
        return 'table', match['rest']
    match = FLIGHT.match(value)
    if match:
        rest = match['rest'] if match['rest'] is not None else match['rest2']
        if re.search(r'самол|авиа|рейс|перел[её]т', value, re.I) or re.search(r'\s(?:в|до)\s+\w+', ' ' + rest) and \
                re.search(r'\bбилет', value, re.I) and not re.search(r'поезд|электричк|кино|театр|концерт|автобус', value, re.I):
            return 'flight', rest
    match = FOOD.match(value)
    if match:
        what = (match['what'] or '').strip()
        if what.casefold() in ('такси',) or re.match(r'(?:такси|билет|столик)', what, re.I):
            return None
        return 'food', (what or 'еда', match['service'])
    return None


class Booking:
    def __init__(self, opener, settings=None):
        self.opener = opener
        self.settings = settings or (lambda: {})

    def handle(self, text):
        request = parse(text)
        if request is None:
            return None
        kind = request[0]
        settings = self.settings() or {}
        if kind == 'food':
            what, service_word = request[1]
            key = settings.get('food_service', 'yandex_eda')
            if service_word:
                key = next((v for k, v in FOOD_WORDS.items() if service_word.casefold().startswith(k)), key)
            title, url = FOOD_SERVICES.get(key, FOOD_SERVICES['yandex_eda'])
            query = re.sub(r'^(?:мне\s+|пожалуйста\s+)', '', what).strip()
            self.opener(url.format(q=quote(query)))
            return f'Открываю {title}: «{query}». Выберите заведение и оформите заказ — оплату подтверждаете вы.'
        if kind == 'flight':
            flight = parse_flight(request[1], settings.get('weather_city') or 'Москва')
            if flight is None:
                return 'Куда лететь? Скажите, например: «купи билет на самолёт из Москвы в Сочи на 5 октября».'
            self.opener(aviasales_url(flight))
            when = f" на {flight['there']:%d.%m}" if flight['there'] else ' на завтра'
            back = f", обратно {flight['back']:%d.%m}" if flight['back'] else ''
            return (f'Ищу билеты {flight["origin"]} → {flight["dest"]}{when}{back}, пассажиров: {flight["people"]}. '
                    'Выберите рейс на Авиасейлс — покупку подтверждаете вы.')
        rest = request[1]
        guests = people(rest, 2)
        when = parse_date(rest)
        time_match = re.search(r'\b(?:на|в|к)\s+(\d{1,2})(?:[:.\s](\d{2}))?\b(?!\s*(?:человек|персон|гост))', rest)
        place = re.sub(r'\b(?:на|в|к)\s+\d{1,2}(?:[:.\s]\d{2})?\b|\bна\s+(?:\d+|' + '|'.join(COUNT) + r')\b.*$|'
                       r'\b(?:завтра|послезавтра|сегодня)\b', '', rest, flags=re.I)
        place = re.sub(r'^\s*(?:в|во)\s+', '', place).strip(' ,')
        place = re.sub(r'^(?:ресторан\w*|кафе|бар\w*)\s+', '', place, flags=re.I).strip()
        query = ('ресторан ' + place) if place else 'ресторан рядом'
        self.opener('https://yandex.ru/maps/?text=' + quote(query))
        parts = [f'{when:%d.%m}' if when else 'сегодня']
        if time_match:
            parts.append(f'{int(time_match[1]):02d}:{time_match[2] or "00"}')
        return (f'Открываю «{place or "рестораны рядом"}» на Яндекс Картах. Нажмите «Забронировать» и выберите '
                f'{" ".join(parts)}, гостей: {guests}. Подтверждаете бронь вы.')
