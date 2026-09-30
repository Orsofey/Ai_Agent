"""Коннекторы 6.1: календари, почта, задачи, файлы, финансы, CRM, музыка, разработка.

Каждое приложение умеет одно или несколько «умений» (calendar, mail, tasks, files, crm, dev) с общими фразами:
- календарь: «что у меня сегодня в календаре», «дела на завтра», «создай встречу с Иваном завтра в 15:00»;
- почта: «прочитай новые письма», «сколько новых писем», «найди письмо от Ивана»;
- задачи: «что в моём списке дел», «добавь задачу купить молоко на завтра», «отметь задачу купить молоко»;
- файлы: «загрузи этот файл на Диск», «найди на Диске договор», «сколько места на Диске»;
- CRM: «новые сделки», «добавь клиента Иван Петров +7 999 123-45-67»;
- разработка: «мои задачи в Jira», «мои merge request», «создай задачу в Linear: …».

Если приложение названо во фразе («в Notion», «на Яндекс Диск», «в Todoist»), команда идёт именно в него.
Иначе — в первое подключённое приложение с нужным умением (порядок — как в настройках).
"""
import base64
import email
import imaplib
import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from . import connector_config as cfg
from .connectors import TIMEOUT, Connector, ConnectorError, GoogleConnector, OAuthConnector

log = logging.getLogger(__name__)
UPLOAD_TIMEOUT = 600
APP_FOLDER = 'Андрей'


def now():
    return datetime.now().astimezone()


# ---------------- даты и время во фразах ----------------
MONTHS = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма': 5, 'июн': 6, 'июл': 7, 'август': 8, 'сентябр': 9,
          'октябр': 10, 'ноябр': 11, 'декабр': 12}
MONTH_NAMES = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября',
               'ноября', 'декабря']
MONTHS_RE = r'(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*'
WEEKDAY_RE = r'(?:понедельник|вторник|сред[уа]|четверг|пятниц[уа]|суббот[уа]|воскресенье)'
WEEKDAYS = ('понедельник', 'вторник', 'сред', 'четверг', 'пятниц', 'суббот', 'воскресен')
DAY_WORD = (r'(?:сегодня|завтра|послезавтра|(?:на\s+)?(?:эт\w+\s+|следующ\w+\s+)?недел\w+|' + WEEKDAY_RE +
            r'|\d{1,2}\s+' + MONTHS_RE + r'|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)')
DATE_RE = re.compile(r'(?:(?<![\w])(?:на|в|во|к|до)\s+)?(?<![\w])(?:сегодня|завтра|послезавтра|' + WEEKDAY_RE +
                     r'|\d{1,2}\s+' + MONTHS_RE + r'|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?(?![\d:])|'
                     r'через\s+(?:\d+|один|два|три|четыре|пять|неделю)\s*(?:дн\w*|день|недел\w*)?)(?![\w])', re.I)
DURATION_RE = re.compile(r'(?<![\w])на\s+(?:(\d+(?:[.,]5)?)\s*(час\w*|минут\w*|мин)|(час|полчаса|полтора часа))(?![\w])', re.I)
TIME_RE = re.compile(r'(?<![\w])(?:в|на|к|с|со)\s+(\d{1,2})(?:[:.](\d{2})|\s+(\d{2})(?=\s|$))?(?:\s*час\w*)?'
                     r'(?:\s*(утра|дня|вечера|ночи))?(?![\w.:/])', re.I)


def parse_day(text, today=None):
    """«завтра», «в пятницу», «5 октября», «05.10», «через 3 дня» → date или None."""
    from .booking import parse_date
    low = str(text).casefold()
    today = today or now().date()
    match = re.search(r'(?<![\w])(?:в|во|на)?\s*(' + WEEKDAY_RE + r')', low)
    if match and not re.search(r'сегодня|завтра|\d', low):
        index = next(i for i, stem in enumerate(WEEKDAYS) if match[1].startswith(stem))
        return today + timedelta(days=(index - today.weekday()) % 7 or 7) if index != today.weekday() else today
    return parse_date(low, today)


def split_when(text, moment=None):
    """«с Иваном завтра в 15:00 на час» → {'day': date, 'time': (15, 0), 'minutes': 60, 'rest': 'с Иваном'}."""
    from .brain.numbers import words_to_digits
    moment = moment or now()
    value = ' ' + words_to_digits(str(text)) + ' '
    value = re.sub(r'(?<![\w])(в|к)\s+полдень(?![\w])', r'\1 12:00', value, flags=re.I)
    result = {'day': None, 'time': None, 'minutes': None}
    match = DATE_RE.search(value)
    if match:
        result['day'] = parse_day(match[0], moment.date())
        value = value[:match.start()] + ' ' + value[match.end():]
    match = DURATION_RE.search(value)
    if match:
        if match[3]:
            result['minutes'] = {'час': 60, 'полчаса': 30, 'полтора часа': 90}[match[3].casefold()]
        else:
            amount = float(match[1].replace(',', '.'))
            result['minutes'] = int(amount * (60 if match[2].casefold().startswith('час') else 1))
        value = value[:match.start()] + ' ' + value[match.end():]
    match = TIME_RE.search(value)
    if match:
        hour, minute = int(match[1]), int(match[2] or match[3] or 0)
        part = (match[4] or '').casefold()
        if part in ('дня', 'вечера') and hour < 12:
            hour += 12
        elif part in ('утра', 'ночи') and hour == 12:
            hour = 0
        elif not part and 1 <= hour <= 7:
            hour += 12            # «встреча в 3» — это 15:00
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            result['time'] = (hour, minute)
            value = value[:match.start()] + ' ' + value[match.end():]
    result['rest'] = re.sub(r'\s+', ' ', value).strip(' ,.:—-')
    return result


def when_start(parts, moment=None):
    """Начало события по split_when: без даты, но с временем — сегодня (или завтра, если время прошло)."""
    moment = moment or now()
    day = parts['day'] or moment.date()
    if parts['time'] is None:
        return day, None
    start = datetime.combine(day, dtime(*parts['time'])).astimezone()
    if parts['day'] is None and start < moment:
        start += timedelta(days=1)
    return start.date(), start


def period(text, moment=None):
    """Какой период спрашивают: (начало, конец, «сегодня»/«завтра»/«на неделе»/«5 октября»)."""
    moment = moment or now()
    low = str(text).casefold()
    today = moment.date()
    if re.search(r'недел', low):
        first = today + timedelta(days=7 - today.weekday()) if 'следующ' in low else today
        last = first + timedelta(days=7 if 'следующ' in low else 7 - today.weekday())
        return local(first), local(last), 'на следующей неделе' if 'следующ' in low else 'на этой неделе'
    day = parse_day(low, today) or today
    return local(day), local(day + timedelta(days=1)), day_label(day, today)


def local(day):
    return datetime.combine(day, dtime()).astimezone()


def day_label(day, today=None):
    today = today or now().date()
    delta = (day - today).days
    named = {0: 'сегодня', 1: 'завтра', 2: 'послезавтра', -1: 'вчера'}
    return named.get(delta) or f'{day.day} {MONTH_NAMES[day.month - 1]}'


def hhmm(value):
    return value.astimezone().strftime('%H:%M')


def iso_utc(value):
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def from_iso(value):
    value = str(value)
    if len(value) == 10:
        return date.fromisoformat(value)
    value = value.replace('Z', '+00:00')
    value = re.sub(r'(\.\d{6})\d+', r'\1', value)    # Graph: 7 знаков долей секунды
    parsed = datetime.fromisoformat(value)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone()


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def capital(text):
    text = str(text).strip()
    return text[:1].upper() + text[1:]


def money(value):
    """MoneyValue/Quotation Т-Инвестиций → число."""
    if not value:
        return 0.0
    return int(value.get('units', 0) or 0) + int(value.get('nano', 0) or 0) / 1e9


def rub(amount, currency='rub'):
    sign = {'rub': '₽', 'usd': '$', 'eur': '€', 'cny': '¥'}.get(str(currency).casefold(), str(currency).upper())
    return f'{amount:,.0f}'.replace(',', ' ') + ' ' + sign


# ---------------- умения ----------------
class Skills:
    """Общие голосовые фразы для приложения с несколькими умениями."""
    skills = ()                # порядок проверки: ('calendar', 'mail', 'tasks', 'files', …)

    def handle(self, text):
        for skill in self.skills:
            reply = getattr(self, 'handle_' + skill)(text)
            if reply is not None:
                return reply
        return None

    def named(self, text, skill):
        """Названо ли приложение (именно для этого умения): «в Яндекс Календаре», «на Яндекс Диск»."""
        names = getattr(self, skill + '_names', '') or self.names
        return bool(names) and re.search(r'(?<![\w])(?:' + names + r')(?![\w])', str(text), re.I) is not None


# ---- календарь ----
CAL_WORD = r'(?:календар\w*|встреч\w*|событи\w*|созвон\w*|мероприяти\w*|расписани\w*)'
CAL_ASK = re.compile(r'^(?:что|какие|какая|какой|покажи|прочитай|озвучь|есть ли|сколько|мои|мой|расскажи|'
                     r'что у меня|какие у меня)\b')
CAL_DAY = re.compile(r'(?:что у меня|что запланировано|какие (?:у меня )?планы|планы|мои дела|дела|что по плану|'
                     r'что в планах)(?:\s+(?:на|в|во))?\s+' + DAY_WORD + r'(?:\s+у меня)?', re.I)
CAL_CREATE = re.compile(r'(?:создай|добавь|запланируй|назначь|поставь|запиши|заведи)\s+(?:мне\s+)?'
                        r'(?:в\s+календар\w*\s+)?(?:нов\w+\s+)?(?P<noun>встреч\w*|событи\w*|созвон\w*|звонок|'
                        r'мероприяти\w*)?(?:\s+в\s+календар\w*)?\s*[:,—-]?\s*(?P<rest>.*)', re.I)
NOUNS = {'встреч': 'Встреча', 'событи': 'Событие', 'созвон': 'Созвон', 'звонок': 'Звонок', 'мероприяти': 'Мероприятие'}


class CalendarSkill:
    """Нужно: calendar_events(start, end) → [{'title', 'start': datetime|date}], calendar_create(title, start, end, all_day)."""

    def handle_calendar(self, text):
        raw = self.plain(text)
        low = raw.casefold().replace('ё', 'е')
        named = self.named(text, 'calendar')
        if re.match(r'^(?:создай|добавь|запланируй|назначь|поставь|запиши|заведи)\b', low):
            match = CAL_CREATE.fullmatch(raw)
            if match and (match['noun'] or 'календар' in low or named):
                return self.calendar_add(match['noun'], match['rest'])
            return None
        asks = CAL_ASK.match(low) and not re.match(r'^что (?:такое|значит|означает)', low) and \
            (named or re.search(r'(?:в|по|из)\s+календар\w*|встреч|событи|созвон|мероприяти|расписани', low))
        if asks or CAL_DAY.fullmatch(low) or \
                (named and re.fullmatch(r'(?:что\s+)?(?:у меня\s+)?(?:на\s+)?' + DAY_WORD, low)):
            if re.search(r'письм|почт|задач|списк\w* дел', low):
                return None
            start, end, label = period(low)
            items = sorted(self.calendar_events(start, end), key=lambda e: (isinstance(e['start'], datetime),
                                                                           str(e['start'])))
            where = f'в {self.calendar_title}' if getattr(self, 'calendar_title', '') else 'в календаре'
            if not items:
                return f'{capital(label)} {where} ничего нет.'
            parts = [('весь день' if not isinstance(e['start'], datetime) else hhmm(e['start'])) + ' — ' +
                     (e['title'] or 'без названия') for e in items[:10]]
            count = len(items)
            return (f'{capital(label)} {where} {count} {plural(count, "событие", "события", "событий")}: ' +
                    '; '.join(parts) + '.')
        return None

    def calendar_add(self, noun, rest):
        parts = split_when(rest or '')
        if parts['day'] is None and parts['time'] is None:
            return 'Когда? Скажите, например: «создай встречу с Иваном завтра в 15:00».'
        base = next((v for k, v in NOUNS.items() if (noun or '').casefold().startswith(k)), '')
        title = parts['rest']
        if base and (not title or re.match(r'^(?:с|со|по|для|про|о|об|на тему)\s', title, re.I)):
            title = f'{base} {title}'.strip()
        title = capital(title or base or 'Событие')
        day, start = when_start(parts)
        if start is None:
            self.calendar_create(title, day, day + timedelta(days=1), True)
            return f'Добавил в календарь на {day_label(day)}: «{title}» (весь день).'
        end = start + timedelta(minutes=parts['minutes'] or 60)
        self.calendar_create(title, start, end, False)
        return f'Добавил в календарь: «{title}», {day_label(start.date())} в {hhmm(start)}.'


