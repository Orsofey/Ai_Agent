"""Онлайн-подключение к Трекеру: вход в аккаунт Трекера и запросы к его API в реальном времени.

«Андрей, что в трекере на сегодня?», «добавь в трекер задачу купить молоко на завтра»,
«отметь задачу купить молоко», «отметь привычку зарядка», «как у меня с привычками на этой неделе?».

Трекер должен отдавать API из docs/TRACKER_API.md (вход, сводка, задачи, привычки).
Токен доступа хранится только на этом ПК; пароль не сохраняется.
"""
import json
import logging
import re
import time
from datetime import date, timedelta
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

TIMEOUT = 12
CONTEXT_WORDS = ('трекер', 'задач', 'привычк', 'цел', 'план', 'дела', 'дело', 'сделал', 'выполнил', 'прогресс',
                 'статистик', 'стрик', 'серия')


class TrackerError(Exception):
    pass


def check_url(url):
    value = str(url or '').strip().rstrip('/')
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('Адрес Трекера: https://…')
    local = parsed.hostname in ('localhost', '127.0.0.1') or (parsed.hostname or '').startswith('192.168.')
    if parsed.scheme == 'http' and not local:
        raise ValueError('Для входа в аккаунт нужен защищённый адрес https://')
    return value


def spoken_day(text):
    """«сегодня», «завтра», «вчера», «понедельник»… → date."""
    value = str(text or '').casefold()
    today = date.today()
    if 'послезавтра' in value:
        return today + timedelta(days=2)
    if 'завтра' in value:
        return today + timedelta(days=1)
    if 'вчера' in value:
        return today - timedelta(days=1)
    days = ('понедельник', 'вторник', 'сред', 'четверг', 'пятниц', 'суббот', 'воскресен')
    for index, stem in enumerate(days):
        if stem in value:
            return today + timedelta(days=(index - today.weekday()) % 7)
    return today


def day_name(day):
    delta = (day - date.today()).days
    return {0: 'сегодня', 1: 'завтра', -1: 'вчера', 2: 'послезавтра'}.get(delta, day.strftime('%d.%m'))


def parse(text):
    """('tasks', day) | ('add', title, day) | ('done', title) | ('habit', name) | ('summary',) или None."""
    raw = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    lower = raw.casefold().replace('ё', 'е')
    day = r'(?:\s+на\s+(?P<day>сегодня|завтра|послезавтра|вчера|понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))?'
    m = re.fullmatch(r'(?:что|что у меня|что там)\s+(?:в|по)\s+трекер[уе]' + day, lower) \
        or re.fullmatch(r'(?:какие\s+)?(?:у меня\s+)?(?:мои\s+)?(?:задачи|дела|планы)(?:\s+в трекере)?' + day, lower) \
        or re.fullmatch(r'(?:прочитай|покажи|озвучь)\s+(?:мои\s+)?(?:задачи|дела|трекер)(?:\s+из трекера)?' + day, lower)
    if m:
        return 'tasks', spoken_day(m['day'])
    m = re.fullmatch(r'(?:добавь|запиши|создай)\s+(?:в\s+трекер\s+)?(?:новую\s+)?(?:задачу|дело|в трекер)\s*[:,-]?\s*(?P<title>.+?)'
                     + day, raw, re.I)
    if m and (('трекер' in lower) or re.match(r'^(?:добавь|создай)\s+(?:новую\s+)?задачу', lower)):
        title = m['title'].strip(' «»"')
        if title and title.casefold() not in ('в трекер',):
            return 'add', title, spoken_day(m['day'])
    m = re.fullmatch(r'(?:отметь|закрой|заверши)\s+(?:задачу|дело)\s+(?P<title>.+?)(?:\s+(?:как\s+)?(?:выполненн\w+|сделанн\w+|готов\w*))?',
                     raw, re.I)
    if m:
        return 'done', m['title'].strip(' «»"')
    m = re.fullmatch(r'(?:отметь|засчитай)\s+привычку\s+(?P<name>.+?)(?:\s+(?:как\s+)?выполненн\w+)?', raw, re.I)
    if m:
        return 'habit', m['name'].strip(' «»"')
    if lower in ('обнови трекер', 'синхронизируй трекер', 'сводка трекера', 'статистика трекера', 'итоги в трекере'):
        return ('summary',)
    return None


