"""Интеграции с приложениями: кнопка «Подключить» → вход в аккаунт → голосовые команды.

Здесь — каркас и первые приложения (Трекер, GitHub, Google Документы и Таблицы, Miro); остальные — в
src/connectors_apps.py (календари, почта, задачи, CRM, Spotify, Microsoft 365, Dropbox, GitLab, Jira, Linear…).
Токены хранятся только на этом ПК; пароли от аккаунтов не хранятся (кроме пароля приложения для почты IMAP).
Способы входа:
- через браузер с возвратом в программу (OAuth 2.0 + PKCE): Трекер, Google, Яндекс, Microsoft, Spotify, Dropbox…;
- по коду устройства (как на телевизорах): GitHub;
- ключ/токен из настроек сервиса (поля в карточке): Todoist, Т-Инвестиции, Битрикс24, Jira…
"""
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from urllib.parse import quote, urlencode

import requests

from . import connector_config as cfg

log = logging.getLogger(__name__)
TIMEOUT = 15


class ConnectorError(Exception):
    pass


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return verifier, challenge


def error_message(response):
    try:
        data = response.json()
    except ValueError:
        return (response.text or '')[:160].strip() or None
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return None
    error = data.get('error')
    if isinstance(error, dict):
        return error.get('message') or error.get('code')
    for key in ('message', 'error_description', 'detail', 'errorMessage', 'description', 'title'):
        if isinstance(data.get(key), str) and data[key]:
            return data[key][:200]
    if isinstance(data.get('errorMessages'), list) and data['errorMessages']:
        return str(data['errorMessages'][0])[:200]
    if isinstance(data.get('errors'), list) and data['errors']:
        first = data['errors'][0]
        return (first.get('message') if isinstance(first, dict) else str(first))[:200]
    return error if isinstance(error, str) else None


def clean(text):
    return re.sub(r'\s+', ' ', str(text)).strip().strip('.!?').strip(' «»"')


