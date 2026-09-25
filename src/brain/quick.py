"""Instant exact answers without an LLM: курсы, конвертация, погода, крипта, калькулятор.

Эти вопросы — самые частые у голосового ассистента. Ответ идёт из
первоисточника (Банк России, MET Norway, CoinGecko) за доли секунды и не зависит
от того, насколько свежи знания языковой модели.
"""
import ast
import math
import operator
import re
from datetime import date, datetime

from .numbers import words_to_digits, plural, say_number
from .tools import (CURRENCY_NAMES, CURRENCY_GENITIVE, COIN_TITLES, currency_code,
                    coin_id, describe_day)

_WEEKDAYS = ('понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье')
_MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
           'сентября', 'октября', 'ноября', 'декабря')


def _clean(text):
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.,!?…').strip()
    return re.sub(r'^(?:скажи|подскажи|а|ну|слушай|пожалуйста)[,\s]+', '', value, flags=re.I)


def _date_words(iso):
    try:
        d = date.fromisoformat(iso[:10])
        return f'{d.day} {_MONTHS[d.month - 1]}'
    except (TypeError, ValueError):
        return ''


def money(amount, code):
    names = CURRENCY_NAMES.get(code, (code, code, code))
    return f'{say_number(amount)} {plural(amount, *names)}'


def signed(value):
    return ('плюс ' if value > 0 else 'минус ' if value < 0 else '') + say_number(abs(value))


# ---------------- калькулятор ----------------

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {'sqrt': math.sqrt, 'sin': lambda x: math.sin(math.radians(x)),
          'cos': lambda x: math.cos(math.radians(x)), 'tan': lambda x: math.tan(math.radians(x)),
          'log': math.log10, 'ln': math.log, 'abs': abs, 'round': round}


def safe_eval(expression):
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError('Слишком большая степень')
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and len(node.args) == 1:
            return _FUNCS[node.func.id](walk(node.args[0]))
        raise ValueError('Недопустимое выражение')
    if len(expression) > 200:
        raise ValueError('Слишком длинное выражение')
    return walk(ast.parse(expression, mode='eval'))


def spoken_math(text):
    """«25 умножить на 4» → «25*4». Возвращает выражение или None."""
    value = words_to_digits(text).casefold().replace('ё', 'е')
    value = re.sub(r'(\d),(\d)', r'\1.\2', value)
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:%|процент\w*)\s+от\s+(\d+(?:\.\d+)?)', value.strip())
    if m:
        return f'{m[1]}/100*{m[2]}'
    replacements = [
        (r'квадратный корень из|корень квадратный из|корень из', ' sqrt '),
        (r'умножить на|умноженное на|помножить на|умножь на|умножить|x|х|×', '*'),
        (r'разделить на|поделить на|делить на|деленное на|раздели на|÷', '/'),
        (r'плюс|прибавить|сложить с', '+'), (r'минус|отнять|вычесть', '-'),
        (r'в квадрате', '**2'), (r'в кубе', '**3'), (r'в степени', '**'),
        (r'синус', ' sin '), (r'косинус', ' cos '), (r'тангенс', ' tan '),
        (r'логарифм', ' log '),
    ]
    for pattern, replacement in replacements:
        value = re.sub(r'(?<![а-я])(?:' + pattern + r')(?![а-я])', replacement, value)
    value = re.sub(r'\b(sqrt|sin|cos|tan|log)\s+(\d+(?:\.\d+)?)', r'\1(\2)', value)
    value = value.replace('^', '**').replace(' ', '')
    if not re.fullmatch(r'[\d.+\-*/%()a-z]+', value) or not re.search(r'\d', value):
        return None
    if not re.search(r'[+\-*/%]|sqrt|sin|cos|tan|log', value):
        return None
    return value


def format_result(value):
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            value = int(value)
        else:
            value = round(value, 6)
    return str(value).replace('.', ',')