# ---- почта ----
MAIL_WORD = r'(?:письм\w*|пис[её]м|почт\w*|входящ\w*|имейл\w*|e-?mail\w*|емейл\w*)'
MAIL_ASK = re.compile(r'^(?:прочитай|покажи|озвучь|проверь|какие|есть ли|есть|сколько|что|кратк\w+|сводк\w+|пришли ли|'
                      r'пришло ли|мои|нов\w+|непрочитан\w+|кто (?:мне )?писал|перескажи)\b')
MAIL_FIND = re.compile(r'(?:найди|поищи|найти|есть ли)\s+(?:мне\s+)?(?:в\s+(?:почте|письмах)\s+)?(?:письм\w*\s+)?'
                       r'(?:(?P<how>от|про|о|об|насчет|по теме|с темой|со словом|со словами)\s+)?(?P<q>.+)', re.I)


def sender(value):
    name, address = parseaddr(value or '')
    return (name or address or 'неизвестный отправитель').strip('"')


def decoded(value):
    try:
        return str(make_header(decode_header(value or '')))
    except Exception:
        return value or ''


class MailSkill:
    """Нужно: mail_unread(limit) → (count, [{'from', 'subject'}]), mail_search(query, how, limit) → [{'from', 'subject'}]."""

    def handle_mail(self, text):
        raw = self.plain(text)
        low = raw.casefold().replace('ё', 'е')
        named = self.named(text, 'mail')
        match = MAIL_FIND.fullmatch(raw)
        if match and re.match(r'^(?:найди|поищи|найти)\b', low) and (re.search(MAIL_WORD, low) or named):
            query = re.sub(r'(?<![\w])(?:в\s+)?(?:почте|письмах)(?![\w])', ' ', match['q'], flags=re.I).strip(' «»"')
            how = (match['how'] or '').casefold()
            how = 'from' if how == 'от' else 'subject' if how in ('по теме', 'с темой') else 'text'
            if not query:
                return None
            found = self.mail_search(query, how, 5)
            if not found:
                return f'Не нашёл писем {"от" if how == "from" else "про"} «{query}».'
            return f'Нашёл писем: {len(found)}. ' + '; '.join(
                f'от {m["from"]}: {m["subject"] or "без темы"}' for m in found[:5]) + '.'
        if (re.search(MAIL_WORD, low) or (named and re.search(r'нов\w+|непрочитан\w+|сводк\w+', low))) and \
                MAIL_ASK.match(low) and not re.search(r'отправь|напиши|перешли|календар|задач', low):
            only_count = low.startswith('сколько')
            count, items = self.mail_unread(0 if only_count else 5)
            where = getattr(self, 'mail_title', '') or 'почте'
            if not count:
                return f'Новых писем в {where} нет.'
            head = f'В {where} {count} {plural(count, "новое письмо", "новых письма", "новых писем")}'
            if only_count or not items:
                return head + '.'
            return head + ': ' + '; '.join(f'от {m["from"]}: {m["subject"] or "без темы"}' for m in items) + '.'
        return None


class Imap:
    """Почта по IMAP: пароль приложения или токен (XOAUTH2 — Яндекс, Gmail, Outlook)."""
    HOSTS = {'mail.ru': 'imap.mail.ru', 'inbox.ru': 'imap.mail.ru', 'list.ru': 'imap.mail.ru', 'bk.ru': 'imap.mail.ru',
             'internet.ru': 'imap.mail.ru', 'yandex.ru': 'imap.yandex.ru', 'ya.ru': 'imap.yandex.ru',
             'yandex.com': 'imap.yandex.ru', 'narod.ru': 'imap.yandex.ru', 'gmail.com': 'imap.gmail.com',
             'googlemail.com': 'imap.gmail.com', 'rambler.ru': 'imap.rambler.ru', 'lenta.ru': 'imap.rambler.ru',
             'icloud.com': 'imap.mail.me.com', 'me.com': 'imap.mail.me.com', 'outlook.com': 'outlook.office365.com',
             'hotmail.com': 'outlook.office365.com', 'live.com': 'outlook.office365.com', 'yahoo.com': 'imap.mail.yahoo.com'}
    factory = imaplib.IMAP4_SSL

    def __init__(self, host, login, password=None, oauth=None):
        self.host = host
        self.login = login
        self.password = password
        self.oauth = oauth
        self.conn = None

    @classmethod
    def host_for(cls, address):
        domain = address.rsplit('@', 1)[-1].casefold()
        return cls.HOSTS.get(domain) or 'imap.' + domain

    def __enter__(self):
        try:
            self.conn = self.factory(self.host, 993, timeout=TIMEOUT)
            if self.oauth:
                auth = f'user={self.login}\x01auth=Bearer {self.oauth}\x01\x01'.encode()
                self.conn.authenticate('XOAUTH2', lambda _: auth)
            else:
                self.conn.login(self.login, self.password)
            self.conn.select('INBOX', readonly=True)
        except imaplib.IMAP4.error as exc:
            raise ConnectorError('Почта не приняла вход: проверьте адрес и пароль приложения '
                                 f'(не обычный пароль). {str(exc)[:80]}')
        except OSError:
            raise ConnectorError(f'Почтовый сервер {self.host} не отвечает.')
        return self

    def __exit__(self, *exc):
        try:
            self.conn.logout()
        except Exception:
            pass

    def _uids(self, *criteria):
        typ, data = self.conn.uid('SEARCH', *criteria)
        return (data[0] or b'').split() if typ == 'OK' and data else []

    def headers(self, uids):
        if not uids:
            return []
        typ, data = self.conn.uid('FETCH', b','.join(uids).decode(), '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])')
        result = []
        for item in data or []:
            if isinstance(item, tuple) and len(item) > 1:
                message = email.message_from_bytes(item[1])
                result.append({'from': sender(decoded(message.get('From'))),
                               'subject': decoded(message.get('Subject')).strip()})
        return list(reversed(result))          # свежие первыми

    def unread(self, limit=5):
        uids = self._uids(None, 'UNSEEN')
        return len(uids), self.headers(uids[-limit:]) if limit else []

    def search(self, query, how='text', limit=5):
        key = {'from': 'FROM', 'subject': 'SUBJECT'}.get(how, 'TEXT')
        try:
            if query.isascii():
                uids = self._uids(None, key, '"' + query.replace('"', '') + '"')
            else:
                self.conn.literal = query.encode('utf-8')
                uids = self._uids('CHARSET', 'UTF-8', key)
        except imaplib.IMAP4.error:
            return []
        return self.headers(uids[-limit:])


# ---- задачи ----
TASK_LIST = re.compile(r'(?:что|какие)\s+(?:у меня\s+)?(?:есть\s+)?(?:в\s+)?(?:мо[её]м\s+|моих\s+|мои\s+)?(?:списк\w*\s+дел|'
                       r'задач\w*|дел[аx]?|туду|to\s?do|списк\w* задач)(?:\s+(?:на|в)\s+(?P<d>' + DAY_WORD + r'))?'
                       r'|(?:мои|покажи(?:\s+мои)?|прочитай(?:\s+мои)?|озвучь(?:\s+мои)?)\s+(?:задачи|дела|список дел|туду)'
                       r'(?:\s+(?:на|в)\s+(?P<d2>' + DAY_WORD + r'))?|(?:мой\s+)?список\s+(?:дел|задач)', re.I)
TASK_ADD = re.compile(r'(?:добавь|создай|запиши|заведи|поставь)\s+(?:мне\s+)?(?:новую\s+|новое\s+)?'
                      r'(?:задачу|дело|таск|карточку|заметку|в список дел|в задачи|в дела|в туду)\s*[:,—-]?\s*(?P<title>.+)', re.I)
TASK_DONE = re.compile(r'(?:отметь|закрой|заверши|выполни)\s+(?:задачу|дело|таск|карточку)\s+(?P<title>.+?)'
                       r'(?:\s+(?:как\s+)?(?:выполненн\w+|сделанн\w+|готов\w*))?', re.I)


def similar(query, title):
    q = [w[:5] for w in re.findall(r'\w+', query.casefold().replace('ё', 'е')) if len(w) > 2]
    t = title.casefold().replace('ё', 'е')
    return bool(q) and all(w in t for w in q)


class TasksSkill:
    """Нужно: tasks_list(day|None) → [{'title', 'due': date|None}], tasks_add(title, day, time).
    По желанию: tasks_done(title) → название закрытой задачи или None."""
    tasks_generic = True    # «добавь задачу…» без названия приложения

    def handle_tasks(self, text):
        raw = self.plain(text)
        low = raw.casefold().replace('ё', 'е')
        named = self.named(text, 'tasks')
        if not named and not self.tasks_generic:
            return None
        where = getattr(self, 'tasks_title', '') or self.title
        match = TASK_ADD.fullmatch(raw)
        if match:
            title = match['title'].strip(' «»"')
            if re.match(r'^(?:в|для)\s+(?:репозитори|проект|доск|команд|календар)', title, re.I):
                return None     # «создай задачу в репозитории…» — это GitHub/GitLab/Jira
            parts = split_when(title)
            title = capital(parts['rest'] or title)
            day, start = when_start(parts) if (parts['day'] or parts['time']) else (None, None)
            self.tasks_add(title, day, start)
            due = f' на {day_label(day)}' if day else ''
            return f'Добавил в {where} задачу «{title}»{due}' + (f' в {hhmm(start)}' if start else '') + '.'
        match = TASK_DONE.fullmatch(raw)
        if match and hasattr(self, 'tasks_done'):
            done = self.tasks_done(match['title'].strip(' «»"'))
            return f'Отметил выполненной: «{done}».' if done else f'Не нашёл задачу «{match["title"]}» в {where}.'
        match = TASK_LIST.fullmatch(low) or (named and re.fullmatch(
            r'(?:что|какие задачи|что у меня|какие дела)(?:\s+у меня)?(?:\s+(?:на|в))?\s+(?P<d>' + DAY_WORD + r')', low))
        if match:
            groups = match.groupdict()
            asked = groups.get('d') or groups.get('d2')
            day = parse_day(asked) if asked else None
            items = self.tasks_list(day)
            label = f' на {day_label(day)}' if day else ''
            if not items:
                return f'В {where}{label} задач нет.'
            shown = '; '.join(t['title'] + (f' ({day_label(t["due"])})' if t.get('due') and not day else '')
                              for t in items[:10])
            count = len(items)
            return f'В {where}{label} {count} {plural(count, "задача", "задачи", "задач")}: {shown}.'
        return None


# ---- файлы в облаке ----
UPLOAD = re.compile(r'(?:загрузи|закинь|залей|сохрани|скинь|отправь|положи|выгрузи|перекинь)\s+(?:мне\s+)?'
                    r'(?:эт\w+\s+|последн\w+\s+|выделенн\w+\s+)?(?:файл\w*|документ\w*|фото\w*|картинк\w*|их|его)'
                    r'(?:\s+(?P<where>(?:на|в)\s+(?:диск|облако)))?', re.I)
FIND_FILE = re.compile(r'(?:найди|поищи|где)\s+(?:мне\s+)?(?:(?:на|в)\s+(?:диске|облаке)\s+)?(?:файл\w*\s+|документ\w*\s+)?'
                       r'(?:(?:на|в)\s+(?:диске|облаке)\s+)?(?P<q>.+)', re.I)