class Connector:
    id = ''
    title = ''
    icon = ''
    auth = 'oauth'           # oauth | device | token
    group = 'Другое'         # раздел в настройках
    description = ''
    examples = ()
    token_hint = ''          # как получить личный токен/ключ (если поддерживается)
    fields = ()              # поля формы входа по ключу: ({'name', 'label', 'type', 'placeholder'}, …)
    names = ''               # как сервис называют голосом (регулярное выражение): «в Notion», «в Тудуисте»
    auth_scheme = 'Bearer'

    def __init__(self, hub):
        self.hub = hub

    # ---- хранение токена ----
    @property
    def key(self):
        return 'connector:' + self.id

    def saved(self):
        try:
            return json.loads(self.hub.store.meta(self.key) or '{}')
        except ValueError:
            return {}

    def save(self, value):
        self.hub.store.set_meta(self.key, json.dumps(value, ensure_ascii=False) if value else None)

    def configured(self):
        return True

    def connected(self):
        return bool(self.saved().get('access_token'))

    def status(self):
        saved = self.saved()
        return {'id': self.id, 'title': self.title, 'icon': self.icon, 'description': self.description,
                'connected': self.connected(), 'user': saved.get('user', ''), 'configured': self.configured(),
                'auth': self.auth, 'examples': list(self.examples), 'token_hint': self.token_hint,
                'fields': self.form(), 'group': self.group}

    def form(self):
        if self.fields:
            return [dict(f) for f in self.fields]
        if self.token_hint:
            return [{'name': 'token', 'label': 'Личный токен', 'type': 'password', 'placeholder': 'вставьте токен'}]
        return []

    def mentioned(self, text):
        """Назван ли сервис во фразе («добавь в Notion…»)."""
        return bool(self.names) and re.search(r'(?<![\w])(?:' + self.names + r')(?![\w])', str(text), re.I) is not None

    def plain(self, text):
        """Фраза без упоминания сервиса: «добавь в Notion задачу X» → «добавь задачу X»."""
        value = clean(text)
        if self.names:
            value = re.sub(r'\s*(?:(?:в|во|на|из|с|через|по)\s+)?(?<![\w])(?:' + self.names + r')(?![\w])', ' ', value,
                           flags=re.I)
        return re.sub(r'\s+', ' ', value).strip(' ,')

    def disconnect(self):
        self.save(None)

    # ---- HTTP ----
    def token(self):
        saved = self.saved()
        if not saved.get('access_token'):
            raise ConnectorError(f'{self.title} не подключён: Настройки → «Интеграции» → «Подключить».')
        if saved.get('expires_at') and saved['expires_at'] < time.time() + 60 and saved.get('refresh_token'):
            saved = self.refresh(saved)
        return saved['access_token']

    def refresh(self, saved):
        return saved

    def auth_headers(self):
        return {'Authorization': f'{self.auth_scheme} {self.token()}'}

    def request(self, method, url, raw=False, **kwargs):
        from .network import MESSAGE, is_web_url, online
        if not online() and is_web_url(url):
            raise ConnectorError(MESSAGE)
        headers = dict(kwargs.pop('headers', {}), **self.auth_headers())
        kwargs.setdefault('timeout', TIMEOUT)
        try:
            response = self.hub.http.request(method, url, headers=headers, **kwargs)
        except requests.RequestException:
            raise ConnectorError(f'{self.title} не отвечает. Проверьте интернет.')
        if response.status_code == 401:
            raise ConnectorError(f'{self.title}: вход устарел. Подключите заново в настройках «Интеграции».')
        if response.status_code >= 400:
            self.failed(response)
            message = error_message(response)
            raise ConnectorError(f'{self.title}: ошибка {response.status_code}' + (f' — {message}' if message else ''))
        if raw:
            return response
        try:
            return response.json()
        except ValueError:
            return {}

    def failed(self, response):
        """Понятное сообщение для особых ошибок сервиса (переопределяется)."""

    # ---- подключение ----
    def start(self, base_url):
        raise ConnectorError('Этот способ входа не поддерживается')

    def use_token(self, token):
        raise ConnectorError('Вход по токену не поддерживается')

    def use_fields(self, values):
        """Вход по форме из карточки (ключ, адрес, логин…)."""
        values = {k: str(v).strip() for k, v in (values or {}).items()}
        missing = [f['label'] for f in self.form() if not f.get('optional') and not values.get(f['name'])]
        if missing:
            raise ConnectorError('Заполните: ' + ', '.join(missing) + '.')
        return self.use_token(values.get('token', ''))

    # ---- голос ----
    def handle(self, text):
        return None


# ---------------- OAuth 2.0 через браузер ----------------
class OAuthConnector(Connector):
    auth = 'oauth'
    authorize_url = ''
    token_url = ''
    scope = ''
    client_id = ''
    client_secret = ''
    extra = {}

    def configured(self):
        return bool(self.client_id)

    def redirect_uri(self, base_url):
        return base_url.rstrip('/') + f'/oauth/{self.id}/callback'

    def start(self, base_url):
        if not self.configured():
            raise ConnectorError(f'Для кнопки «Подключить» разработчику нужно один раз зарегистрировать приложение '
                                 f'{self.title} (docs/INTEGRATIONS_OAUTH.md).')
        verifier, challenge = pkce()
        state = secrets.token_urlsafe(24)
        redirect = self.redirect_uri(base_url)
        self.hub.pending[state] = {'id': self.id, 'verifier': verifier, 'redirect': redirect, 'at': time.time()}
        params = dict(client_id=self.client_id, redirect_uri=redirect, response_type='code', state=state,
                      code_challenge=challenge, code_challenge_method='S256', **self.extra)
        if self.scope:
            params['scope'] = self.scope
        return {'url': self.authorize_url + '?' + urlencode(params)}

    def finish(self, code, pending):
        data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': pending['redirect'],
                'client_id': self.client_id, 'code_verifier': pending['verifier']}
        if self.client_secret:
            data['client_secret'] = self.client_secret
        tokens = self._token_request(data)
        tokens['user'] = self.whoami(tokens) or ''
        self.save(tokens)
        return tokens['user']

    def _token_request(self, data):
        try:
            response = self.hub.http.post(self.token_url, data=data, headers={'Accept': 'application/json'},
                                          timeout=TIMEOUT)
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise ConnectorError(f'{self.title} не выдал доступ. Попробуйте ещё раз.')
        if not payload.get('access_token'):
            raise ConnectorError(f"{self.title}: {payload.get('error_description') or payload.get('error') or 'вход отклонён'}")
        if payload.get('expires_in'):
            payload['expires_at'] = time.time() + int(payload['expires_in'])
        return payload

    def refresh(self, saved):
        data = {'grant_type': 'refresh_token', 'refresh_token': saved['refresh_token'], 'client_id': self.client_id}
        if self.client_secret:
            data['client_secret'] = self.client_secret
        fresh = self._token_request(data)
        saved = dict(saved, **{k: v for k, v in fresh.items() if v})
        self.save(saved)
        return saved

    def whoami(self, tokens):
        return ''


