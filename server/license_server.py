"""Сервер аккаунтов и подписки «Андрей».

Регистрация и вход по email, оплата через ЮKassa (100 ₽ в месяц или 500 ₽ навсегда)
и выдача лицензии, подписанной Ed25519. Приложение проверяет подпись офлайн открытым ключом,
поэтому подделать лицензию без закрытого ключа сервера нельзя.

Запуск (Linux VPS, за HTTPS-прокси nginx/caddy):
    export LICENSE_PRIVATE_KEY=...        # из generate_keys.py
    export YOOKASSA_SHOP_ID=... YOOKASSA_SECRET_KEY=...
    export PUBLIC_URL=https://license.example.ru
    waitress-serve --port 8080 --call license_server:create_app

Для отладки без ЮKassa: LICENSE_TEST_MODE=1 — оплата подтверждается сразу (не включайте в продакшене).
"""
import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

PLANS = {
    'monthly': {'price': '100.00', 'days': 30, 'title': 'Подписка «Андрей» на 1 месяц'},
    'lifetime': {'price': '500.00', 'days': None, 'title': 'Подписка «Андрей» навсегда'},
}
YOOKASSA_API = 'https://api.yookassa.ru/v3'
TOKEN_DAYS = 180
EMAIL = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$')


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if value else None


def parse_iso(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) if value else None


def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def load_private_key(text):
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(text))


class YooKassa:
    """Минимальный клиент API ЮKassa: создание платежа и проверка статуса."""

    def __init__(self, shop_id, secret_key, session=None):
        self.auth = (shop_id, secret_key)
        self.session = session or requests.Session()

    def create(self, plan, email, user_id, return_url):
        info = PLANS[plan]
        amount = {'value': info['price'], 'currency': 'RUB'}
        body = {
            'amount': amount, 'capture': True, 'description': info['title'],
            'confirmation': {'type': 'redirect', 'return_url': return_url},
            'metadata': {'user_id': str(user_id), 'plan': plan},
            # Чек по 54-ФЗ: ЮKassa отправит его покупателю на email.
            'receipt': {'customer': {'email': email}, 'items': [{
                'description': info['title'][:128], 'quantity': '1.00', 'amount': amount,
                'vat_code': int(os.environ.get('YOOKASSA_VAT_CODE', '1')),
                'payment_mode': 'full_payment', 'payment_subject': 'service'}]},
        }
        response = self.session.post(YOOKASSA_API + '/payments', json=body, auth=self.auth, timeout=20,
                                     headers={'Idempotence-Key': str(uuid.uuid4())})
        response.raise_for_status()
        return response.json()

    def get(self, payment_id):
        response = self.session.get(f'{YOOKASSA_API}/payments/{payment_id}', auth=self.auth, timeout=20)
        response.raise_for_status()
        return response.json()


class TestKassa:
    """Тестовый режим без ЮKassa: платёж сразу считается оплаченным."""

    def __init__(self):
        self.payments = {}

    def create(self, plan, email, user_id, return_url):
        payment = {'id': 'test-' + secrets.token_hex(8), 'status': 'succeeded', 'paid': True,
                   'amount': {'value': PLANS[plan]['price'], 'currency': 'RUB'},
                   'metadata': {'user_id': str(user_id), 'plan': plan},
                   'confirmation': {'confirmation_url': return_url}}
        self.payments[payment['id']] = payment
        return payment

    def get(self, payment_id):
        return self.payments[payment_id]


