"""Документы в чате и отправка файлов куда угодно.

Всё, что создаёт агент (справки, PDF, отчёты о дубликатах…), сразу появляется в чате карточкой: «Открыть»,
«Показать в папке», «Копировать», «В Telegram…», «На почту», «Сохранить в…». То же голосом:

«Отправь этот файл Милане в Телеграм» — файл, выделенный в Проводнике/Finder (или последний документ из чата);
«отправь его маме в WhatsApp», «отправь справку на почту ivan@mail.ru», «скопируй документ»,
«сохрани его на рабочий стол», «покажи документ в папке».
"""
import logging
import re
import secrets
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import oshelp

log = logging.getLogger(__name__)

KIND_ICONS = {'.pdf': 'pdf', '.docx': 'word', '.doc': 'word', '.xlsx': 'table', '.csv': 'table', '.md': 'text',
              '.txt': 'text', '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.zip': 'archive'}
_APPS = r'(?P<app>телеграм\w*|телеграмм\w*|телеге|телегу|telegram|тг|ватсап\w*|вотсап\w*|вацап\w*|whatsapp|вайбер\w*|viber|' \
        r'дискорд\w*|discord|слак\w*|slack)'
_THIS = r'(?P<what>этот файл|эти файлы|файл|файлы|его|ее|её|их|документ|документы|справку|отчет|отчёт|pdf|пдф|таблицу|' \
        r'презентацию|скриншот|картинку|фото|последний документ|этот документ)'
SEND_MESSENGER = re.compile(r'^(?:отправь|перешли|скинь|кинь|отошли|пошли)\s+' + _THIS + r'\s+(?P<who>.+?)\s+(?:в|во|на)\s+' +
                            _APPS + r'$', re.I)
SEND_MESSENGER2 = re.compile(r'^(?:отправь|перешли|скинь|кинь|отошли|пошли)\s+(?P<who>.+?)\s+(?:в|во|на)\s+' + _APPS +
                             r'\s+' + _THIS + r'$', re.I)
SEND_MAIL = re.compile(r'^(?:отправь|перешли|скинь|пошли)\s+' + _THIS + r'\s+(?:на\s+(?:почту|email|имейл|емейл)\s*'
                       r'(?P<to>\S+@\S+)?|(?:на|по)\s+(?P<to2>\S+@\S+))$', re.I)
COPY = re.compile(r'^(?:скопируй|копируй)\s+' + _THIS + r'(?:\s+в\s+буфер(?:\s+обмена)?)?$', re.I)
SAVE = re.compile(r'^(?:сохрани|положи|перемести|скопируй)\s+' + _THIS + r'\s+(?:на|в|во)\s+(?P<folder>.+)$', re.I)
REVEAL = re.compile(r'^(?:покажи|открой)\s+' + _THIS + r'\s+в\s+(?:папке|проводнике|finder)$', re.I)
OPEN = re.compile(r'^(?:открой|покажи)\s+(?:этот\s+|последний\s+)?(?:документ|файл|pdf|пдф)$', re.I)


def parse(text):
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!')
    for pattern in (SEND_MESSENGER, SEND_MESSENGER2):
        match = pattern.match(value)
        if match:
            from .desktop.messengers import app_key
            app = app_key(match['app']) or 'telegram'
            who = re.sub(r'^(?:для|к)\s+', '', match['who'].strip(' ,'))
            return {'action': 'messenger', 'app': app, 'who': who, 'what': match['what'].casefold()}
    match = SEND_MAIL.match(value)
    if match:
        return {'action': 'email', 'to': match['to'] or match['to2'] or '', 'what': match['what'].casefold()}
    match = SAVE.match(value)
    if match and not re.match(r'(?:буфер)', match['folder'], re.I):
        return {'action': 'save', 'folder': match['folder'], 'what': match['what'].casefold(),
                'move': value.casefold().startswith('перемести')}
    match = COPY.match(value)
    if match:
        return {'action': 'copy', 'what': match['what'].casefold()}
    match = REVEAL.match(value)
    if match:
        return {'action': 'reveal', 'what': match['what'].casefold()}
    if OPEN.match(value):
        return {'action': 'open', 'what': 'документ'}
    return None


