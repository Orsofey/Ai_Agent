"""Command router: desktop control → apps/browser → small talk → quick facts → LLM."""
import re
import time
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
Видео и сайты: «Включи видео котики», «Пауза», «Останови фильм», «Поставь на паузу», «Продолжи», «Открой YouTube», «Найди рецепт борща».
Вопросы: «Какой курс доллара?», «100 евро в рублях», «Погода завтра в Казани», «Сколько будет 15% от 2000?», «Сколько белка нужно в день?», «Куда вложить 100 тысяч?».'''


# Глаголы-команды: вежливая форма «закройте» → «закрой».
COMMAND_VERBS = {
    'закрой', 'открой', 'запусти', 'включи', 'выключи', 'напиши', 'найди', 'отправь', 'сверни', 'разверни',
    'нажми', 'покажи', 'поставь', 'сделай', 'скажи', 'переведи', 'прочитай', 'выдели', 'скопируй', 'вставь',
    'удали', 'сотри', 'сохрани', 'отмени', 'останови', 'продолжи', 'напечатай', 'введи', 'набери', 'посчитай',
    'сочини', 'придумай', 'исправь', 'перескажи', 'обнови', 'прокрути', 'переключи', 'заблокируй', 'расскажи',
    'зайди', 'войди', 'перейди', 'подключись', 'присоединись', 'выйди', 'лайкни', 'отреагируй', 'ответь',
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


CHAT_ON = {'давай поболтаем', 'поболтаем', 'давай поговорим', 'поговори со мной', 'поболтай со мной',
           'режим болтовни', 'включи режим болтовни', 'давай просто поболтаем', 'давай просто поговорим',
           'хочу поболтать', 'режим поболтать', 'включи режим поболтать'}
CHAT_OFF = {'хватит болтать', 'закончим разговор', 'выключи режим болтовни', 'выйди из режима болтовни',
            'конец болтовни', 'хватит болтовни', 'закончим болтать', 'стоп болтовня', 'пока поболтали'}
CHAT_IDLE = 180  # секунд тишины — и беседа заканчивается сама

QUESTION_WORDS = ('как', 'что', 'кто', 'где', 'когда', 'почему', 'зачем', 'сколько', 'какой', 'какая', 'какое',
                  'какие', 'куда', 'откуда', 'чем', 'можно', 'нужно', 'стоит', 'посоветуй', 'расскажи', 'объясни',
                  'подскажи', 'what', 'who', 'how', 'why', 'when', 'where')


def looks_like_question(text):
    words = re.findall(r'\w+', text.casefold())
    return text.strip().endswith('?') or bool(words and words[0] in QUESTION_WORDS) or len(words) >= 6


def strip_wake(text, settings):
    wake = (settings or {}).get('wake_word', 'Андрей')
    return re.sub(r'^(?:эй\s+|ну\s+|слушай\s+)?' + re.escape(wake) + r'(?![\w])[\s,.:;!?—-]*', '', text, flags=re.I)


# Всё, что можно «поставить на паузу»: видео, фильм, музыка, плеер, воспроизведение…
# «всё/все» сюда не входят: «останови все» — это команда «стоп всему», а не пауза плеера.
MEDIA_WORDS = (r'(?:видео|фильм\w*|кино|ролик\w*|сериал\w*|мульт\w*|клип\w*|музык\w*|песн\w*|трек\w*|плеер\w*|'
               r'воспроизведени\w*|аудио)')
# «Останови фильм», «поставь на паузу», «пауза видео», «приостанови воспроизведение», «стоп фильм»…
PAUSE_RE = re.compile(
    r'^(?:пауза(?:\s+' + MEDIA_WORDS + r')?'
    r'|(?:останови|приостанови|остановить|приостановить|стоп|затормози)\s+(?:' + MEDIA_WORDS + r'|это)(?:\s+на\s+паузу)?'
    r'|(?:поставь|поставить)\s+' + MEDIA_WORDS + r'\s+на\s+паузу'
    r'|(?:поставь|поставить)\s+на\s+паузу(?:\s+' + MEDIA_WORDS + r')?'
    r'|(?:выключи|выключить|отключи)\s+' + MEDIA_WORDS + r''
    r')$', re.I)
# «Продолжи фильм», «возобнови воспроизведение», «сними с паузы», «сними видео с паузы»…
PLAY_RE = re.compile(
    r'^(?:(?:продолжи|возобнови|продолжить|возобновить)(?:\s+' + MEDIA_WORDS + r')?'
    r'|(?:сними|снять)\s+(?:' + MEDIA_WORDS + r'\s+)?с\s+паузы'
    r')$', re.I)


def parse_command(command, settings=None):
    settings = settings or {}
    text = re.sub(r'\s+', ' ', str(command)).strip().rstrip('.,!?…')
    text = strip_wake(text, settings)
    text = re.sub(r'^пожалуйста[, ]+', '', text, flags=re.I)
    lower = text.casefold()
    if lower in ('помощь', 'help', 'справка', 'что ты умеешь делать', 'список команд'):
        return 'help', ''
    # Пауза/продолжение — раньше всех: любые формулировки про плеер, фильм, видео, музыку.
    if PAUSE_RE.match(text):
        return 'pause', ''
    if PLAY_RE.match(text):
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
    def __init__(self, browser, brain=None, desktop_commands=None, integrations=None):
        self.browser = browser
        self.network = None    # src/network.Network: «отключись от сети» / «подключись к сети»
        self.brain = brain
        self.desktop_commands = desktop_commands
        self.integrations = integrations
        self.scenarios = None  # ScenarioManager: подключает app.py
        self.tracker = None    # TrackerClient: подключает app.py
        self.connectors = None # Connectors: Google, Яндекс, Microsoft, Notion, Todoist, Spotify, GitHub…
        self.reminders = None  # Reminders: подключает app.py
        self.power = None      # Power: выключение и перезагрузка ПК
        self.macros = None     # Macros: подключает app.py
        self.files = None      # FileStudy: подключает app.py
        # 6.0: документы в чате, мгновенный поиск, порядок в файлах, зрение, игры, заказы, умный дом, поддержка
        self.documents = None
        self.file_search = None
        self.doc_qa = None
        self.file_ops = None
        self.vision = None
        self.games = None
        self.booking = None
        self.smarthome = None
        self.support = None
        self.dialog = Dialog()
        self.chat_until = {}

    def awaiting(self, owner='default'):
        """Агент задал вопрос или идёт беседа — голос слушает следующую фразу без имени."""
        return self.dialog.awaiting(owner) is True or self.chatting(owner) \
            or bool(self.reminders is not None and self.reminders.awaiting(owner)) \
            or bool(self.power is not None and self.power.awaiting(owner)) \
            or bool(self.file_ops is not None and self.file_ops.awaiting(owner)) \
            or bool(self.smarthome is not None and self.smarthome.awaiting(owner))

    # ---- режим «поболтать» ----
    def chatting(self, owner='default'):
        return self.chat_until.get(owner, 0) > time.monotonic()

    def prepare(self, settings):
        """Услышали имя — пока человек договаривает команду, готовим нейросеть (если её выгрузили)."""
        warm = getattr(self.brain, 'warm', None)
        if warm is not None:
            try:
                warm(settings)
            except Exception:
                pass

    def _chat_toggle(self, text, owner, address):
        lower = re.sub(r'[.!?,]+', '', text.casefold().replace('ё', 'е')).strip()
        if lower in CHAT_ON:
            if self.brain is None:
                return 'Для разговора включите нейросеть в Настройки → ИИ.'
            self.chat_until[owner] = time.monotonic() + CHAT_IDLE
            return (f'С удовольствием, {address}. О чём поговорим?' if address else 'С удовольствием. О чём поговорим?')
        if lower in CHAT_OFF and self.chatting(owner):
            self.chat_until.pop(owner, None)
            return f'Хорошо, {address}. Было приятно поболтать.' if address else 'Хорошо. Было приятно поболтать.'
        return None

    def _is_command(self, text, settings):
        return self._is_known_command(text) or parse_command(text, settings)[0] not in ('unknown', 'search')

    def process_command(self, command, settings=None, owner='default', on_text=None):
        settings = settings or {}
        address = settings.get('address', 'сэр')
        address = '' if address == 'none' else address
        text = strip_wake(re.sub(r'\s+', ' ', str(command)).strip(), settings).strip()
        text = normalize_command(text).strip(' ,.')
        if not text:
            return f'Слушаю, {address}.' if address else 'Слушаю.'

        if self.network is not None:
            reply = self.network.handle(text)
            if reply is not None:
                return reply
            settings = self.network.settings(settings)
        try:
            return self._process(text, settings, owner, on_text, address)
        except ConnectionRefusedError as exc:
            from .network import MESSAGE, Offline
            if isinstance(exc, Offline):
                return MESSAGE
            raise

    def _process(self, text, settings, owner, on_text, address):
        toggled = self._chat_toggle(text, owner, address)
        if toggled is not None:
            return toggled
        if self.chatting(owner) and not self._is_command(text, settings):
            # Беседа: сразу в нейросеть, без разбора команд и уточняющих вопросов — быстро и коротко.
            self.chat_until[owner] = time.monotonic() + CHAT_IDLE
            try:
                return self.brain.answer(text, settings, owner=owner, on_text=on_text, mode='chat')
            except Exception as exc:
                return str(exc) or 'Не получилось ответить.'

        if self.power is not None:
            reply = self.power.handle(text, owner, settings)
            if reply is not None:
                return reply
        if self.reminders is not None:
            reply = self.reminders.handle(text, owner, settings)
            if reply is not None:
                return reply
        if self.macros is not None:
            reply = self.macros.handle(text, owner, settings)
            if reply is not None:
                return reply
            if self.macros.recording(owner):
                self.macros.record(owner, text)  # запись макроса: команда выполняется и запоминается
        reply = self._handle_60(text, owner, settings)
        if reply is not None:
            return reply
        if self.files is not None:
            reply = self.files.handle(text, owner, settings)
            if reply is not None:
                return reply
        for handler in (self.booking, self.smarthome):
            if handler is None:
                continue
            reply = handler.handle(text, owner) if handler is self.smarthome else handler.handle(text)
            if reply is not None:
                return reply

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

    def _handle_60(self, text, owner, settings):
        """Игры, поддержка, файлы (порядок, отправка, PDF), зрение, вопросы по документам, мгновенный поиск."""
        if self.smarthome is not None and self.smarthome.awaiting(owner):
            reply = self.smarthome.handle(text, owner)  # «да» на «перезагрузить роутер?»
            if reply is not None:
                return reply
        if self.connectors is not None:
            # Приложение названо прямо: «загрузи этот файл на Яндекс Диск», «добавь в Notion задачу…» —
            # раньше локальных файлов и Трекера, чтобы фразу не перехватили.
            try:
                reply = self.connectors.handle(text, named_only=True)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception('Connector failed')
                reply = f'Не получилось: {str(exc)[:160]}'
            if reply is not None:
                return reply
        steps = (
            (self.games, lambda h: h.handle(text)),
            (self.support, lambda h: h.handle(text)),
            (self.file_ops, lambda h: h.handle(text, owner, settings)),
            (self.documents, lambda h: h.handle(text)),
            (self.vision, lambda h: h.handle(text, settings)),
            (self.doc_qa, lambda h: h.handle(text, settings)),
            (self.file_search, lambda h: h.handle(text, owner)),
        )
        for handler, call in steps:
            if handler is None:
                continue
            try:
                reply = call(handler)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception('Handler failed')
                return f'Не получилось: {str(exc)[:160]}'
            if reply is not None:
                return reply
        return None

    def _music_request(self, text):
        from . import music
        from .app_control import RU_TO_EN, normalize
        request = music.parse(text, on_music_page=False)
        if request is not None:
            return request
        if music.parse(text, on_music_page=True) is None:
            return None  # не похоже на песню — браузер даже не спрашиваем
        try:
            url = self.browser.call('url') or ''
        except Exception:
            url = ''
        if not isinstance(url, str) or not any(m in url for m in ('music.yandex', 'music.youtube', 'open.spotify',
                                                                   'vk.com/audio', 'vk.com/music', 'zvuk.com', 'soundcloud')):
            return None
        request = music.parse(text, on_music_page=True)
        if request and request[0] == 'play':
            name = normalize(request[1])
            from . import sites, start_menu
            # «Включи Telegram» — программа, а не песня. Для меню «Пуск» нужно точное совпадение названия:
            # иначе группа «Кино» открыла бы приложение «Кино и ТВ».
            if name in RU_TO_EN or name in {v.casefold() for v in RU_TO_EN.values()} or sites.find(name, threshold=0.92) \
                    or start_menu.exact(name):
                return None
        return request

    def _media_key(self, action='play'):
        """Клавиша «Play/Pause» — работает с любым плеером: Spotify, Яндекс Музыка, браузер, VLC."""
        if self.desktop_commands is None:
            return 'Не нашёл плеер. Откройте музыкальный сервис и повторите.'
        try:
            self.desktop_commands.desktop.hotkey('media_play_pause')
        except Exception:
            return 'Не нашёл плеер. Откройте музыкальный сервис и повторите.'
        if action == 'pause':
            return 'Пауза.'
        if action == 'play':
            return 'Продолжаю воспроизведение.'
        return 'Запускаю плеер.'

    def _switch_to_open_site(self, text):
        from . import sites
        from .desktop.navigation import parse_site
        request = parse_site(text)
        if request is None:
            return None
        verb, name = request
        url = sites.find(name, threshold=0.9)
        if not url:
            return None
        go = verb in ('перейди', 'перейти', 'переключись', 'вернись')
        if not go:
            from .app_control import RU_TO_EN, normalize
            from . import start_menu
            key = normalize(name)
            if key in RU_TO_EN or key in {v.casefold() for v in RU_TO_EN.values()} or start_menu.exact(key):
                return None  # «Открой Steam» — программа, а не сайт
        bridge = getattr(self.browser, 'bridge', None)
        if bridge is not None and getattr(bridge, 'connected', False) is True:
            return self.browser.call('open', url)  # расширение само переключится на открытую вкладку
        if self.desktop_commands is not None:
            result = self.desktop_commands.switch_to_site(url, [name])
            if result:
                return result
        return self.browser.call('open', url) if go else None

    @staticmethod
    def _discord_without_server(text):
        from .desktop.messengers import parse_discord
        request = parse_discord(text)
        return request is not None and not request['server']

    def _is_known_command(self, text):
        from .desktop.commands import parse as desktop_parse
        from . import display, music, scenarios, sites
        from .desktop.navigation import parse_site
        from .tracker import parse as tracker_parse
        site = parse_site(text)
        return desktop_parse(text) is not None or youtube_command(text) is not None or music.parse(text) is not None \
            or (site is not None and sites.find(site[1], threshold=0.9) is not None) \
            or display.parse(text) is not None or scenarios.parse(text) is not None \
            or (self.tracker is not None and tracker_parse(text) is not None) \
            or bool(PAUSE_RE.match(text)) or bool(PLAY_RE.match(text))

    def _route(self, text, settings, owner, on_text):
        """Выполнить команду. Вернуть (текст, вид): action — действие, info — ответ."""
        # 1. Действия в активном приложении (печать текста, клавиши, окна, мессенджеры).
        if self.desktop_commands is not None:
            result = self.desktop_commands.handle(text, settings)
            if result is not None:
                return result, 'action'

        # 1а. Чёрно-белый экран, сценарии («Работа», «Игра») и блокировка сайтов/приложений на время.
        from . import display
        grayscale = display.parse(text)
        if grayscale is not None:
            return display.set_grayscale(grayscale), 'action'
        if self.scenarios is not None:
            result = self.scenarios.handle(text)
            if result is not None:
                return result, 'action'

        # 1б. Интеграции с другими приложениями (папка integrations).
        if self.integrations is not None:
            result = self.integrations.handle(text, settings)
            if result is not None:
                return result, 'info'

        # 1в. Трекер (онлайн, аккаунт пользователя): «что в трекере на сегодня», «добавь в трекер …».
        if self.tracker is not None:
            result = self.tracker.handle(text)
            if result is not None:
                return result, 'info'

        # 1г. Подключённые приложения: календари, почта, задачи, облака, CRM, Spotify, GitHub, Google…
        if self.connectors is not None:
            result = self.connectors.handle(text)
            if result is not None:
                return result, 'action'

        # 2. Видео на YouTube в том же окне: «открой первое видео», «найди на ютубе…».
        yt = youtube_command(text)
        if yt is not None:
            return self.browser.call('youtube', *yt), 'action'

        # 3. Музыка: «Включи Imagine Dragons» на открытом музыкальном сервисе, «Запусти плеер».
        from . import sites
        music_request = self._music_request(text)
        if music_request is not None:
            if music_request[0] == 'player':
                result = self.browser.call('player')
                if not result or result.startswith(('Не нашёл', 'Браузер')):
                    result = self._media_key()
                return result, 'action'
            return self.browser.call('music', music_request[1], music_request[2]), 'action'

        # 4. «Открой в браузере Claude Code», «открой в Яндекс Браузере YouTube».
        request = sites.parse(text)
        if request:
            bridge = getattr(self.browser, 'bridge', None)
            if bridge is not None and getattr(bridge, 'connected', False) is True and bridge.matches(request['browser']):
                # Браузер пользователя уже открыт и подключён: открываем там (или переключаемся на вкладку).
                return self.browser.call('open', sites.resolve(request['site'])), 'action'
            return sites.open_site(request['site'], request['browser']), 'action'

        # 4б. «Перейди в ютуб», «открой ютуб»: сайт уже открыт — переключаемся на его вкладку.
        switched = self._switch_to_open_site(text)
        if switched is not None:
            return switched, 'action'

        # 5. Сервисы и браузер.
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
            result = launch(value)
            if result.startswith('Приложение не найдено') and sites.find(value):
                return sites.open_site(value), 'action'  # «Открой Claude Code» — такой программы нет, есть сайт
            return result, 'action'
        if action == 'close_app':
            result = close_application(value)
            url = sites.find(value)
            if url and ('не запущено' in result or result.startswith('Не удалось')):
                # «Закрой YouTube» — это вкладка, а не программа.
                closed = self.browser.call('close_site', url)
                if closed:
                    return closed, 'action'
                if self.desktop_commands is not None:
                    closed = self.desktop_commands.close_browser_tab([value] + sites.SITES.get(url, []))
                    if closed:
                        return closed, 'action'
            return result, 'action'
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
            # Сначала — плеер на вкладке браузера; если его нет, ставим на паузу любой
            # запущенный плеер системной медиаклавишей (VLC, Spotify, «Кино и ТВ»…).
            result = self.browser.call('media', action)
            if not isinstance(result, str) or result.startswith(('Не нашёл', 'Браузер')) \
                    or 'нет управляемых вкладок' in result.casefold():
                result = self._media_key(action)
            return result, 'action'
        if action in ('close_tab', 'close_browser', 'tabs'):
            return self.browser.call(action), 'action'

        # 5. Любой вопрос: точные данные (курсы, погода, калькулятор) или ИИ.
        question = value if action == 'search' else text
        if self.brain is not None:
            from .brain import LLMError
            parts = [self.integrations.context(question, settings) if self.integrations is not None else None,
                     self.tracker.context(question) if self.tracker is not None else None]
            extra = '\n\n'.join(p for p in parts if p) or None
            prompt = f'{question}\n\n{extra}\n\nОтвечай по этим данным.' if extra else question
            try:
                answer = self.brain.answer(prompt, settings, owner=owner, on_text=on_text)
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
