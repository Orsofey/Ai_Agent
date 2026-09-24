"""Audio decoding and light preprocessing (16 kHz mono float32)."""
import io

import numpy as np

SAMPLE_RATE = 16000
MAX_SECONDS = 45


class SpeechError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def decode(data):
    """Декодировать любой контейнер (webm/ogg/wav/m4a) в 16 кГц mono float32."""
    import av
    pieces = []
    samples = 0
    try:
        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format='s16', layout='mono', rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                for output in resampler.resample(frame):
                    chunk = output.to_ndarray().reshape(-1)
                    samples += chunk.size
                    if samples > (MAX_SECONDS + 1) * SAMPLE_RATE:
                        raise SpeechError(f'Запись длиннее {MAX_SECONDS} секунд')
                    pieces.append(chunk)
            for output in resampler.resample(None):
                pieces.append(output.to_ndarray().reshape(-1))
    except SpeechError:
        raise
    except Exception as exc:
        raise SpeechError('Не удалось прочитать аудио') from exc
    if not pieces:
        raise SpeechError('Пустое аудио')
    result = np.concatenate(pieces).astype(np.float32) / 32768.0
    if len(result) > (MAX_SECONDS + 1) * SAMPLE_RATE:
        raise SpeechError(f'Запись длиннее {MAX_SECONDS} секунд')
    return result


def prepare(audio):
    """Убрать постоянную составляющую и поднять тихую запись до нормальной громкости."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return audio
    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio)))
    if 1e-4 < peak < 0.5:
        audio = audio * min(0.9 / peak, 20.0)
    return np.clip(audio, -1.0, 1.0).astype(np.float32)


def resample(audio, source_rate, target_rate=SAMPLE_RATE):
    if source_rate == target_rate or audio.size == 0:
        return audio.astype(np.float32)
    duration = audio.size / source_rate
    target = np.linspace(0, duration, int(round(duration * target_rate)), endpoint=False)
    source = np.arange(audio.size) / source_rate
    return np.interp(target, source, audio).astype(np.float32)
