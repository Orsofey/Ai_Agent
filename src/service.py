"""One entry point for commands from any source: typed text, voice, phone."""
import logging
import threading

from .tts_player import SentenceSpeaker

log = logging.getLogger(__name__)


class Busy(RuntimeError):
    pass


class AssistantService:
    def __init__(self, store, agent, events, player=None):
        self.store = store
        self.agent = agent
        self.events = events
        self.player = player
        self.lock = threading.Lock()

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
                self.events.emit('delta', text=chunk, owner=owner)
                if on_text:
                    on_text(chunk)
                if speaker:
                    speaker.feed(chunk)

            try:
                result = self.agent.process_command(text, settings, owner=owner, on_text=delta)
            except Exception:
                log.exception('Command failed')
                result = 'Не удалось выполнить команду. Подробности в журнале logs/agent.log.'
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
