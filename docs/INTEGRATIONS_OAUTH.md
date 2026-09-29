# Кнопка «Подключить»: GitHub, Google Документы и Таблицы, Miro, Трекер

Пользователь открывает Настройки → **Интеграции** → нажимает **«Подключить»** на карточке приложения
→ входит в свой аккаунт в браузере → готово. Для этого разработчик (вы) один раз регистрирует
«Андрея» в каждом сервисе и вписывает полученные ключи в `src/connector_config.py` перед сборкой.
Пароли пользователей «Андрей» не видит и не хранит: сервис выдаёт ему токен доступа, который
можно отозвать в настройках сервиса.

| Приложение | Как входит пользователь | Что вписать в `connector_config.py` |
|---|---|---|
| Трекер | браузер → страница входа Трекера → «Разрешить» | `TRACKER_URL` |
| GitHub | код устройства: открывается github.com/login/device, вводится код | `GITHUB_CLIENT_ID` |
| Google Документы и Таблицы | браузер → аккаунт Google → «Разрешить» (один вход на оба) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Miro | браузер → аккаунт Miro → «Разрешить» | `MIRO_CLIENT_ID`, `MIRO_CLIENT_SECRET` |

Пока ключей нет, для GitHub и Miro работает запасной путь — **личный токен** (поле под кнопкой).
Для проверки ключи можно задать переменными окружения: `ANDREY_GITHUB_CLIENT_ID` и т. п.

## GitHub (5 минут)

1. github.com → Settings → Developer settings → **OAuth Apps** → **New OAuth App**.
2. Application name: «Андрей»; Homepage URL: сайт или страница проекта; Authorization callback URL:
   `http://127.0.0.1:5000/oauth/github/callback` (для входа по коду не используется, но поле обязательное).
3. Создайте приложение, включите **Enable Device Flow**.
4. Скопируйте **Client ID** → `GITHUB_CLIENT_ID`. Секрет не нужен.

Голосом: «мои репозитории», «мои открытые pull request», «создай issue в репозитории ai_agent: не работает звук»,
«последние коммиты в ai_agent».

## Google Документы и Таблицы (15 минут)

1. console.cloud.google.com → создайте проект «Андрей».
2. APIs & Services → **Library** → включите **Google Docs API**, **Google Sheets API**, **Google Drive API**.
3. **OAuth consent screen**: тип External, название «Андрей», e-mail поддержки; scopes:
   `documents`, `spreadsheets`, `drive.metadata.readonly`; в режиме Testing добавьте свои аккаунты в Test users.
4. **Credentials** → Create credentials → **OAuth client ID** → Application type **Desktop app**.
5. Client ID → `GOOGLE_CLIENT_ID`, Client secret → `GOOGLE_CLIENT_SECRET` (для настольных приложений Google
   не считает его секретом).
6. Для публикации на всех пользователей Google проверяет приложение (для `drive.metadata.readonly` — проверка
   «restricted scope»). До проверки работает у вас и тестовых пользователей (до 100).

Голосом: «создай документ план поездки», «допиши в документ план поездки: купить билеты», «прочитай документ …»,
«создай таблицу покупки», «добавь в таблицу расходы строку: кофе, 250», «прочитай таблицу расходы».

## Miro (10 минут)

1. miro.com → Settings → **Your apps** → Create new app (нужна команда-разработчик, бесплатно).
2. Redirect URI for OAuth2.0: `http://127.0.0.1:5000/oauth/miro/callback`.
3. Permissions: `boards:read`, `boards:write`.
4. Client ID → `MIRO_CLIENT_ID`, Client secret → `MIRO_CLIENT_SECRET`.

Голосом: «создай доску мозговой штурм», «добавь стикер на доску мозговой штурм: идея с ботом», «мои доски».

> Адрес возврата содержит порт 5000 (по умолчанию). Если вы меняли порт (`LOCAL_AI_PORT`), укажите тот же порт
> в настройках приложений Miro и GitHub. Google для настольных приложений принимает любой порт.

## Трекер — что изменить в его коде

Чтобы пользователю не нужно было вставлять ссылки и токены, Трекеру нужны **две вещи** в дополнение к API
из [TRACKER_API.md](TRACKER_API.md) — страница «Разрешить доступ» и выдача токена по коду
(стандартный OAuth 2.0 + PKCE, как у Google):

