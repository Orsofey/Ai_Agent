"""Работа с файлами голосом: изучить папку и дать краткую справку, посчитать итоги в таблицах, найти файл
или текст внутри файлов, открыть последний скачанный файл.

«Андрей, проштудируй папку Загрузки», «изучи pdf в документах за неделю», «посчитай сумму в таблицах в папке Отчёты»,
«найди в файлах слово договор», «найди файл отчёт», «открой последний скачанный файл», «открой справку».

Файлы читаются параллельно; прогресс виден в окне ассистента. Всё локально: содержимое никуда не отправляется
(только в локальную нейросеть, если она включена).
"""
import csv
import io
import logging
import os
import re
import sys
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

log = logging.getLogger(__name__)

MAX_FILES = 3000
MAX_BYTES = 8 * 1024 * 1024      # файлы больше читаем частично
TEXT_LIMIT = 200_000             # символов текста с одного файла
SKIP_DIRS = {'node_modules', '.git', '__pycache__', 'appdata', '$recycle.bin', 'library', '.venv', 'venv', 'site-packages'}

TYPES = {
    'text': {'.txt', '.md', '.log', '.json', '.xml', '.html', '.htm', '.rtf', '.ini', '.py', '.js', '.ts', '.css', '.yml',
             '.yaml', '.sql', '.java', '.cs', '.cpp', '.c', '.h', '.go', '.rs', '.php', '.kt', '.swift'},
    'word': {'.docx', '.odt', '.doc', '.rtf'},
    'table': {'.xlsx', '.csv', '.tsv', '.ods', '.xls'},
    'pdf': {'.pdf'},
    'slides': {'.pptx', '.odp'},
    'image': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.bmp'},
    'video': {'.mp4', '.mov', '.avi', '.mkv', '.webm'},
    'audio': {'.mp3', '.wav', '.flac', '.m4a', '.ogg'},
    'archive': {'.zip', '.rar', '.7z', '.tar', '.gz'},
}
TYPE_WORDS = [
    (r'pdf|пдф', 'pdf'), (r'ворд\w*|word|документ\w* ворд|docx', 'word'),
    (r'таблиц\w*|excel|эксел\w*|иксель\w*|xlsx|csv', 'table'), (r'презентац\w*|pptx|powerpoint', 'slides'),
    (r'текстов\w*|txt|заметк\w*', 'text'), (r'фото\w*|картин\w*|изображени\w*|скриншот\w*', 'image'),
    (r'видео', 'video'), (r'музык\w*|аудио|песн\w*', 'audio'), (r'архив\w*', 'archive'),
]
TYPE_TITLES = {'text': 'текстовых', 'word': 'документов Word', 'table': 'таблиц', 'pdf': 'PDF', 'slides': 'презентаций',
               'image': 'изображений', 'video': 'видео', 'audio': 'аудио', 'archive': 'архивов', 'other': 'других'}
STOPWORDS = set('''это этот эта эти того тому чтобы которые который которая также более может можно будет были было
быть есть если когда только очень после через между перед всех всего таким такой такие однако поэтому потому
where which there their about would could should these those with from that this have been were will your ваш наш
свой своих своей своего своим сейчас здесь тогда затем кроме около именно'''.split())


# ---------------- папки ----------------
def known_folders():
    home = Path.home()
    candidates = {
        'рабочий стол': ['Desktop', 'OneDrive/Desktop', 'OneDrive/Рабочий стол', 'Рабочий стол'],
        'документы': ['Documents', 'OneDrive/Documents', 'OneDrive/Документы', 'Документы'],
        'загрузки': ['Downloads', 'Загрузки'],
        'изображения': ['Pictures', 'OneDrive/Pictures', 'Изображения'],
        'музыка': ['Music', 'Музыка'],
        'видео': ['Videos', 'Movies', 'Видео'],
    }
    result = {}
    for name, options in candidates.items():
        for option in options:
            path = home / option
            if path.is_dir():
                result[name] = path
                break
    return result


FOLDER_ALIASES = {'рабоч': 'рабочий стол', 'стол': 'рабочий стол', 'desktop': 'рабочий стол', 'документ': 'документы',
                  'documents': 'документы', 'загрузк': 'загрузки', 'скачан': 'загрузки', 'downloads': 'загрузки',
                  'изображени': 'изображения', 'картинк': 'изображения', 'фотограф': 'изображения', 'pictures': 'изображения',
                  'музык': 'музыка', 'music': 'музыка', 'видео': 'видео', 'videos': 'видео'}


