"""Butler-style replies and short clarifying dialogs.

• «Включи Telegram» → «Да, сэр, включаю Telegram».
• «Открой» (или ослышанное «откройку») → «Что открыть, сэр?» → «Андрей, телеграм» → открывает.
• «Запустил Telegram» (ослышка) → «Запустить Telegram, сэр?» → «Андрей, да» → запускает.
"""
import random
import re
import time
from difflib import SequenceMatcher

# Главные глаголы: повелительная форма → (инфинитив для вопроса, форма «делаю» для ответа).
VERBS = {
    'открой': ('открыть', 'открываю'), 'запусти': ('запустить', 'запускаю'), 'включи': ('включить', 'включаю'),
    'закрой': ('закрыть', 'закрываю'), 'выключи': ('выключить', 'выключаю'), 'напиши': ('написать', 'пишу'),
    'найди': ('найти', 'ищу'), 'отправь': ('отправить', 'отправляю'), 'покажи': ('показать', 'показываю'),
    'напечатай': ('напечатать', 'печатаю'),
}
YES = {'да', 'ага', 'угу', 'конечно', 'давай', 'да давай', 'да конечно', 'верно', 'правильно', 'yes', 'ок', 'окей',
       'запускай', 'открывай', 'включай', 'закрывай', 'пиши', 'делай', 'да сэр', 'именно'}
NO = {'нет', 'не', 'не надо', 'не нужно', 'отмена', 'отмени', 'ничего', 'стоп', 'no', 'нет спасибо', 'забудь'}
PENDING_SECONDS = 25.0

PROGRESS = ('Открываю', 'Закрываю', 'Запускаю', 'Включаю', 'Выключаю', 'Ищу', 'Отправляю', 'Печатаю', 'Показываю')
DONE = ('Готово', 'Напечатал', 'Отправил', 'Свернул', 'Развернул', 'Восстановил', 'Скриншот', 'Вкладка закрыта',
        'Пауза', 'Воспроизведение', 'Перевёл', 'Исправил', 'Переписал', 'Написал', 'Поле очищено', 'Новая строка',
        'Компьютер заблокирован', 'Закрыт', 'Режим диктовки', 'Диктовка')
ERRORS = ('Не удалось', 'Не понял', 'Приложение не найдено', 'Не нашёл', 'Сначала', 'Управление', 'Браузер:',
          'Не знаю', 'Windows', 'Укажите', 'Для ', 'Массовое', 'Браузер не', 'Открытие', 'Безопасное',
          'Сайт заблокировал', 'Плеер найден', 'Rutube не', 'YouTube не', 'На странице только', 'Скажите',
          'Управляемых', 'Ошибка', 'Остановлено')


def _clean(text):
    return re.sub(r'\s+', ' ', str(text)).strip().strip('.,!?…').strip()


def _lower_first(text):
    return text[:1].lower() + text[1:] if text else text


# Прошедшее время вместо повелительного: «открыл», «запустила», «включили» → «открой»…
PAST = {info[0][:-2] + 'л': verb for verb, info in VERBS.items() if info[0].endswith('ть')}
PAST['нашёл'] = PAST['нашел'] = 'найди'


def fuzzy_verb(word, threshold=0.72):
    """Ближайший командный глагол для ослышанного слова или None."""
    word = word.casefold()
    for ending in ('', 'а', 'и', 'о'):
        if ending == '' or word.endswith('л' + ending):
            base = word[:-len(ending)] if ending else word
            if base in PAST:
                return PAST[base]
    best, score = None, 0.0
    for verb in VERBS:
        ratio = SequenceMatcher(None, word, verb).ratio()
        if ratio > score:
            best, score = verb, ratio
    return best if score >= threshold else None


def incomplete_verb(text):
    """Команда без объекта: «открой», «запусти», «откройку» → глагол."""
    words = re.findall(r'[\w-]+', text.casefold())
    if len(words) != 1:
        return None
    word = words[0]
    if word in VERBS:
        return word
    for verb in VERBS:
        if word.startswith(verb) and len(word) - len(verb) <= 3:
            return verb  # «откройку», «запустика»
    verb = fuzzy_verb(word, 0.8)
    return verb


def misheard_command(text, known_verbs):
    """«Запустил Telegram» → «запусти Telegram», если первое слово похоже на команду, но ею не является."""
    words = text.split(maxsplit=1)
    if len(words) != 2:
        return None
    first = words[0].strip(',.').casefold()
    if first in known_verbs or first in VERBS:
        return None
    verb = fuzzy_verb(first)
    if verb is None:
        return None
    return verb + ' ' + words[1]


class Dialog:
    def __init__(self):
        self.pending = {}

    def get(self, owner):
        item = self.pending.get(owner)
        if item and time.monotonic() > item['until']:
            self.pending.pop(owner, None)
            return None
        return item

    def set(self, owner, kind, command):
        self.pending[owner] = dict(kind=kind, command=command, until=time.monotonic() + PENDING_SECONDS)

    def clear(self, owner):
        self.pending.pop(owner, None)

    def awaiting(self, owner):
        return self.get(owner) is not None

    def resolve(self, owner, text, known_verbs):
        """Вернуть ('run', команда) | ('reply', ответ) | (None, None), если это не ответ на вопрос."""
        item = self.get(owner)
        if not item:
            return None, None
        answer = _clean(text).casefold()
        if answer in NO:
            self.clear(owner)
            return 'reply', 'cancel'
        if item['kind'] == 'confirm':
            self.clear(owner)
            if answer in YES or answer.startswith(('да ', 'да,')):
                return 'run', item['command']
            return None, None  # сказали что-то другое — обычная команда
        if item['kind'] == 'object':
            first = answer.split(maxsplit=1)[0] if answer else ''
            self.clear(owner)
            if not answer or first in known_verbs or first in VERBS:
                return None, None
            return 'run', item['command'] + ' ' + _clean(text)
        return None, None


def question_for_object(verb, address):
    return f'Что {VERBS[verb][0]}{", " + address if address else ""}?'


def question_for_confirm(command, address):
    verb, _, rest = command.partition(' ')
    return f'{VERBS[verb][0].capitalize()} {rest}{", " + address if address else ""}?'


def butler(result, command='', address='сэр', rng=random):
    """Оформить ответ на команду в стиле дворецкого."""
    text = str(result or '').strip()
    if not address or not text:
        return text
    verb = (command.split(maxsplit=1) or [''])[0].casefold()
    # «Включи X» → «включаю X», а не «открываю X».
    if verb in VERBS and text.startswith(PROGRESS):
        first, _, rest = text.partition(' ')
        text = VERBS[verb][1].capitalize() + (' ' + rest if rest else '')
    body = text.rstrip('.')
    if text.startswith(ERRORS):
        return rng.choice([f'Прошу прощения, {address}. {text}', f'Увы, {address}: {_lower_first(text)}'])
    if text.startswith(PROGRESS):
        return rng.choice([f'Да, {address}, {_lower_first(body)}.', f'Слушаюсь, {address}. {body}.',
                           f'Сию минуту, {address}. {body}.', f'Уже {_lower_first(body)}, {address}.'])
    if text.rstrip('.') in ('Готово', 'Слушаю'):
        return rng.choice([f'Готово, {address}.', f'Сделано, {address}.', f'Выполнено, {address}.']) \
            if text.startswith('Готово') else f'Слушаю, {address}.'
    if text.startswith(DONE):
        return rng.choice([f'Сделано, {address}. {text}', f'Выполнено, {address}. {text}', f'{body}, {address}.'])
    return rng.choice([f'Да, {address}. {text}', f'Слушаюсь, {address}. {text}'])
