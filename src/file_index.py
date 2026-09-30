"""Мгновенный поиск файлов: фоновый индекс имён и текста (как в Everything), ответ за доли секунды.

Индекс — SQLite FTS5 в папке данных (file_index.sqlite3). Сначала индексируются имена всех файлов в
Рабочем столе, Документах, Загрузках, Изображениях, Музыке и Видео (и в папках из настроек), затем в фоне —
текст документов (txt, md, docx, pdf, xlsx, csv, pptx…). Изменения подхватываются периодическим
пересканированием: быстро для Загрузок и Рабочего стола, полностью — раз в 10 минут. Всё локально.

Голосом: «найди файл отчёт», «найди документы про аренду», «где файл с договором», «открой второй»;
в окне ассистента — поле поиска над чатом (результаты по мере набора).
"""
import logging
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

TEXT_EXTS = {'.txt', '.md', '.log', '.csv', '.tsv', '.json', '.xml', '.html', '.htm', '.rtf', '.docx', '.odt', '.pdf',
             '.xlsx', '.pptx', '.odp', '.ini', '.py', '.js', '.ts', '.css', '.yml', '.yaml', '.sql'}
BODY_LIMIT = 16_000           # символов текста на файл в индексе (для поиска и фрагментов)
TEXT_MAX_BYTES = 40 * 1024 * 1024
FULL_EVERY = 600              # полное пересканирование, секунд
QUICK_EVERY = 45              # Загрузки и Рабочий стол
START_DELAY = 15              # не мешаем запуску приложения
SKIP_DIRS = {'node_modules', '.git', '__pycache__', 'appdata', '$recycle.bin', '.venv', 'venv', 'site-packages',
             '.cache', '.gradle', '.idea', 'build', 'dist', '.dart_tool', 'library'}
STOP = {'файл', 'файлы', 'файла', 'документ', 'документы', 'документа', 'где', 'мой', 'мои', 'про', 'для', 'с', 'со',
        'в', 'во', 'на', 'по', 'и', 'или', 'о', 'об', 'обо', 'который', 'которые', 'все', 'всё', 'найди', 'покажи'}

ENDINGS = ('ами', 'ями', 'ого', 'его', 'ому', 'ему', 'ыми', 'ими', 'ах', 'ях', 'ов', 'ев', 'ей', 'ой', 'ий', 'ый',
           'ая', 'яя', 'ое', 'ее', 'ую', 'юю', 'ом', 'ем', 'ам', 'ям', 'ы', 'и', 'а', 'я', 'е', 'у', 'ю', 'о', 'ь')


def stem(word):
    """Грубая основа русского слова для префиксного поиска: «договоре» → «договор», «аренды» → «аренд»."""
    word = word.casefold().replace('ё', 'е')
    if not re.search('[а-я]', word) or len(word) <= 4:
        return word
    for ending in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[:-len(ending)]
    return word


def terms(query):
    words = [w for w in re.findall(r'[\wё]+', str(query).casefold()) if w not in STOP]
    return [stem(w) for w in words if len(w) >= 2]


def fts_query(query):
    items = terms(query)
    if not items:
        return None
    return ' '.join('"' + t.replace('"', '') + '"*' for t in items)


def default_folders():
    from .files import known_folders
    return list(known_folders().values())


