"""Always-on voice assistant: microphone → VAD → STT → wake word → command → speech.

Работает в фоне, даже когда окно агента свёрнуто и пользователь в Word или
Telegram. Схема задержки после конца фразы:
  пауза silence_ms (по умолчанию 0,6 с) + распознавание (~0,1–0,4 с) + команда.
"""
import logging
import queue
import threading
import time

from . import wake
from .vad import StreamingVad, Segmenter

log = logging.getLogger(__name__)

ARM_SECONDS = 8.0       # после «Андрей» без команды ждём команду столько секунд
ONCE_SECONDS = 8.0      # после горячей клавиши / кнопки микрофона
STALE_SECONDS = 20.0    # фразы старше не выполняем


def _is_stop(command):
    from ..service import STOP_PHRASES
    return command.casefold().strip(' .,!?…') in STOP_PHRASES


class VoiceAssistant:
    def __init__(self, speech, service, events, settings_provider, owner='device:desktop',
                 player=None, desktop_commands=None, microphone_factory=None):
        self.speech = speech
        self.service = service
        self.events = events
        self.settings_provider = settings_provider
        self.owner = owner
        self.player = player
        self.desktop_commands = desktop_commands
        self.microphone_factory = microphone_factory
        self.segments = queue.Queue(maxsize=20)
        self.stop_event = threading.Event()
        self.capture_thread = None
        self.worker_thread = None
        self.state = 'off'
        self.error = None
        self.armed_until = 0.0
        self.once_until = 0.0
        self.follow_up_until = 0.0
        self.device = None
        self.vad_engine = None
        self.enabled = False

    # ---- управление ----
    def settings(self):
        return self.settings_provider()

    def start(self):
        settings = self.settings()
        self.enabled = settings.get('voice_enabled', True)
        if not self.enabled or (self.capture_thread and self.capture_thread.is_alive()):
            self._set_state(self.state if self.enabled else 'off')
            return
        self.stop_event.clear()
        self.device = settings.get('native_microphone', '')
        self.capture_thread = threading.Thread(target=self._capture, daemon=True, name='voice-capture')
        self.capture_thread.start()
        if not self.worker_thread or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._worker, daemon=True, name='voice-worker')
            self.worker_thread.start()

    def stop(self):
        self.stop_event.set()
        if self.capture_thread:
            self.capture_thread.join(timeout=2)
        self.capture_thread = None
        self._set_state('off')

    def apply_settings(self, settings):
        """Перезапуск захвата при смене микрофона или включения."""
        want = settings.get('voice_enabled', True)
        if not want:
            self.stop()
            self.enabled = False
            return
        if settings.get('native_microphone', '') != self.device or not (self.capture_thread and self.capture_thread.is_alive()):
            self.stop()
            self.start()

    def listen_once(self):
        """Горячая клавиша / кнопка: следующая фраза — команда без имени."""
        if self.player:
            self.player.stop()
            self.player.beep('listen')
        self.once_until = time.monotonic() + ONCE_SECONDS
        self.events.emit('state', state='listening', reason='once')
        if not (self.capture_thread and self.capture_thread.is_alive()):
            self.start()

    def reset(self):
        """Кнопка «Пауза»: забыть ожидание продолжения и вернуться к прослушиванию имени."""
        self.once_until = self.armed_until = self.follow_up_until = 0.0
        if self.state not in ('off', 'error'):
            self._set_state('idle')

    def status(self):
        return dict(state=self.state, error=self.error, device=self.device, vad=self.vad_engine,
                    running=bool(self.capture_thread and self.capture_thread.is_alive()),
                    dictation=bool(self.desktop_commands and self.desktop_commands.dictation))

    def _set_state(self, state, **extra):
        self.state = state
        self.events.emit('state', state=state, **extra)

    # ---- захват ----
    def _open_microphone(self):
        if self.microphone_factory:
            microphone = self.microphone_factory(self.device)
        else:
            from .microphone import Microphone
            microphone = Microphone(self.device)
        return microphone.open()

    def _capture(self):
        # Микрофон могут подключить позже — пробуем снова каждые 5 секунд.
        while not self.stop_event.is_set():
            try:
                microphone = self._open_microphone()
                break
            except Exception as exc:
                message = 'Микрофон недоступен: ' + str(exc)
                if message != self.error:
                    log.warning(message)
                self.error = message
                self._set_state('error', message=message)
                if self.stop_event.wait(5.0):
                    return
        else:
            return
        self.error = None
        try:
            vad = StreamingVad(self.speech.vad_dir())
            self.vad_engine = vad.engine
            settings = self.settings()
            segmenter = Segmenter(vad, threshold=self._threshold(settings), silence_ms=settings.get('silence_ms', 600))
            self._set_state('idle')
            last_config = time.monotonic()
            for frame in microphone.frames(self.stop_event):
                now = time.monotonic()
                if now - last_config > 1.0:
                    settings = self.settings()
                    segmenter.configure(self._threshold(settings), settings.get('silence_ms', 600))
                    last_config = now
                    if vad.engine == 'energy' and self.speech.vad_dir():
                        vad = StreamingVad(self.speech.vad_dir())  # модель VAD только что скачали
                        segmenter.vad = vad
                        self.vad_engine = vad.engine
                self.events.level(microphone.level)
                event, data = segmenter.push(frame, now)
                if event == 'start':
                    self.events.emit('state', state='hearing')
                elif event == 'end':
                    audio, started = data
                    self.events.emit('state', state='transcribing')
                    try:
                        self.segments.put_nowait((audio, started, time.monotonic()))
                    except queue.Full:
                        log.warning('Voice queue full, dropping segment')
        except Exception as exc:
            self.error = str(exc)
            log.exception('Voice capture failed')
            self._set_state('error', message=self.error)
        finally:
            microphone.close()
            if self.state != 'error':
                self._set_state('off')

    @staticmethod
    def _threshold(settings):
        # Чувствительность 10..90 → порог VAD 0.8..0.2
        return max(0.15, min(0.85, 1.0 - settings.get('vad_sensitivity', 50) / 100.0))

    # ---- обработка фраз ----
    def _worker(self):
        while True:
            audio, started, ended = self.segments.get()
            if time.monotonic() - ended > STALE_SECONDS:
                continue
            try:
                self.handle_segment(audio, started, background=True)
            except Exception:
                log.exception('Voice segment failed')
            finally:
                if self.state not in ('off', 'error'):
                    self._set_state('idle')

    def handle_segment(self, audio, started=None, background=False):
        settings = self.settings()
        started = started if started is not None else time.monotonic()
        now = time.monotonic()
        # Фраза началась, пока агент говорил → это может быть эхо динамиков.
        during_speech = bool(self.player) and (self.player.speaking or started < self.player.last_end + 0.35)
        try:
            result = self.speech.transcribe_array(audio, settings.get('voice_language', 'auto'))
        except Exception as exc:
            self.events.emit('voice_error', message=str(exc))
            return None
        text = result['text']
        if not text:
            return None
        self.events.emit('transcript', text=text, elapsed=result.get('elapsed'), engine=result.get('engine'))

        matched, rest = wake.match(text, settings.get('wake_word', 'Андрей'), settings.get('wake_aliases', ''))

        # Режим диктовки: всё сказанное печатается в активное окно.
        if self.desktop_commands and self.desktop_commands.dictation and not during_speech:
            command = rest if matched else text
            from ..desktop.commands import parse
            parsed = parse(command)
            if parsed and parsed[0] in ('dictation', 'keys', 'newline', 'clear'):
                return self._execute(command, settings)
            if matched and not rest:
                return None
            from ..desktop.commands import tidy_typed
            try:
                self.desktop_commands.desktop.type_text(tidy_typed(text if not matched else rest) + ' ',
                                                       settings.get('type_method', 'auto'))
            except Exception as exc:
                self.events.emit('voice_error', message=str(exc))
            return None

        explicit = now < self.once_until
        armed = now < self.armed_until
        follow_up = now < self.follow_up_until and not during_speech
        if explicit or armed or follow_up:
            command = rest if matched else text
            self.once_until = self.armed_until = 0.0
        elif matched:
            if during_speech and self.player:
                self.player.stop()  # перебили голосом
            if not rest:
                self.armed_until = time.monotonic() + ARM_SECONDS
                if self.player:
                    self.player.stop()
                    self.player.beep('wake')
                self._set_state('listening', reason='wake')
                return None
            command = rest
        else:
            return None
        if not command:
            return None
        if _is_stop(command):
            # «Андрей, стоп» — прервать текущую команду и речь немедленно, без очереди.
            self.service.cancel()
            self._set_state('idle')
            return None
        if background:
            threading.Thread(target=self._execute, args=(command, settings), daemon=True, name='voice-command').start()
            return None
        return self._execute(command, settings)

    def _execute(self, command, settings):
        if self.player:
            self.player.stop()
        self._set_state('thinking', command=command)
        try:
            answer, spoken = self.service.run(command, self.owner, settings, source='voice')
        except Exception as exc:
            self.events.emit('voice_error', message=str(exc))
            return None
        cancelled = getattr(self.service, 'cancel_event', None)
        if isinstance(cancelled, threading.Event) and cancelled.is_set():
            return answer  # остановлено — не ждём продолжения
        agent = getattr(self.service, 'agent', None)
        if agent is not None and getattr(agent, 'awaiting', None) and agent.awaiting(self.owner) is True:
            # Агент задал вопрос («Что открыть, сэр?») — ответ можно дать без имени.
            threading.Thread(target=self._arm_answer, daemon=True).start()
            return answer
        follow = settings.get('follow_up_seconds', 5)
        if follow:
            # Окно продолжения разговора открывается после того, как агент договорит.
            threading.Thread(target=self._arm_follow_up, args=(follow,), daemon=True).start()
        return answer

    def _arm_answer(self, seconds=ARM_SECONDS + 4):
        deadline = time.monotonic() + 60
        time.sleep(0.2)
        while self.player and self.player.is_busy() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.armed_until = time.monotonic() + seconds
        self._set_state('listening', reason='answer')

    def _arm_follow_up(self, seconds):
        deadline = time.monotonic() + 120
        time.sleep(0.2)
        while self.player and self.player.is_busy() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.follow_up_until = time.monotonic() + seconds
