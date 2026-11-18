"""Always-on voice assistant: microphone → VAD → STT → wake word → command → speech.

Работает в фоне, даже когда окно агента свёрнуто и пользователь в Word или
Telegram. Схема задержки после конца фразы:
  пауза silence_ms (по умолчанию 0,45 с) + распознавание (~0,1–0,4 с) + команда.
"""
import logging
import queue
import re
import threading
import time

from . import wake
from .vad import StreamingVad, Segmenter

log = logging.getLogger(__name__)

ARM_SECONDS = 8.0       # после «Андрей» без команды ждём команду столько секунд
ONCE_SECONDS = 8.0      # после горячей клавиши / кнопки микрофона
STALE_SECONDS = 20.0    # фразы старше не выполняем
SILENCE_DEFAULT = 450   # мс тишины, после которых фраза считается законченной (меньше — быстрее реакция)
ENROLL_SAMPLES = 3
ENROLL_PHRASE = re.compile(r'^(?:запомни|выучи|запиши|узнай)\s+(?:мой\s+)?голос')

# Частые короткие ответы, которые имеет смысл синтезировать заранее: прозвучат без задержки.
FAST_REPLIES = ('Пауза.', 'Продолжаю воспроизведение.', 'Вкладка закрыта.', 'Компьютер заблокирован.',
                'Диктовка выключена.', 'Напоминания выключены.', 'Напоминания включены.')


def _is_stop(command):
    from ..service import stop_kind
    return stop_kind(command)