# ---------------- Трекер ----------------
class TrackerConnector(OAuthConnector):
    id, title, icon = 'tracker', 'Трекер', '✅'
    group = 'Заметки и задачи'
    description = 'Задачи и привычки: спрашивайте и добавляйте голосом.'
    examples = ('Что в трекере на сегодня?', 'Добавь в трекер задачу купить молоко на завтра', 'Отметь привычку зарядка')

    @property
    def url(self):
        return (cfg.TRACKER_URL or self.hub.store.meta('tracker_url') or '').rstrip('/')

    @property
    def authorize_url(self):
        return self.url + '/connect'

    @property
    def token_url(self):
        return self.url + '/api/agent/token'

    client_id = 'andrey'

    def configured(self):
        return bool(self.url)

    def connected(self):
        return bool(self.hub.tracker and self.hub.tracker.connected)

    def status(self):
        value = super().status()
        if self.hub.tracker:
            value['user'] = self.hub.tracker.status().get('user', '')
        return value

    def finish(self, code, pending):
        tokens = self._token_request({'grant_type': 'authorization_code', 'code': code, 'client_id': 'andrey',
                                      'redirect_uri': pending['redirect'], 'code_verifier': pending['verifier']})
        user = tokens.get('user') or {}
        name = (user.get('name') or user.get('email') or '') if isinstance(user, dict) else str(user)
        self.hub.store.set_meta('tracker', json.dumps({'url': self.url, 'token': tokens['access_token'],
                                                       'user': name, 'since': int(time.time())}, ensure_ascii=False))
        return name

    def disconnect(self):
        if self.hub.tracker:
            self.hub.tracker.logout()

    def handle(self, text):
        return None  # голосовые команды Трекера — в src/tracker.py (агент вызывает их отдельно)


# ---------------- Google Документы и Таблицы ----------------
class GoogleConnector(OAuthConnector):
    group = 'Google'
    authorize_url = 'https://accounts.google.com/o/oauth2/v2/auth'
    token_url = 'https://oauth2.googleapis.com/token'
    # Каждое приложение просит только свои доступы; include_granted_scopes сохраняет выданные раньше.
    needs = ('https://www.googleapis.com/auth/drive.metadata.readonly',)
    extra = {'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true'}
    client_id = cfg.GOOGLE_CLIENT_ID
    client_secret = cfg.GOOGLE_CLIENT_SECRET
    mime = ''

    @property
    def scope(self):
        return ' '.join(('openid', 'email') + tuple(self.needs))

    # Один вход Google на все приложения Google.
    @property
    def key(self):
        return 'connector:google'

    def connected(self):
        saved = self.saved()
        if not saved.get('access_token'):
            return False
        granted = saved.get('scope')
        return granted is None or all(need in granted.split() for need in self.needs)

    def whoami(self, tokens):
        try:
            response = self.hub.http.get('https://openidconnect.googleapis.com/v1/userinfo', timeout=TIMEOUT,
                                         headers={'Authorization': 'Bearer ' + tokens['access_token']})
            return response.json().get('email', '')
        except Exception:
            return ''

    def find(self, name):
        name = clean(name).replace("'", "\\'")
        query = f"name contains '{name}' and mimeType='{self.mime}' and trashed=false"
        data = self.request('GET', 'https://www.googleapis.com/drive/v3/files',
                            params={'q': query, 'orderBy': 'modifiedTime desc', 'pageSize': 5,
                                    'fields': 'files(id,name,webViewLink)'})
        files = data.get('files') or []
        if not files:
            raise ConnectorError(f'Не нашёл «{clean(name)}» в {self.title}.')
        return files[0]


