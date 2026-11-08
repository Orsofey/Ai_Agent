"""Exact-phrase recordings, independent of the installed neural speech models."""
import hashlib
import json
import logging
import re
import wave
from functools import lru_cache
from pathlib import Path

from .paths import app_base

log = logging.getLogger(__name__)


def normalize(text):
    return ' '.join(re.findall(r'\w+', str(text).casefold().replace('ё', 'е')))


def folders(root, preset):
    if preset not in ('jarvis', 'friday'):
        return []
    return [Path(root) / 'models' / 'voice_packs' / preset,
            app_base() / 'models' / 'voice_packs' / preset]


@lru_cache(maxsize=32)
def _manifest(path, modified, size):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def find(text, preset, root):
    wanted = normalize(text)
    if not wanted:
        return None
    for folder in folders(root, preset):
        try:
            manifest = folder / 'manifest.json'
            stat = manifest.stat()
            data = _manifest(str(manifest.resolve()), stat.st_mtime_ns, stat.st_size)
            for item in data.get('phrases', []):
                names = [item['text'], *item.get('aliases', [])]
                if wanted not in (normalize(name) for name in names):
                    continue
                path = (folder / item['file']).resolve()
                if not path.is_relative_to(folder.resolve()) or path.suffix.lower() != '.wav':
                    continue
                if path.is_file():
                    return path
        except (OSError, ValueError, KeyError, TypeError):
            log.debug('Voice pack unavailable: %s', folder, exc_info=True)
    return None


def load(text, preset, root, rate=1.0):
    path = find(text, preset, root)
    if path is None:
        return None
    try:
        import numpy as np
        with wave.open(str(path), 'rb') as wav:
            if wav.getsampwidth() != 2 or wav.getnchannels() != 1 or wav.getnframes() > wav.getframerate() * 30:
                return None
            sample_rate = wav.getframerate()
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').copy()
        # Preserve the timbre and timing of film recordings; speed settings apply to TTS only.
        return (audio, sample_rate) if len(audio) else None
    except (OSError, EOFError, wave.Error, ValueError):
        log.warning('Invalid voice recording: %s', path)
        return None


def fingerprint(text, preset, root):
    path = find(text, preset, root)
    if path is None:
        return ''
    try:
        stat = path.stat()
        return hashlib.sha256(f'{path}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
    except OSError:
        return ''


def available(root, preset):
    return any((folder / 'manifest.json').is_file() for folder in folders(root, preset))
