"""Question answering: instant local answers first, then a streaming LLM."""
import logging
import threading
import time
from collections import deque

from .llm import LLMError, OpenAICompatibleProvider, system_prompt
from .local_llm import LocalLLMServer
from .quick import QuickAnswers, now_context
from .tools import DataTools

log = logging.getLogger(__name__)

__all__ = ['Brain', 'LLMError', 'DataTools', 'QuickAnswers', 'LocalLLMServer']

MEMORY_TURNS = 6          # сколько последних пар вопрос-ответ помнить
MEMORY_IDLE_SECONDS = 900  # после 15 минут тишины разговор начинается заново


class Brain:
    def __init__(self, store, tools=None, local=None):
        self.store = store
        self.tools = tools or DataTools()
        self.local = local or LocalLLMServer(store.root)
        self.quick = QuickAnswers(self.tools)
        self.memory = {}
        self.lock = threading.Lock()
        self._providers = {}
        self._warming = False
        self._primed = None
        self.last_timing = None

    # ---- провайдеры ----
    def provider(self, settings):
        kind = settings.get('llm_provider', 'local')
        if kind == 'off':
            return None
        if kind == 'local':
            try:
                base_url = self.local.ensure(settings)
            except RuntimeError as exc:
                raise LLMError(str(exc))
            cache_key = ('local', base_url)
            if cache_key not in self._providers:
                self._providers = {cache_key: OpenAICompatibleProvider(base_url, 'local', '', self.tools, local=True)}
            return self._providers[cache_key]
        key = self.store.secret('openai_api_key') or ''
        cache_key = ('openai', settings.get('openai_base_url'), settings.get('openai_model'), key)
        if cache_key not in self._providers:
            self._providers = {cache_key: OpenAICompatibleProvider(
                settings.get('openai_base_url'), settings.get('openai_model'), key, self.tools)}
        return self._providers[cache_key]

    # ---- память разговора ----
    def _history(self, owner):
        with self.lock:
            entry = self.memory.get(owner)
            if not entry or time.monotonic() - entry['time'] > MEMORY_IDLE_SECONDS:
                entry = {'time': time.monotonic(), 'turns': deque(maxlen=MEMORY_TURNS)}
                self.memory[owner] = entry
            return entry

    def forget(self, owner):
        with self.lock:
            self.memory.pop(owner, None)

    # ---- ответы ----
    def quick_answer(self, question, settings):
        return self.quick.answer(question, settings)

    def answer(self, question, settings, owner='default', on_text=None, mode='normal'):
        """Ответ на вопрос. on_text получает фрагменты текста по мере генерации. mode='chat' — «поболтать»."""
        quick = self.quick_answer(question, settings)
        if quick:
            self._remember(owner, question, quick)
            return quick
        provider = self.provider(settings)
        if provider is None:
            return None
        entry = self._history(owner)
        history = []
        turns = list(entry['turns'])[-3:] if mode == 'chat' else entry['turns']  # короче контекст — быстрее ответ
        for user_text, agent_text in turns:
            history += [{'role': 'user', 'content': user_text}, {'role': 'assistant', 'content': agent_text}]
        context = f'[Сейчас {now_context()}. Город пользователя: {settings.get("city") or "не указан"}.]\n'
        history.append({'role': 'user', 'content': context + question})
        if mode == 'chat':
            limit = 120
        else:
            limit = 900 if settings.get('answer_style') == 'detailed' else 300
        started = time.monotonic()
        first = []

        def timed(chunk):
            if not first:
                first.append(time.monotonic() - started)
            if on_text:
                on_text(chunk)
        text = provider.stream(history, settings, on_text=timed, max_tokens=limit,
                               system=system_prompt(settings, mode))
        self.last_timing = {'first_token': round(first[0], 2) if first else None,
                            'total': round(time.monotonic() - started, 2), 'mode': mode}
        log.info('LLM answer: first words %.2fs, total %.2fs (%s)', first[0] if first else -1,
                 self.last_timing['total'], mode)
        text = text or 'Не нашёл, что ответить. Переформулируйте вопрос.'
        self._remember(owner, question, text)
        return text

    def warm(self, settings):
        """Подготовить нейросеть заранее (при запуске и когда услышали имя): запустить сервер, если его
        выгрузили, и посчитать системный промпт, чтобы первый ответ начинался быстрее."""
        if settings.get('llm_provider', 'local') != 'local' or self._warming:
            return
        if self.local.running() and self._primed == self.local.port:
            return
        self._warming = True

        def run():
            try:
                provider = self.provider(settings)
                if provider is not None:
                    provider.stream([{'role': 'user', 'content': 'Привет'}], settings, max_tokens=1,
                                    with_tools=False, system=system_prompt(settings))
                    self._primed = self.local.port
            except Exception as exc:
                log.info('LLM warm-up skipped: %s', exc)
            finally:
                self._warming = False
        threading.Thread(target=run, daemon=True, name='llm-prime').start()

    def _remember(self, owner, question, answer):
        entry = self._history(owner)
        with self.lock:
            entry['turns'].append((question, answer))
            entry['time'] = time.monotonic()

    def complete(self, task, text, settings):
        """Обработка текста без инструментов: перевод, исправление, сочинение."""
        provider = self.provider(settings)
        if provider is None:
            return None
        return provider.stream([{'role': 'user', 'content': text}], dict(settings, llm_web_search=False),
                               system=task, max_tokens=1500, with_tools=False)
