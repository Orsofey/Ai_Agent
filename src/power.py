"""Питание компьютера: «Андрей, выключи компьютер», «перезагрузи компьютер через 10 минут», «спящий режим»,
«отмени выключение».

Выключение и перезагрузка — только после подтверждения «да». Компьютер выключается штатно, без принудительного
закрытия программ: несохранённые документы программы предложат сохранить.
"""
import logging
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

CONFIRM_SECONDS = 25
GRACE_SECONDS = 10       # после «да» — ещё 10 секунд, чтобы успеть сказать «отмени»
DEVICE = r'(?:компьютер|компьютера|пк|ноутбук|ноут|комп|систему|машину)'
YES = {'да', 'подтверждаю', 'выключай', 'перезагружай', 'давай', 'конечно', 'да выключай', 'да перезагружай',
       'да давай', 'ага', 'угу', 'точно', 'выключить', 'перезагрузить', 'да конечно', 'yes'}
NO = {'нет', 'не надо', 'не выключай', 'не перезагружай', 'отмена', 'отмени', 'стоп', 'не нужно', 'передумал', 'no'}
# вид → (вопрос, «сейчас», «позже», что отменять, ответ на «нет»)
TITLES = {'shutdown': ('Выключить компьютер', 'Выключаю компьютер', 'Выключу компьютер', 'выключение', 'не выключаю'),
          'restart': ('Перезагрузить компьютер', 'Перезагружаю компьютер', 'Перезагружу компьютер', 'перезагрузку',
                      'не перезагружаю'),
          'sleep': ('Перевести компьютер в сон', 'Перевожу компьютер в спящий режим', 'Переведу компьютер в сон', 'сон',
                    'оставляю как есть')}


def parse(text):
    """('shutdown'|'restart'|'sleep', минуты или None) | ('cancel',) или None."""
    lower = re.sub(r'[.!?,]+', '', str(text).casefold().replace('ё', 'е')).strip()
    lower = re.sub(r'\s+', ' ', lower)
    if re.fullmatch(r'(?:отмени|отмена|останови|стоп|не надо)\s+(?:выключени\w*|перезагрузк\w*|перезапуск\w*|сон)'
                    r'|не выключай(?:\s+' + DEVICE + r')?|не перезагружай(?:\s+' + DEVICE + r')?', lower):
        return ('cancel',)
    when = r'(?:\s+(?:через|спустя)\s+(?P<delay>.+))?'
    for kind, pattern in (
            ('shutdown', r'(?:выключи|выключить|отключи|заверши работу|выруби|погаси)\s+' + DEVICE + when),
            ('shutdown', r'(?:выключение|завершение работы)\s+' + DEVICE + when),
            ('restart', r'(?:перезагрузи|перезапусти|перезагрузить|перезапустить|рестартни)\s+' + DEVICE + when),
            ('restart', r'(?:перезагрузка|перезапуск)\s+' + DEVICE + when),
            ('sleep', r'(?:усыпи|переведи|отправь|включи)\s+(?:' + DEVICE + r'\s+)?(?:в\s+)?(?:спящий режим|режим сна|сон)' + when),
            ('sleep', r'(?:спящий режим|режим сна)' + when)):
        match = re.fullmatch(pattern, lower)
        if match:
            minutes = None
            if match.group('delay'):
                from .scenarios import parse_minutes
                minutes = parse_minutes(match.group('delay'))
                if minutes is None:
                    return None
            return kind, minutes
    return None


def power_command(kind):
    """Команда ОС: штатное выключение/перезагрузка (без /f — программы могут попросить сохранить документы)."""
    if sys.platform == 'win32':
        return {'shutdown': ['shutdown', '/s', '/t', '0'], 'restart': ['shutdown', '/r', '/t', '0'],
                'sleep': ['rundll32.exe', 'powrprof.dll,SetSuspendState', '0,1,0']}[kind]
    if sys.platform == 'darwin':
        verb = {'shutdown': 'shut down', 'restart': 'restart', 'sleep': 'sleep'}[kind]
        return ['osascript', '-e', f'tell application "System Events" to {verb}']
    return None


