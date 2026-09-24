"""LLM providers with streaming: Claude (Anthropic SDK) and any OpenAI-compatible server.

Claude — основной провайдер: потоковый ответ + встроенный веб-поиск Anthropic
и собственные инструменты (курсы ЦБ, погода, криптовалюты). Первые слова
ответа начинают озвучиваться, пока модель ещё пишет продолжение.

OpenAI-совместимый сервер (Ollama, LM Studio, OpenRouter и т.п.) — для
офлайн-режима или других поставщиков; свежие данные подмешиваются поиском.
"""
import json
import logging
import re

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


SYSTEM_PROMPT = """You are {name}, a fast voice assistant running on the user's Windows PC. \
Your replies are read aloud by a speech synthesizer.

Rules:
- Answer in the language of the question (usually Russian).
- {style}
- Plain spoken text only: no markdown, no lists with symbols, no tables, no emoji, no URLs.
- Write numbers so they read naturally; use the local currency (rubles) unless asked otherwise.
- Be precise. For exchange rates, weather, prices, news, sports results and anything time-sensitive, \
use the tools instead of memory. Mention the source briefly if it matters (for example "по данным ЦБ").
- Finance, investments, diet, health: give concrete, practical guidance with numbers, then one short \
caveat when the stakes are high (a doctor or a licensed advisor for personal decisions). Do not refuse everyday questions.
- If the question is ambiguous, answer the most likely meaning instead of asking back.
- The user may also ask to control the PC; those commands are handled elsewhere, so just answer questions.
Latency-sensitive; begin your visible answer immediately."""

STYLES = {
    'short': 'Keep answers short: one to three sentences, the key fact first.',
    'detailed': 'Give a complete but compact answer: up to six sentences.',
}

CUSTOM_TOOLS = [
    {
        'name': 'get_exchange_rates',
        'description': 'Official Central Bank of Russia exchange rates to the ruble for today. '
                       'Use for any question about currency rates or conversions.',
        'eager_input_streaming': True,
        'input_schema': {
            'type': 'object',
            'properties': {'currencies': {'type': 'array', 'items': {'type': 'string'},
                                          'description': 'ISO codes, e.g. ["USD","EUR","CNY"]'}},
            'required': ['currencies'],
        },
    },
    {
        'name': 'get_weather',
        'description': 'Current weather and a daily forecast (up to 7 days) for a city.',
        'eager_input_streaming': True,
        'input_schema': {
            'type': 'object',
            'properties': {'city': {'type': 'string', 'description': 'City name, nominative case'},
                           'days': {'type': 'integer', 'minimum': 1, 'maximum': 7}},
            'required': ['city'],
        },
    },
    {
        'name': 'get_crypto_prices',
        'description': 'Current cryptocurrency prices in USD and RUB with 24h change (CoinGecko ids like bitcoin, ethereum).',
        'eager_input_streaming': True,
        'input_schema': {
            'type': 'object',
            'properties': {'coins': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['coins'],
        },
    },
]

# Модели, для которых включаем серверный резерв при отказе и web_search нового типа.
FALLBACK_MODELS = ('claude-opus-5', 'claude-fable-5-1')
NO_EFFORT_MODELS = ('claude-haiku-4-5',)


def system_prompt(settings):
    return SYSTEM_PROMPT.format(name=settings.get('wake_word') or 'Андрей',
                                style=STYLES.get(settings.get('answer_style'), STYLES['short']))


def run_custom_tool(tools, name, args):
    """Выполнить инструмент; вернуть (content, is_error)."""
    if not isinstance(args, dict):
        return json.dumps({'INVALID_JSON': str(args)}), True
    try:
        if name == 'get_exchange_rates':
            codes = args.get('currencies')
            if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
                return 'currencies must be a list of ISO codes', True
            data = tools.rates([c[:3] for c in codes[:10]])
            return json.dumps({'source': 'Central Bank of Russia', 'rub_per_unit': data}, ensure_ascii=False), False
        if name == 'get_weather':
            city = args.get('city')
            if not isinstance(city, str) or not city.strip():
                return 'city is required', True
            days = args.get('days', 3)
            days = days if isinstance(days, int) else 3
            place, data = tools.forecast(city.strip()[:80], days)
            return json.dumps({'city': place, 'current': data.get('current'), 'daily': data.get('daily'),
                               'units': 'celsius, wind m/s'}, ensure_ascii=False), False
        if name == 'get_crypto_prices':
            coins = args.get('coins')
            if not isinstance(coins, list) or not all(isinstance(c, str) for c in coins):
                return 'coins must be a list of ids', True
            from .tools import coin_id
            ids = [coin_id(c) or c.casefold() for c in coins[:10]]
            return json.dumps(tools.crypto(ids), ensure_ascii=False), False
    except Exception as exc:
        return 'Tool failed: ' + str(exc)[:300], True
    return 'Unknown tool', True


class ClaudeProvider:
    def __init__(self, api_key, tools):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2,
                                          timeout=anthropic.Timeout(90.0, connect=6.0))
        self.tools = tools

    def _params(self, settings, system, messages, max_tokens, with_tools):
        model = settings.get('llm_model') or 'claude-opus-5'
        params = dict(model=model, max_tokens=max_tokens, messages=messages,
                      system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}])
        if model not in NO_EFFORT_MODELS:
            params['output_config'] = {'effort': settings.get('llm_effort') or 'low'}
        if with_tools:
            tools = list(CUSTOM_TOOLS)
            if settings.get('llm_web_search', True):
                search_type = 'web_search_20250305' if model in NO_EFFORT_MODELS else 'web_search_20260209'
                tools.append({'type': search_type, 'name': 'web_search', 'max_uses': 3,
                              'user_location': {'type': 'approximate', 'country': 'RU',
                                                'city': (settings.get('city') or 'Москва')[:60]}})
            params['tools'] = tools
        if model in FALLBACK_MODELS:
            # При отказе классификатора запрос автоматически уходит на резервную модель.
            params['betas'] = ['server-side-fallback-2026-07-01']
            params['fallbacks'] = 'default'
        return params

    def stream(self, history, settings, on_text=None, system=None, max_tokens=8000, with_tools=True):
        anthropic = self.anthropic
        messages = [dict(m) for m in history]
        parts = []
        try:
            for _ in range(8):
                params = self._params(settings, system or system_prompt(settings), messages, max_tokens, with_tools)
                with self.client.beta.messages.stream(**params) as stream:
                    for event in stream:
                        if event.type == 'text':
                            parts.append(event.text)
                            if on_text:
                                on_text(event.text)
                    response = stream.get_final_message()
                if response.stop_reason == 'refusal':
                    return ''.join(parts) or 'Не могу ответить на этот вопрос.'
                if response.stop_reason == 'pause_turn':
                    messages.append({'role': 'assistant', 'content': response.content})
                    continue
                tool_uses = [b for b in response.content if b.type == 'tool_use']
                if response.stop_reason != 'tool_use' or not tool_uses:
                    break
                results = []
                for block in tool_uses:
                    content, is_error = run_custom_tool(self.tools, block.name, block.input)
                    results.append({'type': 'tool_result', 'tool_use_id': block.id,
                                    'content': content, 'is_error': is_error})
                messages.append({'role': 'assistant', 'content': response.content})
                messages.append({'role': 'user', 'content': results})
                if parts and not parts[-1].endswith((' ', '\n')):
                    parts.append(' ')
                    if on_text:
                        on_text(' ')
        except anthropic.AuthenticationError:
            raise LLMError('Ключ Anthropic API неверный. Проверьте его в Настройки → ИИ.')
        except anthropic.PermissionDeniedError:
            raise LLMError('У ключа Anthropic API нет доступа к выбранной модели.')
        except anthropic.NotFoundError:
            raise LLMError('Модель не найдена. Выберите другую в Настройки → ИИ.')
        except anthropic.RateLimitError:
            raise LLMError('Слишком много запросов к ИИ. Подождите немного.')
        except anthropic.APIStatusError as exc:
            raise LLMError(f'Сервис ИИ вернул ошибку {exc.status_code}. Повторите позже.')
        except anthropic.APIConnectionError:
            raise LLMError('Нет связи с сервисом ИИ. Проверьте интернет.')
        except ValueError:
            # Некорректный JSON во входе инструмента — такое бывает крайне редко.
            raise LLMError('ИИ прислал повреждённый ответ. Повторите вопрос.')
        return ''.join(parts).strip()