class QuickAnswers:
    def __init__(self, tools):
        self.tools = tools

    def answer(self, text, settings=None):
        settings = settings or {}
        phrase = _clean(text)
        if not phrase or len(phrase) > 160:
            return None
        lower = phrase.casefold().replace('ё', 'е')
        for handler in (self._calc, self._convert, self._rate, self._crypto, self._weather):
            try:
                result = handler(lower, settings)
            except Exception:
                result = None  # сеть недоступна и т.п. — отвечает ИИ
            if result:
                return result
        return None

    # «сколько будет 25 умножить на 4», «посчитай 15% от 2000»
    def _calc(self, lower, settings):
        m = re.match(r'^(?:сколько будет|посчитай|вычисли|подсчитай|реши|сколько)\s+(.+?)(?:\s*=)?$', lower)
        expression = spoken_math(m[1]) if m else None
        if expression is None and re.fullmatch(r'[\d\s.,+\-*/%()^x×÷]+', lower) and re.search(r'\d\s*[+\-*/^x×÷]\s*\d', lower):
            expression = spoken_math(lower)
        if not expression:
            return None
        try:
            return 'Получается ' + format_result(safe_eval(expression)) + '.'
        except ZeroDivisionError:
            return 'На ноль делить нельзя.'
        except (ValueError, SyntaxError, TypeError, OverflowError):
            return None

    # «100 долларов в рублях», «переведи 5000 рублей в евро»
    def _convert(self, lower, settings):
        value = words_to_digits(lower)
        m = re.search(r'(\d+(?:[.,]\d+)?)\s+([а-яa-z]+(?:\s+рубл\w*)?)\s+(?:в|во|на)\s+([а-яa-z]+)', value)
        if not m:
            return None
        amount = float(m[1].replace(',', '.'))
        source = 'BYN' if m[2].startswith('белорусск') else currency_code(m[2])
        target = currency_code(m[3])
        if not source or not target or source == target:
            return None
        result = self.tools.convert(amount, source, target)
        day = _date_words(self.tools.rate(source if source != 'RUB' else target)['date'] or '')
        return f'{money(amount, source)} — это {money(result, target)} по курсу ЦБ' + (f' на {day}.' if day else '.')

    # «какой курс доллара», «сколько стоит евро», «курс юаня к доллару»
    def _rate(self, lower, settings):
        m = re.search(r'курс\s+([а-яa-z]+)(?:\s+(?:к|в)\s+([а-яa-z]+))?', lower) or \
            re.search(r'(?:сколько стоит|почем|почём|цена)\s+([а-яa-z]+)(?:\s+(?:в|к)\s+([а-яa-z]+))?$', lower)
        if not m:
            return None
        code = currency_code(m[1])
        if not code or code == 'RUB':
            return None
        target = currency_code(m[2]) if m[2] else 'RUB'
        if not target:
            return None
        if target != 'RUB':
            value = self.tools.convert(1, code, target)
            return f'Один {CURRENCY_NAMES[code][0]} стоит {money(value, target)} по кросс-курсу ЦБ.'
        info = self.tools.rate(code)
        change = info['value'] - info['previous']
        day = _date_words(info['date'] or '')
        answer = f'Курс {CURRENCY_GENITIVE[code]} по ЦБ' + (f' на {day}' if day else '') + f': {money(info["value"], "RUB")}.'
        if abs(change) >= 0.005:
            answer += f' Изменение за день: {signed(change)}.'
        return answer

    # «курс биткоина», «сколько стоит эфир»
    def _crypto(self, lower, settings):
        m = re.search(r'(?:курс|сколько стоит|почем|почём|цена)\s+([а-яa-z]+)', lower)
        if not m:
            return None
        cid = coin_id(m[1])
        if not cid:
            return None
        data = self.tools.crypto([cid]).get(cid) or {}
        if 'usd' not in data:
            return None
        answer = f'{COIN_TITLES[cid]} сейчас стоит {say_number(data["usd"], 2)} долларов'
        if data.get('rub'):
            answer += f', это примерно {money(data["rub"], "RUB")}'
        change = data.get('usd_24h_change')
        if change is not None:
            answer += f'. За сутки {signed(round(change, 1))} процента'
        return answer + '. Данные CoinGecko.'

    # «погода», «какая погода завтра в Казани», «будет ли дождь»
    def _weather(self, lower, settings):
        if not re.search(r'погод|градус|температур|дожд|снег|зонт|холодно|жарко|тепло ли', lower):
            return None
        if re.search(r'\b(?:рецепт|песн|фильм|видео|открой|включи|найди)\b', lower):
            return None
        m = re.search(r'(?:^|\s)(?:в|во)\s+([а-яa-z\- ]+?)(?:\s+(?:сегодня|завтра|послезавтра|сейчас|на выходных|будет|вечером|утром|днем|ночью)|$)', lower)
        spoken = m[1].strip() if m else ''
        if spoken in ('городе', 'моем городе', 'мире', 'целом', 'среднем') or not spoken:
            spoken = ''
        index = 2 if 'послезавтра' in lower else 1 if 'завтра' in lower else 0
        name, data = self._forecast(spoken, settings.get('city') or 'Москва')
        where = spoken.title() if spoken else locative(name)
        daily = data['daily']
        if index == 0 and data.get('current'):
            cur = data['current']
            day = describe_day(daily, 0)
            text = (f'Сейчас в {where} {cur["condition"]}, {signed_temp(cur["temperature"])}. '
                    f'Днём до {signed_temp(day["t_max"])}, ночью {signed_temp(day["t_min"])}')
            if day['precipitation'] >= 0.5:
                text += f', осадки до {say_number(day["precipitation"], 1)} миллиметра'
            return text + '. По данным MET Norway.'
        day = describe_day(daily, index)
        when = 'Завтра' if index == 1 else 'Послезавтра'
        text = f'{when} в {where}: {day["condition"]}, от {signed_temp(day["t_min"])} до {signed_temp(day["t_max"])}'
        if day['precipitation'] >= 0.5:
            text += f', осадки до {say_number(day["precipitation"], 1)} миллиметра'
        if day['wind'] is not None and day['wind'] >= 8:
            text += f', сильный ветер до {round(day["wind"])} метров в секунду'
        return text + '. По данным MET Norway.'

    def _forecast(self, spoken, default_city):
        if not spoken:
            return self.tools.forecast(default_city, days=3)
        last = None
        for candidate in city_candidates(spoken):
            try:
                return self.tools.forecast(candidate, days=3)
            except LookupError as exc:
                last = exc
        raise last or LookupError(spoken)


