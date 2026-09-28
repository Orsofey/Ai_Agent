"""Интеграции с другими приложениями: читать их данные и выполнять в них действия голосом.

Папка интеграций: %LOCALAPPDATA%\\LocalAIAgent\\integrations (Настройки → Управление ПК → «Интеграции»).

1. JSON без программирования (tracker.json):
   {
     "name": "Трекер",
     "commands": [
       {"phrases": ["что в трекере( на (?P<day>сегодня|завтра))?", "мои задачи"],
        "method": "GET", "url": "https://tracker.example/api/tasks?day={day}",
        "headers": {"Authorization": "Bearer {secret:TRACKER_TOKEN}"},
        "say": "Задач: {count}. {items[*].title}"},
       {"phrases": ["добавь в трекер (?P<text>.+)"],
        "method": "POST", "url": "https://tracker.example/api/tasks", "json": {"title": "{text}"},
        "say": "Добавил в трекер: {text}"}
     ],
     "context": {"phrases": ["трекер", "задач", "привычк"], "file": "C:/Users/me/Documents/tracker.json"}
   }
   • phrases — регулярные выражения (без учёта регистра), именованные группы подставляются в url/json/say;
   • источник — "url" (HTTP API) или "file" (локальный JSON/CSV/TXT, например экспорт из приложения);
   • say — ответ голосом: {поле}, {поле.вложенное}, {список[*].поле} (до 10 значений через запятую);
   • context — если вопрос содержит эти слова, данные источника передаются нейросети вместе с вопросом
     («Что у меня на сегодня по трекеру?» — ответит по вашим данным);
   • секреты: {secret:ИМЯ} берётся из переменной окружения ИМЯ или из integrations/secrets.json.

2. Python-плагин (tracker.py) для сложной логики:
   COMMANDS = [(r'сколько шагов сегодня', handler)]      # handler(match, settings) -> str
   def context(question, settings) -> str | None           # необязательно: данные для нейросети
"""
import csv
import importlib.util
import io
import json
import logging
import os
import re
import threading
from pathlib import Path

import requests

log = logging.getLogger(__name__)
METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}
MAX_CONTEXT = 3000


def folder(root):
    return Path(root) / 'integrations'


