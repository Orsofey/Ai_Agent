"""Built-in local LLM: llama.cpp `llama-server` + a Qwen GGUF model. Free, offline, no keys.

Сервер запускается в фоне при старте программы и держит модель в памяти,
поэтому первый ответ не ждёт загрузки. API сервера совместим с OpenAI,
с ним работает OpenAICompatibleProvider.
"""
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

LOCAL_MODELS = {
    'qwen3-4b': {
        'repos': ['bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF', 'unsloth/Qwen3-4B-Instruct-2507-GGUF'], 'pattern': 'Q4_K_M.gguf',
        'title': 'Qwen3 4B — быстрая и умная (рекомендуется)', 'size_mb': 2500, 'ram_gb': 6,
    },
    'qwen2.5-7b': {
        'repos': ['bartowski/Qwen2.5-7B-Instruct-GGUF', 'unsloth/Qwen2.5-7B-Instruct-GGUF'], 'pattern': 'Q4_K_M.gguf',
        'title': 'Qwen2.5 7B — точнее, нужен ПК с 12+ ГБ ОЗУ', 'size_mb': 4700, 'ram_gb': 12,
    },
    'qwen3-1.7b': {
        'repos': ['bartowski/Qwen_Qwen3-1.7B-GGUF', 'unsloth/Qwen3-1.7B-GGUF'], 'pattern': 'Q4_K_M.gguf',
        'title': 'Qwen3 1.7B — для слабых ПК', 'size_mb': 1100, 'ram_gb': 4,
    },
}
DEFAULT_MODEL = 'qwen3-4b'
BINARY = 'llama-server.exe' if sys.platform == 'win32' else 'llama-server'


def llm_dir(root):
    return Path(root) / 'models' / 'llm'


def runtime_dir(root, gpu=False):
    return Path(root) / 'models' / 'llama.cpp' / ('vulkan' if gpu else 'cpu')


def _bundled(*parts):
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    return base.joinpath('models', *parts)


def find_binary(root, gpu=False):
    """llama-server: папка данных → папка программы → PATH. Для GPU — сборка Vulkan."""
    flavors = ['vulkan', 'cpu'] if gpu else ['cpu', 'vulkan']
    for flavor in flavors:
        for base in (Path(root) / 'models' / 'llama.cpp' / flavor, _bundled('llama.cpp', flavor)):
            if base.is_dir():
                found = next(iter(base.rglob(BINARY)), None)
                if found:
                    return found, flavor
    found = shutil.which('llama-server')
    return (Path(found), 'system') if found else (None, None)


def find_model(root, key):
    for base in (llm_dir(root) / key, _bundled('llm', key)):
        if base.is_dir():
            files = sorted(base.glob('*.gguf'))
            if files:
                return files[0]
    return None


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class LocalLLMServer:
    def __init__(self, root, session=None):
        self.root = Path(root)
        self.process = None
        self.port = None
        self.key = None
        self.gpu = None
        self.error = None
        self.starting = False
        self.lock = threading.RLock()
        self._session = session

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.trust_env = False  # локальный адрес — без прокси
        return self._session

    @property
    def base_url(self):
        return f'http://127.0.0.1:{self.port}/v1'

    def running(self):
        return self.process is not None and self.process.poll() is None

    def healthy(self):
        if not self.running():
            return False
        try:
            return self.session.get(f'http://127.0.0.1:{self.port}/health', timeout=1.5).status_code == 200
        except Exception:
            return False

    def status(self, settings=None):
        settings = settings or {}
        key = settings.get('local_model', DEFAULT_MODEL)
        binary, flavor = find_binary(self.root, settings.get('llm_gpu', False))
        return dict(model=key, title=LOCAL_MODELS.get(key, {}).get('title', key),
                    model_installed=find_model(self.root, key) is not None,
                    runtime_installed=binary is not None, runtime=flavor,
                    running=self.running(), ready=self.healthy(), starting=self.starting, error=self.error,
                    installed_models=[k for k in LOCAL_MODELS if find_model(self.root, k)])

    def ensure(self, settings, wait=120.0):
        """Запустить сервер (если нужно) и вернуть его адрес. Бросает RuntimeError с понятным текстом."""
        key = settings.get('local_model', DEFAULT_MODEL)
        gpu = bool(settings.get('llm_gpu', False))
        with self.lock:
            if self.running() and (self.key, self.gpu) == (key, gpu):
                pass
            else:
                self.stop()
                self._start(key, gpu)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.healthy():
                self.error = None
                return self.base_url
            if not self.running():
                self.error = 'Локальная нейросеть завершилась при запуске. Подробности: logs/llama-server.log'
                raise RuntimeError(self.error)
            time.sleep(0.3)
        raise RuntimeError('Локальная нейросеть ещё загружается. Повторите вопрос через несколько секунд.')

    def warmup(self, settings):
        """Фоновый запуск при старте программы, чтобы первый вопрос не ждал загрузки модели."""
        def run():
            self.starting = True
            try:
                self.ensure(settings, wait=180)
            except Exception as exc:
                self.error = str(exc)
                log.info('Local LLM warmup: %s', exc)
            finally:
                self.starting = False
        threading.Thread(target=run, daemon=True, name='llm-warmup').start()

    def _start(self, key, gpu):
        model = find_model(self.root, key)
        if model is None:
            installed = [k for k in LOCAL_MODELS if find_model(self.root, k)]
            if not installed:
                raise RuntimeError('Локальная нейросеть не установлена. Откройте Настройки → ИИ → «Скачать нейросеть» '
                                   'или запустите SETUP_WINDOWS.bat.')
            key, model = installed[0], find_model(self.root, installed[0])
        binary, flavor = find_binary(self.root, gpu)
        if binary is None:
            raise RuntimeError('Не найден llama-server. Откройте Настройки → ИИ → «Скачать нейросеть».')
        self.port = free_port()
        threads = max(2, min(8, (os.cpu_count() or 4) - 1))
        args = [str(binary), '-m', str(model), '--host', '127.0.0.1', '--port', str(self.port),
                '-c', '4096', '-t', str(threads), '--jinja']
        if gpu and flavor in ('vulkan', 'system'):
            args += ['-ngl', '99']
        logs = self.root / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        self._close_log()
        log_file = self._log = open(logs / 'llama-server.log', 'ab')
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        self.process = subprocess.Popen(args, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        cwd=str(binary.parent), creationflags=flags)
        self.key, self.gpu = key, gpu
        log.info('llama-server started: %s (%s) port %s', model.name, flavor, self.port)

    def stop(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
            self._close_log()

    def _close_log(self):
        log_file, self._log = getattr(self, '_log', None), None
        if log_file is not None:
            log_file.close()

    def apply_settings(self, settings):
        """Перезапуск при смене модели/видеокарты; остановка, если ИИ выключен."""
        if settings.get('llm_provider') != 'local':
            self.stop()
            return
        key, gpu = settings.get('local_model', DEFAULT_MODEL), bool(settings.get('llm_gpu', False))
        if self.running() and (self.key, self.gpu) != (key, gpu):
            self.stop()
            self.warmup(settings)