SPACE = re.compile(r'(?:сколько|много ли)\s+(?:свободного\s+|осталось\s+)?места(?:\s+осталось)?(?:\s+(?:на|в)\s+(?:диске|облаке))?'
                   r'(?:\s+осталось)?', re.I)


def size_text(n):
    n = float(n or 0)
    for unit in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if n < 1024 or unit == 'ТБ':
            return f'{n:.0f} {unit}' if unit in ('Б', 'КБ') else f'{n:.1f} {unit}'.replace('.0 ', ' ')
        n /= 1024


class FilesSkill:
    """Нужно: files_upload(path) → ссылка или '', files_find(query) → [{'name', 'path', 'url'}], files_space() → (used, total)."""

    def handle_files(self, text):
        raw = self.plain(text)
        low = raw.casefold().replace('ё', 'е')
        named = self.named(text, 'files')
        where = getattr(self, 'files_title', '') or self.title
        match = UPLOAD.fullmatch(raw)
        if match and (named or match['where']):
            docs = getattr(self.hub, 'documents', None)
            paths = [Path(p) for p in (docs.target('этот файл') if docs is not None else [])]
            paths = [p for p in paths if p.is_file()]
            if not paths:
                return 'Не вижу файла: выделите его в Проводнике (или он должен быть последним в чате) и повторите.'
            for path in paths[:10]:
                self.files_upload(path)
            names = f'«{paths[0].name}»' if len(paths) == 1 else f'{len(paths)} {plural(len(paths), "файл", "файла", "файлов")}'
            return f'Загрузил {names} на {where} в папку «{APP_FOLDER}».'
        if named and SPACE.fullmatch(low):
            used, total = self.files_space()
            return f'На {where} занято {size_text(used)} из {size_text(total)}, свободно {size_text(max(0, total - used))}.'
        match = FIND_FILE.fullmatch(raw)
        if match and (named or re.search(r'(?:на|в)\s+(?:диске|облаке)', low)):
            query = match['q'].strip(' «»"')
            found = self.files_find(query)
            if not found:
                return f'На {where} не нашёл «{query}».'
            first = found[0]
            if first.get('url'):
                self.hub.open(first['url'])
            return f'Нашёл на {where}: ' + '; '.join(f['path'] or f['name'] for f in found[:5]) + \
                ('. Открываю первый.' if first.get('url') else '.')
        return None


# ---- CRM ----
CRM_DEALS = re.compile(r'(?:какие\s+|покажи\s+|есть\s+ли\s+|есть\s+)?(?:у меня\s+)?(?:нов\w+|последн\w+|свеж\w+)\s+'
                       r'(?P<what>сделк\w*|лид\w*|заявк\w*)(?:\s+за\s+(?P<period>сегодня|вчера|недел\w+|месяц))?', re.I)
CRM_ADD = re.compile(r'(?:добавь|создай|заведи|внеси)\s+(?:нового\s+|новый\s+)?(?:клиента|контакт|покупателя|лида)\s*[:,—-]?\s*'
                     r'(?P<rest>.+)', re.I)
PHONE = re.compile(r'(?:телефон\w*|номер\w*|тел\.?)?\s*(\+?\d[\d\s()-]{8,}\d)', re.I)
EMAIL = re.compile(r'(?:почта|email|имейл|емейл)?\s*([\w.+-]+@[\w-]+\.[\w.-]+)', re.I)


def contact_parts(rest):
    phone = PHONE.search(rest)
    mail = EMAIL.search(rest)
    name = rest
    for match in (phone, mail):
        if match:
            name = name.replace(match[0], ' ')
    name = re.sub(r'(?<![\w])(?:телефон\w*|номер\w*|почта|email|имейл|с|и)(?![\w])', ' ', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name).strip(' ,.:—-')
    digits = re.sub(r'[^\d+]', '', phone[1]) if phone else ''
    if digits.startswith('8') and len(digits) == 11:
        digits = '+7' + digits[1:]
    return {'name': ' '.join(capital(w) for w in name.split()), 'phone': digits, 'email': mail[1] if mail else ''}


class CrmSkill:
    """Нужно: crm_new(kind, since) → (total, [{'title', 'amount', 'currency'}]), crm_add_contact(name, phone, email)."""

    def handle_crm(self, text):
        raw = self.plain(text)
        low = raw.casefold().replace('ё', 'е')
        named = self.named(text, 'crm')
        match = CRM_DEALS.fullmatch(low)
        if match:
            kind = 'leads' if re.match(r'лид|заявк', match['what']) else 'deals'
            span = match['period'] or ''
            since = now() - timedelta(days=1 if span in ('сегодня', 'вчера') else 30 if span == 'месяц' else 7)
            total, items = self.crm_new(kind, since)
            what = 'сделок' if kind == 'deals' else 'заявок'
            label = {'сегодня': 'за сутки', 'вчера': 'за сутки', 'месяц': 'за месяц'}.get(span, 'за неделю')
            if not total:
                return f'Новых {what} {label} в {self.title} нет.'
            shown = '; '.join(d['title'] + (f' — {rub(d["amount"], d.get("currency") or "rub")}' if d.get('amount') else '')
                              for d in items[:5])
            return f'Новых {what} {label} в {self.title}: {total}. {shown}.'
        match = CRM_ADD.fullmatch(raw)
        if match and (named or 'клиент' in low or 'контакт' in low):
            parts = contact_parts(match['rest'])
            if not parts['name']:
                return 'Как зовут клиента? Например: «добавь клиента Иван Петров +7 999 123-45-67».'
            self.crm_add_contact(parts['name'], parts['phone'], parts['email'])
            extra = ', '.join(v for v in (parts['phone'], parts['email']) if v)
            return f'Добавил клиента «{parts["name"]}» в {self.title}' + (f' ({extra})' if extra else '') + '.'
        return None


# ---- разработка ----
DEV_MINE = re.compile(r'(?:мои|какие у меня|покажи(?:\s+мои)?|что у меня)\s+(?:открытые\s+|активные\s+)?(?:по\s+)?'
                      r'(?:задачи|задач|issues?|ишью|тикеты|таски|карточки)', re.I)
DEV_CREATE = re.compile(r'(?:создай|заведи|добавь|открой)\s+(?:новую\s+|новый\s+)?(?:задачу|issue|ишью|тикет|таск|баг)\s*'
                        r'(?:(?:в|для)\s+(?:проект\w*|команд\w*|репозитори\w*)\s+(?P<project>[^:,—]+?)\s*[:,—-]\s*)?[:,—-]?\s*'
                        r'(?P<title>.+)', re.I)
DEV_MR = re.compile(r'(?:мои\s+|какие у меня\s+|покажи(?:\s+мои)?\s+)?(?:открытые\s+)?(?:merge\s?request\w*|мерж\W?реквест\w*|'
                    r'м[её]рдж\W?реквест\w*|мр|пул\W?реквест\w*|pull\s?request\w*)', re.I)


class DevSkill:
    """Нужно: dev_mine() → [{'key', 'title', 'state'}], dev_create(project, title) → (key, url)."""

    def handle_dev(self, text):
        if not self.named(text, 'dev'):
            return None
        raw = self.plain(text)
        low = raw.casefold().replace('ё', 'е')
        if hasattr(self, 'dev_merge_requests') and DEV_MR.fullmatch(low):
            items = self.dev_merge_requests()
            if not items:
                return f'Открытых merge request в {self.title} нет.'
            return f'Открытых merge request: {len(items)}. ' + '; '.join(
                f'{i["key"]} {i["title"]}' for i in items[:6]) + '.'
        if DEV_MINE.fullmatch(low):
            items = self.dev_mine()
            if not items:
                return f'Открытых задач на вас в {self.title} нет.'
            return f'Ваши задачи в {self.title}: {len(items)}. ' + '; '.join(
                f'{i["key"]} {i["title"]}' + (f' ({i["state"]})' if i.get('state') else '') for i in items[:8]) + '.'
        match = DEV_CREATE.fullmatch(raw)
        if match:
            key, url = self.dev_create((match['project'] or '').strip(), capital(match['title'].strip(' «»"')))
            if url:
                self.hub.open(url)
            return f'Создал задачу {key} в {self.title}: {capital(match["title"].strip(" «»"))}.'
        return None


# ---------------- CalDAV (Яндекс Календарь) ----------------
DAV = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav'}


def ics_escape(text):
    return str(text).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def parse_ics(text, start, end):
    """VEVENT из iCalendar → [{'title', 'start'}] в пределах [start, end)."""
    lines = re.sub(r'\r?\n[ \t]', '', str(text)).splitlines()
    events, current = [], None
    for line in lines:
        if line == 'BEGIN:VEVENT':
            current = {}
        elif line == 'END:VEVENT' and current is not None:
            events.append(current)
            current = None
        elif current is not None and ':' in line:
            name, value = line.split(':', 1)
            key, _, params = name.partition(';')
            current.setdefault(key.upper(), (params, value))
    result = []
    for event in events:
        params, value = event.get('DTSTART', ('', ''))
        when = ics_time(params, value)
        if when is None:
            continue
        moment = when if isinstance(when, datetime) else local(when)
        if not (start <= moment < end):
            continue
        title = event.get('SUMMARY', ('', ''))[1].replace('\\,', ',').replace('\\;', ';').replace('\\n', ' ')
        result.append({'title': title, 'start': when})
    return result


def ics_time(params, value):
    value = value.strip()
    try:
        if 'VALUE=DATE' in params.upper() and len(value) == 8:
            return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        moment = datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S')
    except ValueError:
        return None
    if value.endswith('Z'):
        return moment.replace(tzinfo=timezone.utc).astimezone()
    zone = re.search(r'TZID=([^;:]+)', params)
    if zone:
        try:
            from zoneinfo import ZoneInfo
            return moment.replace(tzinfo=ZoneInfo(zone[1])).astimezone()
        except Exception:
            pass
    return moment.astimezone()