class GoogleDocsConnector(GoogleConnector):
    id, title, icon = 'google_docs', 'Google Документы', '📝'
    description = 'Создавайте документы и дописывайте в них текст голосом.'
    examples = ('Создай документ план поездки', 'Допиши в документ план поездки: купить билеты',
                'Прочитай документ план поездки')
    mime = 'application/vnd.google-apps.document'
    needs = ('https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.metadata.readonly')

    def handle(self, text):
        raw = clean(text)
        m = re.fullmatch(r'(?:создай|сделай|заведи)\s+(?:новый\s+)?(?:гугл\s+|google\s+)?документ\s+(.+)', raw, re.I)
        if m:
            doc = self.request('POST', 'https://docs.googleapis.com/v1/documents', json={'title': clean(m[1])})
            self.hub.open(f"https://docs.google.com/document/d/{doc['documentId']}/edit")
            return f'Создал документ «{clean(m[1])}» и открыл его.'
        m = re.fullmatch(r'(?:допиши|добавь|запиши|вставь)\s+в\s+(?:гугл\s+|google\s+)?документ\s+(.+?)\s*[:,—-]\s*(.+)',
                         raw, re.I)
        if m:
            file = self.find(m[1])
            doc = self.request('GET', f"https://docs.googleapis.com/v1/documents/{file['id']}")
            end = max(1, (doc.get('body', {}).get('content') or [{}])[-1].get('endIndex', 2) - 1)
            self.request('POST', f"https://docs.googleapis.com/v1/documents/{file['id']}:batchUpdate",
                         json={'requests': [{'insertText': {'location': {'index': end}, 'text': '\n' + m[2]}}]})
            return f"Дописал в «{file['name']}»."
        m = re.fullmatch(r'(?:прочитай|что в|что написано в)\s+(?:гугл\s+|google\s+)?документе?\s+(.+)', raw, re.I)
        if m:
            file = self.find(m[1])
            doc = self.request('GET', f"https://docs.googleapis.com/v1/documents/{file['id']}")
            parts = []
            for block in doc.get('body', {}).get('content', []):
                for element in (block.get('paragraph') or {}).get('elements', []):
                    parts.append((element.get('textRun') or {}).get('content', ''))
            body = re.sub(r'\s+', ' ', ''.join(parts)).strip()
            return f"«{file['name']}»: {body[:700]}" if body else f"Документ «{file['name']}» пустой."
        return None


