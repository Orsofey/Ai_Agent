"""Напоминания: голосом («Андрей, напомни через 20 минут позвонить маме»), персональная подборка по вопросам
(«Андрей, настрой напоминания») и встроенные («Сэр, пора отдохнуть от ПК», «Сэр, пора размяться»).

Все напоминания озвучиваются и видны в окне ассистента; редактируются в Настройки → «Напоминания».
Встроенные «отдохнуть от ПК» и «размяться» не звучат, если вы и так отошли от компьютера.
Два встроенных напоминания никогда не звучат подряд: между ними минимум PC_GAP секунд.
"""
import json
import logging
import re
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from .brain.numbers import words_to_digits

log = logging.getLogger(__name__)

CHECK_EVERY = 15          # секунд между проверками
IDLE_BREAK = 5 * 60       # отошли от ПК на 5 минут — это уже перерыв, отсчёт «отдохнуть от ПК» начинается заново
PC_GAP = 3 * 60           # «пора размяться» и «пора отдохнуть» — не чаще, чем одно за 3 минуты, и не подряд
WEEKDAYS = [('понедельник', 0), ('вторник', 1), ('сред', 2), ('четверг', 3), ('пятниц', 4), ('суббот', 5),
            ('воскресен', 6)]
DAY_NAMES = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

BUILTIN = [
    {'id': 'builtin-rest', 'text': '{Address}, пора отдохнуть от ПК.', 'kind': 'interval', 'every': 60,
     'from': '09:00', 'to': '23:00', 'enabled': True, 'builtin': True, 'pc': True},
    {'id': 'builtin-stretch', 'text': '{Address}, пора размяться.', 'kind': 'interval', 'every': 90,
     'from': '09:00', 'to': '23:00', 'enabled': True, 'builtin': True, 'pc': True},
]

_CLOCK = r'(?:в|на|к)\s+(\d{1,2})(?:[:.]\s?(\d{2})|\s+(\d{2})(?!\s*(?:минут|час)))?(?:\s*час\w*)?(?:\s*(утра|дня|вечера|ночи))?'


# ---------------- время ----------------
def _hour(h, part):
    h = int(h)
    if part in ('дня', 'вечера') and h < 12:
        h += 12
    if part == 'ночи' and h == 12:
        h = 0
    if part == 'утра' and h == 12:
        h = 0
    return h


def _clock(match, offset=0):
    h, m1, m2, part = match.group(1 + offset, 2 + offset, 3 + offset, 4 + offset)
    h = _hour(h, part)
    minute = int(m1 or m2 or 0)
    if not (0 <= h <= 23 and 0 <= minute <= 59):
        return None
    return f'{h:02d}:{minute:02d}'


def _days(text):
    if re.search(r'будн', text):
        return [0, 1, 2, 3, 4]
    if re.search(r'выходн', text):
        return [5, 6]
    return sorted({n for stem, n in WEEKDAYS if stem in text})