FRESH_HINTS = re.compile(
    r'сегодня|сейчас|завтра|вчера|новост|курс|цен[аы]|стоит|погод|счет матча|счёт|результат|кто выиграл|'
    r'202\d|последн|актуальн|свеж|расписани|когда выйдет|сколько лет|президент|премьер|акци[ия]|ставк', re.I)


class OpenAICompatibleProvider:
    """Ollama / LM Studio / OpenRouter / любой сервер с /v1/chat/completions."""

    def __init__(self, base_url, model, api_key, tools, session=None):
        if not base_url or not model:
            raise LLMError('Укажите адрес сервера и модель в Настройки → ИИ.')
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key = api_key
        self.tools = tools
        self._session = session

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _context(self, question, settings):
        if not settings.get('llm_web_search', True) or not FRESH_HINTS.search(question):
            return ''
        try:
            results = self.tools.web_search(question, 5)
        except Exception as exc:
            log.info('web search failed: %s', exc)
            return ''
        lines = [f"- {r['title']}: {r['snippet']}" for r in results if r.get('snippet')]
        return ('Web search results (use them for up-to-date facts):\n' + '\n'.join(lines)) if lines else ''

    def stream(self, history, settings, on_text=None, system=None, max_tokens=1500, with_tools=True):
        messages = [{'role': 'system', 'content': system or system_prompt(settings)}]
        for item in history:
            content = item['content'] if isinstance(item['content'], str) else str(item['content'])
            messages.append({'role': item['role'], 'content': content})
        if with_tools and history:
            context = self._context(history[-1]['content'], settings)
            if context:
                messages[-1]['content'] = context + '\n\nQuestion: ' + messages[-1]['content']
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        body = {'model': self.model, 'messages': messages, 'stream': True,
                'temperature': 0.3, 'max_tokens': max_tokens}
        parts = []
        think = ThinkFilter()
        try:
            response = self.session.post(self.base_url + '/chat/completions', json=body, headers=headers,
                                         stream=True, timeout=(5, 120))
        except Exception as exc:
            raise LLMError('Сервер ИИ недоступен: ' + str(exc)[:120])
        if response.status_code >= 400:
            raise LLMError(f'Сервер ИИ вернул ошибку {response.status_code}: {response.text[:160]}')
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
                    on_text(visible)
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