class GoogleSheetsConnector(GoogleConnector):
    id, title, icon = 'google_sheets', 'Google Таблицы', '📊'
    description = 'Добавляйте строки и узнавайте, что в таблице, голосом.'
    examples = ('Добавь в таблицу расходы строку: кофе, 250', 'Прочитай таблицу расходы', 'Создай таблицу покупки')
    mime = 'application/vnd.google-apps.spreadsheet'
    needs = ('https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.metadata.readonly')

    def handle(self, text):
        raw = clean(text)
        m = re.fullmatch(r'(?:создай|сделай|заведи)\s+(?:новую\s+)?(?:гугл\s+|google\s+)?таблицу\s+(.+)', raw, re.I)
        if m:
            sheet = self.request('POST', 'https://sheets.googleapis.com/v4/spreadsheets',
                                 json={'properties': {'title': clean(m[1])}})
            self.hub.open(sheet.get('spreadsheetUrl', ''))
            return f'Создал таблицу «{clean(m[1])}» и открыл её.'
        m = re.fullmatch(r'(?:добавь|запиши|внеси)\s+в\s+(?:гугл\s+|google\s+)?таблицу\s+(.+?)\s*(?:строку|запись)?\s*[:—-]\s*(.+)',
                         raw, re.I)
        if m:
            file = self.find(m[1])
            values = [self._cell(v) for v in re.split(r'\s*[,;]\s*', m[2]) if v.strip()]
            self.request('POST', f"https://sheets.googleapis.com/v4/spreadsheets/{file['id']}/values/A1:append",
                         params={'valueInputOption': 'USER_ENTERED', 'insertDataOption': 'INSERT_ROWS'},
                         json={'values': [values]})
            return f"Добавил в «{file['name']}»: {', '.join(str(v) for v in values)}."
        m = re.fullmatch(r'(?:прочитай|что в|покажи)\s+(?:гугл\s+|google\s+)?таблиц[еуа]\s+(.+)', raw, re.I)
        if m:
            file = self.find(m[1])
            data = self.request('GET', f"https://sheets.googleapis.com/v4/spreadsheets/{file['id']}/values/A1:H12")
            rows = data.get('values') or []
            if not rows:
                return f"Таблица «{file['name']}» пустая."
            lines = '; '.join(', '.join(r) for r in rows[:8])
            return f"«{file['name']}», строк в начале листа: {len(rows)}. {lines}"
        return None

    @staticmethod
    def _cell(value):
        value = value.strip()
        number = value.replace(' ', '').replace(',', '.')
        return float(number) if re.fullmatch(r'-?\d+(?:\.\d+)?', number) else value