def parse_when(text, now=None):
    """Найти в тексте время напоминания. Вернуть (правило, текст_без_времени) или (None, текст)."""
    now = now or datetime.now()
    s = ' ' + words_to_digits(str(text).casefold().replace('ё', 'е')) + ' '
    s = re.sub(r'\bполчаса\b', '30 минут', s)
    s = re.sub(r'\bполтора часа\b', '90 минут', s)
    rules = [
        # каждые 2 часа / каждый час / каждые 30 минут
        (r'\s(?:каждые|каждый|каждую|раз в)\s+(\d+)?\s*(минут\w*|час\w*)', 'interval'),
        # по будням в 8:00, по понедельникам и средам в 19:00, каждый вторник в 10
        (r'\s(?:по|каждый|каждую|каждое|в)\s+((?:(?:будн|выходн|понедельник|вторник|сред|четверг|пятниц|суббот|воскресен)\w*'
         r'(?:\s*(?:,|и)\s*)?)+)\s*' + _CLOCK, 'weekly'),
        # каждый день в 9 / ежедневно в 21:30 / каждое утро / каждый вечер
        (r'\s(?:каждый день|ежедневно|каждое утро|каждый вечер|каждую ночь)(?:\s+' + _CLOCK + r')?', 'daily'),
        # через 20 минут / через 2 часа / через 3 дня
        (r'\sчерез\s+(\d+(?:[.,]\d+)?)?\s*(минут\w*|мин\b|час\w*|дн\w*|день|сутки)', 'after'),
        # завтра в 9 / сегодня в 18:30 / в 7 утра / послезавтра утром
        (r'\s(?:(сегодня|завтра|послезавтра)\s+)?' + _CLOCK, 'at'),
        (r'\s(сегодня|завтра|послезавтра)\s+(утром|днем|вечером)', 'part'),
    ]
    for pattern, kind in rules:
        match = re.search(pattern, s)
        if not match:
            continue
        rest = restore_case((s[:match.start()] + ' ' + s[match.end():]).strip(), text)
        if kind == 'interval':
            amount = float(match[1] or 1)
            every = int(amount * (60 if match[2].startswith('час') else 1))
            if not 5 <= every <= 24 * 60:
                continue
            return {'kind': 'interval', 'every': every, 'from': '08:00', 'to': '23:00'}, rest
        if kind == 'weekly':
            clock, days = _clock(match, 1), _days(match[1])
            if clock and days:
                return {'kind': 'weekly', 'days': days, 'time': clock}, rest
            continue
        if kind == 'daily':
            clock = _clock(match) if match.group(1) else {'каждое утро': '09:00', 'каждый вечер': '20:00',
                                                            'каждую ночь': '23:00'}.get(match.group(0).strip(), '09:00')
            if clock:
                return {'kind': 'daily', 'time': clock}, rest
            continue
        if kind == 'after':
            amount = float((match[1] or '1').replace(',', '.'))
            unit = match[2]
            minutes = amount * (60 if unit.startswith('час') else 1440 if unit.startswith(('дн', 'день', 'сут')) else 1)
            if not 1 <= minutes <= 60 * 24 * 60:
                continue
            return {'kind': 'once', 'at': (now + timedelta(minutes=minutes)).timestamp()}, rest
        if kind == 'at':
            clock = _clock(match, 1)
            if not clock:
                continue
            day = match[1]
            h, m = map(int, clock.split(':'))
            when = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if day == 'завтра':
                when += timedelta(days=1)
            elif day == 'послезавтра':
                when += timedelta(days=2)
            elif when <= now:
                # «в 7» вечером: следующее 7:00 — завтра утром; «в 7» днём без «утра» — скорее 19:00
                if not match[5] and h < 12 and when + timedelta(hours=12) > now:
                    when += timedelta(hours=12)
                else:
                    when += timedelta(days=1)
            return {'kind': 'once', 'at': when.timestamp()}, rest
        if kind == 'part':
            day = {'сегодня': 0, 'завтра': 1, 'послезавтра': 2}[match[1]]
            h = {'утром': 9, 'днем': 13, 'вечером': 19}[match[2]]
            when = (now + timedelta(days=day)).replace(hour=h, minute=0, second=0, microsecond=0)
            if when <= now:
                when += timedelta(days=1)
            return {'kind': 'once', 'at': when.timestamp()}, rest
    return None, restore_case(s.strip(), text)


def restore_case(text, original):
    """parse_when работает в нижнем регистре — вернуть исходные заглавные: «пете» → «Пете»."""
    words = {w.casefold().replace('ё', 'е'): w for w in re.findall(r'\w+', str(original))}
    return re.sub(r'\w+', lambda m: words.get(m[0], m[0]), str(text))


def clean_text(text):
    value = re.sub(r'\s+', ' ', str(text)).strip(' ,.:;-—')
    value = re.sub(r'^(?:мне|пожалуйста|о том,? что|о том,? чтобы|что(?:бы)?|про|о|об|насчет|на тему)\s+', '', value)
    value = re.sub(r'^(?:мне|о том,? что|что(?:бы)?|про|о|об)\s+', '', value)
    return value.strip(' ,.:;-—')


