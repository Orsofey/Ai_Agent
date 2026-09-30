"""Порядок в файлах голосом — только после подтверждения и с отменой.

«Наведи порядок в Загрузках» — разложить файлы по папкам Документы / Картинки / Архивы / Видео / Музыка / Установщики;
«переименуй сканы по дате» — «scan0001.pdf» → «Скан 2026-09-14 10-32.pdf» (дата съёмки/создания);
«найди дубликаты (в загрузках / везде)» — показать и сколько места освободится; «удали дубликаты» — в Корзину;
«сделай из этих файлов PDF» — выделенные картинки, PDF и документы → один PDF, он сразу появляется в чате;
«отмени» / «верни как было» — вернуть последнее перемещение или переименование.

Ничего не меняется без «да». Журнал действий хранится в папке данных (file_ops_journal.json).
"""
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import oshelp
from .documents import output_folder, unique_path

log = logging.getLogger(__name__)

CATEGORIES = [
    ('Документы', {'.pdf', '.doc', '.docx', '.odt', '.rtf', '.txt', '.md', '.xls', '.xlsx', '.csv', '.ods', '.ppt', '.pptx',
                   '.odp', '.djvu', '.epub', '.fb2'}),
    ('Картинки', {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.bmp', '.svg', '.tif', '.tiff', '.ico'}),
    ('Архивы', {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.tgz'}),
    ('Видео', {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.m4v'}),
    ('Музыка', {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac', '.opus'}),
    ('Установщики', {'.exe', '.msi', '.dmg', '.pkg', '.apk', '.appx', '.msix'}),
]
PARTIAL = ('.crdownload', '.part', '.tmp', '.download', '.partial', '.opdownload')
SCAN_NAME = re.compile(r'^(?:scan|скан|сканирование|img|image|doc|document|документ|photo|фото|dsc|pxl|cam|'
                       r'новый документ|new doc|screenshot|снимок)[\s_\-(]*\d', re.I)
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.bmp', '.tif', '.tiff', '.gif'}
CONFIRM_SECONDS = 120
YES = re.compile(r'^(?:да|давай|выполняй|выполни|делай|подтверждаю|ок|окей|хорошо|согласен|удаляй|раскладывай|'
                 r'переименовывай|да давай|да выполняй|конечно)\b', re.I)
NO = re.compile(r'^(?:нет|не надо|отмена|отмени|стоп|не нужно|передумал)\b', re.I)
UNDO = re.compile(r'^(?:отмени|верни)\s+(?:как было|всё обратно|все обратно|перемещени\w*|переименовани\w*|сортировк\w*|'
                  r'последн\w+ действи\w*|порядок|обратно)$|^верни\s+файлы\s+(?:обратно|на место)$|^отмени это$', re.I)

TIDY = re.compile(r'^(?:наведи|навести|наводи)\s+порядок\s+(?:в|во|на)\s+(?P<folder>.+)$|'
                  r'^(?:разложи|рассортируй|отсортируй|разбери)\s+(?:файлы\s+)?(?:в|во|на|по)?\s*(?P<folder2>.+?)'
                  r'(?:\s+по\s+папкам)?$', re.I)
RENAME = re.compile(r'^переименуй\s+(?:все\s+)?(?:сканы|скан\w*|фото\w*|фотки|снимки|картинки)\s+по\s+дат\w+'
                    r'(?:\s+(?:в|во|на)\s+(?P<folder>.+))?$', re.I)
DUPES = re.compile(r'^(?:найди|покажи|поищи|проверь)\s+(?:все\s+)?(?:дубликаты|дубли|повторяющиеся файлы|одинаковые файлы|копии файлов)'
                   r'(?:\s+(?:в|во|на)\s+(?P<folder>.+))?$', re.I)
DELETE_DUPES = re.compile(r'^(?:удали|убери|почисти|очисти|освободи место от)\s+(?:все\s+)?(?:дубликаты|дубли|копии)'
                          r'(?:\s+(?:в|во|на)\s+(?P<folder>.+))?$|^освободи место$', re.I)
MAKE_PDF = re.compile(r'^(?:сделай|собери|создай|сохрани|преврати|конвертируй|объедини)\s+(?:из\s+)?(?:этих|эти|выделенных|'
                      r'выделенные|этого|этот)?\s*(?:файлов|файлы|файла|файл|картинок|картинки|фото|сканов|сканы|документов|'
                      r'документы)?\s*(?:в\s+(?:один\s+)?)?(?:pdf|пдф)(?:\s+(?:из\s+)?(?:этих|выделенных)\s+файлов)?$', re.I)


def parse(text):
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    if UNDO.match(value):
        return ('undo',)
    match = RENAME.match(value)
    if match:
        return 'rename', match['folder'] or 'загрузки'
    match = DELETE_DUPES.match(value)
    if match:
        return 'delete_dupes', match['folder'] if match.groupdict().get('folder') else None
    match = DUPES.match(value)
    if match:
        return 'dupes', match['folder'] or 'загрузки'
    if MAKE_PDF.match(value) or re.match(r'^(?:сделай|собери|создай)\s+(?:один\s+)?(?:pdf|пдф)\s+из\s+(?:этих|выделенных)\s+'
                                         r'(?:файлов|картинок|фото|сканов|документов)$', value, re.I):
        return ('pdf',)
    match = TIDY.match(value)
    if match:
        folder = (match['folder'] or match['folder2'] or '').strip()
        if folder and re.search(r'загрузк|скачан|рабоч|стол|документ|папк|download', folder, re.I):
            return 'tidy', re.sub(r'^папк\w*\s+', '', folder)
    return None


def category_of(path):
    ext = path.suffix.casefold()
    for name, exts in CATEGORIES:
        if ext in exts:
            return name
    return None


def plan_tidy(folder, now=None):
    """[(откуда, куда)] для файлов верхнего уровня папки. Свежие (< 2 мин) и недокачанные не трогаем."""
    now = now or time.time()
    moves = []
    for entry in sorted(os.scandir(folder), key=lambda e: e.name.casefold()):
        if not entry.is_file(follow_symlinks=False) or entry.name.startswith(('.', '~$', 'desktop.ini')):
            continue
        path = Path(entry.path)
        if path.suffix.casefold() in PARTIAL or now - entry.stat().st_mtime < 120:
            continue
        category = category_of(path)
        if category:
            moves.append((path, folder / category / path.name))
    return moves


def file_date(path):
    """Дата съёмки/создания: EXIF у фото, CreationDate у PDF, иначе время изменения файла."""
    ext = path.suffix.casefold()
    try:
        if ext in IMAGE_EXTS:
            from PIL import Image
            with Image.open(path) as image:
                exif = image.getexif()
                value = exif.get_ifd(0x8769).get(36867) if hasattr(exif, 'get_ifd') else None
                value = value or exif.get(306)
                if value:
                    return datetime.strptime(str(value)[:19], '%Y:%m:%d %H:%M:%S')
        elif ext == '.pdf':
            from pypdf import PdfReader
            meta = PdfReader(str(path)).metadata
            created = getattr(meta, 'creation_date', None) if meta else None
            if created:
                return created.replace(tzinfo=None)
    except Exception as exc:
        log.debug('No embedded date for %s: %s', path, exc)
    return datetime.fromtimestamp(path.stat().st_mtime)


def plan_rename(folder):
    moves, taken = [], set()
    for entry in sorted(os.scandir(folder), key=lambda e: e.name.casefold()):
        if not entry.is_file(follow_symlinks=False):
            continue
        path = Path(entry.path)
        if not SCAN_NAME.match(path.stem):
            continue
        prefix = 'Фото' if path.suffix.casefold() in IMAGE_EXTS and not re.match(r'(?i)scan|скан', path.stem) else 'Скан'
        stamp = file_date(path).strftime('%Y-%m-%d %H-%M-%S')
        target = folder / f'{prefix} {stamp}{path.suffix.casefold()}'
        n = 2
        while target in taken or (target.exists() and target != path):
            target = folder / f'{prefix} {stamp} ({n}){path.suffix.casefold()}'
            n += 1
        taken.add(target)
        if target != path:
            moves.append((path, target))
    return moves


def _hash(path, head=None):
    digest = hashlib.blake2b(digest_size=20)
    with open(path, 'rb') as file:
        if head:
            digest.update(file.read(head))
        else:
            for block in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def find_duplicates(folders, min_size=1024, progress=None):
    """Группы одинаковых файлов: сначала по размеру, затем по началу файла, затем полный хэш."""
    by_size = defaultdict(list)
    for folder in folders:
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d.casefold() not in ('node_modules', '.git', 'appdata')]
            for name in names:
                path = Path(root) / name
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size >= min_size and not name.startswith(('.', '~$')):
                    by_size[size].append(path)
    candidates = [paths for paths in by_size.values() if len(paths) > 1]
    groups = []
    total = sum(len(p) for p in candidates)
    done = 0
    for paths in candidates:
        by_head = defaultdict(list)
        for path in paths:
            try:
                by_head[_hash(path, head=65536)].append(path)
            except OSError:
                pass
            done += 1
            if progress:
                progress(done, total, path.name)
        for same_head in by_head.values():
            if len(same_head) < 2:
                continue
            by_full = defaultdict(list)
            for path in same_head:
                try:
                    by_full[_hash(path)].append(path)
                except OSError:
                    pass
            for same in by_full.values():
                if len(same) > 1:
                    # Оставляем самый старый файл (оригинал), остальные — копии.
                    same.sort(key=lambda p: (p.stat().st_mtime, len(str(p))))
                    groups.append(same)
    groups.sort(key=lambda g: -g[0].stat().st_size * (len(g) - 1))
    return groups


def say_size(size):
    from .files import say_size as fmt
    return fmt(size)


# ---------------- PDF ----------------
def make_pdf(paths, target):
    """Картинки, PDF, текст и документы Office → один PDF. Возвращает (путь, пропущенные файлы)."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    skipped = []
    for path in paths:
        ext = path.suffix.casefold()
        try:
            if ext == '.pdf':
                for page in PdfReader(str(path)).pages:
                    writer.add_page(page)
            elif ext in IMAGE_EXTS:
                _append_pdf(writer, _image_pdf([path]))
            elif ext in ('.docx', '.doc', '.rtf', '.odt', '.xlsx', '.xls', '.pptx', '.ppt') and office_to_pdf(path):
                _append_pdf(writer, office_to_pdf(path))
            elif ext in ('.txt', '.md', '.csv', '.docx', '.odt', '.rtf', '.log'):
                from .files import kind_of, read_text
                _append_pdf(writer, _text_pdf(read_text(path, kind_of(path)), path.name))
            else:
                skipped.append(path)
        except Exception as exc:
            log.info('PDF: cannot add %s: %s', path, exc)
            skipped.append(path)
    if not writer.pages:
        raise ValueError('Ни один файл не удалось добавить в PDF.')
    with open(target, 'wb') as file:
        writer.write(file)
    return target, skipped


def _append_pdf(writer, data):
    import io
    from pypdf import PdfReader
    for page in PdfReader(io.BytesIO(data)).pages:
        writer.add_page(page)


def _image_pdf(paths):
    import io
    from PIL import Image, ImageOps
    images = []
    for path in paths:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            images.append(image.convert('RGB'))
    buffer = io.BytesIO()
    images[0].save(buffer, 'PDF', resolution=150.0, save_all=True, append_images=images[1:])
    return buffer.getvalue()


def _font(size):
    from PIL import ImageFont
    for name in ('arial.ttf', 'segoeui.ttf', 'DejaVuSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/Library/Fonts/Arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_pdf(text, title):
    """Текст → страницы A4 (150 dpi) с переносом строк. Шрифт системный — кириллица поддерживается."""
    import io
    import textwrap
    from PIL import Image, ImageDraw
    width, height, margin = 1240, 1754, 110
    font = _font(26)
    lines = []
    for paragraph in (text or '').replace('\r', '').split('\n'):
        lines.extend(textwrap.wrap(paragraph, 88) or [''])
    per_page = (height - 2 * margin) // 38
    pages = []
    for start in range(0, max(1, len(lines)), per_page):
        page = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(page)
        y = margin
        for line in lines[start:start + per_page]:
            draw.text((margin, y), line, fill='black', font=font)
            y += 38
        draw.text((margin, height - margin // 2), title, fill=(120, 120, 120), font=_font(18))
        pages.append(page)
    buffer = io.BytesIO()
    pages[0].save(buffer, 'PDF', resolution=150.0, save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def office_to_pdf(path, _cache={}):
    """Word/Excel/PowerPoint → PDF через установленный Office (Windows). None, если Office нет."""
    import sys
    if sys.platform != 'win32':
        return None
    if str(path) in _cache:
        return _cache[str(path)]
    import tempfile
    out = Path(tempfile.mkdtemp()) / (path.stem + '.pdf')
    ext = path.suffix.casefold()
    p, o = oshelp.ps_string(path), oshelp.ps_string(out)
    if ext in ('.docx', '.doc', '.rtf', '.odt'):
        script = f"$a=New-Object -ComObject Word.Application;$d=$a.Documents.Open({p},$false,$true);$d.ExportAsFixedFormat({o},17);$d.Close($false);$a.Quit()"
    elif ext in ('.xlsx', '.xls'):
        script = f"$a=New-Object -ComObject Excel.Application;$a.DisplayAlerts=$false;$w=$a.Workbooks.Open({p},0,$true);$w.ExportAsFixedFormat(0,{o});$w.Close($false);$a.Quit()"
    else:
        script = f"$a=New-Object -ComObject PowerPoint.Application;$d=$a.Presentations.Open({p},$true,$false,$false);$d.SaveAs({o},32);$d.Close();$a.Quit()"
    try:
        code, _, _ = oshelp.powershell(script, timeout=120)
    except Exception:
        code = 1
    data = out.read_bytes() if code == 0 and out.exists() else None
    _cache[str(path)] = data
    return data


# ---------------- менеджер ----------------
class FileOps:
    def __init__(self, store, documents=None, events=None, notify=None, clock=time.monotonic):
        self.store = store
        self.documents = documents
        self.events = events
        self.notify = notify
        self.clock = clock
        self.pending = {}      # owner → (вид, данные, срок)
        self.lock = threading.Lock()
        self.journal_path = Path(store.root) / 'file_ops_journal.json'

    def awaiting(self, owner):
        item = self.pending.get(owner)
        return bool(item and item[2] > self.clock())

    # ---- журнал для отмены ----
    def _journal(self):
        try:
            return json.loads(self.journal_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []

    def _remember(self, kind, moves):
        journal = self._journal()[-19:]
        journal.append({'kind': kind, 'at': datetime.now().isoformat(timespec='seconds'),
                        'moves': [[str(a), str(b)] for a, b in moves]})
        self.journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=1), encoding='utf-8')

    def undo(self):
        journal = self._journal()
        if not journal:
            return 'Нечего отменять: я ещё ничего не перемещал и не переименовывал.'
        last = journal.pop()
        back, missing = 0, 0
        for source, target in reversed(last['moves']):
            source, target = Path(source), Path(target)
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
                back += 1
            else:
                missing += 1
        for source, target in last['moves']:
            parent = Path(target).parent
            try:
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()  # пустые папки, созданные сортировкой
            except OSError:
                pass
        self.journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=1), encoding='utf-8')
        tail = f' {missing} файл(ов) уже перемещены вручную — их не трогал.' if missing else ''
        return f'Вернул как было: {back} файл(ов).{tail}'

    @staticmethod
    def _apply(moves):
        done = []
        for source, target in moves:
            if not source.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target = unique_path(target) if target.exists() else target
            shutil.move(str(source), str(target))
            done.append((source, target))
        return done

    # ---- голос ----
    def handle(self, text, owner='default', settings=None):
        lower = re.sub(r'[.!?,]+', '', str(text).casefold()).strip()
        pending = self.pending.get(owner)
        if pending and pending[2] > self.clock():
            if YES.match(lower):
                self.pending.pop(owner)
                return self._confirmed(pending[0], pending[1])
            if NO.match(lower) and not UNDO.match(lower):
                self.pending.pop(owner)
                return 'Хорошо, ничего не меняю.'
            self.pending.pop(owner)
        request = parse(text)
        if request is None:
            return None
        kind = request[0]
        if kind == 'undo':
            return self.undo()
        if kind == 'pdf':
            return self.pdf()
        from .files import known_folders, resolve_folder
        if kind in ('dupes', 'delete_dupes'):
            name = request[1]
            if name and re.fullmatch(r'везде|на компьютере|во всех папках|всех папках', name.strip(), re.I):
                folders = list(known_folders().values())
            else:
                folder = resolve_folder(name or 'загрузки')
                if folder is None:
                    return f'Не нашёл папку «{name}».'
                folders = [folder]
            return self.duplicates(owner, folders, delete=kind == 'delete_dupes')
        folder = resolve_folder(request[1])
        if folder is None:
            return f'Не нашёл папку «{request[1]}».'
        if kind == 'tidy':
            return self.propose(owner, 'tidy', plan_tidy(folder), folder)
        return self.propose(owner, 'rename', plan_rename(folder), folder)

    def propose(self, owner, kind, moves, folder):
        if not moves:
            return (f'В «{folder.name}» и так порядок: нечего раскладывать.' if kind == 'tidy' else
                    f'В «{folder.name}» не нашёл сканов с безымянными названиями (scan001, IMG_1234…).')
        self.pending[owner] = (kind, moves, self.clock() + CONFIRM_SECONDS)
        if kind == 'tidy':
            groups = defaultdict(list)
            for source, target in moves:
                groups[target.parent.name].append(source.name)
            parts = [f'{name} — {len(files)}' for name, files in groups.items()]
            examples = '\n'.join(f'• {files[0]} → {name}/' for name, files in groups.items())
            return (f'Разложу {len(moves)} файл(ов) в «{folder.name}»: {", ".join(parts)}. Остальное не трогаю.\n'
                    f'{examples}\nВыполнить? Скажите «да». Потом можно вернуть: «отмени».')
        examples = '\n'.join(f'• {a.name} → {b.name}' for a, b in moves[:5])
        more = f'\n…и ещё {len(moves) - 5}' if len(moves) > 5 else ''
        return (f'Переименую {len(moves)} файл(ов) в «{folder.name}» по дате:\n{examples}{more}\n'
                'Выполнить? Скажите «да». Потом можно вернуть: «отмени».')

    def _confirmed(self, kind, data):
        if kind in ('tidy', 'rename'):
            done = self._apply(data)
            if done:
                self._remember(kind, done)
            verb = 'Разложил' if kind == 'tidy' else 'Переименовал'
            return f'{verb} {len(done)} файл(ов). Чтобы вернуть как было, скажите «отмени».'
        if kind == 'delete_dupes':
            removed = oshelp.to_trash(data)
            freed = sum(size for path, size in getattr(self, '_sizes', {}).items() if Path(path) in removed)
            return (f'Удалил в Корзину {len(removed)} копий, освободится {say_size(freed)} после очистки Корзины. '
                    'Восстановить можно из Корзины.')
        return 'Готово.'

    def duplicates(self, owner, folders, delete=False):
        task = f'dupes-{int(time.time())}'
        title = 'Ищу дубликаты · ' + ', '.join(f.name for f in folders[:3])

        def progress(done, total, current):
            if self.events is not None and (done % 25 == 0 or done == total):
                self.events.emit('progress', task=task, done=done, total=total, current=current, finished=False,
                                 title=title)
        groups = find_duplicates(folders, progress=progress)
        if self.events is not None:
            self.events.emit('progress', task=task, done=1, total=1, current='', finished=True, title=title)
        if not groups:
            return 'Дубликатов не нашёл.'
        extra = [path for group in groups for path in group[1:]]
        self._sizes = {str(p): p.stat().st_size for p in extra}
        freed = sum(self._sizes.values())
        report = [f'# Дубликаты: {", ".join(str(f) for f in folders)}', f'Найдено {datetime.now():%d.%m.%Y %H:%M}', '',
                  f'Групп: {len(groups)}, лишних копий: {len(extra)}, можно освободить {say_size(freed)}.', '']
        for n, group in enumerate(groups, 1):
            report.append(f'## {n}. {group[0].name} — {say_size(group[0].stat().st_size)}')
            report.append(f'- оставить: {group[0]}')
            report += [f'- копия: {p}' for p in group[1:]]
            report.append('')
        path = output_folder('Справки') / f'дубликаты-{datetime.now():%Y-%m-%d_%H-%M}.md'
        path.write_text('\n'.join(report), encoding='utf-8')
        summary = (f'Нашёл {len(extra)} копий в {len(groups)} группах — можно освободить {say_size(freed)}. '
                   'Оригиналы (самые старые файлы) останутся.')
        if self.documents is not None:
            self.documents.publish(path, summary + ' Список — в документе.')
        self.pending[owner] = ('delete_dupes', extra, self.clock() + CONFIRM_SECONDS)
        ask = ' Удалить копии в Корзину? Скажите «да».'
        return summary + ask

    def pdf(self):
        paths = self.documents.target('эти файлы') if self.documents is not None else []
        paths = [p for p in paths if p.is_file()]
        if not paths:
            return 'Выделите файлы в Проводнике (картинки, PDF, документы) и повторите: «сделай из этих файлов PDF».'
        paths.sort(key=lambda p: p.name.casefold())
        name = paths[0].stem if len(paths) == 1 else f'{paths[0].stem} и ещё {len(paths) - 1}'
        target = unique_path(output_folder('PDF') / f'{name[:80]}.pdf')
        try:
            target, skipped = make_pdf(paths, target)
        except ValueError as exc:
            return str(exc)
        text = f'Собрал PDF из {len(paths) - len(skipped)} файл(ов): {target.name}.'
        if skipped:
            text += ' Пропустил: ' + ', '.join(p.name for p in skipped[:4]) + '.'
        if self.documents is not None:
            self.documents.publish(target, text + ' Можно отправить: «отправь его Милане в Телеграм».')
            return text
        return text + f' Файл: {target}'
