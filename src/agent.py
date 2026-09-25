"""Command router: desktop control → apps/browser → small talk → quick facts → LLM."""
import re
from urllib.parse import quote

import psutil

from .app_control import launch, close_application
from .conversation import match_casual
from .dialog import (Dialog, butler, incomplete_verb, misheard_command, question_for_confirm,
                     question_for_object)
from .youtube import youtube_command

HELP = '''Я понимаю команды и отвечаю на вопросы. Обращайтесь по имени, например: «Андрей, …».
В любом приложении: «Напиши текст привет, Милана», «Напиши и отправь …», «Отправь», «Новая строка», «Сотри слово», «Выдели всё», «Скопируй», «Вставь», «Сохрани», «Нажми Ctrl+Shift+T».
Мессенджеры: «Напиши Милане в Телеграме привет», «Отправь маме в WhatsApp я выхожу».
Текст с ИИ: «Сочини поздравление для Миланы», «Переведи выделенное на английский», «Исправь ошибки», «Прочитай выделенное».
Диктовка: «Начни диктовку» … «Стоп диктовка».
Окна и звук: «Сверни окно», «Разверни окно», «Закрой окно», «Покажи рабочий стол», «Громче», «Тише», «Следующий трек», «Сделай скриншот».
Приложения: «Открой калькулятор», «Запусти Telegram», «Закрой Chrome».
Видео и сайты: «Включи видео котики», «Пауза видео», «Открой YouTube», «Найди рецепт борща».
Вопросы: «Какой курс доллара?», «100 евро в рублях», «Погода завтра в Казани», «Сколько будет 15% от 2000?», «Сколько белка нужно в день?», «Куда вложить 100 тысяч?».'''


# Глаголы-команды: вежливая форма «закройте» → «закрой».
COMMAND_VERBS = {
    'закрой', 'открой', 'запусти', 'включи', 'выключи', 'напиши', 'найди', 'отправь', 'сверни', 'разверни',
    'нажми', 'покажи', 'поставь', 'сделай', 'скажи', 'переведи', 'прочитай', 'выдели', 'скопируй', 'вставь',
    'удали', 'сотри', 'сохрани', 'отмени', 'останови', 'продолжи', 'напечатай', 'введи', 'набери', 'посчитай',
    'сочини', 'придумай', 'исправь', 'перескажи', 'обнови', 'прокрути', 'переключи', 'заблокируй', 'расскажи',
}
CLOSABLE = r'(?:браузер|окно|вкладку|программу|приложение|телеграм\w*|ворд|хром|видео|музыку)'
# Частые ошибки распознавания начала команды.
MISHEARD = [(r'^(?:забудь(?:те)?|забей(?:те)?|закрою|закрыть|за\s?крой)\s+(?=' + CLOSABLE + r')', 'закрой '),
            (r'^(?:открою|открыть|от\s?крой)\s+', 'открой ')]


def normalize_command(text):
    """«Закройте браузер» → «закрой браузер», «забудьте браузер» → «закрой браузер»."""
    value = text.strip()
    match = re.match(r'^(\w+?)(?:(й|ь)те|(и)те)(?=\W|$)', value, re.I)
    if match:
        base = match[1] + (match[2] or match[3])
        if base.casefold() in COMMAND_VERBS:
            value = base + value[match.end():]
    for pattern, replacement in MISHEARD:
        value = re.sub(pattern, replacement, value, count=1, flags=re.I)
    value = re.sub(r'^пожалуйста[,\s]+', '', value, flags=re.I)
    return re.sub(r'[,\s]+пожалуйста$', '', value, flags=re.I)


QUESTION_WORDS = ('как', 'что', 'кто', 'где', 'когда', 'почему', 'зачем', 'сколько', 'какой', 'какая', 'какое',
                  'какие', 'куда', 'откуда', 'чем', 'можно', 'нужно', 'стоит', 'посоветуй', 'расскажи', 'объясни',
                  'подскажи', 'what', 'who', 'how', 'why', 'when', 'where')


def looks_like_question(text):
    words = re.findall(r'\w+', text.casefold())
    return text.strip().endswith('?') or bool(words and words[0] in QUESTION_WORDS) or len(words) >= 6