class TrackerClient:
    def __init__(self, store, session=None):
        self.store = store
        self.http = session or requests.Session()
        self.cache = {}

    # ---- аккаунт ----
    def _config(self):
        try:
            return json.loads(self.store.meta('tracker') or '{}')
        except ValueError:
            return {}

    def _save(self, value):
        self.store.set_meta('tracker', json.dumps(value, ensure_ascii=False) if value else None)
        self.cache.clear()

    @property
    def connected(self):
        config = self._config()
        return bool(config.get('url') and config.get('token'))

    def status(self):
        config = self._config()
        return {'connected': self.connected, 'url': config.get('url', ''), 'user': config.get('user', ''),
                'since': config.get('since')}

    def login(self, url, email, password):
        url = check_url(url)
        if not email or not password:
            raise ValueError('Введите e-mail (логин) и пароль от Трекера')
        data = self._request('POST', url + '/api/agent/login', token=None,
                             json={'email': str(email).strip(), 'password': str(password), 'client': 'Андрей'})
        token = str(data.get('token') or '')
        if not token:
            raise TrackerError('Трекер не выдал токен доступа')
        user = data.get('user') or {}
        self._save({'url': url, 'token': token, 'user': user.get('name') or user.get('email') or str(email).strip(),
                    'since': int(time.time())})
        return self.status()

    def use_token(self, url, token):
        url = check_url(url)
        token = str(token or '').strip()
        if not re.fullmatch(r'[\w.~+/=-]{16,500}', token):
            raise ValueError('Токен Трекера выглядит неверно')
        data = self._request('GET', url + '/api/agent/me', token=token)
        user = data.get('user') or data
        self._save({'url': url, 'token': token, 'user': user.get('name') or user.get('email') or '',
                    'since': int(time.time())})
        return self.status()

    def logout(self):
        config = self._config()
        if config.get('token'):
            try:
                self._request('POST', config['url'] + '/api/agent/logout')
            except Exception:
                pass
        self._save(None)
        return self.status()

    # ---- HTTP ----
    def _request(self, method, url, token='config', **kwargs):
        config = self._config()
        if token == 'config':
            token = config.get('token')
        headers = {'Accept': 'application/json', 'User-Agent': 'Andrey-Assistant'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            response = self.http.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException:
            raise TrackerError('Трекер не отвечает. Проверьте интернет и адрес сервера Трекера.')
        if response.status_code == 401:
            if token and token == config.get('token'):
                self._save(dict(config, token=''))  # токен отозван — нужно войти заново
            raise TrackerError('Трекер не принял вход. Подключите аккаунт заново: Настройки → «Трекер».')
        if response.status_code == 404:
            raise TrackerError('В Трекере нет API для ассистента (см. docs/TRACKER_API.md).')
        try:
            data = response.json()
        except ValueError:
            raise TrackerError(f'Трекер ответил не JSON (код {response.status_code}).')
        if response.status_code >= 400 or data.get('ok') is False:
            raise TrackerError(str(data.get('error') or data.get('message') or f'Ошибка Трекера {response.status_code}'))
        return data

    def _api(self, method, path, **kwargs):
        config = self._config()
        if not config.get('url') or not config.get('token'):
            raise TrackerError('Трекер не подключён. Настройки → «Трекер» → войдите в свой аккаунт.')
        return self._request(method, config['url'] + path, **kwargs)

    # ---- данные ----
    def tasks(self, day):
        return self._api('GET', '/api/agent/tasks', params={'date': day.isoformat()}).get('tasks') or []

    def summary(self, max_age=60):
        cached = self.cache.get('summary')
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        data = self._api('GET', '/api/agent/summary', params={'date': date.today().isoformat()})
        self.cache['summary'] = (time.monotonic(), data)
        return data

    # ---- голос ----
    def handle(self, text):
        request = parse(text)
        if request is None:
            return None
        if not self.connected:
            return 'Трекер не подключён. Откройте Настройки → «Трекер» и войдите в свой аккаунт Трекера.'
        try:
            return self._run(request)
        except TrackerError as exc:
            return str(exc)

    def _run(self, request):
        kind = request[0]
        if kind == 'tasks':
            day = request[1]
            items = self.tasks(day)
            open_items = [t for t in items if not t.get('done')]
            if not items:
                return f'На {day_name(day)} в трекере задач нет.'
            titles = '; '.join(str(t.get('title', '')).strip() for t in open_items[:10])
            done = len(items) - len(open_items)
            head = f'На {day_name(day)} {len(open_items)} из {len(items)} задач не выполнено'
            return f'{head}: {titles}.' if open_items else f'На {day_name(day)} все задачи выполнены ({done}). Отлично!'
        if kind == 'add':
            _, title, day = request
            self._api('POST', '/api/agent/tasks', json={'title': title, 'date': day.isoformat()})
            self.cache.clear()
            return f'Добавил в трекер на {day_name(day)}: {title}.'
        if kind == 'done':
            data = self._api('POST', '/api/agent/tasks/complete', json={'title': request[1], 'date': date.today().isoformat()})
            self.cache.clear()
            return f"Отметил выполненной: {data.get('title') or request[1]}."
        if kind == 'habit':
            data = self._api('POST', '/api/agent/habits/check', json={'name': request[1], 'date': date.today().isoformat()})
            self.cache.clear()
            streak = data.get('streak')
            return f"Привычка «{data.get('name') or request[1]}» отмечена." + (f' Серия: {streak} дн.' if streak else '')
        if kind == 'summary':
            data = self.summary(max_age=0)
            return str(data.get('text') or 'Данные Трекера обновлены.')
        return None

    def context(self, question):
        """Данные Трекера для нейросети, если вопрос про задачи, привычки, цели."""
        if not self.connected or not any(word in str(question).casefold() for word in CONTEXT_WORDS):
            return None
        try:
            data = self.summary()
        except TrackerError as exc:
            return f'(Трекер недоступен: {exc})'
        text = json.dumps(data, ensure_ascii=False)[:6000]
        return f'Данные из Трекера пользователя на {date.today().isoformat()} (JSON):\n{text}'
