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
from ..paths import app_base

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
    base = app_base()
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


# Режимы памяти. Кеш диалога (KV) в 8 бит почти не влияет на качество и скорость, но вдвое меньше.
MEMORY_PROFILES = {
    'economy': {'ctx': 2048, 'kv': 'q8_0', 'ubatch': 256, 'idle_minutes': 10,
                'title': 'Экономный — меньше всего памяти, нейросеть выгружается после 10 минут простоя'},
    'balanced': {'ctx': 4096, 'kv': 'q8_0', 'ubatch': 512, 'idle_minutes': 0,
                 'title': 'Сбалансированный — рекомендуется'},
    'max': {'ctx': 8192, 'kv': 'f16', 'ubatch': 512, 'idle_minutes': 0,
            'title': 'Максимум — длинные разговоры, больше памяти'},
}


def total_ram_gb():
    try:
        import psutil
        return psutil.virtual_memory().total / 2 ** 30
    except Exception:
        return 16.0


def memory_profile(settings):
    """Профиль памяти из настроек; «auto» — по объёму ОЗУ компьютера."""
    mode = (settings or {}).get('memory_mode', 'auto')
    if mode not in MEMORY_PROFILES:
        mode = 'economy' if total_ram_gb() < 9 else 'balanced'
    return dict(MEMORY_PROFILES[mode], mode=mode)


def estimate_ram_mb(key, settings):
    """Примерная память нейросети: веса модели + кеш диалога + рабочие буферы."""
    info = LOCAL_MODELS.get(key, LOCAL_MODELS[DEFAULT_MODEL])
    profile = memory_profile(settings)
    kv_per_1k = {'qwen3-1.7b': 112, 'qwen3-4b': 144, 'qwen2.5-7b': 56}.get(key, 144)  # МБ на 1024 токена в f16
    kv = kv_per_1k * profile['ctx'] / 1024 * (0.53 if profile['kv'] == 'q8_0' else 1.0)
    return int(info['size_mb'] + kv + (150 if profile['ubatch'] <= 256 else 300))


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
        self.profile = None
        self.safe_mode = False   # старая сборка llama.cpp не знает новых флагов — запуск без них
        self.last_used = time.monotonic()
        threading.Thread(target=self._idle_watch, daemon=True, name='llm-idle').start()

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
                    installed_models=[k for k in LOCAL_MODELS if find_model(self.root, k)],
                    memory=self.memory(settings))

    def memory(self, settings=None):
        """Сколько памяти занимают ассистент и нейросеть сейчас (МБ) и оценка для выбранного режима."""
        profile = memory_profile(settings or {})
        info = {'mode': profile['mode'], 'mode_title': profile['title'], 'total_ram_gb': round(total_ram_gb(), 1),
                'estimate_mb': estimate_ram_mb((settings or {}).get('local_model', DEFAULT_MODEL), settings or {})}
        try:
            import psutil
            info['agent_mb'] = int(psutil.Process().memory_info().rss / 2 ** 20)
            info['llm_mb'] = int(psutil.Process(self.process.pid).memory_info().rss / 2 ** 20) if self.running() else 0
        except Exception:
            pass
        return info

    def ensure(self, settings, wait=120.0):
        """Запустить сервер (если нужно) и вернуть его адрес. Бросает RuntimeError с понятным текстом."""
        key = settings.get('local_model', DEFAULT_MODEL)
        gpu = bool(settings.get('llm_gpu', False))
        profile = memory_profile(settings)
        self.last_used = time.monotonic()
        with self.lock:
            if self.running() and (self.key, self.gpu, self.profile) == (key, gpu, profile['mode']):
                pass
            else:
                self.stop()
                self._start(key, gpu, profile)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.healthy():
                self.error = None
                self.last_used = time.monotonic()
                return self.base_url
            if not self.running():
                if not self.safe_mode:
                    # Возможно, сборка llama.cpp старая и не знает флагов экономии памяти — пробуем без них.
                    log.warning('llama-server exited, retrying without memory flags')
                    self.safe_mode = True
                    with self.lock:
                        self._start(key, gpu, profile)
                    continue
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

    def _idle_watch(self):
        """Экономный режим: выгрузить нейросеть из памяти после простоя (следующий вопрос запустит её снова)."""
        while True:
            time.sleep(30)
            self.unload_if_idle()

    def unload_if_idle(self):
        minutes = (MEMORY_PROFILES.get(self.profile) or {}).get('idle_minutes', 0)
        if minutes and self.running() and time.monotonic() - self.last_used > minutes * 60:
            log.info('Local LLM unloaded after %s idle minutes', minutes)
            self.stop()
            return True
        return False

    def _start(self, key, gpu, profile=None):
        profile = profile or memory_profile({})
        model = find_model(self.root, key)
        if model is None:
            installed = [k for k in LOCAL_MODELS if find_model(self.root, k)]
            if not installed:
                raise RuntimeError('Локальная нейросеть не установлена. Откройте Настройки → ИИ → «Скачать нейросеть» '
                                   'или запустите SETUP_WINDOWS.bat (SETUP_MAC.sh на Mac).')
            key, model = installed[0], find_model(self.root, installed[0])
        binary, flavor = find_binary(self.root, gpu)
        if binary is None:
            raise RuntimeError('Не найден llama-server. Откройте Настройки → ИИ → «Скачать нейросеть».')
        self.port = free_port()
        threads = max(2, min(8, (os.cpu_count() or 4) - 1))
        args = [str(binary), '-m', str(model), '--host', '127.0.0.1', '--port', str(self.port),
                '-c', str(profile['ctx']), '-t', str(threads), '--jinja']
        if not self.safe_mode:
            # Один слот: весь контекст — одному разговору (по умолчанию llama.cpp делит его на 4 слота).
            args += ['-np', '1', '-ub', str(profile['ubatch'])]
            if profile['kv'] != 'f16':
                args += ['-fa', 'on', '--cache-type-k', profile['kv'], '--cache-type-v', profile['kv']]
        if (gpu and flavor in ('vulkan', 'system')) or sys.platform == 'darwin':
            args += ['-ngl', '99']  # на Mac — Metal: общая память, видеокарта есть всегда
        logs = self.root / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        self._close_log()
        log_file = self._log = open(logs / 'llama-server.log', 'ab')
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        self.process = subprocess.Popen(args, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        cwd=str(binary.parent), creationflags=flags)
        self.key, self.gpu, self.profile = key, gpu, profile['mode']
        log.info('llama-server started: %s (%s, %s) port %s', model.name, flavor, profile['mode'], self.port)

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
        if self.running() and (self.key, self.gpu, self.profile) != (key, gpu, memory_profile(settings)['mode']):
            self.stop()
            self.warmup(settings)
