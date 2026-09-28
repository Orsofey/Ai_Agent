"""Speech-to-text engines.

По умолчанию — onnx-asr (ONNX Runtime, без PyTorch):
  • NVIDIA Parakeet TDT 0.6B v3 — русский + английский (и ещё 23 языка), автоопределение языка;
  • Sber GigaAM v3 E2E RNN-T — лучший для русского, сразу с пунктуацией.
Обе модели в 10–30 раз быстрее Whisper small на CPU и точнее на русском.
Резерв — faster-whisper (large-v3-turbo на видеокарте NVIDIA или small на CPU).
"""
import logging
import os
import time
from pathlib import Path
from ..paths import app_base

log = logging.getLogger(__name__)

ONNX_MODELS = {
    'parakeet': {
        'name': 'nemo-parakeet-tdt-0.6b-v3', 'folder': 'parakeet-tdt-0.6b-v3',
        'title': 'NVIDIA Parakeet v3 — русский + английский', 'size_mb': 670,
        'languages': ('ru', 'en', 'auto'),
    },
    'gigaam': {
        'name': 'gigaam-v3-e2e-rnnt', 'folder': 'gigaam-v3-e2e-rnnt',
        'title': 'Sber GigaAM v3 — максимальная точность русского', 'size_mb': 230,
        'languages': ('ru',),
    },
}
VAD_MODEL = {'name': 'silero', 'folder': 'silero-vad', 'size_mb': 2}
WHISPER_MODELS = {
    'gpu': {'repo': 'mobiuslabsgmbh/faster-whisper-large-v3-turbo', 'folder': 'whisper-large-v3-turbo'},
    'cpu': {'repo': 'Systran/faster-whisper-small', 'folder': 'small'},
}


def models_dir(root):
    """Модели: папка данных пользователя, затем папка установленной программы."""
    return Path(root) / 'models'


def bundled_models_dir():
    base = app_base()
    return base / 'models'


def find_model(root, folder, marker='config.json'):
    for base in (models_dir(root), bundled_models_dir()):
        path = base / folder
        if (path / marker).exists():
            return path
    return None


def cuda_available():
    try:
        import onnxruntime as rt
        return 'CUDAExecutionProvider' in rt.get_available_providers()
    except Exception:
        return False


def onnx_options():
    import onnxruntime as rt
    options = rt.SessionOptions()
    options.intra_op_num_threads = max(1, min(8, os.cpu_count() or 4))
    options.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Без «арены» ONNX Runtime не держит про запас сотни МБ после первой фразы; на скорость почти не влияет.
    options.enable_cpu_mem_arena = False
    providers = ['CPUExecutionProvider']
    if 'CUDAExecutionProvider' in rt.get_available_providers():
        providers.insert(0, 'CUDAExecutionProvider')
    return options, providers


class OnnxAsrEngine:
    kind = 'onnx'

    def __init__(self, key, root):
        self.key = key
        self.info = ONNX_MODELS[key]
        self.root = root
        self.model = None

    @property
    def path(self):
        return find_model(self.root, self.info['folder'])

    def installed(self):
        return self.path is not None

    def load(self):
        path = self.path
        if path is None:
            raise RuntimeError(f'Модель {self.info["title"]} не установлена. Откройте Настройки → Голос → «Скачать модели».')
        import onnx_asr
        quantization = 'int8' if any(path.glob('*.int8.onnx')) else None
        options, providers = onnx_options()
        self.model = onnx_asr.load_model(self.info['name'], str(path), quantization=quantization,
                                         sess_options=options, providers=providers)
        # Прогрев: первый вызов выделяет память, пусть это случится не на команде пользователя.
        import numpy as np
        self.model.recognize(np.zeros(8000, dtype=np.float32), sample_rate=16000)

    def transcribe(self, audio, language):
        text = self.model.recognize(audio, sample_rate=16000)
        return str(text or '').strip(), language if language != 'auto' else None


class WhisperEngine:
    kind = 'whisper'

    def __init__(self, root):
        self.root = root
        self.model = None
        self.device = 'cuda' if self._cuda() else 'cpu'

    @staticmethod
    def _cuda():
        try:
            import ctranslate2
            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    @property
    def info(self):
        return WHISPER_MODELS['gpu' if self.device == 'cuda' else 'cpu']

    @property
    def path(self):
        env = os.getenv('WHISPER_MODEL_DIR')
        if env and (Path(env) / 'model.bin').exists():
            return Path(env)
        found = find_model(self.root, self.info['folder'], 'model.bin')
        if found is None and self.device == 'cuda':
            found = find_model(self.root, WHISPER_MODELS['cpu']['folder'], 'model.bin')
        return found

    def installed(self):
        return self.path is not None

    def load(self):
        path = self.path
        if path is None:
            raise RuntimeError('Модель Whisper не установлена.')
        from faster_whisper import WhisperModel
        compute = 'float16' if self.device == 'cuda' else 'int8'
        self.model = WhisperModel(str(path), device=self.device, compute_type=compute,
                                  cpu_threads=max(1, min(8, os.cpu_count() or 2)), num_workers=1,
                                  local_files_only=True)

    def transcribe(self, audio, language):
        beam = 5 if self.device == 'cuda' else 1
        segments, info = self.model.transcribe(
            audio, language=None if language == 'auto' else language, beam_size=beam, temperature=0,
            condition_on_previous_text=False, vad_filter=False, without_timestamps=True)
        return ' '.join(s.text.strip() for s in segments if s.text.strip()), info.language


def create_engine(key, root):
    if key == 'whisper':
        return WhisperEngine(root)
    return OnnxAsrEngine(key, root)


def choose_engine(settings, installed):
    """Выбрать движок по настройкам и установленным моделям. installed: set ключей."""
    wanted = settings.get('stt_engine', 'auto')
    language = settings.get('voice_language', 'auto')
    if wanted != 'auto':
        if wanted in installed:
            return wanted
    if language == 'ru':
        order = ['gigaam', 'parakeet', 'whisper']
    else:
        order = ['parakeet', 'whisper', 'gigaam']
    for key in order:
        if key in installed:
            return key
    return wanted if wanted != 'auto' else order[0]


def timed(func, *args):
    started = time.monotonic()
    result = func(*args)
    return result, round(time.monotonic() - started, 3)
