"""Speech recognition service shared by the native voice loop and the HTTP API."""
import logging
import re
import threading
import time

from .audio import SpeechError, decode, prepare, SAMPLE_RATE
from .engines import (ONNX_MODELS, VAD_MODEL, choose_engine, create_engine, find_model,
                      cuda_available)

log = logging.getLogger(__name__)

__all__ = ['SpeechService', 'SpeechError', 'decode']

ENGINE_TITLES = {'parakeet': 'Parakeet v3', 'gigaam': 'GigaAM v3', 'whisper': 'Whisper'}


def clean_text(text):
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    # Модели иногда выдают «угу»/«ээ» на шум — это не команда.
    if re.fullmatch(r'(?:[эаму]+|угу|ага|хм+)[.!?]?', value, re.I):
        return ''
    return value


class SpeechService:
    def __init__(self, root, settings=None):
        self.root = root
        self.settings = dict(settings or {})
        self.engines = {}
        self.engine_key = None
        self.loading = False
        self.error = None
        self.lock = threading.Lock()
        self.busy = threading.Lock()
        self.last_elapsed = None

    # ---- модели ----
    def installed(self):
        keys = {k for k in ONNX_MODELS if find_model(self.root, ONNX_MODELS[k]['folder'])}
        if create_engine('whisper', self.root).installed():
            keys.add('whisper')
        return keys

    def vad_dir(self):
        return find_model(self.root, VAD_MODEL['folder'], 'silero_vad.onnx')

    def configure(self, settings):
        """Сменить движок при изменении настроек (загрузка идёт в фоне)."""
        self.settings = dict(settings)
        wanted = choose_engine(self.settings, self.installed())
        if wanted != self.engine_key:
            self.warmup()

    @property
    def engine(self):
        return self.engines.get(self.engine_key)

    def ready(self):
        engine = self.engine
        return engine is not None and engine.model is not None

    def status(self):
        installed = self.installed()
        key = self.engine_key or choose_engine(self.settings, installed)
        return dict(engine=ENGINE_TITLES.get(key, key), engine_key=key, ready=self.ready(),
                    loading=self.loading, error=self.error, installed=sorted(installed),
                    downloaded=bool(installed), gpu=cuda_available(), last_elapsed=self.last_elapsed,
                    vad='silero' if self.vad_dir() else 'energy')

    def warmup(self):
        with self.lock:
            if self.loading:
                return
            self.loading = True
            self.error = None
        threading.Thread(target=self._load, daemon=True, name='stt-load').start()

    def _load(self):
        try:
            installed = self.installed()
            key = choose_engine(self.settings, installed)
            if not installed:
                raise RuntimeError('Модели распознавания не установлены. Откройте Настройки → Голос → «Скачать модели» '
                                   'или запустите SETUP_WINDOWS.bat.')
            engine = self.engines.get(key) or create_engine(key, self.root)
            if engine.model is None:
                started = time.monotonic()
                engine.load()
                log.info('STT %s loaded in %.1fs', key, time.monotonic() - started)
            self.engines = {key: engine}  # старый движок освобождает память
            self.engine_key = key
        except RuntimeError as exc:
            self.error = str(exc)
            log.warning('STT not ready: %s', exc)
        except Exception as exc:
            self.error = 'Не удалось загрузить модель распознавания: ' + str(exc)
            log.exception('STT load failed')
        finally:
            self.loading = False

    # ---- распознавание ----
    def transcribe_array(self, audio, language=None):
        language = language or self.settings.get('voice_language', 'auto')
        if language not in ('ru', 'en', 'auto'):
            raise SpeechError('Поддерживаются ru, en, auto')
        if not self.ready():
            if not self.loading and self.error is None:
                self.warmup()
            raise SpeechError(self.error or 'Модель распознавания загружается. Повторите через пару секунд.', 503)
        if not self.busy.acquire(timeout=20):
            raise SpeechError('Распознаётся предыдущая запись', 429)
        started = time.monotonic()
        try:
            text, detected = self.engine.transcribe(prepare(audio), language)
        finally:
            self.busy.release()
        self.last_elapsed = round(time.monotonic() - started, 3)
        text = clean_text(text)
        return dict(text=text, empty=not text, language=detected or language,
                    elapsed=self.last_elapsed, engine=self.engine_key,
                    duration=round(len(audio) / SAMPLE_RATE, 2))

    def transcribe(self, data, language='ru'):
        """Для HTTP API: байты webm/ogg/wav → текст."""
        if language not in ('ru', 'en', 'auto'):
            raise SpeechError('Поддерживаются ru, en, auto')
        return self.transcribe_array(decode(data), language)