def resolve_folder(name):
    """«загрузках», «рабочем столе», «проект альфа», «C:\\Work» → Path или None."""
    value = str(name or '').strip(' «»"\'.,').casefold().replace('ё', 'е')
    value = re.sub(r'^(?:папк[аеиуой]+|каталог\w*|директори\w*)\s+', '', value)
    if not value:
        return None
    raw = Path(os.path.expandvars(os.path.expanduser(str(name).strip(' «»"\''))))
    if raw.is_absolute() and raw.is_dir():
        return raw
    known = known_folders()
    for stem, key in FOLDER_ALIASES.items():
        if value.startswith(stem) and key in known:
            return known[key]
    # Папка по имени: ищем неглубоко в домашней папке и известных папках (с учётом падежей: «проекте» → «проект»).
    stems = {value, re.sub(r'(?:ах|ях|ами|ями|ом|ем|ой|ей|ах|е|у|ю|и|а|я)$', '', value)}
    roots = [Path.home()] + list(known.values())
    seen, queue = set(), [(root, 0) for root in roots]
    while queue:
        folder, depth = queue.pop(0)
        if folder in seen or depth > 3:
            continue
        seen.add(folder)
        try:
            entries = [e for e in os.scandir(folder) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for entry in entries:
            low = entry.name.casefold().replace('ё', 'е')
            if low.startswith('.') or low in SKIP_DIRS:
                continue
            if low in stems or any(s and len(s) >= 3 and low.startswith(s) for s in stems):
                return Path(entry.path)
            queue.append((Path(entry.path), depth + 1))
        if len(seen) > 4000:
            break
    return None


# ---------------- разбор фраз ----------------
STUDY = re.compile(r'^(?:проштудируй|изучи|проанализируй|просмотри|разбери|прочитай|прошерсти|пробегись по|'
                   r'сделай\s+(?:краткую\s+)?(?:справку|сводку|выжимку|обзор)\s+(?:по|из)|'
                   r'составь\s+(?:краткую\s+)?(?:справку|сводку|обзор)\s+(?:по|из)|что\s+(?:лежит|есть|за файлы))\s+(.+)$')
CALC = re.compile(r'^(?:посчитай|подсчитай|сложи|вычисли|рассчитай|подведи)\s+(.+)$')
IN_FOLDER = re.compile(r'(?:^|\s)(?:в|во|из|на|по)\s+(?:папк[аеиуой]+\s+|каталоге\s+)?(.+?)(?:\s+за\s+.+)?$')


def parse_types(text):
    found = []
    for pattern, kind in TYPE_WORDS:
        if re.search(r'(?<!\w)(?:' + pattern + r')(?!\w)', text):
            found.append(kind)
    return found


def parse_period(text):
    match = re.search(r'за\s+(сегодня|вчера|неделю|последнюю неделю|месяц|последний месяц|год|(\d+)\s+(дн\w*|недел\w*|месяц\w*))',
                      text)
    if not match:
        return None
    word = match[1]
    if match[2]:
        n = int(match[2])
        return timedelta(days=n * (7 if match[3].startswith('недел') else 30 if match[3].startswith('месяц') else 1))
    return {'сегодня': timedelta(days=1), 'вчера': timedelta(days=2), 'неделю': timedelta(days=7),
            'последнюю неделю': timedelta(days=7), 'месяц': timedelta(days=31), 'последний месяц': timedelta(days=31),
            'год': timedelta(days=366)}[word]


def _folder_part(text):
    body = re.sub(r'\s+за\s+(?:сегодня|вчера|\S+\s*\S*)$', '', text)
    match = re.search(r'(?:^|\s)(?:в|во|из|на|по)\s+(?:папк\w*|каталог\w*)\s+(.+)$', body)
    if match:
        return match[1]
    # «сумму в таблицах на рабочем столе» → «на рабочем столе»
    body = re.sub(r'^.*?(?:файл\w*|документ\w* (?=в|на|из)|таблиц\w*|pdf|пдф|презентац\w*|заметк\w*)\s+(?=(?:в|во|из|на|по)\s)',
                  '', body)
    match = IN_FOLDER.search(body)
    if match:
        return match[1]
    # «проштудируй загрузки», «изучи папку проект»
    body = re.sub(r'^(?:все\s+)?(?:файлы|документы|таблицы)\s*', '', body)
    return re.sub(r'^папк\w*\s+', '', body)


def parse(text):
    """('study', {...}) | ('calc', {...}) | ('grep', {...}) | ('find', имя) | ('latest',) | ('open_folder', имя)
    | ('open_report',) или None."""
    raw = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    lower = raw.casefold().replace('ё', 'е')
    if lower in ('открой справку', 'открой последнюю справку', 'покажи справку', 'открой отчет', 'покажи отчет'):
        return ('open_report',)
    if re.fullmatch(r'(?:открой|покажи)\s+(?:последн\w+\s+)?(?:скачанн\w+|загруженн\w+)\s+файл|открой последнюю загрузку', lower):
        return ('latest',)
    match = re.fullmatch(r'(?:открой|покажи)\s+папку\s+(.+)', lower)
    if match:
        return 'open_folder', match[1]
    match = re.fullmatch(r'найди\s+(?:в|во)\s+(?:файлах|документах)(?:\s+(?:слово|фразу|текст))?\s+(.+?)'
                         r'(?:\s+(?:в|во)\s+(?:папке\s+)?(.+))?', lower)
    if match:
        return 'grep', {'query': match[1].strip(' «»"'), 'folder': match[2]}
    match = re.fullmatch(r'(?:найди|где)\s+(?:мой\s+)?(?:файл|документ|таблицу|презентацию)\s+(.+)', lower)
    if match:
        return 'find', match[1].strip(' «»"')
    match = STUDY.match(lower)
    if match and re.search(r'файл|папк|документ|таблиц|pdf|пдф|ворд|загрузк|рабоч\w+ стол|презентац|заметк|'
                           r'документах|в\s+\S+', match[1]):
        rest = match[1]
        return 'study', {'folder': _folder_part(rest), 'types': parse_types(rest), 'period': parse_period(rest)}
    match = CALC.match(lower)
    if match and re.search(r'таблиц|excel|эксел|csv|файл', match[1]):
        rest = match[1]
        what = 'average' if re.search(r'средн', rest) else 'count' if re.search(r'количеств|сколько строк', rest) else 'sum'
        return 'calc', {'folder': _folder_part(rest), 'types': ['table'], 'period': parse_period(rest), 'what': what}
    return None


# ---------------- чтение файлов ----------------
def kind_of(path):
    ext = path.suffix.casefold()
    for kind, exts in TYPES.items():
        if ext in exts:
            return kind
    return 'other'


def _xml_text(data):
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return ''
    parts = []
    for element in root.iter():
        tag = element.tag.rsplit('}', 1)[-1]
        if tag in ('t', 'v') and element.text:
            parts.append(element.text)
        elif tag in ('p', 'br', 'tab') and parts and not parts[-1].endswith('\n'):
            parts.append('\n' if tag != 'tab' else ' ')
    return ''.join(parts)


def read_xlsx(path, limit_rows=5000):
    """Лёгкое чтение .xlsx без сторонних библиотек: {лист: [строки]}."""
    sheets = {}
    with zipfile.ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ElementTree.fromstring(archive.read('xl/sharedStrings.xml'))
            for si in root:
                shared.append(''.join(t.text or '' for t in si.iter() if t.tag.endswith('}t')))
        names = sorted(n for n in archive.namelist() if re.match(r'xl/worksheets/sheet\d+\.xml$', n))
        for name in names:
            rows = []
            root = ElementTree.fromstring(archive.read(name))
            for row in root.iter():
                if not row.tag.endswith('}row'):
                    continue
                values = {}
                for cell in row:
                    if not cell.tag.endswith('}c'):
                        continue
                    ref = cell.get('r', '')
                    column = re.sub(r'\d', '', ref)
                    value = next((v.text for v in cell if v.tag.endswith('}v')), None)
                    if value is None:
                        inline = [t.text or '' for t in cell.iter() if t.tag.endswith('}t')]
                        value = ''.join(inline) if inline else None
                    elif cell.get('t') == 's':
                        value = shared[int(value)] if value.isdigit() and int(value) < len(shared) else value
                    if value is not None:
                        values[column] = value
                if values:
                    width = max(_col_index(c) for c in values) + 1
                    line = [''] * width
                    for c, v in values.items():
                        line[_col_index(c)] = v
                    rows.append(line)
                if len(rows) >= limit_rows:
                    break
            sheets[name.rsplit('/', 1)[-1][:-4]] = rows
    return sheets


def _col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch.upper()) - 64
    return max(0, n - 1)