class LicenseServer:
    def __init__(self, db_path, private_key, kassa, public_url=''):
        self.db_path = str(db_path)
        self.key = private_key
        self.kassa = kassa
        self.public_url = public_url.rstrip('/')
        self.lock = threading.Lock()
        self.attempts = {}
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, password TEXT,
                    plan TEXT, expires TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
                CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY, user_id INTEGER, plan TEXT,
                    status TEXT, applied INTEGER DEFAULT 0, created TEXT);
            ''')

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    # ---- аккаунты ----
    def throttle(self, key):
        """Не больше 10 попыток входа за 10 минут с одного адреса/email."""
        stamp = time.monotonic()
        recent = [t for t in self.attempts.get(key, []) if stamp - t < 600]
        if len(recent) >= 10:
            raise PermissionError('Слишком много попыток. Повторите через 10 минут.')
        self.attempts[key] = recent + [stamp]

    def register(self, email, password):
        email = email.strip().casefold()
        if not EMAIL.match(email):
            raise ValueError('Введите корректный email')
        if not 8 <= len(password) <= 200:
            raise ValueError('Пароль: от 8 символов')
        with self.lock, self.connect() as db:
            if db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
                raise ValueError('Этот email уже зарегистрирован. Войдите.')
            cursor = db.execute('INSERT INTO users(email,password,plan,expires,created) VALUES (?,?,?,?,?)',
                                (email, generate_password_hash(password), 'free', None, iso(now())))
            return self.issue_token(db, cursor.lastrowid)

    def login(self, email, password, remote=''):
        email = email.strip().casefold()
        self.throttle(remote + '|' + email)
        with self.connect() as db:
            row = db.execute('SELECT id,password FROM users WHERE email=?', (email,)).fetchone()
            if not row or not check_password_hash(row['password'], password):
                raise PermissionError('Неверный email или пароль')
            return self.issue_token(db, row['id'])

    @staticmethod
    def issue_token(db, user_id):
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO tokens VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user_id,
                                                         time.time() + TOKEN_DAYS * 86400))
        return token

    def user(self, token):
        with self.connect() as db:
            row = db.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.hash=? AND t.expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            raise PermissionError('Войдите в аккаунт заново')
        return dict(row)

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM tokens WHERE hash=?', (hashlib.sha256(token.encode()).hexdigest(),))

    # ---- лицензия ----
    def license(self, user):
        expires = parse_iso(user['expires'])
        plan = user['plan']
        if plan == 'monthly' and (not expires or expires < now()):
            plan = 'free'
        payload = {'email': user['email'], 'plan': plan, 'expires': user['expires'] if plan == 'monthly' else None,
                   'issued': iso(now()), 'v': 1}
        signature = base64.b64encode(self.key.sign(canonical(payload))).decode()
        return {'payload': payload, 'signature': signature}

    # ---- оплата ----
    def checkout(self, user, plan):
        if plan not in PLANS:
            raise ValueError('Неизвестный тариф')
        if user['plan'] == 'lifetime':
            raise ValueError('У вас уже подписка навсегда')
        return_url = (self.public_url or request.host_url.rstrip('/')) + '/paid'
        payment = self.kassa.create(plan, user['email'], user['id'], return_url)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO payments(id,user_id,plan,status,created) VALUES (?,?,?,?,?)',
                       (payment['id'], user['id'], plan, payment['status'], iso(now())))
        if payment.get('status') == 'succeeded':
            self.apply(payment['id'])
        return {'payment_id': payment['id'], 'url': payment['confirmation']['confirmation_url']}

    def apply(self, payment_id):
        """Проверить платёж в ЮKassa (не доверяя входящему уведомлению) и продлить подписку один раз."""
        payment = self.kassa.get(payment_id)
        with self.lock, self.connect() as db:
            row = db.execute('SELECT * FROM payments WHERE id=?', (payment_id,)).fetchone()
            if not row:
                return 'unknown'
            db.execute('UPDATE payments SET status=? WHERE id=?', (payment['status'], payment_id))
            if payment['status'] != 'succeeded' or not payment.get('paid') or row['applied']:
                return payment['status']
            plan = row['plan']
            if payment['amount']['value'] != PLANS[plan]['price'] or payment['amount']['currency'] != 'RUB' or \
                    str(payment.get('metadata', {}).get('user_id')) != str(row['user_id']):
                return 'mismatch'
            user = db.execute('SELECT plan,expires FROM users WHERE id=?', (row['user_id'],)).fetchone()
            if plan == 'lifetime':
                db.execute("UPDATE users SET plan='lifetime', expires=NULL WHERE id=?", (row['user_id'],))
            elif user['plan'] != 'lifetime':
                start = max(now(), parse_iso(user['expires']) or now())
                db.execute("UPDATE users SET plan='monthly', expires=? WHERE id=?",
                           (iso(start + timedelta(days=PLANS[plan]['days'])), row['user_id']))
            db.execute('UPDATE payments SET applied=1 WHERE id=?', (payment_id,))
            return 'succeeded'


def create_app(server=None):
    if server is None:
        key_text = os.environ.get('LICENSE_PRIVATE_KEY')
        if not key_text:
            raise SystemExit('Задайте LICENSE_PRIVATE_KEY (python generate_keys.py)')
        shop, secret = os.environ.get('YOOKASSA_SHOP_ID'), os.environ.get('YOOKASSA_SECRET_KEY')
        if shop and secret:
            kassa = YooKassa(shop, secret)
        elif os.environ.get('LICENSE_TEST_MODE') == '1':
            kassa = TestKassa()  # только для отладки: любая «оплата» проходит сразу
        else:
            raise SystemExit('Задайте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY (или LICENSE_TEST_MODE=1 для отладки)')
        server = LicenseServer(Path(os.environ.get('LICENSE_DB', 'licenses.db')), load_private_key(key_text), kassa,
                               os.environ.get('PUBLIC_URL', ''))
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
    app.extensions['license_server'] = server

    def token():
        header = request.headers.get('Authorization', '')
        return header[7:] if header.startswith('Bearer ') else ''

    def body():
        data = request.get_json(silent=True) or {}
        return str(data.get('email', '')), str(data.get('password', '')), data

    def account(user):
        return {'email': user['email'], 'plan': user['plan'], 'expires': user['expires'],
                'license': server.license(user), 'plans': {k: v['price'] for k, v in PLANS.items()}}

    @app.errorhandler(ValueError)
    def bad(exc):
        return jsonify(success=False, message=str(exc)), 400

    @app.errorhandler(PermissionError)
    def denied(exc):
        return jsonify(success=False, message=str(exc)), 401

    @app.get('/health')
    def health():
        return jsonify(success=True, test_mode=isinstance(server.kassa, TestKassa))

    @app.post('/api/register')
    def register():
        email, password, _ = body()
        new_token = server.register(email, password)
        return jsonify(success=True, token=new_token, **account(server.user(new_token)))

    @app.post('/api/login')
    def login():
        email, password, _ = body()
        new_token = server.login(email, password, request.remote_addr or '')
        return jsonify(success=True, token=new_token, **account(server.user(new_token)))

    @app.post('/api/logout')
    def logout():
        server.logout(token())
        return jsonify(success=True)

    @app.get('/api/me')
    def me():
        return jsonify(success=True, **account(server.user(token())))

    @app.post('/api/checkout')
    def checkout():
        user = server.user(token())
        return jsonify(success=True, **server.checkout(user, str((request.get_json(silent=True) or {}).get('plan'))))

    @app.get('/api/payments/<payment_id>')
    def payment_status(payment_id):
        user = server.user(token())
        with server.connect() as db:
            row = db.execute('SELECT user_id FROM payments WHERE id=?', (payment_id,)).fetchone()
        if not row or row['user_id'] != user['id']:
            return jsonify(success=False, message='Платёж не найден'), 404
        status = server.apply(payment_id)
        return jsonify(success=True, status=status, **account(server.user(token())))

    @app.post('/yookassa/webhook')
    def webhook():
        """Уведомление ЮKassa. Содержимому не доверяем: статус перепроверяется запросом к API."""
        data = request.get_json(silent=True) or {}
        payment_id = str((data.get('object') or {}).get('id', ''))
        if re.fullmatch(r'[\w-]{8,64}', payment_id):
            server.apply(payment_id)
        return '', 200

    @app.get('/paid')
    def paid():
        return ('<!doctype html><meta charset="utf-8"><title>Оплата</title>'
                '<body style="font-family:system-ui;text-align:center;padding:60px">'
                '<h1>Спасибо!</h1><p>Вернитесь в приложение «Андрей» — подписка включится автоматически.</p>')

    return app
