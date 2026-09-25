"""Russian number words ↔ digits and plural forms (для речи и калькулятора)."""
import re

UNITS = {
    'ноль': 0, 'нуль': 0, 'один': 1, 'одна': 1, 'одну': 1, 'одно': 1, 'одного': 1, 'одной': 1,
    'два': 2, 'две': 2, 'двух': 2, 'три': 3, 'трех': 3, 'трёх': 3, 'четыре': 4, 'четырех': 4,
    'четырёх': 4, 'пять': 5, 'пяти': 5, 'шесть': 6, 'шести': 6, 'семь': 7, 'семи': 7,
    'восемь': 8, 'восьми': 8, 'девять': 9, 'девяти': 9, 'десять': 10, 'десяти': 10,
    'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13, 'четырнадцать': 14,
    'пятнадцать': 15, 'шестнадцать': 16, 'семнадцать': 17, 'восемнадцать': 18, 'девятнадцать': 19,
}
TENS = {
    'двадцать': 20, 'двадцати': 20, 'тридцать': 30, 'тридцати': 30, 'сорок': 40, 'сорока': 40,
    'пятьдесят': 50, 'пятидесяти': 50, 'шестьдесят': 60, 'шестидесяти': 60, 'семьдесят': 70,
    'семидесяти': 70, 'восемьдесят': 80, 'восьмидесяти': 80, 'девяносто': 90, 'девяноста': 90,
}
HUNDREDS = {
    'сто': 100, 'ста': 100, 'двести': 200, 'двухсот': 200, 'триста': 300, 'трехсот': 300,
    'четыреста': 400, 'пятьсот': 500, 'пятисот': 500, 'шестьсот': 600, 'семьсот': 700,
    'восемьсот': 800, 'девятьсот': 900,
}
SCALES = {
    'тысяча': 1000, 'тысячи': 1000, 'тысяч': 1000, 'тысячу': 1000, 'тыщ': 1000, 'тыща': 1000,
    'миллион': 10**6, 'миллиона': 10**6, 'миллионов': 10**6, 'млн': 10**6,
    'миллиард': 10**9, 'миллиарда': 10**9, 'миллиардов': 10**9, 'млрд': 10**9,
}
SPECIAL = {'полтора': 1.5, 'полторы': 1.5, 'полтысячи': 500}
_WORDS = {**UNITS, **TENS, **HUNDREDS}


def _fmt(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def _convert(span):
    total = current = 0
    for word in span:
        if word in SPECIAL:
            current += SPECIAL[word]
        elif word in SCALES:
            total += (current or 1) * SCALES[word]
            current = 0
        else:
            current += _WORDS[word]
    return _fmt(total + current)


def words_to_digits(text):
    """«двадцать пять умножить на четыре» → «25 умножить на 4»."""
    out, span, gap = [], [], ''
    for part in re.findall(r'\w+|\W+', str(text)):
        if span and part.isspace():
            gap = part
            continue
        word = part.casefold().replace('ё', 'е')
        last = next((x for x in reversed(out) if not x.isspace()), '')
        after_digit = bool(re.fullmatch(r'\d+(?:[.,]\d+)?', last))
        if word in _WORDS or word in SPECIAL or (word in SCALES and (span or (not after_digit and word not in ('млн', 'млрд')))):
            span.append(word)
            gap = ''
            continue
        if span:
            out.append(_convert(span))
            out.append(gap)
            span, gap = [], ''
        out.append(part)
    if span:
        out.append(_convert(span))
        out.append(gap)
    value = ''.join(out)

    def scale(match):
        number = float(match[1].replace(',', '.')) * SCALES[match[2].casefold()]
        return _fmt(round(number, 6))
    return re.sub(r'(\d+(?:[.,]\d+)?)\s+(тысяч[аиу]?|тыщ|миллион(?:а|ов)?|млн|миллиард(?:а|ов)?|млрд)(?!\w)', scale, value, flags=re.I)


def plural(number, one, few, many):
    """plural(5, 'рубль', 'рубля', 'рублей') → 'рублей'."""
    if not float(number).is_integer():
        return few
    n = abs(int(number)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def say_number(value, digits=2):
    """81.5234 → '81,52' (запятая — как принято в русском)."""
    if value is None:
        return '—'
    if abs(value) >= 1000:
        digits = 0 if abs(value) >= 100000 else min(digits, 2)
    text = f'{value:,.{digits}f}'.replace(',', ' ').replace('.', ',')
    if ',' in text:
        text = text.rstrip('0').rstrip(',')
    return text
