"""Native speech output with sentence streaming and instant interruption.

Синтез и воспроизведение идут в двух потоках: пока звучит первое предложение,
синтезируется второе. Ответ ИИ начинает звучать после первой фразы, а не
после всего текста. Короткие ответы кэшируются: повторные («Пауза, сэр.»)
звучат мгновенно, без синтеза.
"""
import logging
import subprocess
import sys
import queue
import re
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

URL_RE = re.compile(r'https?://\S+')
CACHEABLE = 120        # ответы короче стольких символов запоминаются и повторно звучат без синтеза
CACHE_LIMIT = 300      # максимум фраз в кэше


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
        self.ack_cache = {}       # (текст, голос, скорость) → звук: «Секунду, сэр» звучит без задержки
        self.ack_playing = False
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
        """Начать новый ответ: старая речь отменяется, но «Секунду, сэр» договаривается до конца."""
        if not self.ack_playing and not self._ack_queued():
            self.stop()
            return self.token
        with self.lock:
            self.token += 1
            self.pending = 0
        self._drain(self.synth_queue)
        keep = [item for item in self._drain(self.play_queue) if item[0] is None]
        for item in keep:
            self.play_queue.put(item)
        return self.token

    def _ack_queued(self):
        with self.play_queue.mutex:
            return any(item[0] is None and item[3] == 'ack' for item in self.play_queue.queue)

    @staticmethod
    def _drain(q):
        items = []
        try:
            while True:
                items.append(q.get_nowait())
        except queue.Empty:
            return items

    # ---- мгновенные подтверждения ----
    def _ack_key(self, text, settings):
        voice = self.tts.pick_voice(text, settings.get('tts_voice', 'irina'), settings.get('tts_voice_en', 'amy'))
        preset = settings.get('voice_preset', 'classic')
        identity = self.tts.cache_identity(text, voice, preset) if hasattr(self.tts, 'cache_identity') else ''
        return text, voice, settings.get('tts_rate', 100), preset, identity

    def _cache_get(self, text, settings):
        return self.ack_cache.get(self._ack_key(text, settings))

    def _cache_put(self, text, settings, result):
        if result is None or len(text) > CACHEABLE:
            return
        if len(self.ack_cache) >= CACHE_LIMIT:
            # Кэш ограничен: выкидываем самые старые фразы (dict помнит порядок добавления).
            for key in list(self.ack_cache)[:CACHE_LIMIT // 2]:
                self.ack_cache.pop(key, None)
        self.ack_cache[self._ack_key(text, settings)] = result

    def prewarm(self, texts, settings):
        """Заранее синтезировать короткие фразы («Секунду, сэр»), чтобы они звучали сразу."""
        def work():
            for text in texts:
                key = self._ack_key(text, settings)
                if key in self.ack_cache:
                    continue
                try:
                    result = self.tts.synthesize_array(text, key[1], key[2] / 100.0, preset=key[3])
                except Exception:
                    result = None
                if result is not None:
                    self.ack_cache[key] = result
        threading.Thread(target=work, daemon=True, name='tts-prewarm').start()

    def acknowledge(self, text, settings):
        """Сказать короткую фразу немедленно; следующий ответ её не обрывает."""
        if not settings.get('tts_enabled', True) or not self.available:
            return
        cached = self._cache_get(text, settings)
        if cached is None:
            key = self._ack_key(text, settings)
            try:
                cached = self.tts.synthesize_array(text, key[1], key[2] / 100.0, preset=key[3])
            except Exception:
                cached = None
            if cached is None:
                return
            self.ack_cache[key] = cached
        self.play_queue.put((None, cached[0], cached[1], 'ack'))

    def stop(self):
        with self.lock:
            self.token += 1
            self.pending = 0
            was = self.speaking
            self.speaking = False
        for q in (self.synth_queue, self.play_queue):
            self._drain(q)
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
            cached = self._cache_get(text, settings)
            if cached is not None:
                # Уже синтезировали такую фразу — звучит сразу, без повторной работы модели.
                self.play_queue.put((token, cached[0], cached[1], None))
                continue
            voice = self.tts.pick_voice(text, settings.get('tts_voice', 'irina'), settings.get('tts_voice_en', 'amy'))
            rate = settings.get('tts_rate', 100) / 100.0
            try:
                result = self.tts.synthesize_array(text, voice, rate, preset=settings.get('voice_preset', 'classic'))
            except Exception:
                log.exception('TTS synthesis failed')
                result = None
            if token != self.token:
                continue
            if result is None:
                self.play_queue.put((token, None, None, (text, rate)))
            else:
                self._cache_put(text, settings, result)
                self.play_queue.put((token, result[0], result[1], None))

    def _play_loop(self):
        while True:
            token, audio, rate, fallback = self.play_queue.get()
            if token is not None and token != self.token:
                continue
            if token is not None:
                self._emit(True)
            try:
                if fallback == 'ack':
                    self.ack_playing = True
                    self._play(audio, rate, None)
                elif fallback is not None:
                    self._system_voice(*fallback)
                elif self.available:
                    self._play(audio, rate, token)
            except Exception:
                log.exception('Playback failed')
            finally:
                self.ack_playing = False
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
        """Системный голос (Windows SAPI, macOS say), если нейросетевые голоса не установлены."""
        if sys.platform == 'darwin':
            try:
                voice = 'Milena' if re.search('[а-яё]', text, re.I) else 'Samantha'
                subprocess.run(['say', '-v', voice, '-r', str(int(180 * rate)), text], timeout=120)
            except Exception as exc:
                log.info('System voice unavailable: %s', exc)
            return
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