CITY_ALIASES = {'питере': 'Санкт-Петербург', 'питер': 'Санкт-Петербург', 'спб': 'Санкт-Петербург',
                'петербурге': 'Санкт-Петербург', 'мск': 'Москва', 'екб': 'Екатеринбург', 'нск': 'Новосибирск'}


def city_candidates(spoken):
    """Предложный падеж → именительный: «казани» → «казань», «москве» → «москва»."""
    spoken = spoken.strip()
    if spoken in CITY_ALIASES:
        return [CITY_ALIASES[spoken]]
    words = spoken.split()
    head, last = words[:-1], words[-1]
    head = [re.sub(r'(?:ем|ом)$', 'ий', w) if len(w) > 4 else w for w in head]
    forms = [last]
    if len(last) > 3:
        stem = last[:-1]
        if last.endswith('е'):
            forms += [stem, stem + 'а', stem + 'ь', stem + 'я', stem + 'о']
        elif last.endswith('и'):
            forms += [stem + 'ь', stem + 'и', stem + 'а', stem]
        else:
            forms += [stem]
    result = []
    for form in forms:
        for option in (' '.join(head + [form]), ' '.join(words[:-1] + [form])):
            if option not in result:
                result.append(option)
    return result


def locative(name):
    """«Москва» → «Москве», «Казань» → «Казани», «Новосибирск» → «Новосибирске»."""
    if not name or ' ' in name or '-' in name:
        return name
    low = name.casefold()
    if low.endswith(('и', 'о', 'у', 'ы', 'э', 'ю')):
        return name
    if low.endswith('а') or low.endswith('я'):
        return name[:-1] + 'е'
    if low.endswith('ь'):
        return name[:-1] + 'и'
    if low.endswith('й'):
        return name[:-1] + 'е'
    return name + 'е'


def signed_temp(value):
    value = round(float(value))
    word = plural(value, 'градус', 'градуса', 'градусов')
    if value > 0:
        return f'плюс {value} {word}'
    if value < 0:
        return f'минус {abs(value)} {word}'
    return f'ноль {word}'


def now_context():
    now = datetime.now()
    return now.strftime('%d.%m.%Y %H:%M, ') + _WEEKDAYS[now.weekday()].replace('среду', 'среда').replace('пятницу', 'пятница').replace('субботу', 'суббота')
