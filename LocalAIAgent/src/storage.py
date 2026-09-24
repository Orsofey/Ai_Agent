"""Persistent local storage. No user data are written into the install folder."""
import json
import os
import secrets
import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path


def data_root():
    if os.getenv('LOCAL_AI_DATA_DIR'):
        return Path(os.environ['LOCAL_AI_DATA_DIR'])
    if sys.platform == 'win32':
        return Path(os.getenv('LOCALAPPDATA', Path.home())) / 'LocalAIAgent'
    return Path.home() / '.local' / 'share' / 'LocalAIAgent'


THEMES = ('aurora', 'cyberpunk', 'sakura', 'ocean', 'luxe', 'dark', 'light')

DEFAULTS = {
    # Внешний вид
    'theme': 'aurora', 'animations': True, 'show_hud': True,
    # Голос: ввод
    'voice_language': 'auto', 'stt_engine': 'auto', 'microphone': '',
    'microphone_label': '', 'native_microphone': '', 'auto_send': True,
    'voice_enabled': True, 'always_listen': True, 'wake_word': 'Андрей',
    'wake_aliases': '', 'follow_up_seconds': 5, 'silence_ms': 600,
    'vad_sensitivity': 50, 'hotkey': 'ctrl+alt+space',
    # Голос: вывод
    'tts_enabled': True, 'tts_voice': 'irina', 'tts_voice_en': 'amy', 'tts_rate': 110,
    # ИИ
    'llm_provider': 'local', 'local_model': 'qwen3-4b', 'llm_gpu': False,
    'llm_web_search': True, 'openai_base_url': 'http://127.0.0.1:11434/v1',
    'openai_model': 'qwen2.5:7b-instruct', 'answer_style': 'short', 'city': 'Москва',
    # Управление ПК
    'type_method': 'auto', 'messenger_autosend': False, 'autostart': True,
    'minimize_to_tray': True, 'video_source': 'youtube',
}

CHOICES = {
    'theme': THEMES,
    'voice_language': ('ru', 'en', 'auto'),
    'stt_engine': ('auto', 'parakeet', 'gigaam', 'whisper'),
    'llm_provider': ('local', 'openai', 'off'),
    'local_model': ('qwen3-4b', 'qwen2.5-7b', 'qwen2.5-3b'),
    'answer_style': ('short', 'detailed'),
    'type_method': ('auto', 'keys', 'paste'),
    'video_source': ('youtube', 'rutube'),
    'tts_voice': ('irina', 'denis', 'baya', 'aidar', 'kseniya', 'xenia'),
    'tts_voice_en': ('amy', 'lessac'),
}

RANGES = {
    'silence_ms': (250, 5000), 'follow_up_seconds': (0, 30),
    'vad_sensitivity': (10, 90), 'tts_rate': (60, 200),
}

# Секреты (ключи API) хранятся отдельно и никогда не возвращаются в /api/settings.
SECRET_NAMES = ('openai_api_key',)


class Store:
    def __init__(self, root=None):
        self.root = Path(root or data_root())
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'agent.sqlite3'
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(owner TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, owner TEXT, role TEXT, text TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, password TEXT, email TEXT);
            ''')
            for key in ('pairing_token', 'session_secret'):
                db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', (key, secrets.token_urlsafe(32)))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    def meta(self, key):
        with self.connect() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        with self.connect() as db:
            if value is None:
                db.execute('DELETE FROM meta WHERE key=?', (key,))
            else:
                db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    # ---- секреты ----
    def secret(self, name):
        if name not in SECRET_NAMES:
            raise ValueError('Неизвестный секрет')
        value = self.meta('secret:' + name)
        if value:
            return value
        return os.getenv(name.upper(), '') or None

    def set_secret(self, name, value):
        if name not in SECRET_NAMES:
            raise ValueError('Неизвестный секрет')
        value = str(value or '').strip()
        if len(value) > 500:
            raise ValueError('Слишком длинный ключ')
        self.set_meta('secret:' + name, value or None)

    def secrets_status(self):
        return {name: bool(self.secret(name)) for name in SECRET_NAMES}

    # ---- настройки ----
    def settings(self, owner):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE owner=?', (owner,)).fetchone()
        stored = json.loads(row[0]) if row else {}
        value = dict(DEFAULTS)
        for key, item in stored.items():
            # Старые/чужие значения не должны ломать запуск после обновления.
            if key in DEFAULTS and type(item) is type(DEFAULTS[key]) and self._valid(key, item):
                value[key] = item
        # Старое имя по умолчанию из прошлых версий заменяем на новое.
        if value['wake_word'] == 'Орсофей' and 'wake_word_migrated' not in stored:
            value['wake_word'] = DEFAULTS['wake_word']
        return value

    @staticmethod
    def _valid(key, item):
        if key in CHOICES and item not in CHOICES[key]:
            return False
        if key in RANGES and not RANGES[key][0] <= item <= RANGES[key][1]:
            return False
        return True

    def save_settings(self, owner, incoming):
        with self.lock:
            value = self.settings(owner)
            for key, item in incoming.items():
                if key not in DEFAULTS:
                    continue
                if type(item) is not type(DEFAULTS[key]):
                    raise ValueError('Неверный тип настройки: ' + key)
                if isinstance(item, str):
                    item = item.strip()
                    if len(item) > 300:
                        raise ValueError('Слишком длинная настройка')
                if not self._valid(key, item):
                    raise ValueError('Недопустимое значение настройки: ' + key)
                value[key] = item
            if not value['wake_word']:
                raise ValueError('Имя агента не может быть пустым')
            stored = dict(value, wake_word_migrated=True)
            with self.connect() as db:
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (owner, json.dumps(stored, ensure_ascii=False)))
            return value

    # ---- история ----
    def add(self, owner, role, text):
        with self.connect() as db:
            db.execute('INSERT INTO history(owner,role,text) VALUES (?,?,?)', (owner, role, text))

    def history(self, owner, limit=1000):
        with self.connect() as db:
            rows = db.execute('SELECT role,text,created FROM history WHERE owner=? ORDER BY id DESC LIMIT ?', (owner, limit)).fetchall()
        return [dict(role=r, text=t, created=c) for r, t, c in reversed(rows)]

    def clear(self, owner):
        with self.connect() as db:
            db.execute('DELETE FROM history WHERE owner=?', (owner,))

    def export(self, owner):
        return {'version': 5, 'settings': self.settings(owner), 'history': self.history(owner, limit=-1)}