class Power:
    def __init__(self, notify=None, speak=None, runner=None, clock=time.monotonic):
        self.notify = notify
        self.speak = speak
        self.runner = runner or self._run_os
        self.clock = clock
        self.pending = {}          # owner → (вид, минуты, срок ответа)
        self.timer = None
        self.scheduled = None      # (вид, когда: datetime)
        self.lock = threading.Lock()

    def awaiting(self, owner):
        item = self.pending.get(owner)
        return bool(item and item[2] > self.clock())

    def handle(self, text, owner, settings=None):
        address = ''
        if settings:
            from .dialog import address_of
            address = address_of(settings)
        tail = f', {address}' if address else ''
        lower = re.sub(r'[.!?,]+', '', str(text).casefold().replace('ё', 'е')).strip()
        pending = self.pending.get(owner)
        if pending and pending[2] > self.clock():
            if lower in YES or re.fullmatch(r'да\b.*', lower):
                self.pending.pop(owner)
                return self.schedule(pending[0], pending[1], address)
            if lower in NO:
                self.pending.pop(owner)
                return f'Хорошо{tail}, {TITLES[pending[0]][4]}.'
            self.pending.pop(owner)  # человек перешёл к другой команде
        request = parse(text)
        if request is None:
            return None
        if request[0] == 'cancel':
            return self.cancel()
        kind, minutes = request
        if power_command(kind) is None:
            return 'Выключение и перезагрузка доступны на Windows и macOS.'
        if kind == 'sleep' and not minutes:
            return self.schedule(kind, None, address)
        self.pending[owner] = (kind, minutes, self.clock() + CONFIRM_SECONDS)
        later = f' через {_say_minutes(minutes)}' if minutes else ''
        return f'{TITLES[kind][0]}{later}{tail}? Скажите «да».'

    def schedule(self, kind, minutes, address=''):
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
            delay = minutes * 60 if minutes else (0 if kind == 'sleep' else GRACE_SECONDS)
            when = datetime.now() + timedelta(seconds=delay)
            self.scheduled = (kind, when)
            self.timer = threading.Timer(delay, self._fire, args=(kind,))
            self.timer.daemon = True
            self.timer.start()
            if minutes and minutes > 2:
                warn = threading.Timer(delay - 60, self._warn, args=(kind,))
                warn.daemon = True
                warn.start()
                self._warner = warn
        if kind == 'sleep' and not minutes:
            return 'Перевожу компьютер в спящий режим.'
        if minutes:
            return f'Хорошо. {TITLES[kind][2]} в {when:%H:%M}. «Отмени {TITLES[kind][3]}» — отмена.'
        return f'{TITLES[kind][1]} через {GRACE_SECONDS} секунд. Сохраните работу. «Отмени {TITLES[kind][3]}» — отмена.'

    def cancel(self):
        with self.lock:
            if self.timer is None or self.scheduled is None:
                self.pending.clear()
                return 'Выключение не запланировано.'
            self.timer.cancel()
            warner = getattr(self, '_warner', None)
            if warner is not None:
                warner.cancel()
            kind = self.scheduled[0]
            self.timer = self.scheduled = None
        return {'shutdown': 'Выключение отменено.', 'restart': 'Перезагрузка отменена.', 'sleep': 'Сон отменён.'}[kind]

    def status(self):
        if not self.scheduled:
            return None
        return {'kind': self.scheduled[0], 'at': self.scheduled[1].strftime('%H:%M:%S')}

    def _warn(self, kind):
        text = {'shutdown': 'Через минуту выключаю компьютер. Сохраните работу.',
                'restart': 'Через минуту перезагружаю компьютер. Сохраните работу.',
                'sleep': 'Через минуту перевожу компьютер в сон.'}[kind]
        for out in (self.notify, self.speak):
            if out:
                try:
                    out(text)
                except Exception:
                    pass

    def _fire(self, kind):
        with self.lock:
            self.timer = self.scheduled = None
        try:
            self.runner(kind)
        except Exception:
            log.exception('Power command failed')
            if self.notify:
                self.notify('Не получилось: система отклонила команду.')

    @staticmethod
    def _run_os(kind):
        command = power_command(kind)
        if command:
            subprocess.run(command, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _say_minutes(minutes):
    from .scenarios import say_minutes
    return say_minutes(minutes)