class FileIndex:
    def __init__(self, root, folders=None, background=False, reader=None):
        self.path = Path(root) / 'file_index.sqlite3'
        self.folders = folders or default_folders      # функция → список папок
        self.reader = reader                             # (path, kind) → текст; по умолчанию files.read_text
        self.lock = threading.RLock()
        self.state = {'files': 0, 'texts': 0, 'scanning': False, 'last_scan': None, 'duration': None}
        self._stop = threading.Event()
        self._thread = None
        self._scan_lock = threading.Lock()
        self.fts = True
        self._init_db()
        if background:
            self.start()

    # ---- база ----
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=NORMAL')
            # SQLite lower() знает только латиницу — для «Отчёт» в середине имени нужен свой.
            db.create_function('ru_lower', 1, lambda v: _yo(str(v or '').casefold()), deterministic=True)
            with db:
                yield db
        finally:
            db.close()

    def _init_db(self):
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, name TEXT, folder TEXT, '
                       'ext TEXT, size INTEGER, mtime REAL, text_state INTEGER DEFAULT 0)')
            db.execute('CREATE INDEX IF NOT EXISTS files_name ON files(name)')
            try:
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(name, body, "
                           "tokenize='unicode61 remove_diacritics 2')")
            except sqlite3.OperationalError:
                self.fts = False  # SQLite без FTS5 — ищем только по имени через LIKE
                log.warning('FTS5 unavailable: searching file names only')
            self.state['files'] = db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
            self.state['texts'] = db.execute('SELECT COUNT(*) FROM files WHERE text_state=2').fetchone()[0]

    # ---- фоновая работа ----
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name='file-index')
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        if self._stop.wait(START_DELAY):
            return
        last_full = 0.0
        while not self._stop.is_set():
            try:
                if time.monotonic() - last_full >= FULL_EVERY:
                    self.scan()
                    last_full = time.monotonic()
                else:
                    from .files import known_folders
                    known = known_folders()
                    self.scan([known[k] for k in ('загрузки', 'рабочий стол') if k in known], prune=False)
            except Exception:
                log.exception('File index scan failed')
            self._stop.wait(QUICK_EVERY)

    def scan(self, folders=None, prune=True):
        """Обойти папки: новые и изменённые файлы — в индекс, удалённые — из индекса. Затем текст документов."""
        if not self._scan_lock.acquire(blocking=False):
            return self.state
        started = time.monotonic()
        self.state['scanning'] = True
        try:
            roots = [Path(f) for f in (folders if folders is not None else self.folders()) if Path(f).is_dir()]
            with self.connect() as db:
                known = {}
                for root in roots:
                    like = str(root).rstrip('\\/') + os.sep + '%'
                    for path, size, mtime in db.execute('SELECT path,size,mtime FROM files WHERE path LIKE ?', (like,)):
                        known[path] = (size, mtime)
            seen = set()
            batch = []
            for root in roots:
                for entry in self._walk(root):
                    path = entry.path
                    seen.add(path)
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    old = known.get(path)
                    if old and old[0] == stat.st_size and abs(old[1] - stat.st_mtime) < 1:
                        continue
                    batch.append((path, entry.name, str(Path(path).parent), Path(path).suffix.casefold(), stat.st_size,
                                  stat.st_mtime))
                    if len(batch) >= 500:
                        self._store(batch)
                        batch = []
            if batch:
                self._store(batch)
            if prune:
                gone = [p for p in known if p not in seen]
                if gone:
                    self._remove(gone)
            self._index_texts()
            with self.connect() as db:
                self.state['files'] = db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
                self.state['texts'] = db.execute('SELECT COUNT(*) FROM files WHERE text_state=2').fetchone()[0]
            self.state['last_scan'] = time.strftime('%H:%M:%S')
            self.state['duration'] = round(time.monotonic() - started, 2)
        finally:
            self.state['scanning'] = False
            self._scan_lock.release()
        return self.state

    def _walk(self, root):
        stack = [root]
        while stack:
            folder = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        name = entry.name
                        if name.startswith(('.', '~$')):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if name.casefold() not in SKIP_DIRS:
                                    stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                yield entry
                        except OSError:
                            continue
            except OSError:
                continue

    def _store(self, rows):
        with self.lock, self.connect() as db:
            for path, name, folder, ext, size, mtime in rows:
                row = db.execute('SELECT id FROM files WHERE path=?', (path,)).fetchone()
                state = 0 if ext in TEXT_EXTS and size <= TEXT_MAX_BYTES else 3   # 3 — текст не нужен
                if row:
                    db.execute('UPDATE files SET size=?, mtime=?, text_state=? WHERE id=?', (size, mtime, state, row[0]))
                    file_id = row[0]
                    if self.fts:
                        db.execute('DELETE FROM fts WHERE rowid=?', (file_id,))
                else:
                    file_id = db.execute('INSERT INTO files(path,name,folder,ext,size,mtime,text_state) VALUES (?,?,?,?,?,?,?)',
                                         (path, name, folder, ext, size, mtime, state)).lastrowid
                if self.fts:
                    db.execute('INSERT INTO fts(rowid,name,body) VALUES (?,?,?)', (file_id, _name_words(name), ''))

    def _remove(self, paths):
        with self.lock, self.connect() as db:
            for path in paths:
                row = db.execute('SELECT id FROM files WHERE path=?', (path,)).fetchone()
                if row:
                    db.execute('DELETE FROM files WHERE id=?', (row[0],))
                    if self.fts:
                        db.execute('DELETE FROM fts WHERE rowid=?', (row[0],))

    def _index_texts(self, limit=2000):
        if not self.fts:
            return
        with self.connect() as db:
            todo = db.execute('SELECT id,path,name FROM files WHERE text_state=0 ORDER BY mtime DESC LIMIT ?',
                              (limit,)).fetchall()
        if not todo:
            return
        reader = self.reader or _read

        def work(item):
            file_id, path, name = item
            try:
                return file_id, name, _yo((reader(Path(path)) or '')[:BODY_LIMIT]), 2
            except Exception as exc:
                log.debug('No text for %s: %s', path, exc)
                return file_id, name, '', 1

        with ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 2), thread_name_prefix='index-text') as pool:
            for chunk in _chunks(todo, 50):
                if self._stop.is_set():
                    return
                results = list(pool.map(work, chunk))
                with self.lock, self.connect() as db:
                    for file_id, name, body, state in results:
                        db.execute('UPDATE files SET text_state=? WHERE id=?', (state, file_id))
                        db.execute('DELETE FROM fts WHERE rowid=?', (file_id,))
                        db.execute('INSERT INTO fts(rowid,name,body) VALUES (?,?,?)', (file_id, _name_words(name), body))

    # ---- поиск ----
    def search(self, query, limit=20, content=True, exts=None):
        """Список совпадений: имя важнее текста, свежие файлы выше. Обычно < 50 мс."""
        started = time.perf_counter()
        results = []
        match = fts_query(query)
        with self.connect() as db:
            if self.fts and match:
                column = '' if content else 'name:'
                sql = ("SELECT f.path,f.name,f.folder,f.size,f.mtime,snippet(fts,1,'«','»','…',10), bm25(fts,8.0,1.0) "
                       "FROM fts JOIN files f ON f.id=fts.rowid WHERE fts MATCH ? ")
                params = [column + '(' + match + ')' if column else match]
                if exts:
                    sql += 'AND f.ext IN (%s) ' % ','.join('?' * len(exts))
                    params += list(exts)
                sql += 'ORDER BY bm25(fts,8.0,1.0), f.mtime DESC LIMIT ?'
                try:
                    rows = db.execute(sql, params + [limit * 3]).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                for path, name, folder, size, mtime, snippet, rank in rows:
                    results.append({'path': path, 'name': name, 'folder': folder, 'size': size, 'mtime': mtime,
                                    'snippet': re.sub(r'\s+', ' ', snippet or '').strip()})
            if len(results) < limit:
                # Подстрока в середине имени («годовойотчет»), когда FTS не нашёл по началу слова.
                needle = _yo(str(query).strip().casefold())
                if needle:
                    rows = db.execute('SELECT path,name,folder,size,mtime FROM files WHERE ru_lower(name) LIKE ? '
                                      'ORDER BY mtime DESC LIMIT ?', ('%' + needle.replace('%', '') + '%', limit)).fetchall()
                    have = {r['path'] for r in results}
                    for path, name, folder, size, mtime in rows:
                        if path not in have and (not exts or Path(name).suffix.casefold() in exts):
                            results.append({'path': path, 'name': name, 'folder': folder, 'size': size, 'mtime': mtime,
                                            'snippet': ''})
        results = [r for r in results if Path(r['path']).exists()][:limit]
        self.last_elapsed = round((time.perf_counter() - started) * 1000, 1)
        return results

    def contains(self, path):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM files WHERE path=?', (str(path),)).fetchone() is not None

    def status(self):
        return dict(self.state, fts=self.fts, ready=self.state['files'] > 0)


