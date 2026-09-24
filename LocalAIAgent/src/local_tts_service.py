"""Локальный нейросетевой синтез речи.

Основной движок — Piper (русские голоса irina / denis, английские amy / lessac).
Резерв — Silero v4_ru (если установлен torch), затем системный голос Windows.

Всё работает офлайн. Голоса скачиваются один раз (SETUP_WINDOWS.bat или
кнопка в настройках) в %LOCALAPPDATA%\\LocalAIAgent\\models\\piper.
Во время работы программа ничего не скачивает — первая фраза звучит сразу.
"""
import hashlib
import logging
import os
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_lock = threading.RLock()
_silero_model = None
_silero_checked = False
_piper_voices = {}

PIPER_VOICES = {
    'irina': {'file': 'ru_RU-irina-medium.onnx', 'repo_path': 'ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx',
              'title': 'Ирина (естественный, рекомендуется)', 'lang': 'ru'},
    'denis': {'file': 'ru_RU-denis-medium.onnx', 'repo_path': 'ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx',
              'title': 'Денис (мужской)', 'lang': 'ru'},
    'amy': {'file': 'en_US-amy-medium.onnx', 'repo_path': 'en/en_US/amy/medium/en_US-amy-medium.onnx',
            'title': 'Amy (английский)', 'lang': 'en'},
    'lessac': {'file': 'en_US-lessac-medium.onnx', 'repo_path': 'en/en_US/lessac/medium/en_US-lessac-medium.onnx',
               'title': 'Lessac (английский)', 'lang': 'en'},
}
SILERO_VOICES = ('baya', 'aidar', 'kseniya', 'xenia')
_HF_BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/'


def piper_models_dir(root):
    return Path(root) / 'models' / 'piper'


def _search_dirs(root):
    dirs = [piper_models_dir(root)]
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    dirs.append(base / 'models' / 'piper')
    return dirs


def voice_files(name, root):
    info = PIPER_VOICES[name]
    for folder in _search_dirs(root):
        onnx = folder / info['file']
        config = folder / (info['file'] + '.json')
        if onnx.exists() and config.exists():
            return onnx, config
    return None, None


def _download(url, destination):
    destination = Path(destination)
    if destination.exists() and destination.stat().st_size > 0:
        return True
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + '.part')
    try:
        import urllib.request
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, destination)
        return True
    except Exception as exc:
        log.warning('Download failed %s: %s', url, exc)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def ensure_piper_voice(name, root):
    """Скачать голос (вызывается только из установщика/кнопки «Скачать»)."""
    info = PIPER_VOICES.get(name)
    if info is None:
        return None, None
    onnx, config = voice_files(name, root)
    if onnx:
        return onnx, config
    folder = piper_models_dir(root)
    onnx, config = folder / info['file'], folder / (info['file'] + '.json')
    if not _download(_HF_BASE + info['repo_path'] + '.json', config):
        return None, None
    if not _download(_HF_BASE + info['repo_path'], onnx):
        return None, None
    return onnx, config


def get_piper_voice(name, root):
    if name not in PIPER_VOICES:
        return None
    with _lock:
        if name in _piper_voices:
            return _piper_voices[name]
        onnx, config = voice_files(name, root)
        if not onnx:
            return None
        try:
            from piper import PiperVoice
            voice = PiperVoice.load(str(onnx), config_path=str(config))
        except Exception as exc:
            log.warning('Piper unavailable: %s', exc)
            return None
        _piper_voices[name] = voice
        return voice


def get_silero_model():
    """Резерв Silero (нужен torch; в обычной установке не используется)."""
    global _silero_model, _silero_checked
    with _lock:
        if _silero_checked:
            return _silero_model
        _silero_checked = True
        try:
            import torch
            path = Path(os.getenv('SILERO_TTS_PATH', ''))
            if path.is_file():
                _silero_model = torch.jit.load(str(path), map_location='cpu')
                _silero_model.eval()
        except Exception as exc:
            log.info('Silero TTS unavailable: %s', exc)
            _silero_model = None
        return _silero_model


