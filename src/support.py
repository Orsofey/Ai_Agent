"""«Ваши предложения»: отзыв или идея — разработчику лично в Telegram.

Приложение отправляет предложение на сервер аккаунтов (server/support.py), а сервер пересылает его владельцу
ботом в Telegram. Кнопка «Написать лично» открывает чат с разработчиком (ник задаётся на сервере переменной
SUPPORT_TELEGRAM или здесь, в SUPPORT_TELEGRAM). Если сервер недоступен, предложение сохраняется в папке данных
и уходит при следующей попытке.

Голосом: «Андрей, предложение: добавь управление кондиционером», «хочу предложить …», «сообщи об ошибке …».
"""
import json
import logging
import re
import sys
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)

# Ник разработчика в Telegram (без @) — запасной вариант, если сервер аккаунтов не задал SUPPORT_TELEGRAM.
SUPPORT_TELEGRAM = ''
CACHE_SECONDS = 600

VOICE = re.compile(r'^(?:у меня\s+)?(?:есть\s+)?(?:предложени[ея]|идея|пожелани[ея]|отзыв|жалоба)\s*[:,—-]?\s*(?P<text>.{3,})$'
                   r'|^(?:хочу|хотел\w*|могу)\s+(?:предложить|посоветовать|пожаловаться)\s*[:,—-]?\s*(?:чтобы\s+)?(?P<text2>.{3,})$'
                   r'|^(?:напиши|передай|отправь|сообщи)\s+(?:разработчику|автору|в поддержку|создателю)\s*[:,—-]?\s*'
                   r'(?:что\s+)?(?P<text3>.{3,})$'
                   r'|^сообщи\s+об\s+(?:ошибке|баге|проблеме)\s*[:,—-]?\s*(?P<text4>.{3,})$', re.I | re.S)
OPEN = re.compile(r'^(?:открой|покажи)\s+(?:ваши\s+)?предложени[яе]|^(?:напиши|написать|связаться с)\s+(?:разработчику|автору)'
                  r'(?:\s+лично)?(?:\s+в\s+(?:телеграм\w*|тг))?$', re.I)


def parse(text):
    """('send', текст) | ('open',) | None."""
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!')
    if OPEN.match(value):
        return ('open',)
    match = VOICE.match(value)
    if match:
        body = next(g for g in match.groups() if g)
        return 'send', body.strip()
    return None


class Support:
    def __init__(self, store, license=None, version='', opener=None, events=None):
        self.store = store
        self.license = license
        self.version = version
        self.opener = opener
        self.events = events
        self._info = None
        self._info_at = 0.0
        self.lock = threading.Lock()

    # ---- куда писать ----
    def info(self, refresh=False):
        with self.lock:
            if not refresh and self._info is not None and time.monotonic() - self._info_at < CACHE_SECONDS:
                return dict(self._info)
        info = {'telegram': SUPPORT_TELEGRAM, 'bot': False, 'server': False}
        server = getattr(self.license, 'server_url', '') if self.license is not None else ''
        if server:
            try:
                response = self.license.session.request('GET', server + '/api/support', json=None, headers={}, timeout=8)
                data = response.json()
                if data.get('success'):
                    info.update(server=True, bot=bool(data.get('bot')), telegram=data.get('telegram') or info['telegram'])
            except Exception as exc:  # нет интернета — не страшно, покажем форму всё равно
                log.info('Support info unavailable: %s', exc)
        info['link'] = f"https://t.me/{info['telegram']}" if info['telegram'] else ''
        with self.lock:
            self._info, self._info_at = info, time.monotonic()
        return dict(info)

    # ---- отправка ----
    def _outbox(self):
        return self.store.root / 'feedback_outbox.jsonl'

    def send(self, text, contact=''):
        text = str(text or '').strip()
        if len(text) < 3:
            raise ValueError('Напишите предложение — хотя бы пару слов.')
        item = {'text': text[:3000], 'contact': str(contact or '').strip()[:200], 'version': self.version,
                'platform': sys.platform, 'created': datetime.now().isoformat(timespec='seconds')}
        self.flush()
        sent = self._post(item)
        if sent is None:
            with open(self._outbox(), 'a', encoding='utf-8') as file:
                file.write(json.dumps(item, ensure_ascii=False) + '\n')
            info = self.info()
            tail = ' Можно написать лично — кнопка «Написать в Telegram».' if info.get('link') else ''
            return {'delivered': False, 'queued': True,
                    'message': 'Нет связи с сервером — сохранил предложение, отправлю позже.' + tail}
        if sent.get('delivered'):
            message = 'Спасибо! Предложение уже у разработчика в Telegram.'
        else:
            message = 'Спасибо! Предложение получено — разработчик его прочитает.'
        return {'delivered': bool(sent.get('delivered')), 'queued': False, 'message': message, 'id': sent.get('id')}

    def _post(self, item):
        license = self.license
        server = getattr(license, 'server_url', '') if license is not None else ''
        if not server:
            return None
        headers = {}
        token = self.store.meta('account_token')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            response = license.session.request('POST', server + '/api/support/feedback', json=item, headers=headers,
                                                timeout=15)
            data = response.json()
        except Exception as exc:
            log.info('Feedback not sent: %s', exc)
            return None
        if response.status_code == 400 or response.status_code == 401:
            raise ValueError(data.get('message') or 'Сервер не принял сообщение.')
        return data if data.get('success') else None

    def flush(self):
        """Отправить то, что не ушло без интернета."""
        path = self._outbox()
        if not path.exists():
            return 0
        try:
            lines = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        except (OSError, ValueError):
            return 0
        left, sent = [], 0
        for item in lines:
            try:
                ok = self._post(item) is not None
            except ValueError:
                ok = True  # сервер отклонил — повторять бессмысленно
            if ok:
                sent += 1
            else:
                left.append(item)
        if left:
            path.write_text(''.join(json.dumps(i, ensure_ascii=False) + '\n' for i in left), encoding='utf-8')
        else:
            path.unlink(missing_ok=True)
        return sent

    def open_telegram(self, text=''):
        """Открыть личный чат с разработчиком; текст — в буфер обмена, чтобы вставить Ctrl+V."""
        info = self.info()
        if not info.get('link'):
            return {'opened': False, 'message': 'Разработчик ещё не указал Telegram. Отправьте предложение через форму.'}
        copied = False
        if text:
            try:
                import pyperclip
                pyperclip.copy(text)
                copied = True
            except Exception:
                copied = False
        if self.opener is not None:
            self.opener(info['link'])
        return {'opened': True, 'link': info['link'], 'copied': copied,
                'message': 'Открываю Telegram.' + (' Текст в буфере обмена — вставьте Ctrl+V.' if copied else '')}

    # ---- голос ----
    def handle(self, text):
        request = parse(text)
        if request is None:
            return None
        if request[0] == 'open':
            if self.events is not None:
                self.events.emit('support', action='open')
            info = self.info()
            if info.get('link') and self.opener is not None:
                self.opener(info['link'])
                return 'Открываю Telegram разработчика.'
            return 'Открыл «Ваши предложения» — напишите, что улучшить.'
        try:
            return self.send(request[1])['message']
        except ValueError as exc:
            return str(exc)