def _name_words(name):
    """Имя для поиска: «Годовой_отчёт-2025.pdf» → «Годовой отчет 2025 pdf»."""
    return _yo(re.sub(r'[_\-.()\[\]]+', ' ', name))


def _yo(text):
    """FTS5 не считает «ё» и «е» одной буквой — приводим к «е», как и запросы."""
    return text.replace('ё', 'е').replace('Ё', 'Е')


def _chunks(items, size):
    for n in range(0, len(items), size):
        yield items[n:n + size]


def _read(path):
    from .files import kind_of, read_text
    return read_text(path, kind_of(path))


# ---------------- голос ----------------
FIND = re.compile(r'^(?:найди|найти|поищи|покажи|где)\s+(?:мне\s+)?(?:мой\s+|мои\s+)?(?:(?P<kind>файл\w*|документ\w*|'
                  r'таблиц\w*|презентаци\w*|pdf|пдф|фото\w*|картинк\w*)\s+)(?:(?:про|о|об|с|со|где|в котор\w+)\s+)?'
                  r'(?P<query>.+)$', re.I)
PICK = re.compile(r'^(?:открой|покажи|запусти)\s+(?P<n>перв\w+|втор\w+|трет\w+|четв[её]рт\w+|пят\w+|\d+)(?:\s+(?:файл|документ|результат))?'
                  r'(?P<reveal>\s+в\s+папке)?$', re.I)
