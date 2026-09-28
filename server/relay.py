"""Мост «телефон ↔ ПК через интернет» для «Андрея».

ПК держит к серверу исходящее соединение (долгий опрос) — поэтому не нужны ни белый IP, ни проброс портов,
ни одна сеть Wi-Fi с телефоном. Телефон отправляет команду на сервер, сервер отдаёт её ПК и возвращает ответ.

Защита: у каждого ПК случайный номер моста и ключ — HMAC от кода подключения ПК. Сервер хранит только
SHA-256 ключа и ничего не пишет на диск: команды живут в памяти, пока ПК их не забрал.
"""
import hashlib
import secrets
import threading
import time

POLL_SECONDS = 25        # сколько ПК ждёт команду в одном запросе
REPLY_SECONDS = 110      # сколько телефон ждёт ответ ПК
ONLINE_SECONDS = 60      # ПК считается в сети, если опрашивал сервер недавно
MAX_QUEUE = 20
ALLOWED = {'/api/chat', '/api/transcribe', '/api/history', '/api/cancel', '/api/connection'}


class RelayError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def digest(key):
    return hashlib.sha256(str(key).encode()).hexdigest()


class Relay:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Condition()
        self.bridges = {}  # rid → {'key': sha256, 'queue': [...], 'replies': {}, 'seen': t}

    def _bridge(self, rid, key, create=False):
        if not (isinstance(rid, str) and 16 <= len(rid) <= 64 and rid.replace('-', '').replace('_', '').isalnum()):
            raise RelayError('Неверный номер моста')
        if not (isinstance(key, str) and 32 <= len(key) <= 128):
            raise RelayError('Неверный ключ моста', 403)
        bridge = self.bridges.get(rid)
        if bridge is None:
            if not create:
                raise RelayError('Компьютер не подключён к мосту. Запустите «Андрея» на ПК и включите '
                                 '«Доступ через интернет».', 503)
            if len(self.bridges) > 10000:
                raise RelayError('Мост перегружен', 503)
            bridge = self.bridges[rid] = {'key': digest(key), 'queue': [], 'replies': {}, 'seen': 0.0}
        if not secrets.compare_digest(bridge['key'], digest(key)):
            raise RelayError('Неверный ключ моста', 403)
        return bridge

    # ---- ПК ----
    def poll(self, rid, key, wait=POLL_SECONDS):
        """ПК забирает команды (ждёт до wait секунд)."""
        deadline = self.clock() + min(float(wait), POLL_SECONDS)
        with self.lock:
            bridge = self._bridge(rid, key, create=True)
            bridge['seen'] = self.clock()
            while not bridge['queue']:
                left = deadline - self.clock()
                if left <= 0:
                    break
                self.lock.wait(min(left, 1.0))
                bridge['seen'] = self.clock()
            items, bridge['queue'] = bridge['queue'], []
            return items

    def reply(self, rid, key, request_id, status, body):
        with self.lock:
            bridge = self._bridge(rid, key)
            bridge['replies'][str(request_id)] = {'status': int(status), 'body': body}
            self.lock.notify_all()

    # ---- телефон ----
    def call(self, rid, key, request, wait=REPLY_SECONDS):
        """Отправить запрос телефона на ПК и дождаться ответа."""
        path = str(request.get('path', ''))
        if path not in ALLOWED:
            raise RelayError('Этот запрос через мост недоступен', 403)
        with self.lock:
            bridge = self._bridge(rid, key)
            if self.clock() - bridge['seen'] > ONLINE_SECONDS:
                raise RelayError('Компьютер не в сети: запустите «Андрея» на ПК и проверьте интернет.', 503)
            if len(bridge['queue']) >= MAX_QUEUE:
                raise RelayError('Слишком много запросов, повторите позже', 429)
            request_id = secrets.token_hex(8)
            bridge['queue'].append({'id': request_id, 'method': request.get('method', 'POST'), 'path': path,
                                    'json': request.get('json'), 'audio': request.get('audio'),
                                    'language': request.get('language'), 'device': request.get('device')})
            self.lock.notify_all()
            deadline = self.clock() + wait
            while request_id not in bridge['replies']:
                left = deadline - self.clock()
                if left <= 0:
                    bridge['queue'] = [q for q in bridge['queue'] if q['id'] != request_id]
                    raise RelayError('Компьютер не ответил вовремя', 504)
                self.lock.wait(min(left, 1.0))
            return bridge['replies'].pop(request_id)

    def online(self, rid):
        bridge = self.bridges.get(rid)
        return bool(bridge and self.clock() - bridge['seen'] <= ONLINE_SECONDS)
