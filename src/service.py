"""One entry point for commands from any source: typed text, voice, phone."""
import logging
import threading

from .tts_player import SentenceSpeaker

log = logging.getLogger(__name__)


class Busy(RuntimeError):
    pass


class Cancelled(Exception):
    """Пользователь нажал «Пауза» или сказал «стоп»."""


STOP_PHRASES = {'стоп', 'стой', 'хватит', 'отмена', 'отмени', 'замолчи', 'пауза', 'остановись', 'прекрати',
                'стоп стоп', 'тихо', 'помолчи', 'stop', 'cancel'}


class AssistantService:
    def __init__(self, store, agent, events, player=None):
        self.store = store
        self.agent = agent
        self.events = events
        self.player = player
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.running = False

    def cancel(self):
        """Прервать текущую команду и озвучку. Возвращает True, если было что прерывать."""
        was = self.running or bool(self.player and self.player.is_busy())
        self.cancel_event.set()
        if self.player is not None:
            self.player.stop()
        self.events.emit('cancelled')
        return was

    def run(self, text, owner, settings=None, source='text', on_text=None, speak=True):
        settings = settings or self.store.settings(owner)
        if not self.lock.acquire(timeout=90):
            raise Busy('Выполняется предыдущая команда. Повторите позже.')
        try:
            self.store.add(owner, 'user', text)
            self.events.emit('message', role='user', text=text, source=source, owner=owner)
            self.events.emit('state', state='thinking')
            speaker = None
            if speak and self.player is not None and self.player.available and settings.get('tts_enabled', True):
                speaker = SentenceSpeaker(self.player, settings)

            def delta(chunk):
                if self.cancel_event.is_set():
                    raise Cancelled()
                self.events.emit('delta', text=chunk, owner=owner)
                if on_text:
                    on_text(chunk)
                if speaker:
                    speaker.feed(chunk)

            outcome = {}

            def work():
                try:
                    outcome['result'] = self.agent.process_command(text, settings, owner=owner, on_text=delta)
                except Cancelled:
                    pass
                except Exception:
                    log.exception('Command failed')
                    outcome['result'] = 'Не удалось выполнить команду. Подробности в журнале logs/agent.log.'

            self.cancel_event.clear()
            self.running = True
            worker = threading.Thread(target=work, daemon=True, name='command')
            worker.start()
            while worker.is_alive() and not self.cancel_event.is_set():
                worker.join(0.05)
            self.running = False
            if self.cancel_event.is_set() and 'result' not in outcome:
                # Долгое действие (браузер, загрузка) дорабатывает в фоне, но ассистент уже свободен.
                self.store.add(owner, 'agent', 'Остановлено.')
                self.events.emit('message', role='agent', text='Остановлено.', source=source, owner=owner, spoken=False)
                self.events.emit('state', state='idle')
                return 'Остановлено.', False
            result = outcome.get('result')
            result = str(result or '').strip() or 'Готово.'
            if speaker:
                speaker.finish(result)
            self.store.add(owner, 'agent', result)
            self.events.emit('message', role='agent', text=result, source=source, owner=owner,
                             spoken=speaker is not None)
            self.events.emit('state', state='idle')
            return result, speaker is not None
        finally:
            self.lock.release()