def describe(path):
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {'name': path.name, 'path': str(path), 'size': size, 'kind': KIND_ICONS.get(path.suffix.casefold(), 'file')}


class Documents:
    """Реестр документов: что создано и показано в чате, чтобы открыть, скопировать или отправить."""

    def __init__(self, store, events=None, desktop=None, settings=None, root=None):
        self.store = store
        self.events = events
        self.desktop = desktop            # DesktopController — для отправки в мессенджеры
        self.settings = settings or (lambda: store.settings('device:desktop'))
        self.root = root
        self.last = None
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, path TEXT, name TEXT, created TEXT, '
                       'source TEXT)')

    # ---- реестр ----
    def register(self, path, source='agent'):
        path = Path(path).resolve()
        doc_id = secrets.token_hex(8)
        with self.store.connect() as db:
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?)',
                       (doc_id, str(path), path.name, datetime.now().isoformat(timespec='seconds'), source))
        self.last = doc_id
        return dict(describe(path), id=doc_id)

    def publish(self, path, text=None, source='agent', owner='device:desktop'):
        """Показать документ в чате сразу после создания (с кнопками действий)."""
        card = self.register(path, source)
        message = text or f'Готово: {card["name"]}.'
        self.store.add(owner, 'agent', message, attachment=card)
        if self.events is not None:
            self.events.emit('message', role='agent', text=message, source='system', owner=owner, spoken=False,
                             attachment=card)
        return card

    def get(self, doc_id):
        with self.store.connect() as db:
            row = db.execute('SELECT path FROM documents WHERE id=?', (str(doc_id),)).fetchone()
        if not row:
            raise ValueError('Документ не найден')
        path = Path(row[0])
        if not path.exists():
            raise ValueError(f'Файл «{path.name}» удалён или перемещён.')
        return path

    def latest(self):
        with self.store.connect() as db:
            rows = db.execute('SELECT id FROM documents ORDER BY created DESC, rowid DESC LIMIT 20').fetchall()
        for (doc_id,) in rows:
            try:
                return self.get(doc_id)
            except ValueError:
                continue
        return None

    # ---- о каком файле речь ----
    def target(self, what=''):
        """«Этот файл» — выделенные в Проводнике/Finder; иначе последний документ из чата."""
        what = (what or '').casefold()
        if what in ('этот файл', 'эти файлы', 'файл', 'файлы', 'их', 'этот документ') or not self.last:
            hwnd = getattr(getattr(self.desktop, 'tracker', None), 'last_external', 0) or 0
            selected = oshelp.selected_files(hwnd or oshelp.foreground_window())
            if selected:
                return selected
        latest = self.latest()
        return [latest] if latest else []

    # ---- действия ----
    def open(self, paths):
        oshelp.open_path(paths[0])
        return f'Открываю {paths[0].name}.'

    def reveal(self, paths):
        oshelp.reveal(paths[0])
        return f'Показываю {paths[0].name} в папке.'

    def copy(self, paths):
        if oshelp.copy_files(paths):
            names = paths[0].name if len(paths) == 1 else f'{len(paths)} файла(ов)'
            return f'Скопировал {names} в буфер обмена — вставьте Ctrl+V в любое приложение.'
        return 'Не получилось скопировать файл в буфер обмена.'

    def save_to(self, paths, folder_name, move=False):
        from .files import resolve_folder
        folder = resolve_folder(folder_name)
        if folder is None:
            return f'Не нашёл папку «{folder_name}».'
        saved = []
        for path in paths:
            target = unique_path(folder / path.name)
            (shutil.move if move else shutil.copy2)(str(path), str(target))
            saved.append(target)
        verb = 'Переместил' if move else 'Сохранил'
        return f'{verb} {saved[0].name if len(saved) == 1 else str(len(saved)) + " файла(ов)"} в «{folder.name}».'

    def to_messenger(self, paths, app, who):
        """Открыть чат, вставить файл из буфера обмена и отправить."""
        from .desktop import messengers, winapi
        if self.desktop is None or not winapi.supported():
            return 'Отправка в мессенджеры работает на Windows и macOS.'
        if not oshelp.copy_files(paths):
            return 'Не получилось подготовить файл к отправке.'
        error = messengers.open_chat(self.desktop, {'app': app, 'who': who}, self.settings(), self.root)
        if error:
            return error
        winapi.hotkey('ctrl', 'v')
        time.sleep(1.6)               # мессенджер показывает окно «Отправить файл»
        winapi.hotkey('enter')
        title = messengers.PROFILES[app]['title']
        names = paths[0].name if len(paths) == 1 else f'{len(paths)} файла(ов)'
        return f'Отправил {names} в {title} для «{who}».'

    def to_email(self, paths, to=''):
        """Черновик письма с вложением: Outlook / Почта macOS; иначе — почтовая программа + файл в буфере."""
        subject = paths[0].stem if len(paths) == 1 else 'Файлы'
        if sys.platform == 'win32':
            script = ('$o = New-Object -ComObject Outlook.Application\n$m = $o.CreateItem(0)\n'
                      f'$m.To = {oshelp.ps_string(to)}\n$m.Subject = {oshelp.ps_string(subject)}\n' +
                      ''.join(f'[void]$m.Attachments.Add({oshelp.ps_string(p)})\n' for p in paths) + '$m.Display()')
            try:
                code, _, _ = oshelp.powershell(script, timeout=40)
            except Exception:
                code = 1
            if code == 0:
                return 'Открыл письмо в Outlook с вложением — проверьте и нажмите «Отправить».'
        elif sys.platform == 'darwin':
            attach = ''.join(f'make new attachment with properties {{file name:(POSIX file {oshelp.as_string(p)})}} '
                             'at after the last paragraph\n' for p in paths)
            script = (f'tell application "Mail"\nset m to make new outgoing message with properties '
                      f'{{subject:{oshelp.as_string(subject)}, visible:true}}\ntell m\n'
                      + (f'make new to recipient with properties {{address:{oshelp.as_string(to)}}}\n' if to else '')
                      + attach + 'end tell\nactivate\nend tell')
            code, _, _ = oshelp.osascript(script)
            if code == 0:
                return 'Открыл письмо в «Почте» с вложением — проверьте и нажмите «Отправить».'
        oshelp.copy_files(paths)
        from urllib.parse import quote
        oshelp.open_path(f'mailto:{to}?subject={quote(subject)}')
        return 'Открыл новое письмо. Файл в буфере обмена — вставьте его в письмо Ctrl+V.'

    # ---- голос ----
    def handle(self, text):
        request = parse(text)
        if request is None:
            return None
        paths = self.target(request.get('what'))
        if not paths:
            return 'Какой файл? Выделите его в Проводнике или сначала создайте документ.'
        action = request['action']
        if action == 'messenger':
            return self.to_messenger(paths, request['app'], request['who'])
        if action == 'email':
            return self.to_email(paths, request.get('to', ''))
        if action == 'copy':
            return self.copy(paths)
        if action == 'save':
            return self.save_to(paths, request['folder'], request.get('move', False))
        if action == 'reveal':
            return self.reveal(paths)
        return self.open(paths)


def unique_path(path):
    """«отчёт.pdf» → «отчёт (2).pdf», если такой уже есть."""
    path = Path(path)
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f'{path.stem} ({n}){path.suffix}')
        if not candidate.exists():
            return candidate
    return path.with_name(f'{path.stem}-{secrets.token_hex(3)}{path.suffix}')


def output_folder(kind='Документы'):
    """Documents/Андрей/<kind> — сюда агент кладёт созданные файлы."""
    from .files import known_folders
    base = known_folders().get('документы', Path.home()) / 'Андрей' / kind
    base.mkdir(parents=True, exist_ok=True)
    return base
