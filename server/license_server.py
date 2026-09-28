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
from contextlib import contextmanager
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


def private_key_from_disk(folder):
    """Ключ подписи из постоянного хранилища (на Amvera — /data). Создаётся при первом запуске."""
    from cryptography.hazmat.primitives import serialization
    path = Path(folder) / 'license_signing_key'
    if path.exists():
        return load_private_key(path.read_text().strip())
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(base64.b64encode(raw).decode())
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def public_key_text(key):
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def parse_promos(text):
    """«ANDREY2026, FRIENDS:50» → {'ANDREY2026': 0, 'FRIENDS': 50} (0 — без ограничения числа)."""
    promos = {}
    for item in re.split(r'[,;\s]+', str(text or '')):
        code, _, limit = item.partition(':')
        if code.strip():
            promos[code.strip().upper()] = int(limit) if limit.strip().isdigit() else 0
    return promos


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


class TBankKassa:
    """Интернет-эквайринг Т-Банка (Т-Бизнес, API v2): Init → ссылка на оплату, GetState — проверка статуса.

    Деньги приходят на расчётный счёт Т-Бизнеса. Запросы подписываются токеном: SHA-256 от значений
    параметров верхнего уровня + Password, отсортированных по имени параметра.
    """
    API = 'https://securepay.tinkoff.ru/v2'
    PAID = {'CONFIRMED'}
    FAILED = {'REJECTED', 'CANCELED', 'DEADLINE_EXPIRED', 'REVERSED', 'PARTIAL_REVERSED', 'REFUNDED',
              'PARTIAL_REFUNDED', 'AUTH_FAIL'}

    def __init__(self, terminal_key, password, session=None, api=None, taxation='usn_income', notification_url=''):
        self.terminal = terminal_key
        self.password = password
        self.session = session or requests.Session()
        self.api = (api or os.environ.get('TBANK_API') or self.API).rstrip('/')
        self.taxation = taxation
        self.notification_url = notification_url

    @staticmethod
    def token(params, password):
        values = {k: v for k, v in params.items() if k != 'Token' and not isinstance(v, (dict, list))}
        values['Password'] = password
        text = ''.join(('true' if v is True else 'false' if v is False else str(v)) for _, v in sorted(values.items()))
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def _call(self, method, params):
        params = dict(params, TerminalKey=self.terminal)
        params['Token'] = self.token(params, self.password)
        response = self.session.post(f'{self.api}/{method}', json=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        if not data.get('Success') or str(data.get('ErrorCode', '0')) != '0':
            raise ValueError('Т-Банк: ' + (data.get('Message') or data.get('Details') or 'ошибка платежа'))
        return data

    def create(self, plan, email, user_id, return_url):
        info = PLANS[plan]
        kopecks = int(round(float(info['price']) * 100))
        params = {
            'Amount': kopecks, 'OrderId': f'{user_id}-{plan}-{secrets.token_hex(6)}', 'Description': info['title'][:140],
            'SuccessURL': return_url, 'FailURL': return_url, 'DATA': {'Email': email},
            # Чек по 54-ФЗ (Т-Банк отправит его покупателю через подключённую онлайн-кассу).
            'Receipt': {'Email': email, 'Taxation': self.taxation, 'Items': [{
                'Name': info['title'][:128], 'Price': kopecks, 'Quantity': 1, 'Amount': kopecks,
                'Tax': os.environ.get('TBANK_TAX', 'none'), 'PaymentMethod': 'full_payment', 'PaymentObject': 'service'}]},
        }
        if self.notification_url:
            params['NotificationURL'] = self.notification_url
        data = self._call('Init', params)
        return {'id': str(data['PaymentId']), 'status': 'pending', 'paid': False,
                'amount': {'value': info['price'], 'currency': 'RUB'},
                'confirmation': {'confirmation_url': data['PaymentURL']}}

    def get(self, payment_id):
        data = self._call('GetState', {'PaymentId': str(payment_id)})
        status = data.get('Status', '')
        paid = status in self.PAID
        return {'id': str(payment_id), 'paid': paid,
                'status': 'succeeded' if paid else 'canceled' if status in self.FAILED else 'pending',
                'amount': {'value': f"{int(data.get('Amount', 0)) / 100:.2f}", 'currency': 'RUB'}}

    def verify_notification(self, data):
        """Подпись уведомления Т-Банка: тот же токен, что и у запросов."""
        return bool(data.get('Token')) and data.get('TerminalKey') == self.terminal and \
            secrets.compare_digest(str(data['Token']), self.token(data, self.password))


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
    def __init__(self, db_path, private_key, kassa, public_url='', owners=(), owner_password='', promo_codes=''):
        self.db_path = str(db_path)
        self.key = private_key
        self.kassa = kassa
        self.public_url = public_url.rstrip('/')
        self.lock = threading.Lock()
        self.attempts = {}
        # Аккаунты владельца: всегда полный доступ. Зарезервированы — зарегистрировать их чужим нельзя.
        self.owners = {e.strip().casefold() for e in owners if e.strip()}
        self.owner_password = owner_password
        self.promos = parse_promos(promo_codes)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, password TEXT,
                    plan TEXT, expires TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
                CREATE TABLE IF NOT EXISTS promo_uses(code TEXT, user_id INTEGER, used TEXT, PRIMARY KEY(code, user_id));
                CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY, user_id INTEGER, plan TEXT,
                    status TEXT, applied INTEGER DEFAULT 0, created TEXT);
            ''')
        self._ensure_owners()

    def _ensure_owners(self):
        """Создать или обновить аккаунты владельца паролем из OWNER_PASSWORD."""
        if not self.owner_password:
            return
        with self.connect() as db:
            for email in self.owners:
                row = db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
                hashed = generate_password_hash(self.owner_password)
                if row:
                    db.execute("UPDATE users SET password=?, plan='lifetime', expires=NULL WHERE id=?", (hashed, row['id']))
                else:
                    db.execute('INSERT INTO users(email,password,plan,expires,created) VALUES (?,?,?,?,?)',
                               (email, hashed, 'lifetime', None, iso(now())))

    @contextmanager
    def connect(self):
        """Транзакция с гарантированным закрытием соединения (иначе Windows держит файл базы)."""
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

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
        if email in self.owners:
            # Владелец нажал «Регистрация» вместо «Вход»: с верным паролем владельца просто входим.
            if self.owner_password and password == self.owner_password:
                return self.login(email, password)
            raise ValueError('Этот email принадлежит владельцу. Войдите на вкладке «Вход» паролем из OWNER_PASSWORD.')
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
        plan = 'lifetime' if user['email'] in self.owners else user['plan']
        if plan == 'monthly' and (not expires or expires < now()):
            plan = 'free'
        payload = {'email': user['email'], 'plan': plan, 'expires': user['expires'] if plan == 'monthly' else None,
                   'issued': iso(now()), 'v': 1}
        signature = base64.b64encode(self.key.sign(canonical(payload))).decode()
        return {'payload': payload, 'signature': signature}

    # ---- промокоды ----
    def redeem(self, user, code):
        """Промокод даёт подписку навсегда бесплатно. Один код — один раз на аккаунт."""
        code = code.strip().upper()
        if code not in self.promos:
            raise ValueError('Промокод не найден или больше не действует')
        if user['plan'] == 'lifetime' or user['email'] in self.owners:
            raise ValueError('У вас уже подписка навсегда')
        limit = self.promos[code]
        with self.lock, self.connect() as db:
            used = db.execute('SELECT COUNT(*) FROM promo_uses WHERE code=?', (code,)).fetchone()[0]
            if limit and used >= limit:
                raise ValueError('Этот промокод уже использован максимальное число раз')
            if db.execute('SELECT 1 FROM promo_uses WHERE code=? AND user_id=?', (code, user['id'])).fetchone():
                raise ValueError('Вы уже использовали этот промокод')
            db.execute('INSERT INTO promo_uses VALUES (?,?,?)', (code, user['id'], iso(now())))
            db.execute("UPDATE users SET plan='lifetime', expires=NULL WHERE id=?", (user['id'],))

    # ---- оплата ----
    def checkout(self, user, plan):
        if plan not in PLANS:
            raise ValueError('Неизвестный тариф')
        if self.kassa is None:
            raise ValueError('Оплата пока не подключена. Используйте промокод или напишите владельцу.')
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
            # Сумма всегда сверяется; владелец платежа — по метаданным, если провайдер их возвращает
            # (ЮKassa возвращает, Т-Банк — нет: там владелец известен по нашей записи о платеже).
            owner = (payment.get('metadata') or {}).get('user_id')
            if payment['amount']['value'] != PLANS[plan]['price'] or payment['amount']['currency'] != 'RUB' or \
                    (owner is not None and str(owner) != str(row['user_id'])):
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
        # Постоянная папка: на Amvera это /data (persistenceMount), локально — рядом с сервером.
        data = Path(os.environ.get('DATA_DIR') or ('/data' if Path('/data').is_dir() else '.'))
        key_text = os.environ.get('LICENSE_PRIVATE_KEY')
        key = load_private_key(key_text) if key_text else private_key_from_disk(data)
        shop, secret = os.environ.get('YOOKASSA_SHOP_ID'), os.environ.get('YOOKASSA_SECRET_KEY')
        terminal, password = os.environ.get('TBANK_TERMINAL_KEY'), os.environ.get('TBANK_PASSWORD')
        public_url = os.environ.get('PUBLIC_URL', '').rstrip('/')
        if terminal and password:
            # Т-Бизнес: деньги на расчётный счёт в Т-Банке.
            kassa = TBankKassa(terminal, password, taxation=os.environ.get('TBANK_TAXATION', 'usn_income'),
                               notification_url=public_url + '/tbank/webhook' if public_url else '')
        elif shop and secret:
            kassa = YooKassa(shop, secret)
        elif os.environ.get('LICENSE_TEST_MODE') == '1':
            kassa = TestKassa()  # только для отладки: любая «оплата» проходит сразу
        else:
            kassa = None  # вход, регистрация и промокоды работают; оплата — после подключения ЮKassa
        server = LicenseServer(Path(os.environ.get('LICENSE_DB') or data / 'licenses.db'), key, kassa,
                               os.environ.get('PUBLIC_URL', ''),
                               owners=os.environ.get('OWNER_EMAILS', 'orsofey@gmail.com').split(','),
                               owner_password=os.environ.get('OWNER_PASSWORD', ''),
                               promo_codes=os.environ.get('PROMO_CODES', ''))
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
        return {'email': user['email'], 'plan': 'lifetime' if user['email'] in server.owners else user['plan'],
                'expires': user['expires'], 'owner': user['email'] in server.owners,
                'license': server.license(user), 'plans': {k: v['price'] for k, v in PLANS.items()}}

    @app.errorhandler(ValueError)
    def bad(exc):
        return jsonify(success=False, message=str(exc)), 400

    @app.errorhandler(PermissionError)
    def denied(exc):
        return jsonify(success=False, message=str(exc)), 401

    @app.get('/health')
    def health():
        return jsonify(success=True, test_mode=isinstance(server.kassa, TestKassa), payments=server.kassa is not None)

    @app.get('/api/public-key')
    def public_key():
        """Открытый ключ проверки лицензий (приложение запоминает его при первом подключении)."""
        return jsonify(success=True, public_key=public_key_text(server.key))

    @app.post('/api/promo')
    def promo():
        user = server.user(token())
        server.redeem(user, str((request.get_json(silent=True) or {}).get('code', '')))
        return jsonify(success=True, **account(server.user(token())))

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

    @app.post('/tbank/webhook')
    def tbank_webhook():
        """Уведомление Т-Банка. Проверяем подпись, затем статус всё равно перепроверяем через GetState."""
        data = request.get_json(silent=True) or {}
        kassa = server.kassa
        if isinstance(kassa, TBankKassa) and kassa.verify_notification(data):
            payment_id = str(data.get('PaymentId', ''))
            if re.fullmatch(r'\d{1,20}', payment_id):
                server.apply(payment_id)
            return 'OK', 200  # Т-Банк ждёт ровно «OK», иначе будет повторять уведомление
        return 'bad token', 400

    @app.post('/yookassa/webhook')
    def webhook():
        """Уведомление ЮKassa. Содержимому не доверяем: статус перепроверяется запросом к API."""
        data = request.get_json(silent=True) or {}
        payment_id = str((data.get('object') or {}).get('id', ''))
        if re.fullmatch(r'[\w-]{8,64}', payment_id):
            server.apply(payment_id)
        return '', 200

    @app.get('/')
    def home():
        """Главная страница сервера — чтобы по адресу проекта было видно, что всё работает."""
        payments = 'подключена' if server.kassa is not None else 'не подключена (вход и промокоды работают)'
        return ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                '<title>Андрей — сервер аккаунтов</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;'
                'font-family:system-ui;background:linear-gradient(135deg,#0b1020,#16243f);color:#eaf2ff">'
                '<div style="max-width:520px;padding:32px;border-radius:20px;background:rgba(255,255,255,.06);'
                'border:1px solid rgba(150,200,255,.2)"><h1 style="margin-top:0">✅ Сервер аккаунтов «Андрей» работает</h1>'
                f'<p>Оплата: {payments}.</p><p>Вставьте адрес этой страницы в приложении: Настройки → '
                '«Аккаунт и подписка» → «Адрес сервера».</p><p style="opacity:.7">Проверка: <a style="color:#5ef2c2" '
                'href="/health">/health</a></p></div></body></html>')

    @app.get('/paid')
    def paid():
        return ('<!doctype html><meta charset="utf-8"><title>Оплата</title>'
                '<body style="font-family:system-ui;text-align:center;padding:60px">'
                '<h1>Спасибо!</h1><p>Вернитесь в приложение «Андрей» — подписка включится автоматически.</p>')

    return app
