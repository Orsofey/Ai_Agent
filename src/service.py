"""One entry point for commands from any source: typed text, voice, phone."""
import logging
import threading

from . import abort
from .tts_player import SentenceSpeaker

log = logging.getLogger(__name__)


class Busy(RuntimeError):
    pass


class Cancelled(Exception):
    """Пользователь нажал «Пауза» или сказал «стоп»."""


# «Отмени» (Ctrl+Z) и «пауза» (видео) — отдельные команды, поэтому их здесь нет.
STOP_PHRASES = {'стоп', 'стой', 'хватит', 'отмена', 'замолчи', 'остановись', 'прекрати',
                'стоп стоп', 'тихо', 'помолчи', 'stop', 'cancel', 'останови команду', 'останови', 'отмени команду',
                'выключись', 'отключись', 'стоп команда', 'хватит хватит', 'всё хватит', 'все хватит', 'остановить',
                'прекрати команду', 'стоп команду'}
STOP_ALL_PHRASES = {'останови все команды', 'останови всё', 'останови все', 'отмени все команды', 'стоп всё', 'стоп все',
                    'прекрати всё', 'прекрати все', 'останови все действия', 'остановить все команды', 'стоп все команды',
                    'отмени всё', 'отмени все', 'стоп всем командам', 'выключи все команды'}


def stop_kind(text):
    """'all' — «останови все команды», 'one' — «стоп», иначе None."""
    import re
    value = re.sub(r'[^\w\s]', ' ', str(text).casefold().replace('ё', 'е'))
    value = ' '.join(value.split())
    phrases = {p.replace('ё', 'е') for p in STOP_ALL_PHRASES}
    if value in phrases:
        return 'all'
    if value in {p.replace('ё', 'е') for p in STOP_PHRASES}:
        return 'one'
    return None


class AssistantService:
    def __init__(self, store, agent, events, player=None):
        self.store = store
        self.agent = agent
        self.events = events
        self.player = player
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.running = False
        self.stop_generation = 0

    def cancel(self):
        """Прервать текущую команду и озвучку. Возвращает True, если было что прерывать."""
        was = self.running or bool(self.player and self.player.is_busy())
        abort.abort_all()  # печать текста и макросы тоже останавливаются
        self.cancel_event.set()
        if self.player is not None:
            self.player.stop()
        self.events.emit('cancelled')
        return was

    def cancel_all(self, settings=None):
        """«Останови все команды»: текущая и ожидающие команды, озвучка, диктовка, уточняющие вопросы."""
        self.stop_generation += 1
        self.cancel()
        commands = getattr(self.agent, 'desktop_commands', None)
        if commands is not None:
            commands.dictation = False
        dialog = getattr(self.agent, 'dialog', None)
        if dialog is not None and hasattr(dialog, 'pending'):
            dialog.pending.clear()
        self.events.emit('state', state='idle')
        from .dialog import address_of, stop_reply
        return stop_reply('all', address_of(settings))

    def control(self, text, settings=None):
        """Стоп-фразы выполняются сразу, мимо очереди команд. Вернуть ответ или None."""
        from .agent import strip_wake
        from .dialog import address_of, stop_reply
        kind = stop_kind(strip_wake(str(text).strip(), settings or {}))
        if kind == 'all':
            return self.cancel_all(settings)
        if kind == 'one':
            self.cancel()
            return stop_reply('one', address_of(settings))
        return None

    def run(self, text, owner, settings=None, source='text', on_text=None, speak=True):
        settings = settings or self.store.settings(owner)
        generation = self.stop_generation
        if not self.lock.acquire(timeout=90):
            raise Busy('Выполняется предыдущая команда. Повторите позже.')
        if generation != self.stop_generation:
            self.lock.release()
            return 'Остановлено.', False  # команда ждала в очереди, а пользователь остановил всё
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
                abort.begin()
                try:
                    outcome['result'] = self.agent.process_command(text, settings, owner=owner, on_text=delta)
                except (Cancelled, abort.Aborted):
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