### 1. Страница `GET /connect`

«Андрей» открывает в браузере:

```
https://ваш-трекер/connect?client_id=andrey&response_type=code
    &redirect_uri=http://127.0.0.1:5000/oauth/tracker/callback
    &state=СЛУЧАЙНАЯ_СТРОКА&code_challenge=ХЕШ&code_challenge_method=S256
```

Трекер:
1. если пользователь не вошёл — показывает обычный вход (и возвращается сюда же после входа);
2. показывает «Разрешить “Андрею” доступ к задачам и привычкам?» и кнопку **Разрешить**;
3. по кнопке создаёт одноразовый `code` (случайная строка, живёт 5 минут) и запоминает рядом:
   пользователя, `code_challenge`, `redirect_uri`;
4. перенаправляет браузер на `redirect_uri?code=…&state=…` (state — тот же, что пришёл).

Проверка безопасности: принимайте `redirect_uri` **только** вида `http://127.0.0.1:ПОРТ/...` или
`http://localhost:ПОРТ/...` — тогда код попадёт только в программу на компьютере пользователя.

### 2. Выдача токена `POST /api/agent/token`

Тело (form-urlencoded): `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id=andrey`, `code_verifier`.

Трекер проверяет: код существует, не истёк и ещё не использован, `redirect_uri` совпадает,
`base64url(sha256(code_verifier)) == code_challenge`. Затем помечает код использованным и отвечает:

```json
{"access_token": "длинная-случайная-строка", "token_type": "Bearer",
 "user": {"name": "Орсофей", "email": "me@example.ru"}}
```

Дальше «Андрей» ходит в `/api/agent/*` с заголовком `Authorization: Bearer <access_token>` — как описано
в TRACKER_API.md. В настройках Трекера стоит показать список подключённых устройств с кнопкой «Отозвать».

### Пример (Python, Flask)

```python
import base64, hashlib, secrets, time
from flask import request, redirect, render_template, abort, jsonify

CODES = {}  # в реальном Трекере — таблица в базе

@app.get('/connect')
def connect():
    user = current_user()                       # ваша функция: вошёл ли пользователь
    if not user:
        return redirect('/login?next=' + quote(request.full_path))
    uri = request.args['redirect_uri']
    if not re.match(r'^http://(127\.0\.0\.1|localhost):\d+/', uri):
        abort(400)
    return render_template('connect.html', args=request.args)   # кнопка «Разрешить» → POST /connect

@app.post('/connect')
def connect_allow():
    user = current_user() or abort(401)
    code = secrets.token_urlsafe(32)
    CODES[code] = dict(user=user.id, challenge=request.form['code_challenge'],
                       redirect=request.form['redirect_uri'], until=time.time() + 300)
    return redirect(f"{request.form['redirect_uri']}?code={code}&state={request.form['state']}")

@app.post('/api/agent/token')
def agent_token():
    item = CODES.pop(request.form.get('code', ''), None)
    if not item or item['until'] < time.time() or item['redirect'] != request.form.get('redirect_uri'):
        return jsonify(error='invalid_grant'), 400
    digest = hashlib.sha256(request.form['code_verifier'].encode()).digest()
    if base64.urlsafe_b64encode(digest).rstrip(b'=').decode() != item['challenge']:
        return jsonify(error='invalid_grant'), 400
    token = secrets.token_urlsafe(32)
    save_token_hash(item['user'], hashlib.sha256(token.encode()).hexdigest())   # как в TRACKER_API.md
    user = load_user(item['user'])
    return jsonify(access_token=token, token_type='Bearer', user={'name': user.name, 'email': user.email})
```

И впишите адрес Трекера в `src/connector_config.py`: `TRACKER_URL = 'https://ваш-трекер'`.

## Как добавить ещё одно приложение

Новый класс в `src/connectors.py` (по образцу `MiroConnector`): адреса OAuth, `handle()` с голосовыми
фразами — и приложение появится карточкой в «Интеграциях». Для приложений без OAuth — JSON-интеграция или
Python-плагин (docs/INTEGRATIONS.md).