# ---------------- GitHub ----------------
class GitHubConnector(Connector):
    id, title, icon, auth = 'github', 'GitHub', '🐙', 'device'
    group = 'Разработка'
    names = r'гитхаб\w*|github'
    description = 'Репозитории, pull request’ы, задачи (issues) и коммиты.'
    examples = ('Мои репозитории', 'Мои открытые pull request', 'Создай issue в репозитории ai_agent: не работает звук',
                'Последние коммиты в ai_agent')
    token_hint = 'github.com → Settings → Developer settings → Fine-grained tokens → доступ к нужным репозиториям.'
    API = 'https://api.github.com'

    def configured(self):
        return bool(cfg.GITHUB_CLIENT_ID)

    def start(self, base_url):
        if not self.configured():
            raise ConnectorError('Кнопке «Подключить» нужен ключ приложения GitHub (docs/INTEGRATIONS_OAUTH.md). '
                                 'Пока можно вставить личный токен.')
        try:
            data = self.hub.http.post('https://github.com/login/device/code', timeout=TIMEOUT,
                                      data={'client_id': cfg.GITHUB_CLIENT_ID, 'scope': 'repo read:user'},
                                      headers={'Accept': 'application/json'}).json()
        except (requests.RequestException, ValueError):
            raise ConnectorError('GitHub не отвечает.')
        self.hub.pending['github-device'] = {'id': self.id, 'device_code': data.get('device_code'),
                                             'interval': data.get('interval', 5), 'at': time.time()}
        return {'device': {'code': data.get('user_code'), 'url': data.get('verification_uri')},
                'url': data.get('verification_uri')}

    def poll(self):
        pending = self.hub.pending.get('github-device')
        if not pending:
            return {'done': False, 'error': 'Сначала нажмите «Подключить».'}
        data = self.hub.http.post('https://github.com/login/oauth/access_token', timeout=TIMEOUT,
                                  headers={'Accept': 'application/json'},
                                  data={'client_id': cfg.GITHUB_CLIENT_ID, 'device_code': pending['device_code'],
                                        'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'}).json()
        if data.get('access_token'):
            self.hub.pending.pop('github-device', None)
            self.save({'access_token': data['access_token'], 'user': self._login(data['access_token'])})
            return {'done': True}
        if data.get('error') in ('authorization_pending', 'slow_down'):
            return {'done': False}
        self.hub.pending.pop('github-device', None)
        return {'done': False, 'error': data.get('error_description') or data.get('error') or 'вход отклонён'}

    def _login(self, token):
        try:
            return self.hub.http.get(self.API + '/user', timeout=TIMEOUT,
                                     headers={'Authorization': 'Bearer ' + token}).json().get('login', '')
        except Exception:
            return ''

    def use_token(self, token):
        login = self._login(token.strip())
        if not login:
            raise ConnectorError('GitHub не принял токен.')
        self.save({'access_token': token.strip(), 'user': login})
        return login

    def _repo(self, name):
        name = clean(name).replace(' ', '-').casefold()
        repos = self.request('GET', self.API + '/user/repos', params={'per_page': 100, 'sort': 'updated'})
        exact = [r for r in repos if r['name'].casefold() == name or r['full_name'].casefold() == name]
        close = exact or [r for r in repos if name in r['name'].casefold()]
        if not close:
            raise ConnectorError(f'Репозиторий «{name}» не найден.')
        return close[0]

    def handle(self, text):
        raw = clean(text)
        lower = raw.casefold()
        if re.fullmatch(r'(?:мои|покажи мои|какие у меня|список)\s+(?:репозитори\w*|репо)(?: на гитхабе| в github)?', lower):
            repos = self.request('GET', self.API + '/user/repos', params={'per_page': 8, 'sort': 'updated'})
            return 'Последние репозитории: ' + ', '.join(r['name'] for r in repos) + '.' if repos else 'Репозиториев нет.'
        if re.fullmatch(r'(?:мои\s+)?(?:открытые\s+)?(?:pull request\w*|пул+ реквест\w*|pr|пиары)(?:\s+на гитхабе)?', lower) \
                or lower in ('какие у меня открытые pull request', 'мои открытые pull request'):
            login = self.saved().get('user', '')
            data = self.request('GET', self.API + '/search/issues',
                                params={'q': f'is:pr is:open involves:{login}', 'per_page': 5})
            items = data.get('items') or []
            if not items:
                return 'Открытых pull request нет.'
            return f"Открытых pull request: {data.get('total_count', len(items))}. " + '; '.join(
                f"{i['title']} ({i['repository_url'].rsplit('/', 1)[-1]})" for i in items) + '.'
        m = re.fullmatch(r'(?:создай|заведи|открой)\s+(?:issue|ишью|ишшью|задачу)\s+(?:в|для)\s+(?:репозитори\w+\s+)?([^\s:,]+)\s*[:,—-]?\s+(.+)',
                         raw, re.I)
        if m:
            repo = self._repo(m[1])
            issue = self.request('POST', f"{self.API}/repos/{repo['full_name']}/issues", json={'title': m[2]})
            return f"Создал задачу №{issue.get('number')} в {repo['name']}: {m[2]}."
        m = re.fullmatch(r'(?:последние\s+)?коммиты\s+(?:в|из)?\s*(?:репозитори\w+\s+)?(\S+)', raw, re.I)
        if m:
            repo = self._repo(m[1])
            commits = self.request('GET', f"{self.API}/repos/{repo['full_name']}/commits", params={'per_page': 5})
            return f"Последние коммиты в {repo['name']}: " + '; '.join(
                c['commit']['message'].split('\n')[0][:80] for c in commits) + '.'
        return None


