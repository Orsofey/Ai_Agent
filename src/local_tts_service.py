"""Локальный нейросетевой синтез речи.

Движок — Piper (русские голоса irina / denis, английский amy).
Если голоса не установлены — системный голос Windows (SAPI).
Вместе с каждым голосом скачивается его MODEL_CARD с лицензией и авторами —
она показывается на странице «Лицензии».

Всё работает офлайн. Голоса скачиваются один раз (SETUP_WINDOWS.bat или
кнопка в настройках) в %LOCALAPPDATA%\\LocalAIAgent\\models\\piper.
Во время работы программа ничего не скачивает — первая фраза звучит сразу.
"""
import hashlib
import logging
import os
import threading
from pathlib import Path
from .paths import app_base

log = logging.getLogger(__name__)

_lock = threading.RLock()
_piper_voices = {}

PIPER_VOICES = {
    'irina': {'file': 'ru_RU-irina-medium.onnx', 'repo_path': 'ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx',
              'title': 'Ирина (естественный, рекомендуется)', 'lang': 'ru'},
    'denis': {'file': 'ru_RU-denis-medium.onnx', 'repo_path': 'ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx',
              'title': 'Денис (мужской)', 'lang': 'ru'},
    'amy': {'file': 'en_US-amy-medium.onnx', 'repo_path': 'en/en_US/amy/medium/en_US-amy-medium.onnx',
            'title': 'Amy (английский)', 'lang': 'en'},
}
_HF_BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/'


def piper_models_dir(root):
    return Path(root) / 'models' / 'piper'


def _search_dirs(root):
    dirs = [piper_models_dir(root)]
    base = app_base()
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
        ensure_model_card(name, root)
        return onnx, config
    folder = piper_models_dir(root)
    onnx, config = folder / info['file'], folder / (info['file'] + '.json')
    if not _download(_HF_BASE + info['repo_path'] + '.json', config):
        return None, None
    if not _download(_HF_BASE + info['repo_path'], onnx):
        return None, None
    ensure_model_card(name, root)
    return onnx, config


def model_card_path(name, root):
    onnx, _ = voice_files(name, root)
    return onnx.with_name(onnx.name + '.MODEL_CARD') if onnx else None


def ensure_model_card(name, root):
    """Карточка голоса (датасет, лицензия, авторы) рядом с моделью."""
    card = model_card_path(name, root)
    if card is None or card.exists():
        return card
    url = _HF_BASE + PIPER_VOICES[name]['repo_path'].rsplit('/', 1)[0] + '/MODEL_CARD'
    return card if _download(url, card) else None


def model_card(name, root):
    card = model_card_path(name, root)
    if card is None or not card.exists():
        return None
    return card.read_text(encoding='utf-8', errors='replace')[:4000]


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

    def synthesize_array(self, text, voice='irina', rate=1.0, preset='classic'):
        """Вернуть (numpy int16, sample_rate) или None, если локальных голосов нет."""
        import numpy as np
        from . import voice_fx
        text = str(text).strip()[:2000]
        if not text:
            return None
        style = voice_fx.preset(preset)
        if style['voice'] and PIPER_VOICES.get(voice, {}).get('lang') == 'ru' and voice_files(style['voice'], self.root)[0]:
            voice = style['voice']  # «Джарвис» — мужской голос, даже если выбрана Ирина
        # Понижение тона растягивает звук — заранее говорим быстрее, чтобы темп остался прежним.
        length_scale = round(style['pitch'] / rate, 3) if rate and rate > 0 else style['pitch']
        piper_voice = get_piper_voice(voice, self.root) if voice in PIPER_VOICES else None
        if piper_voice is None:
            piper_voice = get_piper_voice('irina', self.root) or get_piper_voice('denis', self.root)
        if piper_voice is not None:
            try:
                pcm, sample_rate = _piper_pcm(piper_voice, text, length_scale)
                audio = np.frombuffer(pcm, dtype=np.int16)
                if preset and preset != 'classic':
                    audio = voice_fx.apply(audio, sample_rate, preset)
                return audio, sample_rate
            except Exception as exc:
                log.warning('Piper synthesis failed: %s', exc)
        return None  # дальше — системный голос Windows

    def synthesize(self, text, voice='irina', rate=1.0, preset='classic'):
        """WAV-файл для удалённых клиентов (телефон). Возвращает путь или None."""
        import wave
        text = str(text).strip()[:2000]
        if not text:
            return None
        key = hashlib.sha1(f'{voice}|{rate}|{preset}|{text}'.encode()).hexdigest()[:20]
        path = self.cache / f'{key}.wav'
        if path.exists():
            return str(path)
        result = self.synthesize_array(text, voice, rate, preset)
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
