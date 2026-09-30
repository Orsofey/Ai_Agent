"""Поддержка: «Ваши предложения» из приложения — владельцу в Telegram.

Переменные окружения (Amvera → Переменные / Секреты):
    SUPPORT_TELEGRAM     — ваш ник в Telegram без @ (кнопка «Написать лично» откроет чат с вами);
    TELEGRAM_BOT_TOKEN   — токен бота от @BotFather (секрет);
    TELEGRAM_CHAT_ID     — куда бот пересылает предложения: ваш chat id (напишите боту /start,
                           затем откройте https://<сервер>/support/chat-id?key=<OWNER_PASSWORD>).

Без бота предложения всё равно сохраняются в базе (таблица feedback) и видны по /support/list?key=<OWNER_PASSWORD>.
"""
import hashlib
import html
import os
import re
import secrets
import threading
import time

import requests

TELEGRAM_API = 'https://api.telegram.org/bot{token}/{method}'
MAX_TEXT = 3000
USERNAME = re.compile(r'^[A-Za-z][A-Za-z0-9_]{3,31}$')


class Support:
    def __init__(self, server, telegram='', bot_token='', chat_id='', session=None):
        self.server = server
        self.telegram = telegram.strip().lstrip('@') if USERNAME.match(telegram.strip().lstrip('@') or '-') else ''
        self.bot_token = bot_token.strip()
        self.chat_id = str(chat_id).strip()
        self.session = session or requests.Session()
        self.attempts = {}
        self.lock = threading.Lock()
        self.ready = False

    def _ensure(self):
        """Таблица предложений создаётся при первом обращении."""
        if not self.ready:
            with self.server.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, created TEXT, email TEXT, '
                           'contact TEXT, text TEXT, version TEXT, platform TEXT, delivered INTEGER DEFAULT 0)')
            self.ready = True

    @classmethod
    def from_env(cls, server):
        return cls(server, os.environ.get('SUPPORT_TELEGRAM', ''), os.environ.get('TELEGRAM_BOT_TOKEN', ''),
                   os.environ.get('TELEGRAM_CHAT_ID', ''))

    def info(self):
        return {'telegram': self.telegram, 'link': f'https://t.me/{self.telegram}' if self.telegram else '',
                'bot': bool(self.bot_token and self.chat_id)}

    def throttle(self, key):
        """Не больше 5 предложений за 10 минут с одного адреса — защита от спама."""
        stamp = time.monotonic()
        with self.lock:
            recent = [t for t in self.attempts.get(key, []) if stamp - t < 600]
            if len(recent) >= 5:
                raise PermissionError('Слишком много сообщений подряд. Повторите через 10 минут.')
            self.attempts[key] = recent + [stamp]

    def submit(self, text, contact='', email='', version='', platform='', remote=''):
        text = str(text or '').strip()
        if len(text) < 3:
            raise ValueError('Напишите предложение — хотя бы пару слов.')
        text = text[:MAX_TEXT]
        contact = str(contact or '').strip()[:200]
        self.throttle(remote or 'unknown')
        from license_server import iso, now
        self._ensure()
        with self.server.connect() as db:
            cursor = db.execute('INSERT INTO feedback(created,email,contact,text,version,platform) VALUES (?,?,?,?,?,?)',
                                (iso(now()), email, contact, text, str(version)[:20], str(platform)[:20]))
            feedback_id = cursor.lastrowid
        delivered = self.forward(feedback_id, text, contact, email, version, platform)
        if delivered:
            with self.server.connect() as db:
                db.execute('UPDATE feedback SET delivered=1 WHERE id=?', (feedback_id,))
        return {'id': feedback_id, 'delivered': delivered}

    def forward(self, feedback_id, text, contact, email, version, platform):
        if not (self.bot_token and self.chat_id):
            return False
        who = ' · '.join(x for x in (email, contact) if x) or 'без контакта'
        message = (f'💡 <b>Предложение №{feedback_id}</b>\n{html.escape(text)}\n\n'
                   f'<i>{html.escape(who)} · «Андрей» {html.escape(str(version))} · {html.escape(str(platform))}</i>')
        try:
            response = self.session.post(TELEGRAM_API.format(token=self.bot_token, method='sendMessage'),
                                         json={'chat_id': self.chat_id, 'text': message, 'parse_mode': 'HTML',
                                               'disable_web_page_preview': True}, timeout=15)
            return response.ok and bool(response.json().get('ok'))
        except (requests.RequestException, ValueError):
            return False

    def chat_ids(self):
        """Кто писал боту /start — чтобы владелец узнал свой TELEGRAM_CHAT_ID."""
        if not self.bot_token:
            return []
        response = self.session.get(TELEGRAM_API.format(token=self.bot_token, method='getUpdates'), timeout=15)
        found = {}
        for update in (response.json().get('result') or []):
            chat = (update.get('message') or {}).get('chat') or {}
            if chat.get('id') is not None:
                found[chat['id']] = chat.get('username') or chat.get('first_name') or ''
        return [{'chat_id': k, 'name': v} for k, v in found.items()]

    def listing(self, limit=100):
        self._ensure()
        with self.server.connect() as db:
            rows = db.execute('SELECT * FROM feedback ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]


def owner_key_ok(server, key):
    """Служебные страницы поддержки открываются только с паролем владельца."""
    expected = getattr(server, 'owner_password', '')
    return bool(expected) and secrets.compare_digest(hashlib.sha256(str(key).encode()).digest(),
                                                     hashlib.sha256(expected.encode()).digest())


def register(app, server, support):
    from flask import jsonify, request

    @app.get('/api/support')
    def support_info():
        return jsonify(success=True, **support.info())

    @app.post('/api/support/feedback')
    def support_feedback():
        data = request.get_json(silent=True) or {}
        email = ''
        header = request.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            try:
                email = server.user(header[7:])['email']
            except PermissionError:
                email = ''
        result = support.submit(data.get('text'), data.get('contact'), email, data.get('version', ''),
                                data.get('platform', ''), request.remote_addr or '')
        return jsonify(success=True, **result, **support.info())

    @app.get('/support/chat-id')
    def support_chat_id():
        if not owner_key_ok(server, request.args.get('key', '')):
            return jsonify(success=False, message='Нужен ?key=<OWNER_PASSWORD>'), 403
        return jsonify(success=True, chats=support.chat_ids())

    @app.get('/support/list')
    def support_list():
        if not owner_key_ok(server, request.args.get('key', '')):
            return jsonify(success=False, message='Нужен ?key=<OWNER_PASSWORD>'), 403
        return jsonify(success=True, feedback=support.listing())