class CalDav:
    def __init__(self, connector, base):
        self.connector = connector
        self.base = base.rstrip('/')

    def _dav(self, method, url, body, depth='0'):
        response = self.connector.request(method, url if url.startswith('http') else self.base + url, raw=True,
                                          data=body.encode('utf-8'),
                                          headers={'Depth': depth, 'Content-Type': 'application/xml; charset=utf-8'})
        try:
            return ET.fromstring(response.content)
        except ET.ParseError:
            raise ConnectorError(f'{self.connector.title}: календарь ответил непонятно.')

    def _href(self, url, prop):
        body = (f'<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                f'<d:prop><{prop}/></d:prop></d:propfind>')
        tree = self._dav('PROPFIND', url, body)
        found = tree.find(f'.//{{{DAV["d" if prop.startswith("d:") else "c"]}}}{prop.split(":")[1]}/{{DAV:}}href')
        return found.text if found is not None else None

    def calendar_url(self):
        saved = self.connector.saved()
        if saved.get('caldav'):
            return saved['caldav']
        principal = self._href('/', 'd:current-user-principal') or '/'
        home = self._href(principal, 'c:calendar-home-set')
        if not home:
            raise ConnectorError(f'{self.connector.title}: не нашёл календарь в аккаунте.')
        body = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                '<d:prop><d:resourcetype/><d:displayname/><c:supported-calendar-component-set/></d:prop></d:propfind>')
        tree = self._dav('PROPFIND', home, body, depth='1')
        url = None
        for response in tree.findall('{DAV:}response'):
            if response.find('.//{urn:ietf:params:xml:ns:caldav}calendar') is None:
                continue
            comps = [c.get('name') for c in response.findall('.//{urn:ietf:params:xml:ns:caldav}comp')]
            if comps and 'VEVENT' not in comps:
                continue
            url = response.findtext('{DAV:}href')
            break
        if not url:
            raise ConnectorError(f'{self.connector.title}: в аккаунте нет календаря событий.')
        saved['caldav'] = url
        self.connector.save(saved)
        return url

    def events(self, start, end):
        a, b = iso_utc(start).replace('-', '').replace(':', ''), iso_utc(end).replace('-', '').replace(':', '')
        body = ('<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                f'<d:prop><c:calendar-data><c:expand start="{a}" end="{b}"/></c:calendar-data></d:prop>'
                '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
                f'<c:time-range start="{a}" end="{b}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
        tree = self._dav('REPORT', self.calendar_url(), body, depth='1')
        result = []
        for data in tree.iter('{urn:ietf:params:xml:ns:caldav}calendar-data'):
            result.extend(parse_ics(data.text or '', start, end))
        return result

    def create(self, title, start, end, all_day):
        uid = str(uuid.uuid4())
        if all_day:
            span = f'DTSTART;VALUE=DATE:{start:%Y%m%d}\r\nDTEND;VALUE=DATE:{end:%Y%m%d}'
        else:
            span = (f'DTSTART:{start.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}\r\n'
                    f'DTEND:{end.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}')
        body = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Andrey//RU\r\nBEGIN:VEVENT\r\n'
                f'UID:{uid}\r\nDTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}\r\n{span}\r\n'
                f'SUMMARY:{ics_escape(title)}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
        url = self.calendar_url().rstrip('/') + f'/{uid}.ics'
        self.connector.request('PUT', url if url.startswith('http') else self.base + url, raw=True,
                               data=body.encode('utf-8'),
                               headers={'Content-Type': 'text/calendar; charset=utf-8', 'If-None-Match': '*'})


# =====================================================================
#                              ПРИЛОЖЕНИЯ
# =====================================================================
def field(name, label, kind='text', placeholder='', optional=False):
    return {'name': name, 'label': label, 'type': kind, 'placeholder': placeholder, 'optional': optional}


class KeyConnector(Connector):
    """Вход по ключу из настроек сервиса: проверяем ключ запросом «кто я» и сохраняем."""
    auth = 'token'

    def whoami_with(self, values):
        raise NotImplementedError

    def use_fields(self, values):
        values = {k: str(v).strip() for k, v in (values or {}).items()}
        missing = [f['label'] for f in self.form() if not f.get('optional') and not values.get(f['name'])]
        if missing:
            raise ConnectorError('Заполните: ' + ', '.join(missing) + '.')
        saved = self.prepare(values)
        self.save(saved)
        try:
            user = self.whoami_with(saved)
        except ConnectorError as exc:
            self.save(None)
            raise ConnectorError(f'{self.title} не принял ключ: {exc}')
        saved['user'] = user or self.title
        self.save(saved)
        return saved['user']

    def prepare(self, values):
        return {'access_token': values.get('token', '')}

    def use_token(self, token):
        return self.use_fields({'token': token})


# ---------------- Google Календарь и Gmail ----------------
class GoogleCalendarConnector(Skills, CalendarSkill, GoogleConnector):
    id, title, icon = 'google_calendar', 'Google Календарь', '📅'
    description = 'События на сегодня, завтра и неделю; новые встречи голосом.'
    examples = ('Что у меня сегодня в календаре?', 'Создай встречу на завтра в 15:00', 'Какие встречи на этой неделе?')
    needs = ('https://www.googleapis.com/auth/calendar.events',)
    names = r'гугл\W?календар\w*|google\W?календар\w*|google calendar|календар\w* (?:гугл|google)'
    calendar_title = 'Google Календаре'
    skills = ('calendar',)
    API = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'

    def calendar_events(self, start, end):
        data = self.request('GET', self.API, params={'timeMin': start.isoformat(), 'timeMax': end.isoformat(),
                                                     'singleEvents': 'true', 'orderBy': 'startTime', 'maxResults': 25})
        result = []
        for item in data.get('items') or []:
            when = item.get('start') or {}
            result.append({'title': item.get('summary', ''), 'start': from_iso(when.get('dateTime') or when.get('date'))})
        return result

    def calendar_create(self, title, start, end, all_day):
        span = ({'start': {'date': start.isoformat()}, 'end': {'date': end.isoformat()}} if all_day else
                {'start': {'dateTime': start.isoformat()}, 'end': {'dateTime': end.isoformat()}})
        self.request('POST', self.API, json=dict(summary=title, **span))


class GmailConnector(Skills, MailSkill, GoogleConnector):
    id, title, icon = 'gmail', 'Gmail', '✉️'
    description = 'Сколько новых писем, от кого они и поиск по почте.'
    examples = ('Прочитай новые письма', 'Сколько новых писем?', 'Найди письмо от Ивана')
    needs = ('https://www.googleapis.com/auth/gmail.readonly',)
    names = r'gmail|гмейл\w*|джимейл\w*|гугл\W?почт\w*'
    mail_title = 'Gmail'
    skills = ('mail',)
    API = 'https://gmail.googleapis.com/gmail/v1/users/me'

    def _messages(self, query, limit):
        data = self.request('GET', self.API + '/messages', params={'q': query, 'maxResults': limit})
        result = []
        for item in (data.get('messages') or [])[:limit]:
            message = self.request('GET', f"{self.API}/messages/{item['id']}",
                                   params=[('format', 'metadata'), ('metadataHeaders', 'From'), ('metadataHeaders', 'Subject')])
            headers = {h['name'].casefold(): h['value'] for h in (message.get('payload') or {}).get('headers', [])}
            result.append({'from': sender(headers.get('from')), 'subject': headers.get('subject', '')})
        return result

    def mail_unread(self, limit):
        count = self.request('GET', self.API + '/labels/INBOX').get('messagesUnread', 0)
        return count, self._messages('is:unread in:inbox', limit) if limit and count else []

    def mail_search(self, query, how, limit):
        q = {'from': f'from:({query})', 'subject': f'subject:({query})'}.get(how, query)
        return self._messages(q, limit)


# ---------------- Яндекс: Диск, Календарь, Почта ----------------
class YandexConnector(Skills, CalendarSkill, MailSkill, FilesSkill, OAuthConnector):
    id, title, icon = 'yandex', 'Яндекс: Диск, Календарь, Почта', '🟠'
    group = 'Яндекс'
    description = 'Один вход в Яндекс ID: файлы на Диске, события Календаря и новые письма.'
    examples = ('Загрузи этот файл на Яндекс Диск', 'Дела на завтра в Яндекс Календаре', 'Сколько новых писем в Яндекс Почте?')
    authorize_url = 'https://oauth.yandex.ru/authorize'
    token_url = 'https://oauth.yandex.ru/token'
    client_id = cfg.YANDEX_CLIENT_ID
    client_secret = cfg.YANDEX_CLIENT_SECRET
    extra = {'force_confirm': 'yes'}
    auth_scheme = 'OAuth'
    calendar_names = r'яндекс\W?календар\w*|календар\w* яндекс\w*'
    mail_names = r'яндекс\W?почт\w*|почт\w* яндекс\w*'
    files_names = r'яндекс\W?диск\w*|диск\w* яндекс\w*'
    names = calendar_names + '|' + mail_names + '|' + files_names
    calendar_title = 'Яндекс Календаре'
    mail_title = 'Яндекс Почте'
    files_title = 'Яндекс Диск'
    skills = ('calendar', 'mail', 'files')
    DISK = 'https://cloud-api.yandex.net/v1/disk'

    def whoami(self, tokens):
        try:
            info = self.hub.http.get('https://login.yandex.ru/info', params={'format': 'json'}, timeout=TIMEOUT,
                                     headers={'Authorization': 'OAuth ' + tokens['access_token']}).json()
        except Exception:
            return ''
        tokens['email'] = info.get('default_email') or (info.get('login', '') + '@yandex.ru' if info.get('login') else '')
        return tokens['email'] or info.get('login', '')

    # календарь (CalDAV)
    def calendar_events(self, start, end):
        return CalDav(self, 'https://caldav.yandex.ru').events(start, end)

    def calendar_create(self, title, start, end, all_day):
        CalDav(self, 'https://caldav.yandex.ru').create(title, start, end, all_day)

    # почта (IMAP с токеном)
    def _imap(self):
        saved = self.saved()
        return Imap('imap.yandex.ru', saved.get('email') or saved.get('user', ''), oauth=self.token())

    def mail_unread(self, limit):
        with self._imap() as box:
            return box.unread(limit)

    def mail_search(self, query, how, limit):
        with self._imap() as box:
            return box.search(query, how, limit)

    # диск
    def files_upload(self, path):
        try:
            self.request('PUT', self.DISK + '/resources', params={'path': f'disk:/{APP_FOLDER}'})
        except ConnectorError as exc:
            if '409' not in str(exc):
                raise
        name = path.name
        for attempt in range(3):
            try:
                link = self.request('GET', self.DISK + '/resources/upload',
                                    params={'path': f'disk:/{APP_FOLDER}/{name}', 'overwrite': 'false'})
                break
            except ConnectorError as exc:
                if '409' not in str(exc) or attempt == 2:
                    raise
                name = f'{path.stem} ({now():%Y-%m-%d %H-%M-%S}){path.suffix}'
        with open(path, 'rb') as fh:
            response = self.hub.http.put(link['href'], data=fh, timeout=UPLOAD_TIMEOUT)
        if response.status_code >= 400:
            raise ConnectorError(f'Яндекс Диск не принял файл (ошибка {response.status_code}).')
        return ''

    def files_find(self, query):
        data = self.request('GET', self.DISK + '/resources/files',
                            params={'limit': 1000, 'fields': 'items.name,items.path', 'sort': '-modified'})
        found = [i for i in data.get('items') or [] if similar(query, i.get('name', ''))]
        return [{'name': i['name'], 'path': i['path'].replace('disk:', ''),
                 'url': 'https://disk.yandex.ru/client/disk' + quote(str(Path(i['path'].replace('disk:', '')).parent))}
                for i in found[:5]]

    def files_space(self):
        data = self.request('GET', self.DISK)
        return data.get('used_space', 0), data.get('total_space', 0)


# ---------------- любая почта по IMAP ----------------
class ImapConnector(Skills, MailSkill, KeyConnector):
    id, title, icon = 'imap', 'Почта (Mail.ru, Яндекс, Gmail, Rambler…)', '📬'
    group = 'Почта и календарь'
    description = 'Любой ящик по IMAP с паролем приложения: сводка входящих и поиск письма.'
    examples = ('Что нового в почте?', 'Краткая сводка входящих', 'Найди письмо про счёт')
    token_hint = ('Нужен ПАРОЛЬ ПРИЛОЖЕНИЯ, не обычный. Mail.ru: Настройки → Безопасность → Пароли для внешних '
                  'приложений. Яндекс: id.yandex.ru → Безопасность → Пароли приложений → Почта. Gmail: '
                  'myaccount.google.com/apppasswords (нужна двухэтапная проверка). Outlook.com IMAP с паролем больше '
                  'не пускает — подключите «Microsoft 365».')
    fields = (field('email', 'Адрес почты', 'email', 'name@mail.ru'),
              field('password', 'Пароль приложения', 'password'),
              field('server', 'IMAP-сервер', 'text', 'определится сам', optional=True))
    names = r'mail\.?ru|м[эе]йл\W?ру'
    mail_title = 'почте'
    skills = ('mail',)

    def prepare(self, values):
        return {'access_token': 'imap', 'email': values['email'], 'password': values['password'],
                'host': values.get('server') or Imap.host_for(values['email'])}

    def whoami_with(self, saved):
        with self._box(saved):
            return saved['email']

    def _box(self, saved=None):
        saved = saved or self.saved()
        if not saved.get('password'):
            raise ConnectorError('Почта не подключена: Настройки → «Интеграции» → «Почта».')
        return Imap(saved['host'], saved['email'], saved['password'])

    def mail_unread(self, limit):
        with self._box() as box:
            return box.unread(limit)

    def mail_search(self, query, how, limit):
        with self._box() as box:
            return box.search(query, how, limit)


# ---------------- Notion ----------------
class NotionConnector(Skills, TasksSkill, OAuthConnector):
    id, title, icon = 'notion', 'Notion', '📓'
    group = 'Заметки и задачи'
    description = 'Задачи и заметки в вашей базе Notion (например, «Задачи» или «To Do»).'
    examples = ('Добавь в Notion задачу подготовить отчёт', 'Что в моём списке дел в Notion?', 'Запиши в Notion заметку: идея для поста')
    authorize_url = 'https://api.notion.com/v1/oauth/authorize'
    token_url = 'https://api.notion.com/v1/oauth/token'
    client_id = cfg.NOTION_CLIENT_ID
    client_secret = cfg.NOTION_CLIENT_SECRET
    extra = {'owner': 'user'}
    token_hint = ('notion.so/profile/integrations → «Новая интеграция» (внутренняя) → скопируйте «Internal Integration '
                  'Secret». Затем откройте базу задач → ••• → «Подключения» → добавьте эту интеграцию.')
    names = r'ноушн\w*|notion|нотион\w*'
    tasks_title = 'Notion'
    tasks_generic = True
    skills = ('tasks',)
    API = 'https://api.notion.com/v1'
    DONE = ('done', 'готово', 'выполнено', 'сделано', 'завершено', 'complete', 'completed')

    def auth_headers(self):
        return {'Authorization': 'Bearer ' + self.token(), 'Notion-Version': '2022-06-28'}

    def _token_request(self, data):
        # Notion принимает код в JSON и ключ приложения через Basic.
        basic = base64.b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()
        try:
            response = self.hub.http.post(self.token_url, timeout=TIMEOUT, headers={'Authorization': 'Basic ' + basic},
                                          json={k: v for k, v in data.items() if k in ('grant_type', 'code', 'redirect_uri',
                                                                                       'refresh_token')})
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise ConnectorError('Notion не выдал доступ. Попробуйте ещё раз.')
        if not payload.get('access_token'):
            raise ConnectorError(f"Notion: {payload.get('error_description') or payload.get('error') or 'вход отклонён'}")
        return payload

    def whoami(self, tokens):
        owner = (tokens.get('owner') or {}).get('user') or {}
        return owner.get('name') or tokens.get('workspace_name') or 'Notion'

    def use_token(self, token):
        self.save({'access_token': token.strip()})
        try:
            me = self.request('GET', self.API + '/users/me')
        except ConnectorError:
            self.save(None)
            raise ConnectorError('Notion не принял ключ интеграции.')
        self.save({'access_token': token.strip(), 'user': (me.get('bot') or {}).get('workspace_name') or me.get('name') or 'Notion'})
        return self.saved()['user']

    def database(self):
        saved = self.saved()
        if saved.get('database'):
            return saved['database']
        data = self.request('POST', self.API + '/search',
                            json={'filter': {'property': 'object', 'value': 'database'}, 'page_size': 50})
        bases = data.get('results') or []
        if not bases:
            raise ConnectorError('В Notion не видно ни одной базы. Откройте базу задач → ••• → «Подключения» → '
                                 'добавьте интеграцию «Андрей».')
        title = lambda b: ''.join(t.get('plain_text', '') for t in b.get('title') or [])  # noqa: E731
        best = next((b for b in bases if re.search(r'задач|дел|todo|to-do|to do|tasks', title(b), re.I)), bases[0])
        props = best.get('properties') or {}
        saved['database'] = {
            'id': best['id'], 'name': title(best),
            'title': next((k for k, v in props.items() if v.get('type') == 'title'), 'Name'),
            'check': next((k for k, v in props.items() if v.get('type') == 'checkbox'), ''),
            'status': next((k for k, v in props.items() if v.get('type') == 'status'), ''),
            'date': next((k for k, v in props.items() if v.get('type') == 'date'), '')}
        self.save(saved)
        return saved['database']

    def tasks_list(self, day):
        base = self.database()
        body = {'page_size': 30}
        if base['check']:
            body['filter'] = {'property': base['check'], 'checkbox': {'equals': False}}
        pages = self.request('POST', f"{self.API}/databases/{base['id']}/query", json=body).get('results') or []
        result = []
        for page in pages:
            props = page.get('properties') or {}
            status = ((props.get(base['status']) or {}).get('status') or {}).get('name', '') if base['status'] else ''
            if status.casefold() in self.DONE:
                continue
            due = ((props.get(base['date']) or {}).get('date') or {}).get('start') if base['date'] else None
            due = from_iso(due[:10]) if due else None
            if day and due != day:
                continue
            text = ''.join(t.get('plain_text', '') for t in (props.get(base['title']) or {}).get('title', []))
            result.append({'title': text or 'без названия', 'due': due})
        return result

    def tasks_add(self, title, day, start):
        base = self.database()
        props = {base['title']: {'title': [{'text': {'content': title}}]}}
        if day and base['date']:
            props[base['date']] = {'date': {'start': start.isoformat() if start else day.isoformat()}}
        self.request('POST', self.API + '/pages', json={'parent': {'database_id': base['id']}, 'properties': props})


# ---------------- Todoist ----------------
class TodoistConnector(Skills, TasksSkill, KeyConnector):
    id, title, icon = 'todoist', 'Todoist', '☑️'
    group = 'Заметки и задачи'
    description = 'Задачи на сегодня и завтра, новые задачи со сроком, отметка о выполнении.'
    examples = ('Что у меня в Todoist на сегодня?', 'Добавь в Todoist задачу позвонить маме завтра в 18:00',
                'Отметь задачу позвонить маме')
    token_hint = 'todoist.com → Настройки → Интеграции → Для разработчиков → «Токен API» → скопируйте.'
    fields = (field('token', 'Токен API', 'password'),)
    names = r'тудуист\w*|todoist|тодоист\w*'
    skills = ('tasks',)
    API = 'https://api.todoist.com/api/v1'

    def whoami_with(self, saved):
        me = self.request('GET', self.API + '/user')
        return me.get('full_name') or me.get('email') or 'Todoist'

    def _tasks(self, query):
        data = self.request('GET', self.API + '/tasks/filter', params={'query': query, 'limit': 50})
        return data.get('results') if isinstance(data, dict) else data or []

    def tasks_list(self, day):
        query = 'today | overdue' if day is None or day == now().date() else day.strftime('%Y-%m-%d')
        return [{'title': t.get('content', ''), 'due': from_iso(t['due']['date'][:10]) if t.get('due') else None}
                for t in self._tasks(query) or []]

    def tasks_add(self, title, day, start):
        body = {'content': title}
        if start:
            body['due_datetime'] = iso_utc(start)
        elif day:
            body['due_date'] = day.isoformat()
        self.request('POST', self.API + '/tasks', json=body)

    def tasks_done(self, title):
        task = next((t for t in self._tasks('all') or [] if similar(title, t.get('content', ''))), None)
        if task is None:
            return None
        self.request('POST', f"{self.API}/tasks/{task['id']}/close")
        return task['content']


# ---------------- YouGile ----------------
class YouGileConnector(Skills, TasksSkill, KeyConnector):
    id, title, icon = 'yougile', 'YouGile', '🟩'
    group = 'Заметки и задачи'
    description = 'Задачи на досках YouGile: список и новые задачи в первую колонку.'
    examples = ('Какие задачи в YouGile?', 'Добавь в YouGile задачу обновить прайс')
    token_hint = ('Введите логин и пароль YouGile один раз — программа создаст ключ API и сохранит только его '
                  '(пароль не сохраняется). Если компаний несколько — впишите название нужной.')
    fields = (field('login', 'Логин (почта)', 'email'), field('password', 'Пароль', 'password'),
              field('company', 'Компания', 'text', 'если их несколько', optional=True))
    names = r'ю\W?гайл\w*|yougile|югил\w*'
    skills = ('tasks',)
    API = 'https://ru.yougile.com/api-v2'

    def prepare(self, values):
        http = self.hub.http
        auth = {'login': values['login'], 'password': values['password']}
        try:
            companies = http.post(self.API + '/auth/companies', json=auth, timeout=TIMEOUT).json().get('content') or []
        except (requests.RequestException, ValueError, AttributeError):
            raise ConnectorError('YouGile не отвечает.')
        if not companies:
            raise ConnectorError('YouGile: неверный логин или пароль.')
        wanted = values.get('company', '').casefold()
        company = next((c for c in companies if wanted and wanted in c.get('name', '').casefold()), companies[0])
        try:
            key = http.post(self.API + '/auth/keys', json=dict(auth, companyId=company['id']), timeout=TIMEOUT).json().get('key')
        except (requests.RequestException, ValueError, AttributeError):
            key = None
        if not key:
            raise ConnectorError('YouGile не выдал ключ API.')
        return {'access_token': key, 'company': company.get('name', '')}

    def whoami_with(self, saved):
        self.request('GET', self.API + '/columns', params={'limit': 1})
        return saved.get('company') or 'YouGile'

    def tasks_list(self, day):
        data = self.request('GET', self.API + '/task-list', params={'limit': 50})
        result = []
        for task in data.get('content') or []:
            if task.get('completed') or task.get('archived') or task.get('deleted'):
                continue
            deadline = (task.get('deadline') or {}).get('deadline')
            due = datetime.fromtimestamp(deadline / 1000).date() if deadline else None
            if day and due != day:
                continue
            result.append({'title': task.get('title', ''), 'due': due})
        return result

    def tasks_add(self, title, day, start):
        columns = self.request('GET', self.API + '/columns', params={'limit': 1}).get('content') or []
        if not columns:
            raise ConnectorError('В YouGile нет ни одной колонки — создайте доску.')
        body = {'title': title, 'columnId': columns[0]['id']}
        if day:
            moment = start or local(day)
            body['deadline'] = {'deadline': int(moment.timestamp() * 1000), 'withTime': bool(start)}
        self.request('POST', self.API + '/tasks', json=body)


# ---------------- Kaiten ----------------
class KaitenConnector(Skills, TasksSkill, KeyConnector):
    id, title, icon = 'kaiten', 'Kaiten', '🟦'
    group = 'Заметки и задачи'
    description = 'Карточки Kaiten: ваши активные карточки и новые на первой доске.'
    examples = ('Мои задачи в Kaiten', 'Добавь в Kaiten задачу согласовать макет')
    token_hint = 'Kaiten → аватар → «Профиль» → «API/Интеграции» → создайте ключ. Адрес — как в браузере: company.kaiten.ru.'
    fields = (field('domain', 'Адрес Kaiten', 'text', 'company.kaiten.ru'), field('token', 'Ключ API', 'password'))
    names = r'кайт[еэ]н\w*|kaiten'
    tasks_generic = True
    skills = ('tasks',)

    def prepare(self, values):
        domain = urlparse(values['domain'] if '//' in values['domain'] else '//' + values['domain']).hostname or ''
        if not domain:
            raise ConnectorError('Укажите адрес вида company.kaiten.ru.')
        return {'access_token': values['token'], 'domain': domain}

    @property
    def api(self):
        return f"https://{self.saved().get('domain', '')}/api/latest"

    def whoami_with(self, saved):
        me = self.request('GET', self.api + '/users/current')
        saved['uid'] = me.get('id')
        return me.get('full_name') or me.get('username') or 'Kaiten'

    def tasks_list(self, day):
        params = {'states': '1,2', 'condition': 1, 'limit': 50}
        uid = self.saved().get('uid')
        if uid:
            params['member_ids'] = uid
        cards = self.request('GET', self.api + '/cards', params=params)
        result = []
        for card in cards if isinstance(cards, list) else []:
            due = from_iso(card['due_date'][:10]) if card.get('due_date') else None
            if day and due != day:
                continue
            result.append({'title': card.get('title', ''), 'due': due})
        return result

    def tasks_add(self, title, day, start):
        saved = self.saved()
        if not saved.get('board'):
            spaces = self.request('GET', self.api + '/spaces')
            for space in spaces if isinstance(spaces, list) else []:
                boards = self.request('GET', f"{self.api}/spaces/{space['id']}/boards")
                if isinstance(boards, list) and boards:
                    saved['board'] = boards[0]['id']
                    break
            if not saved.get('board'):
                raise ConnectorError('В Kaiten нет ни одной доски.')
            self.save(saved)
        body = {'title': title, 'board_id': saved['board']}
        if day:
            body['due_date'] = (start or local(day)).isoformat()
        self.request('POST', self.api + '/cards', json=body)


# ---------------- Weeek ----------------
class WeeekConnector(Skills, TasksSkill, KeyConnector):
    id, title, icon = 'weeek', 'Weeek', '🟪'
    group = 'Заметки и задачи'
    description = 'Задачи Weeek на день и новые задачи со сроком.'
    examples = ('Что в Weeek на сегодня?', 'Добавь в Weeek задачу оплатить хостинг на пятницу')
    token_hint = 'Weeek → Настройки рабочего пространства → API → «Создать токен».'
    fields = (field('token', 'Токен API', 'password'),)
    names = r'вик\b|weeek|виик\w*'
    skills = ('tasks',)
    API = 'https://api.weeek.net/public/v1'

    def whoami_with(self, saved):
        me = self.request('GET', self.API + '/user/me').get('user') or {}
        return ' '.join(filter(None, (me.get('firstName'), me.get('lastName')))) or me.get('email') or 'Weeek'

    def tasks_list(self, day):
        day = day or now().date()
        data = self.request('GET', self.API + '/tm/tasks', params={'day': day.strftime('%d.%m.%Y'), 'completed': 'false'})
        return [{'title': t.get('title', ''), 'due': day} for t in data.get('tasks') or [] if not t.get('isCompleted')]

    def tasks_add(self, title, day, start):
        body = {'title': title, 'type': 'action'}
        if day:
            body['day'] = day.strftime('%d.%m.%Y')
        if start:
            body['startTime'] = hhmm(start)
        self.request('POST', self.API + '/tm/tasks', json=body)


# ---------------- Т-Инвестиции ----------------
INVEST_WORD = r'(?:портфел\w*|акци\w*|инвестици\w*|брокерск\w*|бумаг\w*|облигаци\w*)'


class TInvestConnector(KeyConnector):
    id, title, icon = 'tinvest', 'Т-Инвестиции', '📈'
    group = 'Финансы'
    description = 'Стоимость портфеля, доходность и изменение бумаг за день (только чтение).'
    examples = ('Сколько стоит мой портфель?', 'Как изменились акции за день?', 'Что с моими инвестициями?')
    token_hint = ('Приложение Т-Банка → Инвестиции → ⚙ Настройки → «Токены T-Invest API» → «Создать токен» → '
                  'выберите «Только для чтения». Токен с правом торговли вводить не нужно.')
    fields = (field('token', 'Токен T-Invest API (только чтение)', 'password', 't.xxxx'),)
    names = r'т[\W-]?инвестици\w*|тинькофф\W?инвестици\w*|т\W?банк\w* инвестици\w*|tinkoff invest\w*|t-invest'
    API = 'https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1.'

    def call(self, method, body=None):
        return self.request('POST', self.API + method, json=body or {})

    def whoami_with(self, saved):
        accounts = self._accounts()
        return f'счетов: {len(accounts)}'

    def _accounts(self):
        items = self.call('UsersService/GetAccounts').get('accounts') or []
        return [a for a in items if a.get('status') in (None, 'ACCOUNT_STATUS_OPEN')]

    def _portfolios(self):
        return [(a, self.call('OperationsService/GetPortfolio', {'accountId': a['id'], 'currency': 'RUB'}))
                for a in self._accounts()]

    def _name(self, position):
        if position.get('ticker'):
            return position['ticker']
        uid = position.get('instrumentUid')
        try:
            data = self.call('InstrumentsService/GetInstrumentBy',
                             {'idType': 'INSTRUMENT_ID_TYPE_UID', 'id': uid} if uid else
                             {'idType': 'INSTRUMENT_ID_TYPE_FIGI', 'id': position.get('figi', '')})
            return (data.get('instrument') or {}).get('name') or position.get('figi', '?')
        except ConnectorError:
            return position.get('figi', '?')

    def handle(self, text):
        low = self.plain(text).casefold().replace('ё', 'е')
        named = self.mentioned(text)
        if not (re.search(INVEST_WORD, low) or named):
            return None
        daily = re.search(r'измен|за день|сегодня|вырос|упал|подешев|подорож|динамик|как (?:там|дела|себя)|что с', low)
        value = re.search(r'сколько|стоимост|стоит|сумм|баланс|мой портфель|мои инвестиции|доходност', low)
        if not (daily or value) or re.search(r'купи|продай|продать|купить|заявк', low):
            if re.search(r'купи|продай|продать|купить', low) and (named or re.search(INVEST_WORD, low)):
                return 'Покупать и продавать бумаги голосом я не буду — только показываю портфель. Сделки — в приложении Т-Инвестиций.'
            return None
        portfolios = self._portfolios()
        if not portfolios:
            return 'В Т-Инвестициях нет открытых счетов.'
        total = sum(money(p.get('totalAmountPortfolio')) for _, p in portfolios)
        if daily:
            change = sum(money(p.get('dailyYield')) for _, p in portfolios)
            percent = change / (total - change) * 100 if total - change else 0
            movers = []
            for _, portfolio in portfolios:
                for position in portfolio.get('positions') or []:
                    if position.get('instrumentType') == 'currency':
                        continue
                    movers.append((money(position.get('dailyYield')), position))
            movers.sort(key=lambda m: -abs(m[0]))
            parts = [f'{self._name(p)} {"+" if v >= 0 else "−"}{rub(abs(v))}' for v, p in movers[:3] if v]
            head = (f'За день портфель {"вырос" if change >= 0 else "снизился"} на {rub(abs(change))} '
                    f'({"+" if change >= 0 else "−"}{abs(percent):.2f}%), сейчас {rub(total)}.')
            return head + (' Больше всего изменились: ' + ', '.join(parts) + '.' if parts else '')
        profit = sum(money(p.get('expectedYield')) for _, p in portfolios) if len(portfolios) == 1 else None
        yield_text = f' Доходность за всё время: {money(portfolios[0][1].get("expectedYield")):+.2f}%.' if profit is not None else ''
        accounts = f' на {len(portfolios)} {plural(len(portfolios), "счёте", "счетах", "счетах")}' if len(portfolios) > 1 else ''
        return f'Портфель стоит {rub(total)}{accounts}.{yield_text}'


# ---------------- CRM: Битрикс24 и amoCRM ----------------
class Bitrix24Connector(Skills, CrmSkill, KeyConnector):
    id, title, icon = 'bitrix24', 'Битрикс24', '🔷'
    group = 'CRM'
    description = 'Новые сделки и заявки, добавление клиентов в CRM.'
    examples = ('Новые сделки', 'Новые лиды за сегодня', 'Добавь клиента Иван Петров +7 999 123-45-67')
    token_hint = ('Битрикс24 → Разработчикам → Другое → «Входящий вебхук» → права «CRM» и «Пользователи» → '
                  'скопируйте адрес вида https://ваша-компания.bitrix24.ru/rest/1/abc123…/')
    fields = (field('webhook', 'Адрес входящего вебхука', 'password', 'https://…bitrix24.ru/rest/1/…/'),)
    names = r'битрикс\w*|bitrix\w*'
    skills = ('crm',)

    def prepare(self, values):
        url = values['webhook'].strip()
        if not re.match(r'^https://[\w.-]+/rest/\d+/[\w]+/?', url):
            raise ConnectorError('Нужен адрес вебхука вида https://ваша-компания.bitrix24.ru/rest/1/код/')
        return {'access_token': url.rstrip('/') + '/'}

    def auth_headers(self):
        return {}

    def call(self, method, params=None):
        return self.request('POST', self.token() + method + '.json', json=params or {})

    def whoami_with(self, saved):
        me = self.call('profile').get('result') or {}
        return ' '.join(filter(None, (me.get('NAME'), me.get('LAST_NAME')))) or 'Битрикс24'

    def crm_new(self, kind, since):
        method = 'crm.deal.list' if kind == 'deals' else 'crm.lead.list'
        data = self.call(method, {'order': {'DATE_CREATE': 'DESC'}, 'filter': {'>=DATE_CREATE': since.isoformat()},
                                  'select': ['ID', 'TITLE', 'OPPORTUNITY', 'CURRENCY_ID']})
        items = [{'title': d.get('TITLE') or f"№{d.get('ID')}", 'amount': float(d.get('OPPORTUNITY') or 0),
                  'currency': d.get('CURRENCY_ID') or 'rub'} for d in data.get('result') or []]
        return data.get('total', len(items)), items

    def crm_add_contact(self, name, phone, mail):
        first, _, last = name.partition(' ')
        fields = {'NAME': first, 'LAST_NAME': last, 'OPENED': 'Y'}
        if phone:
            fields['PHONE'] = [{'VALUE': phone, 'VALUE_TYPE': 'WORK'}]
        if mail:
            fields['EMAIL'] = [{'VALUE': mail, 'VALUE_TYPE': 'WORK'}]
        self.call('crm.contact.add', {'fields': fields})


class AmoCrmConnector(Skills, CrmSkill, KeyConnector):
    id, title, icon = 'amocrm', 'amoCRM', '🔵'
    group = 'CRM'
    description = 'Новые сделки и добавление контактов.'
    examples = ('Новые сделки в амо', 'Добавь клиента Анна Смирнова anna@mail.ru')
    token_hint = ('amoCRM → amoМаркет → ⋯ → «Создать интеграцию» (внешняя) → вкладка «Ключи и доступы» → '
                  '«Долгосрочный токен» → создайте и скопируйте. Адрес — как в браузере: company.amocrm.ru.')
    fields = (field('domain', 'Адрес amoCRM', 'text', 'company.amocrm.ru'),
              field('token', 'Долгосрочный токен', 'password'))
    names = r'амо\W?(?:crm|срм|црм)|amo\W?crm|амо(?![\w])|amo(?![\w])|коммо|kommo'
    skills = ('crm',)

    def prepare(self, values):
        domain = urlparse(values['domain'] if '//' in values['domain'] else '//' + values['domain']).hostname or ''
        if '.' not in domain:
            domain = domain + '.amocrm.ru'
        return {'access_token': values['token'], 'domain': domain}

    @property
    def api(self):
        return f"https://{self.saved().get('domain', '')}/api/v4"

    def whoami_with(self, saved):
        return self.request('GET', self.api + '/account').get('name') or 'amoCRM'

    def crm_new(self, kind, since):
        data = self.request('GET', self.api + '/leads', params={'order[created_at]': 'desc', 'limit': 50,
                                                               'filter[created_at][from]': int(since.timestamp())})
        leads = (data.get('_embedded') or {}).get('leads') or []
        return len(leads), [{'title': d.get('name') or f"№{d.get('id')}", 'amount': float(d.get('price') or 0)} for d in leads]

    def crm_add_contact(self, name, phone, mail):
        fields = []
        if phone:
            fields.append({'field_code': 'PHONE', 'values': [{'value': phone, 'enum_code': 'WORK'}]})
        if mail:
            fields.append({'field_code': 'EMAIL', 'values': [{'value': mail, 'enum_code': 'WORK'}]})
        body = {'name': name}
        if fields:
            body['custom_fields_values'] = fields
        self.request('POST', self.api + '/contacts', json=[body])


# ---------------- Spotify ----------------
class SpotifyConnector(OAuthConnector):
    id, title, icon = 'spotify', 'Spotify', '🎧'
    group = 'Музыка'
    description = 'Ваши плейлисты, «что сейчас играет»; управление воспроизведением — с Premium.'
    examples = ('Включи мой плейлист для бега', 'Что сейчас играет?', 'Следующий трек в Spotify', 'Включи в Spotify Imagine Dragons')
    authorize_url = 'https://accounts.spotify.com/authorize'
    token_url = 'https://accounts.spotify.com/api/token'
    client_id = cfg.SPOTIFY_CLIENT_ID
    scope = ('user-read-playback-state user-modify-playback-state user-read-currently-playing '
             'playlist-read-private playlist-read-collaborative user-library-read')
    names = r'спотифа\w*|spotify|спотик\w*'
    API = 'https://api.spotify.com/v1'

    def whoami(self, tokens):
        try:
            me = self.hub.http.get(self.API + '/me', timeout=TIMEOUT,
                                   headers={'Authorization': 'Bearer ' + tokens['access_token']}).json()
            return me.get('display_name') or me.get('id', '')
        except Exception:
            return ''

    def failed(self, response):
        if response.status_code == 403 and '/me/player' in str(getattr(response, 'url', '')):
            raise ConnectorError('Управлять воспроизведением Spotify разрешает только с подпиской Premium. '
                                 'Без неё я могу открыть плейлист в приложении Spotify.')
        if response.status_code == 404 and '/me/player' in str(getattr(response, 'url', '')):
            raise ConnectorError('NO_DEVICE')

    def _play(self, body=None, uri=None):
        try:
            self.request('PUT', self.API + '/me/player/play', json=body or {})
            return True
        except ConnectorError as exc:
            if str(exc) != 'NO_DEVICE':
                raise
        devices = self.request('GET', self.API + '/me/player/devices').get('devices') or []
        if devices:
            self.request('PUT', self.API + '/me/player/play', params={'device_id': devices[0]['id']}, json=body or {})
            return True
        if uri:
            self.hub.open(uri)
        return False

    def _control(self, method, path):
        try:
            self.request(method, self.API + '/me/player/' + path)
        except ConnectorError as exc:
            if str(exc) == 'NO_DEVICE':
                raise ConnectorError('Spotify сейчас ничего не играет — откройте его на компьютере или телефоне.')
            raise

    def handle(self, text):
        raw = self.plain(text)
        low = raw.casefold().replace('ё', 'е')
        named = self.mentioned(text)
        if re.fullmatch(r'(?:что|какая песня|какой трек)\s*(?:сейчас|это)?\s*(?:играет|звучит|за (?:песня|трек|музыка)|'
                        r'поет|поют)?(?:\s+сейчас)?', low) and re.search(r'игра|звуч|песн|трек|музык|по[её]т', low):
            data = self.request('GET', self.API + '/me/player/currently-playing')
            item = (data or {}).get('item')
            if not item:
                return 'В Spotify сейчас ничего не играет.'
            artists = ', '.join(a['name'] for a in item.get('artists') or [])
            return f'Сейчас играет: {artists} — «{item.get("name", "")}».'
        match = re.fullmatch(r'(?:включи|поставь|запусти|играй)\s+(?:мой\s+|мне\s+)?плейлист\s*(?P<name>.*)', raw, re.I)
        if match:
            return self.play_playlist(match['name'].strip(' «»"'))
        if re.fullmatch(r'(?:включи|поставь|запусти)\s+(?:мои\s+)?(?:любим\w+|понравивш\w+|сохран[её]нн\w+)\s+'
                        r'(?:треки|песни|музыку)|(?:включи\s+)?мои лайки', low):
            me = self.request('GET', self.API + '/me')
            ok = self._play({'context_uri': f"spotify:user:{me.get('id')}:collection"}, 'spotify:collection:tracks')
            return 'Включаю ваши любимые треки в Spotify.' if ok else 'Открыл любимые треки в Spotify — нажмите «Play».'
        if not named:
            return None
        if re.fullmatch(r'(?:поставь на |на )?пауз\w*|останови\w*|стоп|выключи(?: музыку)?', low):
            self._control('PUT', 'pause')
            return 'Пауза.'
        if re.fullmatch(r'(?:следующ\w+|дальше|переключи|пропусти)(?:\s+(?:трек|песн\w+))?', low):
            self._control('POST', 'next')
            return 'Следующий трек.'
        if re.fullmatch(r'(?:предыдущ\w+|назад|верни)(?:\s+(?:трек|песн\w+))?', low):
            self._control('POST', 'previous')
            return 'Предыдущий трек.'
        if re.fullmatch(r'(?:продолжи|возобнови|играй|включи)(?:\s+музыку)?', low):
            self._play()
            return 'Продолжаю.'
        match = re.fullmatch(r'(?:включи|поставь|найди|сыграй)\s+(?:песню\s+|трек\s+|музыку\s+)?(?P<q>.+)', raw, re.I)
        if match:
            found = self.request('GET', self.API + '/search', params={'q': match['q'], 'type': 'track', 'limit': 1})
            tracks = (found.get('tracks') or {}).get('items') or []
            if not tracks:
                return f'В Spotify не нашёл «{match["q"]}».'
            track = tracks[0]
            name = f"{', '.join(a['name'] for a in track.get('artists') or [])} — «{track.get('name')}»"
            ok = self._play({'uris': [track['uri']]}, track['uri'])
            return f'Включаю {name}.' if ok else f'Открыл {name} в Spotify — нажмите «Play».'
        return None

    def play_playlist(self, name):
        items = self.request('GET', self.API + '/me/playlists', params={'limit': 50}).get('items') or []
        items = [p for p in items if p]
        if not items:
            return 'В Spotify у вас нет плейлистов.'
        chosen = next((p for p in items if name and similar(name, p.get('name', ''))), None) if name else items[0]
        if chosen is None:
            return f'Не нашёл плейлист «{name}». Есть: ' + ', '.join(p['name'] for p in items[:6]) + '.'
        ok = self._play({'context_uri': chosen['uri']}, chosen['uri'])
        return f'Включаю плейлист «{chosen["name"]}».' if ok else f'Открыл плейлист «{chosen["name"]}» в Spotify — нажмите «Play».'


# ---------------- Microsoft 365 ----------------
class MicrosoftConnector(Skills, CalendarSkill, MailSkill, TasksSkill, FilesSkill, OAuthConnector):
    id, title, icon = 'microsoft', 'Microsoft 365: Outlook, OneDrive, To Do', '🟦'
    group = 'Microsoft'
    description = 'Личный или рабочий аккаунт Microsoft: календарь и почта Outlook, задачи To Do, файлы OneDrive.'
    examples = ('Что у меня завтра в Outlook?', 'Сколько новых писем в Outlook?', 'Добавь в To Do задачу купить билеты',
                'Загрузи этот файл в OneDrive')
    authorize_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
    token_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    client_id = cfg.MS_CLIENT_ID
    scope = 'offline_access User.Read Calendars.ReadWrite Mail.Read Tasks.ReadWrite Files.ReadWrite'
    calendar_names = r'(?:outlook|аутлук\w*)\W?календар\w*|календар\w* (?:outlook|аутлук\w*)'
    mail_names = r'outlook|аутлук\w*'
    tasks_names = r'microsoft to\W?do|майкрософт ту\W?ду|to\W?do|ту\W?ду'
    files_names = r'onedrive|one drive|ван\W?драйв\w*|уан\W?драйв\w*'
    names = calendar_names + '|' + mail_names + '|' + tasks_names + '|' + files_names
    calendar_title = 'календаре Outlook'
    mail_title = 'Outlook'
    tasks_title = 'To Do'
    files_title = 'OneDrive'
    tasks_generic = True
    skills = ('calendar', 'mail', 'tasks', 'files')
    API = 'https://graph.microsoft.com/v1.0'

    def redirect_uri(self, base_url):
        # Microsoft разрешает http только для localhost.
        return super().redirect_uri(base_url.replace('://127.0.0.1', '://localhost'))

    def whoami(self, tokens):
        try:
            me = self.hub.http.get(self.API + '/me', timeout=TIMEOUT,
                                   headers={'Authorization': 'Bearer ' + tokens['access_token']}).json()
            return me.get('mail') or me.get('userPrincipalName') or me.get('displayName', '')
        except Exception:
            return ''

    # календарь
    def calendar_events(self, start, end):
        data = self.request('GET', self.API + '/me/calendarView', headers={'Prefer': 'outlook.timezone="UTC"'},
                            params={'startDateTime': iso_utc(start), 'endDateTime': iso_utc(end), '$top': 25,
                                    '$orderby': 'start/dateTime', '$select': 'subject,start,isAllDay'})
        result = []
        for item in data.get('value') or []:
            moment = from_iso((item.get('start') or {}).get('dateTime', '') + 'Z')
            result.append({'title': item.get('subject', ''), 'start': moment.date() if item.get('isAllDay') else moment})
        return result

    def calendar_create(self, title, start, end, all_day):
        if all_day:
            span = {'start': {'dateTime': f'{start}T00:00:00', 'timeZone': 'UTC'},
                    'end': {'dateTime': f'{end}T00:00:00', 'timeZone': 'UTC'}, 'isAllDay': True}
        else:
            span = {'start': {'dateTime': iso_utc(start)[:-1], 'timeZone': 'UTC'},
                    'end': {'dateTime': iso_utc(end)[:-1], 'timeZone': 'UTC'}}
        self.request('POST', self.API + '/me/events', json=dict(subject=title, **span))

    # почта
    @staticmethod
    def _mail(items):
        return [{'from': ((m.get('from') or {}).get('emailAddress') or {}).get('name') or
                         ((m.get('from') or {}).get('emailAddress') or {}).get('address', ''),
                 'subject': m.get('subject', '')} for m in items]

    def mail_unread(self, limit):
        count = self.request('GET', self.API + '/me/mailFolders/inbox', params={'$select': 'unreadItemCount'}).get('unreadItemCount', 0)
        if not limit or not count:
            return count, []
        data = self.request('GET', self.API + '/me/mailFolders/inbox/messages',
                            params={'$filter': 'isRead eq false', '$top': limit, '$select': 'from,subject'})
        return count, self._mail(data.get('value') or [])

    def mail_search(self, query, how, limit):
        term = {'from': f'from:{query}', 'subject': f'subject:{query}'}.get(how, query).replace('"', '')
        data = self.request('GET', self.API + '/me/messages', params={'$search': f'"{term}"', '$top': limit,
                                                                     '$select': 'from,subject'})
        return self._mail(data.get('value') or [])

    # To Do
    def _list(self):
        lists = self.request('GET', self.API + '/me/todo/lists').get('value') or []
        if not lists:
            raise ConnectorError('В To Do нет списков задач.')
        return next((l for l in lists if l.get('wellknownListName') == 'defaultList'), lists[0])['id']

    def _todo(self):
        data = self.request('GET', f'{self.API}/me/todo/lists/{self._list()}/tasks',
                            params={'$filter': "status ne 'completed'", '$top': 50})
        return data.get('value') or []

    def tasks_list(self, day):
        result = []
        for task in self._todo():
            due = (task.get('dueDateTime') or {}).get('dateTime')
            due = date.fromisoformat(due[:10]) if due else None
            if day and due != day:
                continue
            result.append({'title': task.get('title', ''), 'due': due})
        return result

    def tasks_add(self, title, day, start):
        body = {'title': title}
        if day:
            body['dueDateTime'] = {'dateTime': f'{day}T00:00:00', 'timeZone': 'UTC'}
        if start:
            body['reminderDateTime'] = {'dateTime': iso_utc(start)[:-1], 'timeZone': 'UTC'}
            body['isReminderOn'] = True
        self.request('POST', f'{self.API}/me/todo/lists/{self._list()}/tasks', json=body)

    def tasks_done(self, title):
        task = next((t for t in self._todo() if similar(title, t.get('title', ''))), None)
        if task is None:
            return None
        self.request('PATCH', f"{self.API}/me/todo/lists/{self._list()}/tasks/{task['id']}", json={'status': 'completed'})
        return task['title']

    # OneDrive
    def files_upload(self, path):
        target = quote(f'{APP_FOLDER}/{path.name}')
        size = path.stat().st_size
        if size <= 4 * 2 ** 20:
            with open(path, 'rb') as fh:
                self.request('PUT', f'{self.API}/me/drive/root:/{target}:/content', timeout=UPLOAD_TIMEOUT,
                             params={'@microsoft.graph.conflictBehavior': 'rename'}, data=fh.read())
            return ''
        session = self.request('POST', f'{self.API}/me/drive/root:/{target}:/createUploadSession',
                               json={'item': {'@microsoft.graph.conflictBehavior': 'rename'}})
        chunk = 320 * 1024 * 32
        with open(path, 'rb') as fh:
            offset = 0
            while offset < size:
                data = fh.read(chunk)
                response = self.hub.http.put(session['uploadUrl'], data=data, timeout=UPLOAD_TIMEOUT, headers={
                    'Content-Range': f'bytes {offset}-{offset + len(data) - 1}/{size}'})
                if response.status_code >= 400:
                    raise ConnectorError(f'OneDrive не принял файл (ошибка {response.status_code}).')
                offset += len(data)
        return ''

    def files_find(self, query):
        data = self.request('GET', f"{self.API}/me/drive/root/search(q='{quote(query.replace(chr(39), ''))}')",
                            params={'$top': 5, '$select': 'name,webUrl,parentReference'})
        return [{'name': i.get('name', ''), 'path': i.get('name', ''), 'url': i.get('webUrl', '')}
                for i in data.get('value') or []]

    def files_space(self):
        quota = self.request('GET', self.API + '/me/drive', params={'$select': 'quota'}).get('quota') or {}
        return quota.get('used', 0), quota.get('total', 0)


# ---------------- Dropbox ----------------
class DropboxConnector(Skills, FilesSkill, OAuthConnector):
    id, title, icon = 'dropbox', 'Dropbox', '📦'
    group = 'Файлы'
    description = 'Загрузка выделенного файла, поиск файлов и свободное место.'
    examples = ('Загрузи этот файл в Dropbox', 'Найди в Dropbox договор', 'Сколько места в Dropbox?')
    authorize_url = 'https://www.dropbox.com/oauth2/authorize'
    token_url = 'https://api.dropboxapi.com/oauth2/token'
    client_id = cfg.DROPBOX_APP_KEY
    extra = {'token_access_type': 'offline'}
    names = r'дропбокс\w*|dropbox|дроп бокс\w*'
    files_title = 'Dropbox'
    skills = ('files',)
    API = 'https://api.dropboxapi.com/2'
    CONTENT = 'https://content.dropboxapi.com/2'

    def whoami(self, tokens):
        try:
            me = self.hub.http.post(self.API + '/users/get_current_account', timeout=TIMEOUT,
                                    headers={'Authorization': 'Bearer ' + tokens['access_token']}).json()
            return me.get('email') or (me.get('name') or {}).get('display_name', '')
        except Exception:
            return ''

    def files_upload(self, path):
        target = f'/{APP_FOLDER}/{path.name}'
        size = path.stat().st_size
        headers = {'Content-Type': 'application/octet-stream'}
        commit = {'path': target, 'mode': 'add', 'autorename': True}
        with open(path, 'rb') as fh:
            if size <= 140 * 2 ** 20:
                self.request('POST', self.CONTENT + '/files/upload', timeout=UPLOAD_TIMEOUT, data=fh.read(),
                             headers=dict(headers, **{'Dropbox-API-Arg': json.dumps(commit)}))
                return ''
            chunk = 64 * 2 ** 20
            session = self.request('POST', self.CONTENT + '/files/upload_session/start', data=fh.read(chunk),
                                   timeout=UPLOAD_TIMEOUT, headers=dict(headers, **{'Dropbox-API-Arg': '{}'}))
            offset = chunk
            while True:
                data = fh.read(chunk)
                cursor = {'session_id': session['session_id'], 'offset': offset}
                if offset + len(data) >= size:
                    self.request('POST', self.CONTENT + '/files/upload_session/finish', data=data, timeout=UPLOAD_TIMEOUT,
                                 headers=dict(headers, **{'Dropbox-API-Arg': json.dumps({'cursor': cursor, 'commit': commit})}))
                    return ''
                self.request('POST', self.CONTENT + '/files/upload_session/append_v2', data=data, timeout=UPLOAD_TIMEOUT,
                             headers=dict(headers, **{'Dropbox-API-Arg': json.dumps({'cursor': cursor})}))
                offset += len(data)

    def files_find(self, query):
        data = self.request('POST', self.API + '/files/search_v2', json={'query': query, 'options': {'max_results': 5}})
        result = []
        for match in data.get('matches') or []:
            meta = (match.get('metadata') or {}).get('metadata') or {}
            path = meta.get('path_display', '')
            parent = path.rsplit('/', 1)[0]
            result.append({'name': meta.get('name', ''), 'path': path,
                           'url': 'https://www.dropbox.com/home' + quote(parent)})
        return result

    def files_space(self):
        data = self.request('POST', self.API + '/users/get_space_usage')
        return data.get('used', 0), (data.get('allocation') or {}).get('allocated', 0)


# ---------------- GitLab, Jira, Linear ----------------
class GitLabConnector(Skills, DevSkill, KeyConnector):
    id, title, icon = 'gitlab', 'GitLab', '🦊'
    group = 'Разработка'
    description = 'Ваши задачи и merge request, новые задачи в проектах (gitlab.com или свой сервер).'
    examples = ('Мои merge request в GitLab', 'Мои задачи в GitLab', 'Создай задачу в GitLab в проекте site: поправить меню')
    token_hint = 'GitLab → аватар → Preferences → Access tokens → Add new token → права «api» (или «read_api» только для чтения).'
    fields = (field('url', 'Адрес GitLab', 'text', 'https://gitlab.com', optional=True),
              field('token', 'Personal access token', 'password', 'glpat-…'))
    names = r'гитлаб\w*|gitlab|гит лаб\w*'
    dev_names = names
    skills = ('dev',)

    def prepare(self, values):
        url = (values.get('url') or 'https://gitlab.com').rstrip('/')
        if not url.startswith('http'):
            url = 'https://' + url
        return {'access_token': values['token'], 'url': url}

    @property
    def api(self):
        return self.saved().get('url', 'https://gitlab.com') + '/api/v4'

    def whoami_with(self, saved):
        return self.request('GET', self.api + '/user').get('username') or 'GitLab'

    def dev_mine(self):
        items = self.request('GET', self.api + '/issues', params={'state': 'opened', 'scope': 'assigned_to_me', 'per_page': 10})
        return [{'key': f"#{i.get('iid')}", 'title': i.get('title', ''),
                 'state': (i.get('references') or {}).get('full', '').split('#')[0]} for i in items or []]

    def dev_merge_requests(self):
        seen, result = set(), []
        for scope in ('created_by_me', 'assigned_to_me'):
            for mr in self.request('GET', self.api + '/merge_requests',
                                   params={'state': 'opened', 'scope': scope, 'per_page': 10}) or []:
                if mr['id'] not in seen:
                    seen.add(mr['id'])
                    result.append({'key': f"!{mr.get('iid')}", 'title': mr.get('title', '')})
        return result

    def dev_create(self, project, title):
        params = {'membership': 'true', 'per_page': 20, 'order_by': 'last_activity_at'}
        if project:
            params['search'] = project
        projects = self.request('GET', self.api + '/projects', params=params)
        if not projects:
            raise ConnectorError(f'Проект «{project}» в GitLab не найден.' if project else 'В GitLab нет проектов.')
        issue = self.request('POST', f"{self.api}/projects/{projects[0]['id']}/issues", json={'title': title})
        return f"#{issue.get('iid')}", ''


class JiraConnector(Skills, DevSkill, KeyConnector):
    id, title, icon = 'jira', 'Jira', '🔹'
    group = 'Разработка'
    description = 'Ваши открытые задачи и новые задачи в проекте (Jira Cloud или свой сервер).'
    examples = ('Мои задачи в Jira', 'Создай задачу в Jira в проекте WEB: обновить форму оплаты')
    token_hint = ('Jira Cloud: id.atlassian.com/manage-profile/security/api-tokens → Create API token; укажите адрес '
                  'company.atlassian.net и почту. Свой сервер (Data Center): Профиль → Personal Access Tokens, почту не указывайте.')
    fields = (field('site', 'Адрес Jira', 'text', 'company.atlassian.net'),
              field('email', 'Почта аккаунта', 'email', 'для Jira Cloud', optional=True),
              field('token', 'API token', 'password'))
    names = r'джир\w*|jira|жир[аеуы](?![\w])'
    dev_names = names
    skills = ('dev',)

    def prepare(self, values):
        site = values['site'].rstrip('/')
        if not site.startswith('http'):
            site = 'https://' + site
        return {'access_token': values['token'], 'site': site, 'email': values.get('email', '')}

    def auth_headers(self):
        saved = self.saved()
        token = self.token()
        if saved.get('email'):
            return {'Authorization': 'Basic ' + base64.b64encode(f"{saved['email']}:{token}".encode()).decode()}
        return {'Authorization': 'Bearer ' + token}

    @property
    def api(self):
        saved = self.saved()
        return saved.get('site', '') + ('/rest/api/3' if 'atlassian.net' in saved.get('site', '') else '/rest/api/2')

    def whoami_with(self, saved):
        me = self.request('GET', self.api + '/myself')
        return me.get('displayName') or me.get('name') or 'Jira'

    def dev_mine(self):
        jql = 'assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC'
        path = '/search/jql' if self.api.endswith('/3') else '/search'
        data = self.request('GET', self.api + path, params={'jql': jql, 'fields': 'summary,status', 'maxResults': 10})
        return [{'key': i.get('key', ''), 'title': (i.get('fields') or {}).get('summary', ''),
                 'state': ((i.get('fields') or {}).get('status') or {}).get('name', '')} for i in data.get('issues') or []]

    def dev_create(self, project, title):
        key = project.upper().replace(' ', '') if project else ''
        if not key:
            projects = self.request('GET', self.api + '/project/search', params={'maxResults': 1,
                                                                               'orderBy': '-lastIssueUpdatedTime'})
            values = projects.get('values') or []
            if not values:
                raise ConnectorError('В Jira нет проектов. Скажите: «создай задачу в Jira в проекте KEY: …».')
            key = values[0]['key']
        types = self.request('GET', f'{self.api}/issue/createmeta/{key}/issuetypes')
        kinds = [t for t in (types.get('issueTypes') or types.get('values') or []) if not t.get('subtask')]
        kind = next((t for t in kinds if t.get('name', '').casefold() in ('task', 'задача')), kinds[0] if kinds else None)
        fields = {'project': {'key': key}, 'summary': title,
                  'issuetype': {'id': kind['id']} if kind else {'name': 'Task'}}
        issue = self.request('POST', self.api + '/issue', json={'fields': fields})
        return issue.get('key', ''), ''


class LinearConnector(Skills, DevSkill, KeyConnector):
    id, title, icon = 'linear', 'Linear', '📐'
    group = 'Разработка'
    description = 'Ваши задачи в работе и новые задачи в команде.'
    examples = ('Мои задачи в Linear', 'Создай задачу в Linear: починить вход по почте')
    token_hint = 'linear.app → Settings → Security & access → Personal API keys → New API key.'
    fields = (field('token', 'Personal API key', 'password', 'lin_api_…'),)
    names = r'линеар\w*|linear|линир\w*'
    dev_names = names
    skills = ('dev',)
    API = 'https://api.linear.app/graphql'

    def auth_headers(self):
        return {'Authorization': self.token()}

    def gql(self, query, variables=None):
        data = self.request('POST', self.API, json={'query': query, 'variables': variables or {}})
        if data.get('errors'):
            raise ConnectorError('Linear: ' + str(data['errors'][0].get('message', 'ошибка'))[:160])
        return data.get('data') or {}

    def whoami_with(self, saved):
        return (self.gql('{ viewer { name email } }').get('viewer') or {}).get('name') or 'Linear'

    def dev_mine(self):
        data = self.gql('{ viewer { assignedIssues(first: 10, filter: {state: {type: {nin: ["completed", "canceled"]}}}) '
                        '{ nodes { identifier title state { name } } } } }')
        nodes = (((data.get('viewer') or {}).get('assignedIssues')) or {}).get('nodes') or []
        return [{'key': n['identifier'], 'title': n['title'], 'state': (n.get('state') or {}).get('name', '')} for n in nodes]

    def dev_create(self, project, title):
        teams = ((self.gql('{ teams { nodes { id name key } } }').get('teams')) or {}).get('nodes') or []
        if not teams:
            raise ConnectorError('В Linear нет команд.')
        team = next((t for t in teams if project and project.casefold() in (t['name'].casefold(), t['key'].casefold())),
                    teams[0])
        data = self.gql('mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { identifier url } } }',
                        {'input': {'teamId': team['id'], 'title': title}})
        issue = (data.get('issueCreate') or {}).get('issue') or {}
        return issue.get('identifier', ''), ''


APPS = (GoogleCalendarConnector, GmailConnector, YandexConnector, MicrosoftConnector, ImapConnector,
        NotionConnector, TodoistConnector, YouGileConnector, KaitenConnector, WeeekConnector,
        DropboxConnector, TInvestConnector, Bitrix24Connector, AmoCrmConnector, SpotifyConnector,
        GitLabConnector, JiraConnector, LinearConnector)
