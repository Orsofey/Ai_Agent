"""Bounded WAV cache with atomic writes and shared in-process request locks."""
import logging
import os
import tempfile
import threading
import time
import wave
from pathlib import Path

log = logging.getLogger(__name__)
_locks = tuple(threading.RLock() for _ in range(64))
MAX_BYTES = 256 * 1024 * 1024
MAX_AGE = 7 * 86400


def request_lock(path):
    return _locks[hash(str(Path(path).resolve())) % len(_locks)]


def write_wav(path, audio, sample_rate):
    """A unique temporary file also permits writers in different processes."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.stem + '-', suffix='.tmp',
                                         delete=False) as file:
            temporary = Path(file.name)
        with wave.open(str(temporary), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(audio.tobytes())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prune(folder, *, keep=None, max_bytes=MAX_BYTES, max_age=MAX_AGE, now=None):
    """Keep recent audio within a byte budget; leave active temporary files alone."""
    now = time.time() if now is None else now
    entries = []
    for path in Path(folder).glob('*.wav'):
        try:
            stat = path.stat()
            entries.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in entries)
    for modified, size, path in sorted(entries):
        if path == keep or (now - modified <= max_age and total <= max_bytes):
            continue
        try:
            with request_lock(path):
                # A concurrent cache hit may have made the file recent again.
                if path.stat().st_mtime != modified:
                    continue
                path.unlink()
                total -= size
        except OSError:
            pass