def strip_wake(text, settings):
    wake = (settings or {}).get('wake_word', 'Андрей')
    return re.sub(r'^(?:эй\s+|ну\s+|слушай\s+)?' + re.escape(wake) + r'(?![\w])[\s,.:;!?—-]*', '', text, flags=re.I)


def parse_command(command, settings=None):
    settings = settings or {}
    text = re.sub(r'\s+', ' ', str(command)).strip().rstrip('.,!?…')
    text = strip_wake(text, settings)
    text = re.sub(r'^пожалуйста[, ]+', '', text, flags=re.I)
    lower = text.casefold()
    if lower in ('помощь', 'help', 'справка', 'что ты умеешь делать', 'список команд'):
        return 'help', ''
    if lower in ('пауза', 'пауза видео', 'останови видео', 'приостанови видео', 'поставь на паузу', 'поставь видео на паузу'):
        return 'pause', ''
    if lower in ('продолжи', 'продолжи видео', 'возобнови видео', 'сними с паузы'):
        return 'play', ''
    if lower in ('закрой вкладку', 'закрыть вкладку', 'закрой текущую вкладку', 'закрой видео'):
        return 'close_tab', ''
    if lower in ('закрой браузер агента', 'закрой все вкладки агента'):
        return 'close_browser', ''
    if lower in ('список вкладок', 'покажи вкладки'):
        return 'tabs', ''
    if lower in ('информация о системе', 'система', 'нагрузка', 'нагрузка на компьютер'):
        return 'system', ''
    match = re.match(r'^(?:закрой|закрыть|выключи|close|quit)\s+(.+)$', text, re.I)
    if match:
        target = match[1]
        if target.casefold() in ('все', 'всё', 'все приложения', 'все окна', 'компьютер', 'пк'):
            return 'refuse_mass', ''
        return 'close_app', target
    match = re.match(r'^(?:открой|включи|запусти|покажи|найди)\s+(?:видео|ролик|песню|клип|фильм)\s+(.+)$', text, re.I)
    if match:
        return 'video', match[1]
    match = re.match(r'^(?:открой\s+)?(?:ютуб|youtube)\s+и\s+(?:найди|включи|запусти)\s+(?:видео\s+|песню\s+)?(.+)$', text, re.I)
    if match:
        return 'video', match[1] + ' на youtube'
    match = re.match(r'^(?:открой|открыть|запусти|включи|open|launch)\s+(.+)$', text, re.I)
    if match:
        value = re.sub(r'^сайт\s+', '', match[1], flags=re.I)
        if re.match(r'^https?://', value, re.I):
            return 'open_url', value
        if value.casefold() in ('ютуб', 'youtube'):
            return 'open_url', 'https://www.youtube.com'
        if value.casefold() in ('рутуб', 'rutube'):
            return 'open_url', 'https://rutube.ru'
        if value.casefold() in ('браузер', 'браузер агента'):
            return 'open_url', 'https://ya.ru'
        return 'open_app', value
    match = re.match(r'^(?:найди в интернете|найди в гугле|поищи|загугли|поиск)\s+(.+)$', text, re.I)
    if match:
        return 'open_url', 'https://www.google.com/search?q=' + quote(match[1])
    match = re.match(r'^найди\s+(.+)$', text, re.I)
    if match:
        return 'search', match[1]
    return 'unknown', text


