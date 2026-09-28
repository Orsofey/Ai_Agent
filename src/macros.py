"""Макросы — повторяющиеся действия одной фразой.

«Андрей, создай макрос утро: открой Telegram, затем открой YouTube, потом включи музыку»
«Андрей, запиши макрос работа» … обычные команды … «Андрей, сохрани макрос»
«Андрей, запусти макрос утро» или своя фраза запуска («доброе утро»).
Шаг «подожди 5 секунд» делает паузу. Шаги — обычные команды ассистента.
"""
import json
import re
import threading
import time

from . import abort

MAX_STEPS = 30
SPLIT = re.compile(r'\s*(?:[,;]?\s+(?:затем|потом|а потом|и потом|после этого|дальше|следом)\s+|;\s*|\n+|\.\s+(?=\S))\s*',
                   re.I)
WAIT = re.compile(r'^(?:подожди|жди|пауза|подождать)\s+(\d+(?:[.,]\d+)?|\w+)?\s*(секунд\w*|сек|минут\w*)?$', re.I)


def split_steps(text):
    return [s.strip(' ,.') for s in SPLIT.split(str(text)) if s.strip(' ,.')][:MAX_STEPS]


def wait_seconds(step):
    from .brain.numbers import words_to_digits
    match = WAIT.match(words_to_digits(step.strip()))
    if not match:
        return None
    amount = float((match[1] or '1').replace(',', '.')) if re.match(r'[\d.,]+$', match[1] or '1') else 1.0
    unit = (match[2] or 'секунд').casefold()
    return min(600.0, amount * (60 if unit.startswith('минут') else 1))


def validate(items):
    if not isinstance(items, list) or len(items) > 50:
        raise ValueError('Нужен список макросов (до 50)')
    result, names = [], set()
    for item in items:
        name = re.sub(r'\s+', ' ', str((item or {}).get('name', ''))).strip(' «»"').casefold()
        if not 1 <= len(name) <= 40:
            raise ValueError('Название макроса: 1–40 символов')
        if name in names:
            raise ValueError('Макросы с одинаковым названием: ' + name)
        names.add(name)
        steps = item.get('steps') or []
        if isinstance(steps, str):
            steps = steps.split('\n')
        steps = [re.sub(r'\s+', ' ', str(s)).strip() for s in steps if str(s).strip()][:MAX_STEPS]
        if not steps:
            raise ValueError(f'В макросе «{name}» нет шагов')
        if any(len(s) > 500 for s in steps):
            raise ValueError('Шаг макроса слишком длинный')
        phrase = re.sub(r'\s+', ' ', str(item.get('phrase') or '')).strip(' .!?').casefold()[:80]
        result.append({'name': name, 'steps': steps, 'phrase': phrase})
    return result