KIND_EXTS = {'таблиц': {'.xlsx', '.xls', '.csv', '.ods'}, 'презентаци': {'.pptx', '.ppt', '.odp'},
             'pdf': {'.pdf'}, 'пдф': {'.pdf'}, 'фото': {'.jpg', '.jpeg', '.png', '.heic', '.webp'},
             'картинк': {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.bmp'}}
ORDINALS = {'перв': 1, 'втор': 2, 'трет': 3, 'четв': 4, 'пят': 5}


def parse(text):
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    match = PICK.match(value)
    if match:
        word = match['n'].casefold()
        n = int(word) if word.isdigit() else next((v for k, v in ORDINALS.items() if word.startswith(k)), 1)
        return 'pick', n, bool(match['reveal'])
    match = FIND.match(value)
    if match and match['query'].strip():
        kind = match['kind'].casefold()
        exts = next((v for k, v in KIND_EXTS.items() if kind.startswith(k)), None)
        return 'find', match['query'].strip(' «»"'), exts
    return None


class FileSearch:
    """Голосовой поиск по индексу: результаты — в чат, «открой второй» открывает нужный."""

    def __init__(self, index, publish=None, opener=None, revealer=None):
        self.index = index
        self.publish = publish        # (path, text) → карточка документа в чате
        self.opener = opener
        self.revealer = revealer
        self.results = {}             # owner → последние результаты

    def handle(self, text, owner='default'):
        request = parse(text)
        if request is None:
            return None
        if request[0] == 'pick':
            found = self.results.get(owner) or []
            n = request[1]
            if not found or n > len(found):
                return None if not found else f'Результатов только {len(found)}.'
            path = Path(found[n - 1]['path'])
            if request[2]:
                self.revealer and self.revealer(path)
                return f'Показываю {path.name} в папке.'
            self.opener and self.opener(path)
            return f'Открываю {path.name}.'
        if not self.index.status()['ready']:
            return None   # индекс ещё строится — пусть ищет старый способ
        found = self.index.search(request[1], limit=8, exts=request[2])
        self.results[owner] = found
        if not found:
            return f'Не нашёл файлов по запросу «{request[1]}».'
        lines = [f'{n}. {r["name"]} — {Path(r["folder"]).name}' + (f': {r["snippet"][:120]}' if r['snippet'] else '')
                 for n, r in enumerate(found[:5], 1)]
        head = f'Нашёл {len(found)} за {self.index.last_elapsed:.0f} мс. «Открой первый» — открыть.'
        if self.publish is not None:
            self.publish(found[0]['path'], head + '\n' + '\n'.join(lines))
            return head.split('.')[0] + '.'
        return head + '\n' + '\n'.join(lines)