class VoiceAssistant:
    def __init__(self, speech, service, events, settings_provider, owner='device:desktop',
                 player=None, desktop_commands=None, microphone_factory=None, gate=None):
        self.gate = gate            # SpeakerGate: слушать только знакомые голоса
        self.enroll = None          # запоминание голоса: {'name', 'vectors', 'until'}
        self.stranger = None        # незнакомый голос ждёт пароль: {'vectors', 'command', 'until', 'fails'}
        self.verified_until = 0.0
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
        self.prewarm(settings)
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

    def prewarm(self, settings=None):
        """Заранее озвучить «Секунду, сэр», частые короткие ответы и их варианты-дворецкого."""
        if not self.player or not hasattr(self.player, 'prewarm'):
            return
        from ..dialog import ack_phrases, address_of, filler_phrases, stop_reply
        settings = settings or self.settings()
        address = address_of(settings)
        phrases = ack_phrases(address) + filler_phrases(address) + \
            [stop_reply('one', address), stop_reply('all', address)]
        for reply in FAST_REPLIES:
            if address:
                body = reply.rstrip('.')
                phrases += [f'Сделано, {address}. {reply}', f'Выполнено, {address}. {reply}',
                            f'{body}, {address}.']
            else:
                phrases.append(reply)
        self.player.prewarm(phrases, settings)

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
            segmenter = Segmenter(vad, threshold=self._threshold(settings),
                                  silence_ms=settings.get('silence_ms', SILENCE_DEFAULT))
            self._set_state('idle')
            last_config = time.monotonic()
            for frame in microphone.frames(self.stop_event):
                now = time.monotonic()
                if now - last_config > 1.0:
                    settings = self.settings()
                    segmenter.configure(self._threshold(settings), settings.get('silence_ms', SILENCE_DEFAULT))
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

        # Запоминание голоса и знакомство по паролю — фразы без имени ассистента.
        if self.enroll is not None and not during_speech:
            return self._enroll_sample(audio, settings)
        if self.stranger is not None and not during_speech:
            if now < self.stranger['until']:
                return self._stranger_answer(audio, text, settings)
            self.stranger = None

        matched, rest = wake.match(text, settings.get('wake_word', 'Андрей'), settings.get('wake_aliases', ''))
        agent = getattr(self.service, 'agent', None)
        if matched and hasattr(agent, 'prepare'):
            agent.prepare(settings)  # нейросеть выгружена после простоя — начинаем загрузку, пока звучит команда

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

        # Игровой режим: короткие игровые фразы нажимают клавиши сразу, без имени и без ответа голосом.
        games = getattr(agent, 'games', None)
        if games is not None and getattr(games, 'active', False) is True and not during_speech:
            if games.run_phrase(rest if matched else text):
                self._set_state('idle')
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
        kind = _is_stop(command)
        if kind:
            # «Андрей, стоп» / «Андрей, останови все команды» — сразу, без очереди; ответ «Хорошо, сэр».
            from ..dialog import address_of, stop_reply
            if kind == 'all':
                reply = self.service.cancel_all(settings)
                self.reset()
            else:
                self.service.cancel()
                reply = stop_reply('one', address_of(settings))
                self._set_state('idle')
            if self.player and getattr(self.player, 'available', False):
                self.player.acknowledge(reply, settings)
            self.events.emit('voice_reply', text=reply)
            return None
        wants_enroll = bool(ENROLL_PHRASE.match(command.casefold().strip(' .!?')))
        if self.gate is not None and self.gate.active(settings):
            # Слушаем только знакомые голоса. «Стоп» выше работает для всех — это безопасно.
            vector = self.gate.embed(audio)
            profile, score = self.gate.identify(vector, settings)
            if profile is None and not (vector is None and now < self.verified_until):
                log.info('Unknown voice (similarity %.2f): %s', score, command)
                return self._stranger(vector, command, settings)
            self.verified_until = time.monotonic() + 15
        if wants_enroll:
            name = 'Владелец' if self.gate is None or not self.gate.profiles() else f'Голос {len(self.gate.profiles()) + 1}'
            self._say(self.start_enroll(name), settings)
            return None
        if background:
            threading.Thread(target=self._execute, args=(command, settings), daemon=True, name='voice-command').start()
            return None
        return self._execute(command, settings)

    def _execute(self, command, settings):
        if self.player:
            self.player.stop()
            if settings.get('ack', True) and getattr(self.player, 'available', False):
                # «Секунду, сэр» — сразу, из заранее синтезированных фраз; ответ прозвучит следом.
                from ..dialog import ack_phrase, address_of
                self.player.acknowledge(ack_phrase(address_of(settings)), settings)
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

    # ---- узнавание голоса ----
    def _say(self, text, settings=None):
        settings = settings or self.settings()
        if self.player and getattr(self.player, 'available', False):
            self.player.say(text, settings)
        self.events.emit('message', role='agent', text=text, source='system', owner=self.owner, spoken=True)

    def start_enroll(self, name='Владелец'):
        """Запомнить голос: следующие три фразы (без имени ассистента)."""
        if self.gate is None:
            return 'Узнавание голоса недоступно.'
        if not self.gate.model_installed():
            return 'Сначала скачайте модель: Настройки → Голос и микрофон → «Узнавание голоса».'
        self.stranger = None
        self.enroll = {'name': name, 'vectors': [], 'until': time.monotonic() + 90}
        self.events.emit('voiceid', stage='start', count=0, total=ENROLL_SAMPLES)
        if not (self.capture_thread and self.capture_thread.is_alive()):
            self.start()
        return ('Запоминаю ваш голос. Скажите три любые фразы, по одной, например: «Какая завтра погода», '
                '«Открой календарь», «Сегодня отличный день».')

    def _enroll_sample(self, audio, settings):
        state = self.enroll
        if time.monotonic() > state['until']:
            self.enroll = None
            self.events.emit('voiceid', stage='timeout')
            self._say('Время вышло — голос не запомнил. Попробуйте ещё раз.', settings)
            return None
        vector = self.gate.embed(audio)
        if vector is None:
            self._say('Фраза слишком короткая. Скажите подлиннее.', settings)
            return None
        state['vectors'].append(vector)
        count = len(state['vectors'])
        self.events.emit('voiceid', stage='sample', count=count, total=ENROLL_SAMPLES)
        if count < ENROLL_SAMPLES:
            if self.player:
                self.player.beep('listen')
            return None
        profile = self.gate.add_profile(state['name'], state['vectors'])
        self.enroll = None
        self.verified_until = time.monotonic() + 15
        self.events.emit('voiceid', stage='done', name=profile['name'])
        self._say('Готово, запомнил ваш голос. Теперь я слушаю только знакомые голоса.' if settings.get('voice_id')
                  else 'Готово, запомнил ваш голос. Включите «Слушать только знакомые голоса» в настройках.', settings)
        return None

    def _stranger(self, vector, command, settings):
        if not self.gate.has_password():
            self._say('Я не узнаю ваш голос. Владелец может добавить вас в настройках голоса.', settings)
            return None
        self.stranger = {'vectors': [vector] if vector is not None else [], 'command': command,
                         'until': time.monotonic() + 20, 'fails': 0}
        self._say('Я не узнаю ваш голос. Чтобы познакомиться, назовите голосовой пароль.', settings)
        return None

    def _stranger_answer(self, audio, text, settings):
        state = self.stranger
        if self.gate.check_password(text):
            vector = self.gate.embed(audio)
            vectors = state['vectors'] + ([vector] if vector is not None else [])
            self.stranger = None
            if not vectors:
                self._say('Пароль верный, но фраза слишком короткая, чтобы запомнить голос. Скажите «запомни мой голос».',
                          settings)
                return None
            self.gate.add_profile(f'Голос {len(self.gate.profiles()) + 1}', vectors)
            self.verified_until = time.monotonic() + 15
            self._say('Приятно познакомиться! Запомнил ваш голос.', settings)
            if state['command']:
                threading.Thread(target=self._execute, args=(state['command'], settings), daemon=True,
                                 name='voice-command').start()
            return None
        state['fails'] += 1
        if state['fails'] >= 3:
            self.stranger = None
            self._say('Пароль неверный. Команды незнакомого голоса не выполняю.', settings)
        else:
            state['until'] = time.monotonic() + 20
            self._say('Пароль неверный. Попробуйте ещё раз.', settings)
        return None

    def expect_answer(self):
        """Вопрос задан из окна или по кнопке — следующую фразу слушать без имени, когда ассистент договорит."""
        threading.Thread(target=self._arm_answer, daemon=True).start()

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