# ---------------- Miro ----------------
class MiroConnector(OAuthConnector):
    id, title, icon = 'miro', 'Miro', '🟨'
    group = 'Заметки и задачи'
    names = r'миро|miro'
    description = 'Доски и стикеры голосом.'
    examples = ('Создай доску мозговой штурм', 'Добавь стикер на доску мозговой штурм: идея с ботом', 'Мои доски')
    authorize_url = 'https://miro.com/oauth/authorize'
    token_url = 'https://api.miro.com/v1/oauth/token'
    client_id = cfg.MIRO_CLIENT_ID
    client_secret = cfg.MIRO_CLIENT_SECRET
    token_hint = 'miro.com → Settings → Your apps → создайте приложение → «Install app and get OAuth token».'
    API = 'https://api.miro.com/v2'

    def use_token(self, token):
        self.save({'access_token': token.strip()})
        try:
            self.request('GET', self.API + '/boards', params={'limit': 1})
        except ConnectorError:
            self.save(None)
            raise ConnectorError('Miro не принял токен.')
        self.save({'access_token': token.strip(), 'user': 'Miro'})
        return 'Miro'

    def _board(self, name):
        data = self.request('GET', self.API + '/boards', params={'query': clean(name), 'limit': 5})
        boards = data.get('data') or []
        if not boards:
            raise ConnectorError(f'Доска «{clean(name)}» не найдена.')
        return boards[0]

    def handle(self, text):
        raw = clean(text)
        m = re.fullmatch(r'(?:создай|сделай|заведи)\s+(?:новую\s+)?доску\s+(?:в\s+миро\s+)?(.+)', raw, re.I)
        if m:
            board = self.request('POST', self.API + '/boards', json={'name': clean(m[1])})
            self.hub.open(board.get('viewLink', ''))
            return f'Создал доску «{clean(m[1])}» в Miro и открыл её.'
        m = re.fullmatch(r'(?:добавь|создай|прикрепи)\s+(?:стикер|заметку)\s+на\s+доску\s+(.+?)\s*[:—-]\s*(.+)', raw, re.I)
        if m:
            board = self._board(m[1])
            self.request('POST', f"{self.API}/boards/{quote(board['id'], safe='')}/sticky_notes",
                         json={'data': {'content': m[2], 'shape': 'square'}})
            return f"Добавил стикер на доску «{board['name']}»."
        if re.fullmatch(r'(?:мои|какие у меня|покажи мои)\s+доски(?:\s+в\s+миро)?', raw.casefold()):
            boards = self.request('GET', self.API + '/boards', params={'limit': 8}).get('data') or []
            return 'Доски: ' + ', '.join(b['name'] for b in boards) + '.' if boards else 'Досок нет.'
        return None


# ---------------- хаб ----------------
class Connectors:
    def __init__(self, store, tracker=None, http=None, opener=None, documents=None):
        from .connectors_apps import APPS
        self.store = store
        self.tracker = tracker
        self.http = http or requests.Session()
        self.opener = opener
        self.documents = documents   # «загрузи этот файл на Диск» — выделенный в Проводнике или последний из чата
        self.pending = {}
        self.items = [c(self) for c in (TrackerConnector, GitHubConnector, GoogleDocsConnector,
                                        GoogleSheetsConnector, MiroConnector) + tuple(APPS)]

    def get(self, connector_id):
        found = next((c for c in self.items if c.id == connector_id), None)
        if found is None:
            raise ConnectorError('Неизвестная интеграция')
        return found

    def status(self):
        return [c.status() for c in self.items]

    def open(self, url):
        if url and self.opener:
            try:
                self.opener(url)
            except Exception:
                pass

    def callback(self, connector_id, code, state):
        pending = self.pending.pop(state, None)
        if not pending or pending['id'] != connector_id or time.time() - pending['at'] > 900:
            raise ConnectorError('Ссылка входа устарела. Нажмите «Подключить» ещё раз.')
        return self.get(connector_id).finish(code, pending)

    def _try(self, connector, text):
        try:
            return connector.handle(text)
        except ConnectorError as exc:
            return str(exc)
        except requests.RequestException:
            return f'{connector.title} не отвечает.'

    def handle(self, text, named_only=False):
        """Сначала — приложения, названные во фразе («в Notion», «на Яндекс Диск»), даже если они не подключены
        (тогда подскажем, где подключить). Потом (если не named_only) — все подключённые по порядку."""
        for connector in self.items:
            if connector.id != 'tracker' and connector.mentioned(text):
                reply = self._try(connector, text)
                if reply is not None:
                    return reply
        if named_only:
            return None
        for connector in self.items:
            if connector.id == 'tracker' or not connector.connected():
                continue
            reply = self._try(connector, text)
            if reply is not None:
                return reply
        return None