def describe(rule):
    kind = rule.get('kind')
    if kind == 'once':
        when = datetime.fromtimestamp(rule['at'])
        today = datetime.now().date()
        day = 'сегодня' if when.date() == today else 'завтра' if when.date() == today + timedelta(days=1) \
            else when.strftime('%d.%m')
        return f'{day} в {when:%H:%M}'
    if kind == 'daily':
        return f"каждый день в {rule['time']}"
    if kind == 'weekly':
        days = rule.get('days') or []
        label = 'по будням' if days == [0, 1, 2, 3, 4] else 'по выходным' if days == [5, 6] \
            else ', '.join(DAY_NAMES[d] for d in days)
        return f"{label} в {rule['time']}"
    if kind == 'interval':
        every = rule['every']
        span = f'{every // 60} ч' if every % 60 == 0 else f'{every} мин'
        return f"каждые {span}, с {rule.get('from', '08:00')} до {rule.get('to', '23:00')}"
    return ''


def _minutes(clock):
    h, m = map(int, str(clock).split(':'))
    return h * 60 + m


def next_time(rule, now=None, after=None):
    """Следующее срабатывание (epoch) по правилу."""
    now = now or datetime.now()
    kind = rule.get('kind')
    if kind == 'once':
        return rule['at']
    if kind in ('daily', 'weekly'):
        h, m = map(int, rule['time'].split(':'))
        days = rule.get('days') if kind == 'weekly' else list(range(7))
        for shift in range(0, 8):
            day = now + timedelta(days=shift)
            when = day.replace(hour=h, minute=m, second=0, microsecond=0)
            if when > now and when.weekday() in days:
                return when.timestamp()
        return (now + timedelta(days=7)).timestamp()
    if kind == 'interval':
        start = datetime.fromtimestamp(after) if after else now
        when = start + timedelta(minutes=rule['every'])
        low, high = _minutes(rule.get('from', '00:00')), _minutes(rule.get('to', '23:59'))
        minute = when.hour * 60 + when.minute
        if minute < low:
            when = when.replace(hour=low // 60, minute=low % 60, second=0) + timedelta(minutes=rule['every'])
        elif minute > high:
            when = (when + timedelta(days=1)).replace(hour=low // 60, minute=low % 60, second=0) \
                + timedelta(minutes=rule['every'])
        return when.timestamp()
    return None


def idle_seconds():
    """Сколько секунд пользователь не трогал мышь и клавиатуру."""
    try:
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]
            info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
        elif sys.platform == 'darwin':
            out = subprocess.run(['ioreg', '-c', 'IOHIDSystem'], capture_output=True, text=True, timeout=5).stdout
            match = re.search(r'"HIDIdleTime" = (\d+)', out)
            if match:
                return int(match[1]) / 1e9
    except Exception:
        pass
    return 0.0


# ---------------- персональная подборка ----------------
INTERVIEW = [
    ('wake', 'Во сколько вы обычно встаёте?'),
    ('sleep', 'Во сколько ложитесь спать?'),
    ('work', 'С какого и до какого времени работаете за компьютером? Например: с 9 до 18.'),
    ('water', 'Напоминать пить воду? Скажите, как часто — например, «каждые 2 часа», — или «нет».'),
    ('meds', 'Принимаете лекарства или витамины по расписанию? Скажите что и во сколько, или «нет».'),
    ('sport', 'Когда у вас тренировки? Например: «по понедельникам и средам в 19:00», или «нет».'),
    ('other', 'Что ещё важно не забывать? Скажите дело и время, например «каждый день в 21:00 план на завтра», '
              'или «всё».'),
]
NO = re.compile(r'^(?:нет|не надо|не нужно|никогда|пропусти|пропустить|дальше|не знаю|всё|все|хватит|нету|не принимаю)\b')


def _time_only(text):
    """«в 7 утра», «7:30», «к девяти» → 'ЧЧ:ММ'."""
    s = ' ' + words_to_digits(str(text).casefold()) + ' '
    match = re.search(r'(?:^|\s)(?:в|к|на|около)?\s*(\d{1,2})(?:[:.]\s?(\d{2})|\s+(\d{2}))?\s*(?:час\w*)?\s*(утра|дня|вечера|ночи)?(?:\s|$)', s)
    if not match:
        return None
    h = _hour(match[1], match[4])
    minute = int(match[2] or match[3] or 0)
    return f'{h:02d}:{minute:02d}' if 0 <= h <= 23 and 0 <= minute <= 59 else None


def _shift(clock, minutes):
    total = (_minutes(clock) + minutes) % (24 * 60)
    return f'{total // 60:02d}:{total % 60:02d}'


def plan_from_answers(answers):
    """Ответы опроса → список напоминаний и настройки встроенных."""
    plan, work = [], None
    wake = _time_only(answers.get('wake', ''))
    if wake:
        plan.append({'text': '{Address}, доброе утро! Стакан воды и лёгкая зарядка.', 'kind': 'daily',
                     'time': _shift(wake, 10)})
    sleep = _time_only(answers.get('sleep', ''))
    if sleep:
        plan.append({'text': '{Address}, через полчаса пора спать. Отложите экраны.', 'kind': 'daily',
                     'time': _shift(sleep, -30)})
    work_text = words_to_digits(str(answers.get('work', '')).casefold())
    match = re.search(r'(\d{1,2})(?:[:.](\d{2}))?\D+?(\d{1,2})(?:[:.](\d{2}))?', work_text)
    if match and not NO.match(work_text.strip()):
        start = f'{int(match[1]):02d}:{int(match[2] or 0):02d}'
        end_h = int(match[3]) + (12 if int(match[3]) < int(match[1]) else 0)
        end = f'{end_h % 24:02d}:{int(match[4] or 0):02d}'
        work = (start, end)
        plan.append({'text': '{Address}, рабочий день окончен. Пора отдохнуть.', 'kind': 'weekly',
                     'days': [0, 1, 2, 3, 4], 'time': end})
    water = str(answers.get('water', '')).strip()
    if water and not NO.match(water.casefold()):
        rule, _ = parse_when(water if re.search(r'кажд|раз в', water) else 'каждые ' + water)
        if not rule or rule['kind'] != 'interval':
            rule = {'kind': 'interval', 'every': 120}
        rule.update({'from': work[0] if work else (wake or '09:00'), 'to': work[1] if work else '21:00'})
        plan.append(dict(rule, text='{Address}, выпейте стакан воды.'))
    for key, prefix in (('meds', '{Address}, пора принять: '), ('sport', '{Address}, сегодня тренировка: '),
                        ('other', '{Address}, напоминаю: ')):
        answer = str(answers.get(key, '')).strip()
        if not answer or NO.match(answer.casefold()):
            continue
        for part in re.split(r'\s*(?:;|\.|,?\s+а также\s+|,?\s+и ещё\s+)\s*', answer):
            rule, rest = parse_when(part)
            if rule is None:
                continue
            if rule['kind'] == 'once':  # «витамины в 9» — каждый день
                rule = {'kind': 'daily', 'time': datetime.fromtimestamp(rule['at']).strftime('%H:%M')}
            what = clean_text(rest)
            if key == 'sport' and what.casefold() in ('', 'тренировка', 'тренировки', 'спорт'):
                plan.append(dict(rule, text='{Address}, сегодня тренировка.'))
                continue
            plan.append(dict(rule, text=prefix + (what or 'дело') + '.'))
    return plan, work


# ---------------- менеджер ----------------
class Reminders:
    def __init__(self, store, notify=None, speak=None, clock=time.time, idle=idle_seconds, background=False):
        self.store = store
        self.background = background  # фоновая проверка по времени — только в запущенной программе, не в тестах
        self.notify = notify
        self.speak = speak
        self.clock = clock
        self.idle = idle
        self.lock = threading.RLock()
        self.pending = {}      # owner → текст напоминания без времени (ждём «когда?»)
        self.interview = {}    # owner → {'step': n, 'answers': {}}
        self.last_fired = None
        self.last_pc_fired = 0.0  # когда последний раз звучало встроенное «размяться/отдохнуть» (для PC_GAP)
        self.thread = None
        self.items = self._load()

    # ---- хранение ----
    def _load(self):
        raw = self.store.meta('reminders')
        if raw:
            try:
                return [self._normal(i) for i in json.loads(raw)]
            except (ValueError, TypeError, KeyError):
                log.warning('Broken reminders in storage, restoring defaults')
        return [self._normal(dict(i)) for i in BUILTIN]

    def _normal(self, item):
        item = dict(item)
        item.setdefault('id', 'r-' + secrets.token_hex(4))
        item.setdefault('enabled', True)
        item.setdefault('builtin', False)
        item['text'] = str(item.get('text') or 'Напоминание')[:300]
        if item.get('kind') not in ('once', 'daily', 'weekly', 'interval'):
            raise ValueError('Неизвестный вид напоминания')
        if item['kind'] in ('daily', 'weekly') and not re.fullmatch(r'\d{2}:\d{2}', str(item.get('time', ''))):
            raise ValueError('Время напоминания: ЧЧ:ММ')
        if item['kind'] == 'weekly':
            item['days'] = sorted({int(d) for d in item.get('days') or [] if 0 <= int(d) <= 6})
            if not item['days']:
                raise ValueError('Выберите дни недели')
        if item['kind'] == 'interval':
            item['every'] = max(5, min(24 * 60, int(item.get('every') or 60)))
            for key, default in (('from', '08:00'), ('to', '23:00')):
                if not re.fullmatch(r'\d{2}:\d{2}', str(item.get(key, ''))):
                    item[key] = default
        if item['kind'] == 'once':
            item['at'] = float(item['at'])
        if not item.get('next') or item.get('kind') != item.get('_kind_seen'):
            item['next'] = next_time(item, datetime.fromtimestamp(self.clock()))
            item['_kind_seen'] = item['kind']
        return item

    def _save(self):
        self.store.set_meta('reminders', json.dumps(self.items, ensure_ascii=False))

    def list(self):
        with self.lock:
            return [dict(i, when=describe(i)) for i in self.items]

    def replace(self, items):
        """Сохранить список из окна настроек (изменения, удаление, новые)."""
        with self.lock:
            old = {i['id']: i for i in self.items}
            result = []
            for raw in items or []:
                raw = {k: v for k, v in dict(raw).items() if k not in ('when', 'next', '_kind_seen')}
                previous = old.get(raw.get('id'))
                if previous and all(previous.get(k) == raw.get(k) for k in ('kind', 'time', 'days', 'every', 'at',
                                                                           'from', 'to')):
                    raw['next'], raw['_kind_seen'] = previous.get('next'), previous.get('_kind_seen')
                result.append(self._normal(raw))
            self.items = result
            self._save()
        self.ensure_thread()
        return self.list()

    def add(self, text, rule, source='voice'):
        with self.lock:
            item = self._normal(dict(rule, text=text, source=source))
            self.items.append(item)
            self._save()
        self.ensure_thread()
        return item

    # ---- срабатывание ----
    def render(self, text, settings=None):
        from .dialog import address_of
        address = address_of(settings or {})
        value = text.replace('{Address}', address[:1].upper() + address[1:] if address else '') \
                    .replace('{address}', address)
        value = re.sub(r'^\s*,\s*', '', value).strip()
        return value[:1].upper() + value[1:]

    def say_text(self, item, settings=None):
        text = item['text']
        if '{' not in text and not item.get('builtin'):
            text = '{Address}, напоминаю: ' + text.rstrip('.') + '.'
        return self.render(text, settings)

    def tick(self, settings=None):
        """Проверить и выполнить наступившие напоминания. Вернуть список прозвучавших текстов."""
        fired = []
        if self.store.meta('reminders_muted') == '1':
            return fired
        now = self.clock()
        with self.lock:
            idle = None
            changed = False
            for item in list(self.items):
                if not item.get('enabled') or not item.get('next') or item['next'] > now:
                    continue
                if item.get('pc'):
                    idle = self.idle() if idle is None else idle
                    if idle >= IDLE_BREAK:  # человек и так отдыхает — отсчёт заново с момента возвращения
                        item['next'] = next_time(item, datetime.fromtimestamp(now), after=now)
                        changed = True
                        continue
                    # «Размяться» и «отдохнуть» не должны звучать друг за другом:
                    # если недавно уже прозвучало одно из них, второе откладываем на остаток паузы.
                    gap = PC_GAP - (now - self.last_pc_fired)
                    if gap > 0:
                        item['next'] = now + gap
                        changed = True
                        continue
                late = now - item['next']
                if item['kind'] != 'once' and late > 30 * 60:
                    item['next'] = next_time(item, datetime.fromtimestamp(now), after=now)  # ПК спал — не догоняем
                    changed = True
                    continue
                text = self.say_text(item, settings)
                fired.append(text)
                self.last_fired = item
                if item.get('pc'):
                    self.last_pc_fired = now
                if item['kind'] == 'once':
                    self.items.remove(item)
                else:
                    item['next'] = next_time(item, datetime.fromtimestamp(now), after=now)
                changed = True
            if changed:
                self._save()
        for text in fired:
            if self.notify:
                self.notify(text)
            if self.speak:
                try:
                    self.speak(text)
                except Exception:
                    log.exception('Reminder speech failed')
        return fired

    def ensure_thread(self):
        if not self.background or (self.thread is not None and self.thread.is_alive()):
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name='reminders')
        self.thread.start()

    def _run(self):
        while True:
            if not self.store.root.exists():
                return  # хранилище удалили (тесты, смена профиля)
            try:
                settings = self.store.settings('device:desktop')
                self.tick(settings)
            except Exception:
                log.exception('Reminders check failed')
            time.sleep(CHECK_EVERY)

    # ---- голос ----
    def awaiting(self, owner):
        return owner in self.pending or owner in self.interview

    def handle(self, text, owner, settings=None):
        raw = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
        lower = raw.casefold().replace('ё', 'е')
        if owner in self.interview:
            return self._interview_answer(owner, raw, settings)
        if owner in self.pending:
            if lower in ('отмена', 'отмени', 'не надо', 'нет', 'забудь'):
                self.pending.pop(owner)
                return 'Хорошо, не буду.'
            rule, _ = parse_when(raw)
            if rule is None:
                if re.match(r'^(?:создай|сделай|напомни|какие|удали|отключи|включи|открой|закрой)\b', lower):
                    self.pending.pop(owner)
                    return None  # человек перешёл к другой команде
                return 'Не понял время. Скажите, например: «через 15 минут» или «завтра в 9 утра».'
            what = self.pending.pop(owner)
            item = self.add(what, rule)
            return f'Хорошо, напомню {describe(item)}: {what}.'

        if re.fullmatch(r'(?:настрой|подбери|составь|сделай|создай)\s+(?:мне\s+)?(?:персональные\s+|личные\s+)?'
                        r'(?:напоминания|подборку напоминаний)(?:\s+для меня)?|персональные напоминания', lower):
            self.interview[owner] = {'step': 0, 'answers': {}}
            return ('Подберу напоминания под ваш день — задам семь коротких вопросов. На любой можно ответить «нет». '
                    + INTERVIEW[0][1])
        if re.fullmatch(r'(?:какие|покажи|перечисли|прочитай|назови)\s+(?:у меня\s+)?(?:мои\s+)?(?:все\s+)?напоминания'
                        r'|мои напоминания|список напоминаний', lower):
            return self._spoken_list()
        if lower in ('выключи напоминания', 'отключи напоминания', 'отключи все напоминания', 'выключи все напоминания',
                     'не напоминай'):
            self.store.set_meta('reminders_muted', '1')
            return 'Напоминания выключены. Скажите «включи напоминания», чтобы вернуть.'
        if lower in ('включи напоминания', 'включи все напоминания'):
            self.store.set_meta('reminders_muted', None)
            return 'Напоминания включены.'
        match = re.fullmatch(r'(?:отложи|перенеси)(?:\s+напоминание)?(?:\s+на\s+(.+))?|напомни позже', lower)
        if match and self.last_fired is not None:
            from .scenarios import parse_minutes
            minutes = parse_minutes(match[1]) if match.lastindex and match[1] else 10
            minutes = minutes or 10
            text_ = self.last_fired['text']
            self.add(text_, {'kind': 'once', 'at': self.clock() + minutes * 60})
            return f'Хорошо, напомню ещё раз через {minutes} мин.'
        match = re.fullmatch(r'(удали|убери|отмени|отключи|выключи|включи)\s+напоминани[ея]\s+(?:про\s+|о\s+|об\s+|с текстом\s+)?(.+)',
                             lower)
        if match:
            return self._change(match[1], match[2])
        match = re.fullmatch(r'(?:создай|сделай|поставь|добавь|заведи|установи)\s+(?:мне\s+)?(?:новое\s+)?напоминание'
                             r'(?:\s*[:,-]?\s*(.*))?', raw, re.I) \
            or re.fullmatch(r'напомни(?:\s+мне)?(?:\s+(.*))?', raw, re.I)
        if match:
            return self._create(match[1] or '', owner)
        return None

    def _create(self, body, owner):
        rule, rest = parse_when(body)
        what = clean_text(rest)
        if rule is None:
            if not what:
                return 'О чём и когда напомнить? Например: «напомни через 20 минут позвонить маме».'
            self.pending[owner] = what
            return 'Когда напомнить?'
        what = what or 'Напоминание'
        item = self.add(what, rule)
        return f'Хорошо, напомню {describe(item)}: {what}.'

    def _find(self, query):
        from difflib import SequenceMatcher
        query = clean_text(query).casefold()
        best, score = None, 0.0
        for item in self.items:
            text = self.render(item['text']).casefold()
            ratio = 1.0 if query and query in text else SequenceMatcher(None, query, text).ratio()
            if ratio > score:
                best, score = item, ratio
        return best if score >= 0.5 else None

    def _change(self, verb, query):
        with self.lock:
            item = self._find(query)
            if item is None:
                return f'Не нашёл напоминание «{query}».'
            name = self.render(item['text'])
            if verb in ('удали', 'убери', 'отмени'):
                self.items.remove(item)
                reply = f'Удалил напоминание: {name}'
            else:
                item['enabled'] = verb == 'включи'
                if item['enabled']:
                    item['next'] = next_time(item, datetime.fromtimestamp(self.clock()))
                reply = ('Включил' if item['enabled'] else 'Отключил') + f' напоминание: {name}'
            self._save()
        return reply

    def _spoken_list(self):
        active = [i for i in self.items if i.get('enabled')]
        if not active:
            return 'Напоминаний нет. Скажите, например: «напомни завтра в 9 позвонить маме».'
        parts = [f"{self.render(i['text']).rstrip('.')} — {describe(i)}" for i in active[:8]]
        more = f' И ещё {len(active) - 8}.' if len(active) > 8 else ''
        return f'Напоминаний: {len(active)}. ' + '; '.join(parts) + '.' + more

    def _interview_answer(self, owner, answer, settings):
        state = self.interview[owner]
        lower = answer.casefold()
        if lower in ('отмена', 'хватит', 'стоп опрос', 'прекрати опрос', 'отмени настройку'):
            self.interview.pop(owner)
            return 'Хорошо, настройку напоминаний отменил.'
        key = INTERVIEW[state['step']][0]
        if key in ('wake', 'sleep') and not NO.match(lower) and not _time_only(answer):
            return 'Не расслышал время. Скажите, например, «в 7 утра» или «нет».'
        state['answers'][key] = answer
        state['step'] += 1
        if state['step'] < len(INTERVIEW):
            return INTERVIEW[state['step']][1]
        self.interview.pop(owner)
        plan, work = plan_from_answers(state['answers'])
        with self.lock:
            self.items = [i for i in self.items if i.get('source') != 'interview']
            for item in self.items:
                if item.get('pc') and work:
                    item['from'], item['to'] = work
            self._save()
        for item in plan:
            text = item.pop('text')
            self.add(text, item, source='interview')
        if not plan:
            return 'Готово. Новых напоминаний не понадобилось — встроенные «отдохнуть от ПК» и «размяться» работают.'
        listing = '; '.join(f"{self.render(i['text'], settings).rstrip('.')} — {describe(i)}"
                            for i in self.items if i.get('source') == 'interview')
        return (f'Готово. Добавил напоминаний: {len(plan)}. {listing}. Изменить или удалить их можно '
                f'в Настройки → «Напоминания».')
