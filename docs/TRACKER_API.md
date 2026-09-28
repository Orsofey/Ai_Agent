# Трекер ↔ «Андрей»: онлайн-подключение

Как это работает — так же, как у сервисов с кнопкой «Подключить ассистента»:

1. В «Андрее»: Настройки → **Трекер** → адрес Трекера + ваш логин и пароль → «Войти в Трекер».
2. Трекер проверяет пароль и выдаёт **токен доступа** для ассистента. Пароль нигде не сохраняется;
   токен лежит только на вашем ПК и отзывается в Трекере в любой момент.
3. Дальше каждый голосовой запрос — это запрос к API Трекера в реальном времени:

| Говорите | Запрос к Трекеру |
|---|---|
| «Что в трекере на сегодня?», «Мои задачи на завтра» | `GET /api/agent/tasks?date=2026-09-28` |
| «Добавь в трекер задачу купить молоко на завтра» | `POST /api/agent/tasks` |
| «Отметь задачу купить молоко» | `POST /api/agent/tasks/complete` |
| «Отметь привычку зарядка» | `POST /api/agent/habits/check` |
| «Как у меня с привычками на этой неделе?», «Что я не доделал?» | `GET /api/agent/summary` — нейросеть отвечает по этим данным |

## Что добавить в код Трекера

Трекеру нужен сервер (бэкенд) с базой данных, где лежат ваши задачи и привычки, и шесть
адресов API ниже. Если сейчас Трекер хранит данные только в браузере или в артефакте claude.ai,
программа на ПК не может до них достучаться. Тогда данные нужно перенести на сервер: подойдёт
тот же Amvera, где работает сервер аккаунтов. Сам интерфейс Трекера при этом почти не меняется:
он начинает читать и сохранять данные через этот же сервер. Пришлите код или ссылку на
репозиторий Трекера — я допишу эти адреса под его структуру данных.

Все ответы — JSON в UTF-8. Ошибка — HTTP-код 4xx и `{"error": "текст для пользователя"}`.
Авторизация — заголовок `Authorization: Bearer <токен>`. Адрес — только `https://`.

### Вход и выход

```
POST /api/agent/login
{"email": "me@example.ru", "password": "…", "client": "Андрей"}
→ 200 {"token": "длинная-случайная-строка", "user": {"name": "Орсофей", "email": "me@example.ru"}}
→ 401 {"error": "Неверный логин или пароль"}

GET  /api/agent/me        → {"user": {"name": "…", "email": "…"}}      (проверка токена)
POST /api/agent/logout    → {"ok": true}                               (токен отзывается)
```

Токен: не меньше 32 случайных символов (например, `secrets.token_urlsafe(32)`).
В базе храните его хеш (SHA-256), а не сам токен, как пароль. Если токен отозван или истёк,
Трекер отвечает 401, и «Андрей» попросит войти заново.

### Задачи

```
GET /api/agent/tasks?date=2026-09-28
→ {"tasks": [{"id": "1", "title": "Купить молоко", "done": false, "time": "18:00"}, …]}

POST /api/agent/tasks
{"title": "Позвонить маме", "date": "2026-09-29"}
→ {"ok": true, "id": "57"}

POST /api/agent/tasks/complete
{"title": "купить молоко", "date": "2026-09-28"}
→ {"ok": true, "title": "Купить молоко"}
```

Название в `complete` приходит так, как его сказали голосом. Ищите задачу без учёта регистра
и по началу слов: «купить молоко» → «Купить молоко 2 л».

### Привычки

```
POST /api/agent/habits/check
{"name": "зарядка", "date": "2026-09-28"}
→ {"ok": true, "name": "Зарядка", "streak": 12}
```

### Сводка для вопросов нейросети

```
GET /api/agent/summary?date=2026-09-28
→ {
    "text": "Сегодня 3 из 5 задач выполнено, привычки: зарядка 12 дней подряд.",
    "today": {"tasks": [...], "habits": [{"name": "Зарядка", "done": true, "streak": 12}]},
    "week": {"done": 21, "total": 30, "habits": {"Зарядка": 6, "Чтение": 3}},
    "goals": [{"title": "Пробежать 10 км", "progress": 0.6}]
  }
```

Состав сводки свободный: всё, что в ней есть, нейросеть использует для ответа. Вопрос при
этом должен касаться задач, привычек, целей или планов. Сводка до ~6000 символов JSON.

## Пример сервера (Python, Flask)

```python
import hashlib, secrets
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

def user_by_token():
    token = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
    user = db.find_user_by_token_hash(hashlib.sha256(token.encode()).hexdigest())  # ваша база
    if not user:
        abort(401)
    return user

@app.post('/api/agent/login')
def login():
    data = request.get_json()
    user = db.check_password(data['email'], data['password'])
    if not user:
        return jsonify(error='Неверный логин или пароль'), 401
    token = secrets.token_urlsafe(32)
    db.save_token(user.id, hashlib.sha256(token.encode()).hexdigest(), client=data.get('client'))
    return jsonify(token=token, user={'name': user.name, 'email': user.email})

@app.get('/api/agent/tasks')
def tasks():
    user = user_by_token()
    items = db.tasks(user.id, request.args['date'])
    return jsonify(tasks=[{'id': t.id, 'title': t.title, 'done': t.done} for t in items])
```

## Альтернатива без пароля: кнопка в Трекере

Можно добавить в Трекер кнопку «Подключить ассистента», которая показывает токен. В «Андрее»
его вставляют в поле «или токен доступа». Для проверки такого токена используется `GET /api/agent/me`.
