"""Streaming chat with a local or free OpenAI-compatible LLM server.

По умолчанию — встроенная локальная нейросеть (llama.cpp + Qwen, см. local_llm.py):
бесплатно, без ключей и без интернета. Можно указать любой другой сервер с
/v1/chat/completions: Ollama, LM Studio или бесплатные облачные тарифы.
Факты («кто такой…», «что такое…», «столица…») подмешиваются из Википедии,
по желанию пользователя — ещё и из DuckDuckGo, чтобы маленькая модель отвечала точно.
"""
import json
import logging
import re

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


SYSTEM_PROMPT = """Ты — {name}, голосовой ассистент на компьютере пользователя. Твои ответы озвучиваются синтезатором речи.

Правила:
- Отвечай на языке вопроса (обычно по-русски).
- {style}
- Только обычный разговорный текст: без markdown, списков со звёздочками, таблиц, эмодзи и ссылок.
- Будь точным. Если в сообщении есть результаты поиска или данные — опирайся на них, а не на память.
  Если точных данных нет и вопрос о том, что меняется (цены, новости, курсы), честно скажи, что данные могут быть неактуальны.
- Финансы, питание, здоровье, спорт: давай конкретные практичные советы с цифрами, а при серьёзных решениях
  добавь одну короткую оговорку (врач или финансовый консультант). Не отказывайся от бытовых вопросов.
- Если вопрос неоднозначен, отвечай на самый вероятный смысл, не переспрашивай.
- Команды управления компьютером обрабатываются отдельно, тебе нужно только отвечать на вопросы."""

STYLES = {
    'short': 'Отвечай коротко: одно-три предложения, главное — в первом.',
    'detailed': 'Отвечай полно, но компактно: до шести предложений.',
}


def system_prompt(settings):
    prompt = SYSTEM_PROMPT.format(name=settings.get('wake_word') or 'Андрей',
                                  style=STYLES.get(settings.get('answer_style'), STYLES['short']))
    address = settings.get('address', 'сэр')
    if address and address != 'none' and settings.get('butler', True):
        prompt += (f'\n- Ты вежливый дворецкий: иногда (не в каждой фразе) обращайся к пользователю «{address}», '
                   'например «Сегодня, {address}, около плюс десяти».').replace('{address}', address)
    return prompt


FRESH_HINTS = re.compile(
    r'сегодня|сейчас|завтра|вчера|новост|курс|цен[аы]|стоит|стоимост|погод|счет матча|счёт|результат|кто выиграл|'
    r'202\d|последн|актуальн|свеж|расписани|когда выйдет|сколько лет|президент|премьер|акци[ия]|ставк|'
    r'кто так|кто был|кто написал|кто изобр|что такое|когда был|когда будет|где наход|столиц|население|'
    r'сколько жив|рейтинг|лучши[ей]|отзыв|адрес|телефон|who is|what is|when did|latest|price|news', re.I)


class OpenAICompatibleProvider:
    """Встроенный llama-server, Ollama, LM Studio или облачный сервер с /v1/chat/completions."""

    def __init__(self, base_url, model, api_key, tools, session=None, local=False):
        if not base_url or not model:
            raise LLMError('Укажите адрес сервера и модель в Настройки → ИИ.')
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key = api_key
        self.tools = tools
        self.local = local
        self._session = session

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            if self.local or '127.0.0.1' in self.base_url or 'localhost' in self.base_url:
                self._session.trust_env = False  # локальный сервер — мимо системного прокси
        return self._session

    def _context(self, question, settings):
        if not settings.get('llm_web_search', True) or not FRESH_HINTS.search(question):
            return ''
        try:
            results = self.tools.web_search(question, 5, duckduckgo=settings.get('ddg_search', False))
        except Exception as exc:
            log.info('web search failed: %s', exc)
            return ''
        lines = [f"- [{r.get('source', 'поиск')}] {r['title']}: {r['snippet']}" for r in results if r.get('snippet')]
        return ('Справочные данные (используй их для точного ответа):\n' + '\n'.join(lines)) if lines else ''

    def stream(self, history, settings, on_text=None, system=None, max_tokens=1500, with_tools=True):
        messages = [{'role': 'system', 'content': system or system_prompt(settings)}]
        for item in history:
            content = item['content'] if isinstance(item['content'], str) else str(item['content'])
            messages.append({'role': item['role'], 'content': content})
        if with_tools and history:
            context = self._context(history[-1]['content'], settings)
            if context:
                messages[-1]['content'] = context + '\n\nВопрос: ' + messages[-1]['content']
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        body = {'model': self.model, 'messages': messages, 'stream': True,
                'temperature': 0.3, 'max_tokens': max_tokens}
        if self.local:
            # Qwen3: отвечать сразу, без режима размышлений.
            body['chat_template_kwargs'] = {'enable_thinking': False}
            body['cache_prompt'] = True  # llama-server повторно использует уже посчитанный системный промпт
        parts = []
        think = ThinkFilter()
        try:
            response = self.session.post(self.base_url + '/chat/completions', json=body, headers=headers,
                                         stream=True, timeout=(5, 120))
        except Exception as exc:
            raise LLMError(('Локальная нейросеть не отвечает: ' if self.local else 'Сервер ИИ недоступен: ') + str(exc)[:120])
        if response.status_code >= 400:
            raise LLMError(f'Сервер ИИ вернул ошибку {response.status_code}: {response.text[:160]}')
        try:
            for raw in response.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                try:
                    delta = json.loads(payload)['choices'][0].get('delta', {}).get('content') or ''
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    parts.append(delta)
                    visible = think.feed(delta)
                    if visible and on_text:
                        on_text(visible)  # может бросить Cancelled — тогда соединение закрывается ниже
        finally:
            # Закрытое соединение останавливает генерацию на сервере (кнопка «Пауза»).
            getattr(response, 'close', lambda: None)()
        text = ''.join(parts)
        # Локальные «думающие» модели иногда присылают размышления в тегах.
        return re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()


class ThinkFilter:
    """Не озвучивать размышления <think>…</think> локальных моделей."""

    def __init__(self):
        self.buffer = ''
        self.inside = False

    def feed(self, chunk):
        self.buffer += chunk
        out = []
        while self.buffer:
            if self.inside:
                end = self.buffer.find('</think>')
                if end < 0:
                    self.buffer = self.buffer[-8:]
                    break
                self.buffer = self.buffer[end + 8:]
                self.inside = False
            else:
                start = self.buffer.find('<think>')
                if start < 0:
                    # Хвост может быть началом тега «<think>» — придержим его.
                    cut = self.buffer.rfind('<')
                    if cut >= 0 and '<think>'.startswith(self.buffer[cut:]):
                        out.append(self.buffer[:cut])
                        self.buffer = self.buffer[cut:]
                    else:
                        out.append(self.buffer)
                        self.buffer = ''
                    break
                out.append(self.buffer[:start])
                self.buffer = self.buffer[start + 7:]
                self.inside = True
        return ''.join(out)