def read_csv(path):
    raw = path.read_bytes()[:MAX_BYTES]
    text = _decode(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return {'csv': [row for row in csv.reader(io.StringIO(text), dialect)][:20000]}


def _decode(raw):
    for encoding in ('utf-8-sig', 'cp1251', 'latin-1'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace')


def read_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ''
    reader = PdfReader(str(path))
    parts, total = [], 0
    for page in reader.pages[:200]:
        text = page.extract_text() or ''
        parts.append(text)
        total += len(text)
        if total > TEXT_LIMIT:
            break
    return '\n'.join(parts)


def read_text(path, kind):
    """Текст файла (или '' если не умеем читать)."""
    ext = path.suffix.casefold()
    if kind == 'text' and ext != '.rtf':
        with open(path, 'rb') as f:
            return _decode(f.read(TEXT_LIMIT * 2))[:TEXT_LIMIT]
    if ext in ('.docx', '.pptx', '.odt', '.odp'):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n in ('word/document.xml', 'content.xml')
                     or re.match(r'ppt/slides/slide\d+\.xml$', n)]
            return '\n'.join(_xml_text(archive.read(n)) for n in sorted(names))[:TEXT_LIMIT]
    if ext == '.rtf':
        raw = _decode(path.read_bytes()[:TEXT_LIMIT])
        return re.sub(r'\\[a-z]+-?\d* ?|[{}]', '', raw)[:TEXT_LIMIT]
    if ext == '.pdf':
        return read_pdf(path)[:TEXT_LIMIT]
    if ext in ('.xlsx', '.csv', '.tsv'):
        sheets = read_xlsx(path) if ext == '.xlsx' else read_csv(path)
        return '\n'.join(' | '.join(row) for rows in sheets.values() for row in rows[:300])[:TEXT_LIMIT]
    return ''


def read_table(path):
    ext = path.suffix.casefold()
    if ext == '.xlsx':
        return read_xlsx(path)
    if ext in ('.csv', '.tsv'):
        return read_csv(path)
    return {}


NUMBER = re.compile(r'^[-+]?\d{1,3}(?:[ \u00a0]\d{3})*(?:[.,]\d+)?$|^[-+]?\d+(?:[.,]\d+)?$')


def to_number(value):
    text = str(value).strip().replace('\u00a0', ' ').rstrip('₽$€ р.руб').strip()
    if not NUMBER.match(text):
        return None
    try:
        return float(text.replace(' ', '').replace(',', '.'))
    except ValueError:
        return None


def table_totals(sheets):
    """Итоги числовых столбцов: [(заголовок, сумма, количество)]."""
    result = []
    for rows in sheets.values():
        if len(rows) < 2:
            continue
        header = rows[0]
        width = max(len(r) for r in rows)
        for col in range(width):
            values = [to_number(r[col]) for r in rows[1:] if col < len(r) and str(r[col]).strip()]
            numbers = [v for v in values if v is not None]
            if len(numbers) >= 2 and len(numbers) >= 0.6 * len(values):
                title = str(header[col]).strip() if col < len(header) and header[col] and to_number(header[col]) is None \
                    else f'столбец {col + 1}'
                result.append((title, sum(numbers), len(numbers)))
    return result


# ---------------- обход ----------------
def collect(folder, types=None, period=None, limit=MAX_FILES):
    since = (datetime.now() - period).timestamp() if period else None
    wanted = set().union(*(TYPES[t] for t in types)) if types else None
    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d.casefold() not in SKIP_DIRS]
        for name in names:
            if name.startswith(('~$', '.')):
                continue
            path = Path(root) / name
            if wanted is not None and path.suffix.casefold() not in wanted:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if since and stat.st_mtime < since:
                continue
            files.append((path, stat))
            if len(files) >= limit:
                return files, True
    return files, False


