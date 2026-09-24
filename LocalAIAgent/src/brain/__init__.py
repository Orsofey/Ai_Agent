"""Question answering: instant local answers first, then a streaming LLM."""
import logging
import threading
import time
from collections import deque

from .llm import ClaudeProvider, LLMError, OpenAICompatibleProvider
from .quick import QuickAnswers, now_context
from .tools import DataTools

log = logging.getLogger(__name__)

__all__ = ['Brain', 'LLMError', 'DataTools', 'QuickAnswers']

MEMORY_TURNS = 6          # сколько последних пар вопрос-ответ помнить
MEMORY_IDLE_SECONDS = 900  # после 15 минут тишины разговор начинается заново


class Brain:
    def __init__(self, store, tools=None):
        self.store = store
        self.tools = tools or DataTools()
        self.quick = QuickAnswers(self.tools)
        self.memory = {}
        self.lock = threading.Lock()
        self._providers = {}

    # ---- провайдеры ----
    def provider(self, settings):
        kind = settings.get('llm_provider', 'claude')
        if kind == 'off':
            return None
        if kind == 'claude':
            key = self.store.secret('anthropic_api_key')
            if not key:
                raise LLMError('Чтобы я отвечал на любые вопросы, добавьте ключ Anthropic API в Настройки → ИИ.')
            cache_key = ('claude', key)
            if cache_key not in self._providers:
                self._providers = {cache_key: ClaudeProvider(key, self.tools)}
            return self._providers[cache_key]
        key = self.store.secret('openai_api_key') or ''
        cache_key = ('openai', settings.get('openai_base_url'), settings.get('openai_model'), key)
        if cache_key not in self._providers:
            self._providers = {cache_key: OpenAICompatibleProvider(
                settings.get('openai_base_url'), settings.get('openai_model'), key, self.tools)}
        return self._providers[cache_key]

    def configured(self, settings):
        try:
            return self.provider(settings) is not None
        except LLMError:
            return False

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

    def answer(self, question, settings, owner='default', on_text=None):
        """Ответ на вопрос. on_text получает фрагменты текста по мере генерации."""
        quick = self.quick_answer(question, settings)
        if quick:
            self._remember(owner, question, quick)
            return quick
        provider = self.provider(settings)
        if provider is None:
            return None
        entry = self._history(owner)
        history = []
        for user_text, agent_text in entry['turns']:
            history += [{'role': 'user', 'content': user_text}, {'role': 'assistant', 'content': agent_text}]
        context = f'[Сейчас {now_context()}. Город пользователя: {settings.get("city") or "не указан"}.]\n'
        history.append({'role': 'user', 'content': context + question})
        text = provider.stream(history, settings, on_text=on_text)
        text = text or 'Не нашёл, что ответить. Переформулируйте вопрос.'
        self._remember(owner, question, text)
        return text

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
                               system=task, max_tokens=4000, with_tools=False)