class LocalComputerAgent:
    def __init__(self, browser, brain=None, desktop_commands=None):
        self.browser = browser
        self.brain = brain
        self.desktop_commands = desktop_commands
        self.dialog = Dialog()

    def awaiting(self, owner='default'):
        """Агент задал вопрос и ждёт ответа (голос слушает без имени)."""
        return self.dialog.awaiting(owner)

    def process_command(self, command, settings=None, owner='default', on_text=None):
        settings = settings or {}
        address = settings.get('address', 'сэр')
        address = '' if address == 'none' else address
        text = strip_wake(re.sub(r'\s+', ' ', str(command)).strip(), settings).strip()
        text = normalize_command(text).strip(' ,.')
        if not text:
            return f'Слушаю, {address}.' if address else 'Слушаю.'

        # Ответ на уточняющий вопрос агента: «Что открыть, сэр?» → «Телеграм».
        kind, value = self.dialog.resolve(owner, text, COMMAND_VERBS)
        if kind == 'reply':
            return f'Хорошо, {address}, отменяю.' if address else 'Хорошо, отменяю.'
        if kind == 'run':
            text = value
        elif self._discord_without_server(text):
            self.dialog.set(owner, 'object', 'зайди на дискорд сервер')
            return f'На какой сервер Discord зайти, {address}?' if address else 'На какой сервер Discord зайти?'
        elif not self._is_known_command(text):
            verb = incomplete_verb(text)
            if verb:
                self.dialog.set(owner, 'object', verb)
                return question_for_object(verb, address)
            if not looks_like_question(text):
                fixed = misheard_command(text, COMMAND_VERBS)
                if fixed:
                    self.dialog.set(owner, 'confirm', fixed)
                    return question_for_confirm(fixed, address)

        result, kind = self._route(text, settings, owner, on_text)
        if kind == 'action' and settings.get('butler', True):
            return butler(result, text, address)
        return result

    @staticmethod
    def _discord_without_server(text):
        from .desktop.messengers import parse_discord
        request = parse_discord(text)
        return request is not None and not request['server']

    def _is_known_command(self, text):
        from .desktop.commands import parse as desktop_parse
        return desktop_parse(text) is not None or youtube_command(text) is not None

    def _route(self, text, settings, owner, on_text):
        """Выполнить команду. Вернуть (текст, вид): action — действие, info — ответ."""
        # 1. Действия в активном приложении (печать текста, клавиши, окна, мессенджеры).
        if self.desktop_commands is not None:
            result = self.desktop_commands.handle(text, settings)
            if result is not None:
                return result, 'action'

        # 2. Видео на YouTube в том же окне: «открой первое видео», «найди на ютубе…».
        yt = youtube_command(text)
        if yt is not None:
            return self.browser.call('youtube', *yt), 'action'

        # 3. Сервисы и браузер.
        from .assistant_commands import handle, HELP_EXTRA
        extra = handle(self, text, settings)
        if extra is not None:
            return extra, 'action'

        # 4. Разговор: приветствия, время, дата — мгновенно и офлайн.
        casual, answer = match_casual(text)
        if casual:
            return answer, 'info'

        action, value = parse_command(text, settings)
        if action == 'help':
            return HELP + HELP_EXTRA, 'info'
        if action == 'system':
            return f'Процессор загружен на {psutil.cpu_percent(interval=0.2):.0f}%, память — на {psutil.virtual_memory().percent:.0f}%.', 'info'
        if action == 'refuse_mass':
            return 'Массовое закрытие отключено для защиты несохранённых данных. Назовите конкретное приложение.', 'action'
        if action == 'open_app':
            return launch(value), 'action'
        if action == 'close_app':
            return close_application(value), 'action'
        if action == 'open_url':
            return self.browser.call('open', value), 'action'
        if action == 'video':
            source = settings.get('video_source', 'youtube')
            match = re.search(r'\s+(?:на|в)\s+(ютубе?|youtube|рутубе?|rutube)$', value, re.I)
            if match:
                source = 'rutube' if match[1].casefold().startswith(('рутуб', 'rutube')) else 'youtube'
                value = value[:match.start()].strip()
            if not value:
                return 'Укажите название или ссылку на видео.', 'action'
            return self.browser.call('video', value, source), 'action'
        if action in ('pause', 'play'):
            return self.browser.call('media', action), 'action'
        if action in ('close_tab', 'close_browser', 'tabs'):
            return self.browser.call(action), 'action'

        # 5. Любой вопрос: точные данные (курсы, погода, калькулятор) или ИИ.
        question = value if action == 'search' else text
        if self.brain is not None:
            from .brain import LLMError
            try:
                answer = self.brain.answer(question, settings, owner=owner, on_text=on_text)
            except LLMError as exc:
                answer = None
                error = str(exc)
            else:
                error = None
            if answer:
                return answer, 'info'
            if action == 'search':
                return self.browser.call('open', 'https://www.google.com/search?q=' + quote(value)), 'action'
            if error:
                if looks_like_question(question):
                    return error, 'info'
                # Нейросеть недоступна, а фраза похожа на команду — не пугаем техническими ошибками.
                return f'Не понял команду «{question}». Скажите «помощь», чтобы услышать примеры.', 'info'
        elif action == 'search':
            return self.browser.call('open', 'https://www.google.com/search?q=' + quote(value)), 'action'
        return 'Не понял команду. Скажите «помощь», чтобы услышать примеры.', 'info'