def _piper_pcm(voice, text, length_scale):
    """PCM int16 bytes + sample rate for piper-tts 1.2 and 1.3+."""
    try:
        from piper import SynthesisConfig
    except ImportError:
        SynthesisConfig = None
    if SynthesisConfig is not None and hasattr(voice, 'synthesize'):
        chunks = list(voice.synthesize(text, syn_config=SynthesisConfig(length_scale=length_scale)))
        if chunks and hasattr(chunks[0], 'audio_int16_bytes'):
            return b''.join(c.audio_int16_bytes for c in chunks), chunks[0].sample_rate
    if hasattr(voice, 'synthesize_stream_raw'):
        audio = b''.join(voice.synthesize_stream_raw(text, length_scale=length_scale))
        return audio, voice.config.sample_rate
    raise RuntimeError('Неподдерживаемая версия piper-tts')


def detect_language(text):
    latin = sum(ch.isascii() and ch.isalpha() for ch in text)
    cyrillic = sum('а' <= ch.casefold() <= 'я' or ch in 'ёЁ' for ch in text)
    return 'en' if latin > cyrillic * 2 and latin > 3 else 'ru'


class LocalTTSService:
    def __init__(self, root):
        self.root = Path(root)
        self.cache = self.root / 'tts_cache'
        self.cache.mkdir(parents=True, exist_ok=True)

    def available_voices(self):
        voices = []
        for name, info in PIPER_VOICES.items():
            voices.append({'id': name, 'title': info['title'], 'engine': 'piper', 'lang': info['lang'],
                           'installed': voice_files(name, self.root)[0] is not None})
        for name in SILERO_VOICES:
            voices.append({'id': name, 'title': name.capitalize() + ' (Silero, резерв)', 'engine': 'silero',
                           'lang': 'ru', 'installed': get_silero_model() is not None})
        return voices

    def status(self):
        voices = self.available_voices()
        ready = [v['id'] for v in voices if v['engine'] == 'piper' and v['installed']]
        return {'provider': 'local', 'model': 'piper' if ready else 'system', 'available': True,
                'offline': True, 'voices': voices, 'piper_ready': ready}

    def pick_voice(self, text, voice='irina', voice_en='amy'):
        if detect_language(text) == 'en' and voice_files(voice_en, self.root)[0]:
            return voice_en
        return voice

    def synthesize_array(self, text, voice='irina', rate=1.0):
        """Вернуть (numpy int16, sample_rate) или None, если локальных голосов нет."""
        import numpy as np
        text = str(text).strip()[:2000]
        if not text:
            return None
        length_scale = round(1.0 / rate, 3) if rate and rate > 0 else 1.0
        piper_voice = get_piper_voice(voice, self.root) if voice in PIPER_VOICES else None
        if piper_voice is None and voice not in SILERO_VOICES:
            piper_voice = get_piper_voice('irina', self.root) or get_piper_voice('denis', self.root)
        if piper_voice is not None:
            try:
                pcm, sample_rate = _piper_pcm(piper_voice, text, length_scale)
                return np.frombuffer(pcm, dtype=np.int16), sample_rate
            except Exception as exc:
                log.warning('Piper synthesis failed: %s', exc)
        model = get_silero_model()
        if model is not None:
            try:
                speaker = voice if voice in SILERO_VOICES else 'baya'
                audio = model.apply_tts(text=text, speaker=speaker, sample_rate=24000, put_accent=True, put_yo=True)
                return (audio.numpy() * 32767).astype(np.int16), 24000
            except Exception as exc:
                log.warning('Silero synthesis failed: %s', exc)
        return None

    def synthesize(self, text, voice='irina', rate=1.0):
        """WAV-файл для удалённых клиентов (телефон). Возвращает путь или None."""
        import wave
        text = str(text).strip()[:2000]
        if not text:
            return None
        key = hashlib.sha1(f'{voice}|{rate}|{text}'.encode()).hexdigest()[:20]
        path = self.cache / f'{key}.wav'
        if path.exists():
            return str(path)
        result = self.synthesize_array(text, voice, rate)
        if result is None:
            return None
        audio, sample_rate = result
        tmp = path.with_suffix('.tmp')
        with wave.open(str(tmp), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(audio.tobytes())
        os.replace(tmp, path)
        return str(path)