def say_size(size):
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if size < 1024 or unit == 'ГБ':
            return f'{size:.0f} {unit}' if unit == 'Б' else f'{size:.1f} {unit}'.replace('.', ',')
        size /= 1024


def say_number(value):
    from .brain.numbers import say_number as fmt
    return fmt(value)


def keywords(texts, top=12):
    counter = Counter()
    for text in texts:
        words = re.findall(r'[A-Za-zА-Яа-яЁё]{5,}', text.casefold())
        counter.update(w for w in words if w not in STOPWORDS)
    return [w for w, _ in counter.most_common(top)]


# ---------------- менеджер ----------------
class FileStudy:
    def __init__(self, store, events=None, brain=None, notify=None, speak=None, open_path=None):
        self.store = store
        self.events = events
        self.brain = brain
        self.notify = notify
        self.speak = speak
        self.open_path = open_path or _system_open
        self.running = None
        self.last_report = None
        self.lock = threading.Lock()

    def handle(self, text, owner=None, settings=None):
        request = parse(text)
        if request is None:
            return None
        kind = request[0]
        if kind == 'open_report':
            if not self.last_report or not Path(self.last_report).exists():
                return 'Справок пока нет. Скажите, например: «проштудируй папку загрузки».'
            self.open_path(self.last_report)
            return 'Открываю справку.'
        if kind == 'latest':
            return self.open_latest()
        if kind == 'open_folder':
            folder = resolve_folder(request[1])
            if folder is None:
                return f'Не нашёл папку «{request[1]}».'
            self.open_path(folder)
            return f'Открываю папку {folder.name}.'
        if kind == 'find':
            return self.find(request[1])
        if kind == 'grep':
            args = request[1]
            folder = resolve_folder(args['folder']) if args.get('folder') else None
            return self.start('grep', folder or Path.home(), dict(args, types=['text', 'word', 'pdf', 'table', 'slides']),
                              settings or {})
        args = request[1]
        folder = resolve_folder(args['folder'])
        if folder is None:
            return (f"Не нашёл папку «{args['folder']}». Скажите, например: «проштудируй папку загрузки» "
                    'или «изучи документы на рабочем столе».')
        return self.start(kind, folder, args, settings or {})

    # ---- быстрые действия ----
    def open_latest(self):
        folder = known_folders().get('загрузки')
        if folder is None:
            return 'Не нашёл папку «Загрузки».'
        files = [p for p in folder.iterdir() if p.is_file() and not p.name.endswith(('.crdownload', '.part', '.tmp'))]
        if not files:
            return 'В папке «Загрузки» пусто.'
        latest = max(files, key=lambda p: p.stat().st_mtime)
        self.open_path(latest)
        return f'Открываю {latest.name}.'

    def find(self, name, limit=5):
        from difflib import SequenceMatcher
        query = name.casefold()
        roots = list(known_folders().values()) or [Path.home()]
        found = []
        deadline = time.monotonic() + 4.0  # поиск по имени — не дольше 4 секунд
        for root in roots:
            for current, dirs, names in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.casefold() not in SKIP_DIRS]
                for file_name in names:
                    stem = Path(file_name).stem.casefold()
                    if query in stem or SequenceMatcher(None, query, stem).ratio() > 0.8:
                        found.append(Path(current) / file_name)
                if time.monotonic() > deadline or len(found) > 50:
                    break
        if not found:
            return f'Файл «{name}» не нашёл в Документах, Загрузках и на Рабочем столе.'
        found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        self.open_path(found[0])
        others = '' if len(found) == 1 else f' Ещё похожих: {len(found) - 1}, например: ' + \
            ', '.join(p.name for p in found[1:limit]) + '.'
        return f'Открываю {found[0].name} ({found[0].parent.name}).{others}'

    # ---- долгие задачи в фоне ----
    def start(self, kind, folder, args, settings):
        with self.lock:
            if self.running is not None and self.running.is_alive():
                return 'Я ещё изучаю файлы — дождитесь окончания (прогресс в окне ассистента).'
            files, cut = collect(folder, args.get('types'), args.get('period'))
            if not files:
                what = ', '.join(TYPE_TITLES[t] for t in args.get('types') or []) or 'файлов'
                return f'В папке «{folder.name}» нет подходящих {what}.'
            self.running = threading.Thread(target=self._run, args=(kind, folder, files, args, settings),
                                            daemon=True, name='file-study')
            self.running.start()
        label = {'study': 'Изучаю', 'calc': 'Считаю итоги в', 'grep': 'Ищу в'}[kind]
        return f"{label} {len(files)} файл(ов) в «{folder.name}»{' (первые ' + str(MAX_FILES) + ')' if cut else ''}. " \
               'Прогресс — в окне ассистента, результат скажу.'

    def _progress(self, task, done, total, current='', finished=False, title=''):
        if self.events is not None:
            self.events.emit('progress', task=task, done=done, total=total, current=current, finished=finished,
                             title=title)

    def _run(self, kind, folder, files, args, settings):
        task = f'{kind}-{int(time.time())}'
        title = {'study': 'Изучаю файлы', 'calc': 'Считаю таблицы', 'grep': 'Ищу в файлах'}[kind] + f' · {folder.name}'
        try:
            results = self._read_all(task, title, files, tables=kind == 'calc')
            if kind == 'study':
                text = self._study_report(folder, files, results, settings, task, title)
            elif kind == 'calc':
                text = self._calc_report(folder, results, args.get('what', 'sum'))
            else:
                text = self._grep_report(folder, results, args['query'])
        except Exception as exc:
            log.exception('File study failed')
            text = f'Не получилось изучить файлы: {exc}'
        self._progress(task, len(files), len(files), finished=True, title=title)
        if self.notify:
            self.notify(text)
        if self.speak:
            self.speak(text.split('\n')[0][:600])

    def _read_all(self, task, title, files, tables=False):
        results = {}
        total = len(files)
        done = 0
        last = 0.0
        readable = {'text', 'word', 'table', 'pdf', 'slides'}

        def work(item):
            path, stat = item
            kind = kind_of(path)
            if kind not in readable or stat.st_size > MAX_BYTES * 8:
                return path, kind, stat, None
            try:
                if tables:
                    return path, kind, stat, read_table(path)
                return path, kind, stat, read_text(path, kind)
            except Exception as exc:
                log.debug('Cannot read %s: %s', path, exc)
                return path, kind, stat, None

        workers = min(16, (os.cpu_count() or 4) * 2)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='file-read') as pool:
            for future in as_completed([pool.submit(work, item) for item in files]):
                path, kind, stat, content = future.result()
                results[path] = (kind, stat, content)
                done += 1
                now = time.monotonic()
                if now - last > 0.15 or done == total:
                    self._progress(task, done, total, path.name, title=title)
                    last = now
        return results

    def _study_report(self, folder, files, results, settings, task, title):
        by_kind = Counter(kind for kind, _, _ in results.values())
        size = sum(stat.st_size for _, stat, _ in results.values())
        times = [stat.st_mtime for _, stat, _ in results.values()]
        texts = {p: c for p, (k, s, c) in results.items() if isinstance(c, str) and c.strip()}
        largest = sorted(results.items(), key=lambda x: x[1][1].st_size, reverse=True)[:3]
        newest = sorted(results.items(), key=lambda x: x[1][1].st_mtime, reverse=True)[:3]
        kinds = ', '.join(f'{n} {TYPE_TITLES.get(k, k)}' for k, n in by_kind.most_common())
        first = (f'В «{folder.name}» {len(results)} файл(ов), {say_size(size)}: {kinds}. '
                 f'Период: {datetime.fromtimestamp(min(times)):%d.%m.%Y} — {datetime.fromtimestamp(max(times)):%d.%m.%Y}.')
        words = keywords(texts.values())
        summary = ''
        if texts and self.brain is not None:
            self._progress(task, len(files), len(files), 'нейросеть составляет справку…', title=title)
            excerpt = '\n\n'.join('### ' + p.name + '\n' + re.sub(r'\s+', ' ', c)[:500] for p, c in list(texts.items())[:14])
            try:
                summary = (self.brain.complete(
                    'Ты составляешь краткую справку по файлам пользователя. По фрагментам ниже напиши 3–5 предложений: '
                    'о чём эти файлы, главное, важные даты и числа. Без markdown, по-русски.',
                    excerpt[:7000], dict(settings, llm_web_search=False)) or '').strip()
            except Exception as exc:
                log.info('LLM summary skipped: %s', exc)
        spoken = first + (' ' + summary if summary else (f" Частые темы: {', '.join(words[:6])}." if words else ''))
        report = [f'# Справка: {folder}', f'Составлена {datetime.now():%d.%m.%Y %H:%M}', '', first, '']
        if summary:
            report += ['## Кратко', summary, '']
        if words:
            report += ['## Ключевые слова', ', '.join(words), '']
        report += ['## Самые большие', *[f'- {p.name} — {say_size(s.st_size)}' for p, (_, s, _) in largest], '',
                   '## Самые новые', *[f'- {p.name} — {datetime.fromtimestamp(s.st_mtime):%d.%m.%Y %H:%M}'
                                       for p, (_, s, _) in newest], '', '## Файлы']
        for path, (kind, stat, content) in sorted(results.items(), key=lambda x: str(x[0]).casefold()):
            line = re.sub(r'\s+', ' ', content)[:160] if isinstance(content, str) else ''
            report.append(f'- {path.relative_to(folder)} ({say_size(stat.st_size)}){": " + line if line else ""}')
        path = self._save_report(folder, '\n'.join(report))
        return spoken + f'\nПолная справка: {path}. Скажите «открой справку».'

    def _calc_report(self, folder, results, what):
        lines, spoken = [], []
        grand = Counter()
        counts = Counter()
        tables = 0
        for path, (kind, stat, sheets) in results.items():
            if not sheets:
                continue
            totals = table_totals(sheets)
            if not totals:
                continue
            tables += 1
            lines.append(f'## {path.name}')
            for name, value, count in totals:
                grand[name] += value
                counts[name] += count
                average = value / count if count else 0
                lines.append(f'- {name}: сумма {say_number(value)}, среднее {say_number(average)}, значений {count}')
        if not tables:
            return f'В таблицах «{folder.name}» не нашёл числовых столбцов.'
        for name, value in grand.most_common(4):
            if what == 'average':
                spoken.append(f'«{name}» — в среднем {say_number(value / max(1, counts[name]))}')
            elif what == 'count':
                spoken.append(f'«{name}» — {counts[name]} значений')
            else:
                spoken.append(f'«{name}» — итого {say_number(value)}')
        path = self._save_report(folder, f'# Итоги таблиц: {folder}\n\n' + '\n'.join(lines), prefix='итоги')
        return (f'Таблиц с числами: {tables}. ' + '; '.join(spoken) + '.' +
                f'\nПодробно по каждой таблице: {path}. Скажите «открой справку».')

    def _grep_report(self, folder, results, query):
        needle = query.casefold()
        hits = []
        for path, (kind, stat, content) in results.items():
            if isinstance(content, str) and needle in content.casefold():
                index = content.casefold().find(needle)
                snippet = re.sub(r'\s+', ' ', content[max(0, index - 60): index + 90])
                hits.append((path, content.casefold().count(needle), snippet))
        if not hits:
            return f'«{query}» не встречается в файлах папки «{folder.name}».'
        hits.sort(key=lambda h: h[1], reverse=True)
        lines = [f'- {p} — {n} раз: …{s}…' for p, n, s in hits]
        path = self._save_report(folder, f'# Поиск «{query}»: {folder}\n\n' + '\n'.join(lines), prefix='поиск')
        top = ', '.join(p.name for p, _, _ in hits[:3])
        return f'«{query}» нашлось в {len(hits)} файл(ах): {top}.\nСписок с фрагментами: {path}. Скажите «открой справку».'

    def _save_report(self, folder, text, prefix='справка'):
        base = known_folders().get('документы', Path.home()) / 'Андрей' / 'Справки'
        base.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[^\w.-]+', '_', folder.name)[:40] or 'папка'
        path = base / f'{prefix}-{name}-{datetime.now():%Y-%m-%d_%H-%M}.md'
        path.write_text(text, encoding='utf-8')
        self.last_report = str(path)
        return path


def _system_open(path):
    from .web_services import system_open
    if not system_open(str(path)) and sys.platform.startswith('linux'):
        import subprocess
        try:
            subprocess.Popen(['xdg-open', str(path)])
        except OSError:
            pass