class Integrations:
    def __init__(self, root, session=None):
        self.root = Path(root)
        self.session = session or requests.Session()
        self.lock = threading.Lock()
        self.items = []
        self.errors = []
        self.mtime = None

    # ---- загрузка ----
    def _stamp(self):
        path = folder(self.root)
        if not path.is_dir():
            return None
        return tuple(sorted((p.name, p.stat().st_mtime) for p in path.iterdir() if p.suffix in ('.json', '.py')))

    def load(self, force=False):
        """Перечитать папку, если файлы изменились (новые интеграции подхватываются без перезапуска)."""
        stamp = self._stamp()
        if not force and stamp == self.mtime:
            return self.items
        with self.lock:
            items, errors = [], []
            path = folder(self.root)
            for file in sorted(path.glob('*.json')) if path.is_dir() else []:
                if file.name == 'secrets.json':
                    continue
                try:
                    items.append(self._from_json(json.loads(file.read_text(encoding='utf-8')), file))
                except Exception as exc:
                    errors.append(f'{file.name}: {exc}')
            for file in sorted(path.glob('*.py')) if path.is_dir() else []:
                try:
                    items.append(self._from_python(file))
                except Exception as exc:
                    errors.append(f'{file.name}: {exc}')
            self.items, self.errors, self.mtime = items, errors, stamp
            for error in errors:
                log.warning('Integration skipped: %s', error)
            return items

    @staticmethod
    def _compile(phrases):
        return [re.compile(p, re.I) for p in phrases]

    def _from_json(self, data, file):
        name = str(data.get('name') or file.stem)
        commands = []
        for spec in data.get('commands', []):
            if spec.get('method', 'GET').upper() not in METHODS:
                raise ValueError('метод должен быть GET/POST/PUT/PATCH/DELETE')
            commands.append((self._compile(spec.get('phrases', [])), spec))
        context = data.get('context')
        if context:
            context = dict(context, _patterns=self._compile(context.get('phrases', [])))
        return {'name': name, 'kind': 'json', 'commands': commands, 'context': context, 'file': file.name}

    def _from_python(self, file):
        spec = importlib.util.spec_from_file_location('andrey_integration_' + file.stem, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        commands = [(self._compile([pattern]), handler) for pattern, handler in getattr(module, 'COMMANDS', [])]
        return {'name': getattr(module, 'NAME', file.stem), 'kind': 'python', 'commands': commands,
                'context': getattr(module, 'context', None), 'file': file.name}

    def status(self):
        self.load()
        return {'folder': str(folder(self.root)), 'errors': self.errors,
                'items': [{'name': i['name'], 'file': i['file'], 'commands': len(i['commands']),
                           'context': bool(i['context'])} for i in self.items]}

    # ---- выполнение ----
    def handle(self, text, settings=None):
        """Команда интеграции → ответ или None, если фраза не относится ни к одной интеграции."""
        value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
        for item in self.load():
            for patterns, action in item['commands']:
                for pattern in patterns:
                    match = pattern.fullmatch(value)
                    if not match:
                        continue
                    try:
                        if item['kind'] == 'python':
                            return str(action(match, settings or {}))
                        return self._run(action, {k: v or '' for k, v in match.groupdict().items()})
                    except Exception as exc:
                        log.warning('Integration %s failed: %s', item['name'], exc)
                        return f'Не удалось выполнить команду «{item["name"]}»: {exc}'
        return None

    def context(self, question, settings=None):
        """Данные интеграций для вопроса к нейросети («что у меня в трекере на сегодня?»)."""
        parts = []
        for item in self.load():
            source = item['context']
            if not source:
                continue
            try:
                if item['kind'] == 'python':
                    data = source(question, settings or {})
                elif any(p.search(question) for p in source['_patterns']):
                    data = self._fetch(source, {})
                else:
                    data = None
            except Exception as exc:
                log.warning('Integration context %s failed: %s', item['name'], exc)
                data = None
            if data:
                text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
                parts.append(f'Данные из «{item["name"]}»:\n{text[:MAX_CONTEXT]}')
        return '\n\n'.join(parts) or None

    # ---- HTTP и файлы ----
    def _secret(self, name):
        value = os.environ.get(name)
        if value:
            return value
        try:
            return json.loads((folder(self.root) / 'secrets.json').read_text(encoding='utf-8')).get(name, '')
        except (OSError, ValueError):
            return ''

    def _fill(self, value, values):
        if isinstance(value, dict):
            return {k: self._fill(v, values) for k, v in value.items()}
        if isinstance(value, list):
            return [self._fill(v, values) for v in value]
        if not isinstance(value, str):
            return value
        value = re.sub(r'\{secret:(\w+)\}', lambda m: self._secret(m[1]), value)
        return re.sub(r'\{(\w+)\}', lambda m: str(values.get(m[1], m[0])), value)

    def _fetch(self, spec, values):
        if spec.get('file'):
            path = Path(self._fill(spec['file'], values)).expanduser()
            text = path.read_text(encoding='utf-8', errors='replace')
            if path.suffix.lower() == '.json':
                return json.loads(text)
            if path.suffix.lower() == '.csv':
                return list(csv.DictReader(io.StringIO(text)))[:200]
            return text
        url = self._fill(spec['url'], values)
        if not re.match(r'^https?://', url, re.I):
            raise ValueError('поддерживаются только адреса http(s)')
        response = self.session.request(spec.get('method', 'GET').upper(), url, headers=self._fill(spec.get('headers', {}), values),
                                        json=self._fill(spec['json'], values) if 'json' in spec else None, timeout=10)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return response.text

    def _run(self, spec, values):
        data = self._fetch(spec, values)
        template = spec.get('say')
        if not template:
            return 'Готово.' if spec.get('method', 'GET').upper() != 'GET' else summarize(data)
        return say(template, data, values)


def _path(data, path):
    for part in path.split('.'):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def say(template, data, values=None):
    """Шаблон ответа: {поле}, {а.б}, {список[*].поле}, {count} — длина списка/ответа."""
    values = dict(values or {})

    def repl(match):
        key = match[1]
        if key in values:
            return str(values[key])
        if key == 'count':
            items = data if isinstance(data, list) else next((v for v in (data or {}).values() if isinstance(v, list)), []) \
                if isinstance(data, dict) else []
            return str(len(items))
        if '[*]' in key:
            head, _, tail = key.partition('[*]')
            items = _path(data, head) if head else data
            items = items if isinstance(items, list) else []
            found = [_path(x, tail.lstrip('.')) if tail else x for x in items[:10]]
            return ', '.join(str(x) for x in found if x not in (None, '')) or 'ничего'
        value = _path(data, key)
        return match[0] if value is None else str(value)
    return re.sub(r'\{([\w.\[\]*]+)\}', repl, template)


def summarize(data):
    if isinstance(data, list):
        names = [str(x.get('title') or x.get('name') or x) if isinstance(x, dict) else str(x) for x in data[:10]]
        return f'Записей: {len(data)}. ' + ', '.join(names) if data else 'Пусто.'
    if isinstance(data, dict):
        return ', '.join(f'{k}: {v}' for k, v in list(data.items())[:8] if not isinstance(v, (dict, list)))
    return str(data)[:500]
