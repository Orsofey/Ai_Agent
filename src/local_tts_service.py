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
import time
from pathlib import Path
from .paths import app_base

log = logging.getLogger(__name__)

_lock = threading.RLock()
_piper_voices = {}
MAX_LOADED_VOICES = 3

# trial: лицензия датасета не проверена для коммерческого использования — голос для проверки;
# перед продажей прочитайте карточку голоса (MODEL_CARD рядом с моделью) или уберите его.
PIPER_VOICES = {
    'irina': {'file': 'ru_RU-irina-medium.onnx', 'repo_path': 'ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx',
              'title': 'Ирина (естественный, рекомендуется)', 'lang': 'ru'},
    'denis': {'file': 'ru_RU-denis-medium.onnx', 'repo_path': 'ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx',
              'title': 'Денис (мужской)', 'lang': 'ru'},
    'dmitri': {'file': 'ru_RU-dmitri-medium.onnx', 'repo_path': 'ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx',
               'title': 'Дмитрий (мужской)', 'lang': 'ru', 'trial': True},
    'ruslan': {'file': 'ru_RU-ruslan-medium.onnx', 'repo_path': 'ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx',
               'title': 'Руслан (мужской)', 'lang': 'ru', 'trial': True},
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
    try:
        from .model_downloader import http_download
        http_download(url, destination)
        return True
    except Exception as exc:
        log.warning('Download failed %s: %s', url, exc)
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


# ---- свои голоса: models/voices/<имя>.onnx + <имя>.onnx.json (обученные или купленные с правами) ----
def custom_voice_dirs(root):
    return [Path(root) / 'models' / 'voices', app_base() / 'models' / 'voices']


def custom_voices(root):
    """Список своих голосов Piper: id «custom:<имя>», название, язык."""
    import json
    found = {}
    for folder in custom_voice_dirs(root):
        if not folder.is_dir():
            continue
        for onnx in sorted(folder.glob('*.onnx')):
            config = onnx.with_name(onnx.name + '.json')
            if not config.exists() or onnx.stem in found:
                continue
            try:
                info = json.loads(config.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            language = (info.get('language') or {}).get('code', '') or info.get('espeak', {}).get('voice', '')
            title = info.get('title') or info.get('dataset') or onnx.stem
            found[onnx.stem] = {'id': 'custom:' + onnx.stem, 'title': str(title)[:60], 'lang': language[:2] or 'ru',
                                'onnx': onnx, 'config': config}
    return list(found.values())


def _custom_files(name, root):
    for voice in custom_voices(root):
        if voice['id'] == name:
            return voice['onnx'], voice['config']
    return None, None


def get_piper_voice(name, root):
    if name not in PIPER_VOICES and not str(name).startswith('custom:'):
        return None
    with _lock:
        onnx, config = _custom_files(name, root) if name.startswith('custom:') else voice_files(name, root)
        if not onnx:
            return None
        try:
            key = (str(onnx.resolve()), onnx.stat().st_mtime_ns, onnx.stat().st_size,
                   str(config.resolve()), config.stat().st_mtime_ns, config.stat().st_size)
            if key in _piper_voices:
                voice = _piper_voices.pop(key)
                _piper_voices[key] = voice
                return voice
            from piper import PiperVoice
            voice = PiperVoice.load(str(onnx), config_path=str(config))
        except Exception as exc:
            log.warning('Piper unavailable: %s', exc)
            return None
        # Replaced models must not remain alive indefinitely.
        for old in list(_piper_voices):
            if old[0] == key[0]:
                del _piper_voices[old]
        _piper_voices[key] = voice
        while len(_piper_voices) > MAX_LOADED_VOICES:
            _piper_voices.pop(next(iter(_piper_voices)))
        return voice


def clear_voice_cache():
    with _lock:
        _piper_voices.clear()


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
        self._cleanup_lock = threading.Lock()
        self._last_cleanup = float('-inf')

    def cache_identity(self, text, voice='irina', preset='classic'):
        """Include model/recording revisions in both RAM and disk cache keys."""
        from . import voice_fx, voice_samples
        selected = preset if str(preset).startswith('custom:') else \
            self._character_voice(preset) or voice_fx.preset(preset)['voice'] or voice
        files = _custom_files(selected, self.root) if str(selected).startswith('custom:') else \
            voice_files(selected, self.root) if selected in PIPER_VOICES else (None, None)
        identity = ['tts-v2', str(self.root.resolve()), voice_samples.fingerprint(text, preset, self.root)]
        # These are the two fallback models used when the selected model is unavailable.
        fallback_files = voice_files('irina', self.root) + voice_files('denis', self.root)
        for path in (*files, *fallback_files):
            try:
                stat = path.stat() if path else None
                identity.append(f'{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}' if stat else '')
            except OSError:
                identity.append('')
        return '|'.join(identity)

    def _character_voice(self, preset):
        if preset in ('jarvis', 'friday'):
            key = 'custom:' + preset
            if _custom_files(key, self.root)[0] is not None:
                return key
        return None

    def cleanup_cache(self, keep=None, force=False):
        from .tts_cache import prune
        if not self._cleanup_lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            if force or now - self._last_cleanup >= 60:
                prune(self.cache, keep=keep)
                self._last_cleanup = now
        except OSError as exc:
            log.debug('TTS cache cleanup failed: %s', exc)
        finally:
            self._cleanup_lock.release()

    def available_voices(self):
        voices = []
        for name, info in PIPER_VOICES.items():
            voices.append({'id': name, 'title': info['title'], 'engine': 'piper', 'lang': info['lang'],
                           'installed': voice_files(name, self.root)[0] is not None})
        return voices

    def assistant_voices(self):
        """Голоса ассистента для настроек: Джарвис, Пятница и свои голоса из models/voices."""
        from . import voice_fx
        voices = []
        for key in voice_fx.MAIN:
            style = voice_fx.PRESETS[key]
            base = style['voice'] or 'irina'
            from . import voice_samples
            character = self._character_voice(key)
            samples = voice_samples.available(self.root, key)
            note = 'Своя модель: весь текст' if character else \
                'Записи для готовых реплик; остальное — синтез' if samples else style['note']
            voices.append({'id': key, 'title': style['title'], 'note': note, 'voice': character or base,
                           'group': style.get('group', 'assistant'),
                           'recordings': samples, 'full_voice_model': bool(character),
                           'installed': bool(character or samples or voice_files(base, self.root)[0] is not None)})
        voices += [{'id': v['id'], 'title': v['title'], 'note': 'Свой голос', 'group': 'custom', 'installed': True}
                   for v in custom_voices(self.root)]
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
        from . import voice_samples
        recording = voice_samples.load(text, preset, self.root, rate)
        if recording is not None:
            return recording
        character = self._character_voice(preset)
        if character and detect_language(text) == 'ru':
            voice, preset = character, 'classic'
        if str(preset).startswith('custom:') and get_piper_voice(preset, self.root) is not None \
                and detect_language(text) == 'ru':
            voice, preset = preset, 'classic'  # свой голос звучит как есть, без обработки
        style = voice_fx.preset(preset)
        if style['voice'] and PIPER_VOICES.get(voice, {}).get('lang') == 'ru' and voice_files(style['voice'], self.root)[0]:
            voice = style['voice']  # «Джарвис» — мужской голос, «Пятница» — женский
        # Понижение тона растягивает звук — заранее говорим быстрее, чтобы темп остался прежним.
        length_scale = round(style['pitch'] / rate, 3) if rate and rate > 0 else style['pitch']
        piper_voice = get_piper_voice(voice, self.root) if voice in PIPER_VOICES or voice.startswith('custom:') else None
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
        from .tts_cache import request_lock, write_wav
        text = str(text).strip()[:2000]
        if not text:
            return None
        identity = self.cache_identity(text, voice, preset)
        key = hashlib.sha1(f'{identity}|{voice}|{rate}|{preset}|{text}'.encode()).hexdigest()[:20]
        path = self.cache / f'{key}.wav'
        with request_lock(path):
            if path.exists():
                path.touch()
            else:
                result = self.synthesize_array(text, voice, rate, preset)
                if result is None:
                    return None
                write_wav(path, *result)
        self.cleanup_cache(keep=path)
        return str(path)