class Macros:
    def __init__(self, store, runner=None):
        self.store = store
        self.runner = runner        # runner(command, settings, owner) → ответ
        self.recordings = {}        # owner → {'name': ..., 'steps': []}
        self.lock = threading.RLock()

    def list(self):
        try:
            return validate(json.loads(self.store.meta('macros') or '[]'))
        except (ValueError, TypeError):
            return []

    def save(self, items):
        value = validate(items)
        self.store.set_meta('macros', json.dumps(value, ensure_ascii=False))
        return value

    def find(self, name):
        from difflib import SequenceMatcher
        key = str(name).strip(' «»"').casefold()
        best, score = None, 0.0
        for item in self.list():
            ratio = 1.0 if item['name'] == key else SequenceMatcher(None, key, item['name']).ratio()
            if ratio > score:
                best, score = item, ratio
        return best if score >= 0.75 else None

    def _put(self, name, steps, phrase=None):
        with self.lock:
            items = [i for i in self.list() if i['name'] != name.casefold()]
            old = self.find(name)
            items.append({'name': name, 'steps': steps, 'phrase': phrase if phrase is not None else (old or {}).get('phrase', '')})
            self.save(items)

    # ---- запись ----
    def recording(self, owner):
        return owner in self.recordings

    def record(self, owner, text):
        state = self.recordings.get(owner)
        if state is not None and len(state['steps']) < MAX_STEPS:
            state['steps'].append(text)

    # ---- голос ----
    def handle(self, text, owner, settings=None):
        raw = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
        lower = raw.casefold().replace('ё', 'е')
        if owner in self.recordings and re.fullmatch(r'(?:сохрани|закончи|заверши|останови|стоп)\s+(?:запись\s+)?(?:макрос\w*|запись)'
                                                     r'|стоп запись|конец записи|конец макроса', lower):
            state = self.recordings.pop(owner)
            if not state['steps']:
                return 'Запись остановлена: в макросе нет ни одной команды.'
            self._put(state['name'], state['steps'])
            return f"Макрос «{state['name']}» сохранён: {len(state['steps'])} шаг(ов). Запуск: «запусти макрос {state['name']}»."
        if owner in self.recordings and lower in ('отмени запись', 'отмена записи', 'не сохраняй'):
            self.recordings.pop(owner)
            return 'Запись макроса отменена.'
        match = re.fullmatch(r'(?:запиши|начни запись|записывай|запомни)\s+(?:макрос|макроса)\s+(.+)', lower)
        if match:
            name = match[1].strip(' «»"')
            self.recordings[owner] = {'name': name, 'steps': []}
            return f'Записываю макрос «{name}». Говорите команды, я их выполню и запомню. В конце скажите «сохрани макрос».'
        match = re.fullmatch(r'(?:создай|сделай|добавь|новый)\s+макрос\s+(.+?)\s*[:,—-]\s*(.+)', raw, re.I) \
            or re.fullmatch(r'(?:создай|сделай|добавь)\s+макрос\s+(\S+)\s+(.+)', raw, re.I)
        if match:
            name, steps = match[1].strip(' «»"').casefold(), split_steps(match[2])
            if not steps:
                return 'Назовите шаги макроса через «затем»: «создай макрос утро: открой почту, затем открой ютуб».'
            self._put(name, steps)
            return f"Макрос «{name}» создан: {'; '.join(steps)}. Запуск: «запусти макрос {name}»."
        match = re.fullmatch(r'(?:удали|убери)\s+макрос\s+(.+)', lower)
        if match:
            found = self.find(match[1])
            if not found:
                return f'Макроса «{match[1]}» нет.'
            self.save([i for i in self.list() if i['name'] != found['name']])
            return f"Удалил макрос «{found['name']}»."
        if re.fullmatch(r'(?:какие|покажи|перечисли)\s+(?:у меня\s+)?(?:мои\s+)?макросы|мои макросы|список макросов', lower):
            items = self.list()
            if not items:
                return 'Макросов пока нет. Скажите: «создай макрос утро: открой почту, затем открой ютуб».'
            return 'Макросы: ' + '; '.join(f"{i['name']} ({len(i['steps'])} шаг.)" for i in items) + '.'
        match = re.fullmatch(r'(?:запусти|выполни|включи|сделай|давай)\s+макрос\s+(.+)|макрос\s+(.+)', lower)
        macro = None
        if match:
            macro = self.find(match[1] or match[2])
            if macro is None:
                return f'Макроса «{match[1] or match[2]}» нет. Скажите «мои макросы», чтобы услышать список.'
        else:
            macro = next((i for i in self.list() if i['phrase'] and i['phrase'] == lower.strip(' ,')), None)
        if macro is not None:
            return self.run(macro, settings or {}, owner)
        return None

    def run(self, macro, settings, owner):
        if self.runner is None:
            return 'Макросы недоступны.'
        done, problems = 0, []
        quiet = dict(settings, butler=False)
        for step in macro['steps']:
            abort.check()  # «Андрей, стоп» останавливает макрос между шагами
            seconds = wait_seconds(step)
            if seconds is not None:
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    abort.check()
                    time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
                done += 1
                continue
            result = str(self.runner(step, quiet, owner) or '')
            done += 1
            if result.startswith(('Не удалось', 'Не понял', 'Приложение не найдено', 'Не нашёл')):
                problems.append(f'«{step}»: {result}')
            time.sleep(0.4)  # окну нужно время открыться перед следующим шагом
        reply = f"Макрос «{macro['name']}» выполнен: шагов {done}."
        if problems:
            reply += ' Не получилось: ' + '; '.join(problems[:3])
        return reply
