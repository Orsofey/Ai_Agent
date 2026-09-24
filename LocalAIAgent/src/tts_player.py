"""Native speech output with sentence streaming and instant interruption.

Синтез и воспроизведение идут в двух потоках: пока звучит первое предложение,
синтезируется второе. Ответ ИИ начинает звучать после первой фразы, а не
после всего текста.
"""
import logging
import queue
import re
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

URL_RE = re.compile(r'https?://\S+')


def readable(text, limit=1500):
    value = URL_RE.sub('ссылку', str(text))
    value = re.sub(r'[*_#`>|]+', ' ', value)          # остатки markdown
    value = re.sub(r'^\s*[-•]\s*', '', value, flags=re.M)
    value = re.sub(r'\s{2,}', ' ', value).strip()
    if len(value) > limit:
        cut = value[:limit]
        value = cut[:max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '), limit // 2) + 1]
    return value


class TTSPlayer:
    def __init__(self, tts_service, events=None):
        self.tts = tts_service
        self.events = events
        self.token = 0
        self.synth_queue = queue.Queue()
        self.play_queue = queue.Queue()
        self.speaking = False
        self.pending = 0
        self.last_end = 0.0
        self.lock = threading.Lock()
        self.available = self._check_audio()
        self._sapi = None
        threading.Thread(target=self._synth_loop, daemon=True, name='tts-synth').start()
        threading.Thread(target=self._play_loop, daemon=True, name='tts-play').start()

    @staticmethod
    def _check_audio():
        try:
            import sounddevice as sd
            sd.query_devices(kind='output')
            return True
        except Exception:
            return False

    # ---- API ----
    def say(self, text, settings, token=None):
        text = readable(text)
        if not text or not settings.get('tts_enabled', True):
            return
        with self.lock:
            self.pending += 1
            self.speaking = True
        self.synth_queue.put((self.token if token is None else token, text, dict(settings)))

    def new_utterance(self):
        """Остановить текущую речь и вернуть токен для новой."""
        self.stop()
        return self.token

    def stop(self):
        with self.lock:
            self.token += 1
            self.pending = 0
            was = self.speaking
            self.speaking = False
        for q in (self.synth_queue, self.play_queue):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if was:
            self.last_end = time.monotonic()
            self._emit(False)

    def beep(self, kind='wake'):
        """Короткий звуковой сигнал: имя услышано / начата запись."""
        rate = 16000
        freqs = (880, 1320) if kind == 'wake' else (660,)
        parts = []
        for f in freqs:
            t = np.arange(int(rate * 0.07)) / rate
            envelope = np.minimum(1, np.minimum(t, t[::-1]) * 60)
            parts.append((np.sin(2 * np.pi * f * t) * envelope * 0.25 * 32767).astype(np.int16))
        self.play_queue.put((None, np.concatenate(parts), rate, None))

    def is_busy(self):
        return self.speaking or not self.synth_queue.empty()

    # ---- потоки ----
    def _emit(self, speaking):
        if self.events:
            self.events.emit('speaking', speaking=speaking)

    def _synth_loop(self):
        while True:
            token, text, settings = self.synth_queue.get()
            if token != self.token:
                continue
            voice = self.tts.pick_voice(text, settings.get('tts_voice', 'irina'), settings.get('tts_voice_en', 'amy'))
            rate = settings.get('tts_rate', 100) / 100.0
            try:
                result = self.tts.synthesize_array(text, voice, rate)
            except Exception:
                log.exception('TTS synthesis failed')
                result = None
            if token != self.token:
                continue
            if result is None:
                self.play_queue.put((token, None, None, (text, rate)))
            else:
                self.play_queue.put((token, result[0], result[1], None))

    def _play_loop(self):
        while True:
            token, audio, rate, fallback = self.play_queue.get()
            if token is not None and token != self.token:
                continue
            if token is not None:
                self._emit(True)
            try:
                if fallback is not None:
                    self._system_voice(*fallback)
                elif self.available:
                    self._play(audio, rate, token)
            except Exception:
                log.exception('Playback failed')
            if token is None:
                continue
            with self.lock:
                if token == self.token:
                    self.pending = max(0, self.pending - 1)
                    if self.pending == 0:
                        self.speaking = False
                        self.last_end = time.monotonic()
            if not self.speaking:
                self._emit(False)

    def _play(self, audio, rate, token):
        import sounddevice as sd
        sd.play(audio, rate, blocking=False)
        duration = len(audio) / rate
        deadline = time.monotonic() + duration + 0.5
        while time.monotonic() < deadline:
            if token is not None and token != self.token:
                sd.stop()
                return
            stream = sd.get_stream()
            if not stream.active:
                return
            time.sleep(0.03)

    def _system_voice(self, text, rate):
        """Системный голос Windows (SAPI), если нейросетевые голоса не установлены."""
        try:
            import pyttsx3
            if self._sapi is None:
                self._sapi = pyttsx3.init()
                for voice in self._sapi.getProperty('voices'):
                    if 'ru' in (str(getattr(voice, 'languages', '')) + voice.name + voice.id).casefold():
                        self._sapi.setProperty('voice', voice.id)
                        break
            self._sapi.setProperty('rate', int(180 * rate))
            self._sapi.say(text)
            self._sapi.runAndWait()
        except Exception as exc:
            log.info('System voice unavailable: %s', exc)


class SentenceSpeaker:
    """Принимает поток текста от ИИ и отдаёт синтезатору готовые предложения."""

    BOUNDARY = re.compile(r'(.+?[.!?…]+["»)]?)(?:\s+|$)|(.+?)\n+', re.S)

    def __init__(self, player, settings):
        self.player = player
        self.settings = settings
        self.buffer = ''
        self.spoken = False
        self.token = player.new_utterance()

    def feed(self, chunk):
        self.buffer += chunk
        while True:
            match = self.BOUNDARY.match(self.buffer)
            if not match or match.end() >= len(self.buffer) and not self.buffer.endswith((' ', '\n')):
                # Первое предложение длинное — начинаем говорить на запятой, не дожидаясь точки.
                if not self.spoken and len(self.buffer) > 90:
                    cut = self.buffer.rfind(', ', 30)
                    if cut > 0:
                        self._say(self.buffer[:cut + 1])
                        self.buffer = self.buffer[cut + 2:]
                        continue
                return
            sentence = (match.group(1) or match.group(2) or '').strip()
            self.buffer = self.buffer[match.end():]
            if sentence:
                self._say(sentence)

    def _say(self, text):
        if self.token != self.player.token:
            return  # пользователь перебил
        self.spoken = True
        self.player.say(text, self.settings, token=self.token)

    def finish(self, full_text):
        if self.spoken:
            if self.buffer.strip():
                self._say(self.buffer.strip())
        else:
            self._say(full_text)
        self.buffer = ''
