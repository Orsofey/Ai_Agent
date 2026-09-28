"""Узнавание пользователя по голосу: ассистент слушает только знакомые голоса.

Модель 3D-Speaker CAM++ (Apache 2.0, ~28 МБ, ONNX) превращает фразу в «отпечаток» из 192 чисел.
Признаки — стандартный Kaldi fbank (80 полос), как при обучении модели. Всё локально.

Знакомство: Настройки → Голос → «Запомнить мой голос» (три фразы) или «Андрей, запомни мой голос».
Незнакомый голос → «Я не узнаю ваш голос. Назовите пароль» → верный голосовой пароль → голос запоминается.
"""
import json
import logging
import re
import secrets
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MIN_SECONDS = 0.7          # короче — отпечаток ненадёжен
ENROLL_SAMPLES = 3


# ---------------- признаки (Kaldi fbank, как torchaudio.compliance.kaldi.fbank) ----------------
def _mel_banks(bins=80, nfft=512, low=20.0, rate=SAMPLE_RATE):
    mel = lambda f: 1127.0 * np.log(1.0 + f / 700.0)  # noqa: E731
    centers = np.linspace(mel(low), mel(rate / 2), bins + 2)
    m = mel(np.arange(nfft // 2 + 1) * rate / nfft)
    banks = np.zeros((bins, nfft // 2 + 1))
    for i in range(bins):
        left, center, right = centers[i:i + 3]
        banks[i] = np.maximum(0.0, np.minimum((m - left) / (center - left), (right - m) / (right - center)))
    banks[:, -1] = 0.0  # Kaldi не использует полосу Найквиста
    return banks


_BANKS = _mel_banks()
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 399)) ** 0.85  # окно Povey


def fbank(audio):
    """float32 [-1, 1], 16 кГц → (кадры, 80) логарифм мел-энергий; кадр 25 мс, шаг 10 мс."""
    x = np.asarray(audio, dtype=np.float64)
    if x.size < 400:
        return np.zeros((0, 80))
    count = 1 + (x.size - 400) // 160
    frames = x[np.arange(400)[None, :] + 160 * np.arange(count)[:, None]]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] * 0.03, frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    power = np.abs(np.fft.rfft(frames * _WINDOW, n=512)) ** 2
    return np.log(np.maximum(power @ _BANKS.T, np.finfo(np.float32).eps))


def normalize_password(text):
    from ..brain.numbers import words_to_digits
    value = words_to_digits(str(text).casefold().replace('ё', 'е'))
    return ' '.join(re.findall(r'\w+', value))


# ---------------- модель и профили ----------------
class SpeakerGate:
    def __init__(self, store, model_path=None):
        self.store = store
        self._model_path = model_path
        self._session = None
        self.lock = threading.Lock()

    # ---- модель ----
    @property
    def model_path(self):
        if self._model_path is None:
            from ..model_downloader import speaker_model_path
            self._model_path = speaker_model_path(self.store.root)
        return self._model_path

    def model_installed(self):
        return self.model_path.exists()

    def _load(self):
        if self._session is None:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.enable_cpu_mem_arena = False
            self._session = ort.InferenceSession(str(self.model_path), options, providers=['CPUExecutionProvider'])
        return self._session

    def embed(self, audio):
        """Отпечаток голоса (единичный вектор) или None, если фраза слишком короткая."""
        audio = np.asarray(audio, dtype=np.float32)
        if audio.size < MIN_SECONDS * SAMPLE_RATE:
            return None
        feats = fbank(audio)
        feats = feats - feats.mean(axis=0, keepdims=True)
        with self.lock:
            vector = self._load().run(None, {'x': feats[None].astype(np.float32)})[0][0]
        norm = np.linalg.norm(vector)
        return vector / norm if norm else None

    # ---- профили ----
    def profiles(self):
        try:
            return json.loads(self.store.meta('voice_profiles') or '[]')
        except ValueError:
            return []

    def _save(self, items):
        self.store.set_meta('voice_profiles', json.dumps(items, ensure_ascii=False))

    def summary(self):
        return [{k: p[k] for k in ('id', 'name', 'samples', 'created')} for p in self.profiles()]

    def add_profile(self, name, vectors):
        vector = np.mean(np.asarray(vectors), axis=0)
        vector = vector / np.linalg.norm(vector)
        items = self.profiles()
        profile = {'id': 'v-' + secrets.token_hex(4), 'name': str(name or 'Голос')[:40],
                   'vector': [round(float(v), 5) for v in vector], 'samples': len(vectors),
                   'created': time.strftime('%Y-%m-%d %H:%M')}
        items.append(profile)
        self._save(items)
        return profile

    def delete(self, profile_id):
        items = [p for p in self.profiles() if p['id'] != profile_id]
        self._save(items)
        return self.summary()

    def active(self, settings):
        return bool(settings.get('voice_id')) and bool(self.profiles()) and self.model_installed()

    @staticmethod
    def threshold(settings):
        # Строгость 30…80 → порог сходства 0,30…0,70 (CAM++: свой голос обычно 0,6–0,9, чужой — до 0,35).
        return max(0.2, min(0.8, settings.get('voice_id_strictness', 45) / 100.0))

    def identify(self, vector, settings):
        """(профиль или None, сходство). Узнанный профиль понемногу подстраивается под микрофон."""
        items = self.profiles()
        if vector is None or not items:
            return None, 0.0
        scores = [float(np.dot(vector, np.asarray(p['vector']))) for p in items]
        best = int(np.argmax(scores))
        score = scores[best]
        limit = self.threshold(settings)
        if score < limit:
            return None, score
        if score > limit + 0.1:  # уверенно узнали — чуть уточняем отпечаток (другой микрофон, простуда)
            merged = 0.95 * np.asarray(items[best]['vector']) + 0.05 * vector
            items[best]['vector'] = [round(float(v), 5) for v in merged / np.linalg.norm(merged)]
            self._save(items)
        return items[best], score

    # ---- пароль ----
    def set_password(self, password):
        value = normalize_password(password)
        if password and len(value) < 3:
            raise ValueError('Пароль — хотя бы одно слово из трёх букв, например «синий кит»')
        if not value:
            self.store.set_meta('voice_password', None)
            return False
        from werkzeug.security import generate_password_hash
        self.store.set_meta('voice_password', generate_password_hash(value))
        return True

    def has_password(self):
        return bool(self.store.meta('voice_password'))

    def check_password(self, spoken):
        stored = self.store.meta('voice_password')
        if not stored:
            return False
        from ..passwords import matches
        value = normalize_password(spoken)
        # Имя ассистента в начале («Андрей, синий кит») не мешает.
        candidates = {value, ' '.join(value.split()[1:])}
        return any(c and matches(stored, c) for c in candidates)
