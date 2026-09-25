"""Streaming voice activity detection: Silero VAD (ONNX), energy fallback."""
import math
from pathlib import Path

import numpy as np

FRAME = 512      # 32 мс при 16 кГц
CONTEXT = 64


class StreamingVad:
    def __init__(self, model_dir=None):
        self.session = None
        model = None
        if model_dir:
            files = sorted(Path(model_dir).glob('silero_vad*.onnx'))
            model = next((f for f in files if '.int8.' not in f.name), files[0] if files else None)
        if model is not None:
            import onnxruntime as rt
            options = rt.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            self.session = rt.InferenceSession(str(model), options, providers=['CPUExecutionProvider'])
        self.engine = 'silero' if self.session else 'energy'
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, CONTEXT), dtype=np.float32)
        self.noise_db = -55.0

    def __call__(self, frame):
        frame = np.asarray(frame, dtype=np.float32).reshape(1, -1)
        if self.session is not None:
            data = np.concatenate([self.context, frame], axis=1)
            output, self.state = self.session.run(
                ['output', 'stateN'], {'input': data, 'state': self.state, 'sr': np.array([16000], dtype=np.int64)})
            self.context = frame[:, -CONTEXT:]
            return float(output.reshape(-1)[0])
        return self._energy(frame)

    def _energy(self, frame):
        rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
        db = 20 * math.log10(rms)
        probability = min(1.0, max(0.0, (db - self.noise_db - 8.0) / 12.0))
        if probability < 0.3:
            self.noise_db = 0.97 * self.noise_db + 0.03 * db
        return probability


class Segmenter:
    """Режет поток кадров на фразы: начало — устойчивая речь, конец — пауза silence_ms."""

    def __init__(self, vad, threshold=0.5, silence_ms=600, preroll_ms=320, min_ms=250, max_seconds=25):
        self.vad = vad
        self.threshold = threshold
        self.silence_frames = max(1, int(silence_ms / 32))
        self.preroll = max(1, int(preroll_ms / 32))
        self.min_frames = max(1, int(min_ms / 32))
        self.max_frames = int(max_seconds * 1000 / 32)
        self.history = []
        self.frames = []
        self.speaking = False
        self.voiced = 0
        self.quiet = 0
        self.started_at = None

    def configure(self, threshold=None, silence_ms=None):
        if threshold is not None:
            self.threshold = threshold
        if silence_ms is not None:
            self.silence_frames = max(1, int(silence_ms / 32))

    def push(self, frame, now=0.0):
        """Вернуть (событие, данные): ('start', None), ('end', (audio, started_at)) или (None, None)."""
        probability = self.vad(frame)
        if not self.speaking:
            self.history.append(frame)
            if len(self.history) > self.preroll:
                self.history.pop(0)
            self.voiced = self.voiced + 1 if probability >= self.threshold else 0
            if self.voiced >= 2:
                self.speaking = True
                self.frames = list(self.history)
                self.history = []
                self.quiet = 0
                self.started_at = now
                return 'start', probability
            return None, probability
        self.frames.append(frame)
        if probability < max(0.05, self.threshold - 0.15):
            self.quiet += 1
        else:
            self.quiet = 0
        if self.quiet >= self.silence_frames or len(self.frames) >= self.max_frames:
            frames, started, quiet = self.frames, self.started_at, self.quiet
            self.frames, self.speaking, self.voiced, self.quiet = [], False, 0, 0
            # Хвост тишины не нужен распознавателю: оставляем ~200 мс.
            frames = frames[:len(frames) - max(0, quiet - 6)]
            if len(frames) - self.preroll < self.min_frames:
                return None, probability
            audio = np.concatenate(frames).astype(np.float32)
            return 'end', (audio, started)
        return None, probability
