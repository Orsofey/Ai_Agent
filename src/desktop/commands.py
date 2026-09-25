"""Universal voice commands that act on the active window of ANY application.

parse() — чистая функция (тестируется без Windows), execute() — выполнение.
"""
import re
import time

from . import messengers
from .winapi import DesktopUnavailable

# Фраза → сочетание клавиш.
KEY_PHRASES = {
    ('выдели всё', 'выдели все', 'выдели весь текст', 'выделить всё', 'выбери всё', 'выдели текст', 'выделить текст',
     'выдели весь', 'выдели это', 'выдели', 'выдели все текст', 'выделить весь текст', 'выделить все'): ('ctrl', 'a'),
    ('скопируй', 'скопируй текст', 'скопируй выделенное', 'копировать'): ('ctrl', 'c'),
    ('вставь', 'вставь текст', 'вставить'): ('ctrl', 'v'),
    ('вырежи', 'вырежи текст', 'вырезать'): ('ctrl', 'x'),
    ('отмени', 'отмени действие', 'отменить', 'отмена'): ('ctrl', 'z'),
    ('повтори действие', 'верни действие', 'верни как было'): ('ctrl', 'y'),
    ('сохрани', 'сохрани документ', 'сохрани файл', 'сохранить'): ('ctrl', 's'),
    ('распечатай', 'печать', 'напечатай документ'): ('ctrl', 'p'),
    ('жирный', 'сделай жирным', 'жирный шрифт'): ('ctrl', 'b'),
    ('курсив', 'сделай курсивом'): ('ctrl', 'i'),
    ('подчеркни', 'подчеркнуть', 'сделай подчёркнутым'): ('ctrl', 'u'),
    ('новая вкладка', 'открой новую вкладку'): ('ctrl', 't'),
    ('обнови', 'обнови страницу', 'перезагрузи страницу'): ('f5',),
    ('назад', 'вернись назад', 'страница назад'): ('alt', 'left'),
    ('вперёд', 'вперед', 'страница вперёд'): ('alt', 'right'),
    ('нажми enter', 'нажми ввод', 'нажми энтер', 'энтер'): ('enter',),
    ('сотри слово', 'удали слово', 'удали последнее слово', 'стереть слово'): ('ctrl', 'backspace'),
    ('сотри', 'сотри букву', 'удали букву', 'удали символ'): ('backspace',),
    ('удали выделенное', 'удали выделенный текст', 'удали текст'): ('delete',),
    ('прокрути вниз', 'листай вниз', 'пролистай вниз', 'ниже'): ('pagedown',),
    ('прокрути вверх', 'листай вверх', 'пролистай вверх', 'выше'): ('pageup',),
    ('в начало', 'в начало документа', 'в самое начало'): ('ctrl', 'home'),
    ('в конец', 'в конец документа', 'в самый конец'): ('ctrl', 'end'),
    ('переключи окно', 'следующее окно', 'другое окно', 'предыдущее окно'): ('alt', 'tab'),
    ('покажи рабочий стол', 'сверни все окна', 'сверни всё', 'сверни все'): ('win', 'd'),
    ('выключи звук', 'без звука', 'включи звук', 'убери звук'): ('volume_mute',),
    ('следующий трек', 'следующая песня', 'переключи трек', 'следующую песню'): ('media_next',),
    ('предыдущий трек', 'предыдущая песня', 'прошлая песня'): ('media_prev',),
    ('пауза музыки', 'останови музыку', 'продолжи музыку', 'поставь музыку на паузу'): ('media_play_pause',),
    ('закрой вкладку в браузере',): ('ctrl', 'w'),
    ('полный экран', 'во весь экран'): ('f11',),
}
# «Отправь сообщение» — отправить уже набранный черновик в открытом чате.
SEND_DRAFT = {'отправь', 'отправить', 'отправь сообщение', 'отправить сообщение', 'отправь это', 'отправляй',
              'отправь черновик', 'отправь текст', 'отправь его', 'отправь в чат', 'да отправь', 'отсылай', 'отправь пожалуйста'}

_KEY_MAP = {phrase: keys for phrases, keys in KEY_PHRASES.items() for phrase in phrases}

REPEAT_PHRASES = {
    ('громче', 'сделай громче', 'прибавь звук', 'погромче'): ('volume_up', 5),
    ('тише', 'сделай тише', 'убавь звук', 'потише'): ('volume_down', 5),
}
_REPEAT_MAP = {phrase: value for phrases, value in REPEAT_PHRASES.items() for phrase in phrases}

WINDOW_PHRASES = {
    ('закрой окно', 'закрой это окно', 'закрой текущее окно', 'закрой программу'): 'close',
    ('сверни окно', 'сверни', 'сверни это окно'): 'minimize',
    ('разверни окно', 'разверни', 'разверни на весь экран', 'на весь экран'): 'maximize',
    ('восстанови окно',): 'restore',
}
_WINDOW_MAP = {phrase: value for phrases, value in WINDOW_PHRASES.items() for phrase in phrases}

KEY_WORDS = {
    'контрол': 'ctrl', 'контроль': 'ctrl', 'ctrl': 'ctrl', 'control': 'ctrl', 'кнтрл': 'ctrl',
    'шифт': 'shift', 'shift': 'shift', 'альт': 'alt', 'alt': 'alt', 'вин': 'win', 'win': 'win',
    'виндовс': 'win', 'windows': 'win', 'энтер': 'enter', 'ввод': 'enter', 'enter': 'enter',
    'эскейп': 'esc', 'escape': 'esc', 'esc': 'esc', 'эск': 'esc', 'таб': 'tab', 'tab': 'tab',
    'пробел': 'space', 'space': 'space', 'делит': 'delete', 'delete': 'delete', 'удалить': 'delete',
    'бэкспейс': 'backspace', 'backspace': 'backspace', 'вниз': 'down', 'вверх': 'up',
    'влево': 'left', 'вправо': 'right', 'home': 'home', 'хоум': 'home', 'end': 'end', 'энд': 'end',
    'си': 'c', 'вэ': 'v', 'ви': 'v', 'икс': 'x', 'зет': 'z', 'эс': 's', 'а': 'a', 'эф': 'f',
    'ти': 't', 'дабл ю': 'w', 'эн': 'n', 'пи': 'p', 'эр': 'r', 'игрек': 'y', 'би': 'b', 'ай': 'i',
}

PUNCTUATION = [
    (r'\s*\b(?:запятая)\b', ','), (r'\s*\b(?:точка с запятой)\b', ';'),
    (r'\s*\b(?:вопросительный знак)\b', '?'), (r'\s*\b(?:восклицательный знак)\b', '!'),
    (r'\s*\b(?:двоеточие)\b', ':'), (r'\s*\b(?:многоточие)\b', '…'), (r'\s*\b(?:точка)\b', '.'),
    (r'\s*\b(?:тире)\b', ' —'), (r'\s*\b(?:новая строка|с новой строки|новый абзац)\b\s*', '\n'),
    (r'\b(?:открой скобку|открыть скобку)\b\s*', '('), (r'\s*\b(?:закрой скобку|закрыть скобку)\b', ')'),
    (r'\b(?:смайлик)\b', '🙂'),
]

LANGUAGES = {
    'английский': 'English', 'английском': 'English', 'русский': 'Russian', 'немецкий': 'German',
    'французский': 'French', 'испанский': 'Spanish', 'итальянский': 'Italian', 'китайский': 'Chinese',
    'украинский': 'Ukrainian', 'турецкий': 'Turkish', 'японский': 'Japanese',
}

GENERATE_KINDS = r'письмо|поздравление|стих\w*|сочинение|пост|отзыв|резюме|статью|эссе|рассказ|ответ|объявление|заявление|текст песни|сообщение с поздравлением'


def clean(text):
    return re.sub(r'\s+', ' ', str(text)).strip().strip('.,!?…').strip()


def apply_punctuation(text):
    value = str(text)
    for pattern, replacement in PUNCTUATION:
        value = re.sub(pattern, replacement, value, flags=re.I)
    value = re.sub(r'([,.;:!?…])(?=[^\s\n\d)])', r'\1 ', value)
    return value.strip(' ')


def tidy_typed(text):
    """Текст для ввода: без лишней точки в конце короткой фразы."""
    value = apply_punctuation(str(text).strip().lstrip(':,-— '))
    if value.endswith('.') and value.count('.') == 1 and not value.endswith('..'):
        value = value[:-1]
    return value


def parse_keys(spec):
    spec = spec.casefold().replace('+', ' плюс ')
    parts = [p.strip() for p in re.split(r'\s+плюс\s+|\s+и\s+', spec) if p.strip()]
    if len(parts) == 1:
        parts = parts[0].split()
    keys = []
    for part in parts:
        if re.fullmatch(r'(?:f|эф)\s*(\d{1,2})', part):
            keys.append('f' + re.fullmatch(r'(?:f|эф)\s*(\d{1,2})', part)[1])
        elif part in KEY_WORDS:
            keys.append(KEY_WORDS[part])
        elif re.fullmatch(r'[a-z0-9]', part):
            keys.append(part)
        elif re.fullmatch(r'стрелк[уа]\s+(\w+)', part):
            word = re.fullmatch(r'стрелк[уа]\s+(\w+)', part)[1]
            keys.append(KEY_WORDS.get(word, word))
        else:
            return None
    return keys or None


def parse(text):
    """Разобрать команду. Вернуть (action, args) или None."""
    raw = re.sub(r'\s+', ' ', str(text)).strip()
    lower = clean(raw).casefold().replace('ё', 'е')
    lower_yo = clean(raw).casefold()

    for candidate in (lower_yo, lower):
        if candidate in _KEY_MAP:
            return 'keys', {'keys': _KEY_MAP[candidate], 'times': 1}
        if candidate in _REPEAT_MAP:
            key, times = _REPEAT_MAP[candidate]
            return 'keys', {'keys': (key,), 'times': times}
        if candidate in _WINDOW_MAP:
            return 'window', {'action': _WINDOW_MAP[candidate]}

    if lower in ('новая строка', 'с новой строки', 'абзац', 'новый абзац'):
        return 'newline', {}
    if lower in ('очисти поле', 'удали все', 'сотри все', 'очисти все'):
        return 'clear', {}
    if lower in ('закрой вкладку', 'закрыть вкладку', 'закрой текущую вкладку'):
        return 'close_tab', {}
    if lower in ('сделай скриншот', 'скриншот', 'снимок экрана', 'сфотографируй экран'):
        return 'screenshot', {}
    if lower in ('заблокируй компьютер', 'заблокируй экран', 'заблокируй пк'):
        return 'lock', {}
    if lower in ('начни диктовку', 'режим диктовки', 'диктовка', 'включи диктовку'):
        return 'dictation', {'on': True}
    if lower in ('стоп диктовка', 'закончи диктовку', 'выключи диктовку', 'останови диктовку', 'конец диктовки'):
        return 'dictation', {'on': False}
    if lower in ('где я', 'какое окно активно', 'какая программа открыта'):
        return 'where', {}

    m = re.match(r'^(?:громче|тише)\s+на\s+(\d+)$', lower)
    if m:
        return 'keys', {'keys': ('volume_up' if lower.startswith('громче') else 'volume_down',), 'times': int(m[1])}

    m = re.match(r'^(?:нажми|нажать|press)\s+(.+?)(?:\s+(\d+)\s+раз[а]?)?$', lower)
    if m:
        keys = parse_keys(m[1])
        if keys:
            return 'keys', {'keys': tuple(keys), 'times': int(m[2] or 1)}

    # Чтение и обработка выделенного текста в любом приложении.
    if re.match(r'^(?:прочитай|прочти|озвучь)\s+(?:выделенное|выделенный текст|вслух|это)', lower):
        return 'selection', {'mode': 'read'}
    m = re.match(r'^переведи\s+(?:выделенное|выделенный текст|это|текст)(?:\s+на\s+(\w+))?', lower)
    if m:
        return 'selection', {'mode': 'translate', 'language': LANGUAGES.get(m[1] or '', 'auto')}
    if re.match(r'^(?:исправь ошибки|проверь орфографию|исправь текст|исправь выделенное|исправь)(?:\s|$)', lower):
        return 'selection', {'mode': 'fix'}
    if re.match(r'^(?:перескажи|кратко перескажи|сократи|сделай выжимку)(?:\s+(?:выделенное|выделенный текст|это|текст))?$', lower):
        return 'selection', {'mode': 'summary'}
    if re.match(r'^(?:улучши|перепиши|сделай красивее)(?:\s+(?:выделенное|выделенный текст|это|текст))?$', lower):
        return 'selection', {'mode': 'improve'}

    m = re.match(r'^найди на странице\s+(.+)$', raw, re.I)
    if m:
        return 'find', {'text': clean(m[1])}

    request = messengers.parse(raw)
    if request:
        return 'messenger', request
    if lower in SEND_DRAFT:
        return 'send_draft', {}
    request = messengers.parse_voice_channel(raw)
    if request is not None:
        return 'discord_voice', request
    request = messengers.parse_discord_toggle(raw)
    if request is not None:
        return 'discord_toggle', request
    request = messengers.parse_reaction(raw)
    if request is not None:
        return 'reaction', request
    request = messengers.parse_discord(raw)
    if request is not None:
        return 'discord_server', request
    request = messengers.parse_open(raw)
    if request:
        return 'open_chat', request
    request = messengers.parse_current(raw)
    if request:
        return 'chat_type', request

    m = re.match(r'^(?:сочини|придумай|составь|сгенерируй)\s+(.+)$', raw, re.I | re.S)
    if m:
        return 'generate', {'prompt': m[0]}
    m = re.match(r'^напиши\s+(?:мне\s+)?(?:' + GENERATE_KINDS + r')\b.*$', raw, re.I | re.S)
    if m:
        return 'generate', {'prompt': m[0]}

    m = re.match(r'^(?:напиши|набери)\s+и\s+отправь\s+(?:текст\s+|сообщение\s+)?(.+)$', raw, re.I | re.S)
    if m:
        return 'type', {'text': tidy_typed(m[1]), 'send': True}
    m = re.match(r'^отправь\s+(?:сообщение|текст)\s+(.+)$', raw, re.I | re.S)
    if m:
        return 'type', {'text': tidy_typed(m[1]), 'send': True}
    m = re.match(r'^(?:напиши|напечатай|введи|набери|впиши|вбей)(?:\s+(?:текст|фразу|слово|слова|сообщение))?\s*[:,\-—]?\s+(.+)$', raw, re.I | re.S)
    if m:
        return 'type', {'text': tidy_typed(m[1]), 'send': False}
    return None


SELECTION_TASKS = {
    'translate': 'Translate the text to {language}. If it is already in that language, translate it to Russian. Output only the translation.',
    'fix': 'Fix spelling, grammar and punctuation. Keep the language, meaning and formatting. Output only the corrected text.',
    'summary': 'Summarize the text in 2-3 short sentences in the language of the text, for reading aloud.',
    'improve': 'Rewrite the text to be clearer and more polished. Keep the language and meaning. Output only the new text.',
}


class DesktopCommands:
    """Выполняет команды из parse(). brain нужен для ИИ-действий с текстом."""

    def __init__(self, desktop, brain=None, browser=None, root=None):
        self.desktop = desktop
        self.brain = brain
        self.browser = browser
        self.root = root
        self.dictation = False
        self.chat = None  # открытый голосом чат: dict(app, who)

    def handle(self, text, settings):
        parsed = parse(text)
        if not parsed:
            return None
        action, args = parsed
        try:
            return self.execute(action, args, settings)
        except DesktopUnavailable as exc:
            if action == 'close_tab':
                return None  # пусть закроет вкладку браузер агента
            return str(exc)

    def close_browser_tab(self, names):
        """«Закрой YouTube» в обычном браузере: Ctrl+W, если в заголовке активной вкладки есть название сайта."""
        from .controller import BROWSER_PROCESSES
        try:
            title, process = self.desktop.target_title()
        except Exception:
            return None
        title = (title or '').casefold()
        name = next((n for n in names if n and n.casefold() in title), None)
        if process not in BROWSER_PROCESSES or not name:
            return None
        self.desktop.hotkey('ctrl', 'w')
        return 'Закрываю вкладку ' + name + '.'

    def execute(self, action, args, settings):
        d = self.desktop
        if not getattr(d, 'available', True):
            raise DesktopUnavailable('Управление другими приложениями доступно на Windows.')
        method = settings.get('type_method', 'auto')
        if action == 'keys':
            d.hotkey(*args['keys'], times=args['times'])
            return 'Готово.'
        if action == 'newline':
            process = d.target_process()
            from .controller import MESSENGER_PROCESSES
            d.hotkey(*(('shift', 'enter') if process in MESSENGER_PROCESSES else ('enter',)))
            return 'Новая строка.'
        if action == 'clear':
            d.hotkey('ctrl', 'a')
            d.hotkey('delete')
            return 'Поле очищено.'
        if action == 'close_tab':
            from .controller import BROWSER_PROCESSES
            if d.target_process() in BROWSER_PROCESSES:
                d.hotkey('ctrl', 'w')
                return 'Вкладка закрыта.'
            return None
        if action == 'window':
            d.window(args['action'])
            return {'close': 'Закрываю окно.', 'minimize': 'Свернул окно.',
                    'maximize': 'Развернул окно.', 'restore': 'Восстановил окно.'}[args['action']]
        if action == 'screenshot':
            return 'Скриншот сохранён: ' + str(d.screenshot())
        if action == 'lock':
            d.lock_workstation()
            return 'Компьютер заблокирован.'
        if action == 'dictation':
            self.dictation = args['on']
            return ('Режим диктовки включён. Говорите — я печатаю в активное окно. Скажите «стоп диктовка», чтобы закончить.'
                    if args['on'] else 'Диктовка выключена.')
        if action == 'where':
            title, process = d.target_title()
            return f'Активное окно: {title or process}.'
        if action == 'find':
            d.hotkey('ctrl', 'f')
            time.sleep(0.25)
            d.type_text(args['text'], method)
            return 'Ищу на странице: ' + args['text']
        if action == 'type':
            if not args['text']:
                return 'Скажите, какой текст напечатать.'
            d.type_text(args['text'], method)
            if args['send']:
                time.sleep(0.08)
                d.hotkey('enter')
                return 'Отправил: ' + args['text']
            return 'Напечатал: ' + args['text']
        if action == 'messenger':
            result = messengers.send_message(d, args, settings.get('messenger_autosend', False), self.root, settings)
            if not result.startswith('Не удалось'):
                self.chat = dict(app=args['app'], who=args['who'])
            return result
        if action == 'open_chat':
            error = messengers.open_chat(d, args, settings, self.root)
            if error:
                return error
            self.chat = dict(args)
            title = messengers.PROFILES[args['app']]['title']
            return f"Открываю чат «{args['who']}» в {title}. Теперь «напиши …» пишет в этот чат."
        if action == 'send_draft':
            from .controller import MESSENGER_PROCESSES
            process = d.target_process()
            if process not in MESSENGER_PROCESSES and self.chat and d.activate_process({messengers.PROFILES[self.chat['app']]['process']}):
                time.sleep(0.2)  # черновик остался в последнем открытом чате
            d.hotkey('enter')
            return 'Отправил сообщение.'
        if action == 'discord_voice':
            return messengers.join_voice_channel(d, args['channel'], settings)
        if action == 'discord_toggle':
            return messengers.discord_toggle(d, args['what'])
        if action == 'reaction':
            return messengers.react(d, args, self.chat)
        if action == 'discord_server':
            if not args['server']:
                return 'Скажите, на какой сервер Discord зайти.'
            result = messengers.open_discord_server(d, args['server'], settings, self.root)
            if result.startswith('Захожу'):
                self.chat = dict(app='discord', who=args['server'])
            return result
        if action == 'chat_type':
            app = (self.chat or {}).get('app', 'telegram')
            return messengers.type_in_chat(d, app, tidy_typed(args['text']), args['send'], self.root)
        if action == 'generate':
            if self.brain is None:
                return 'Для сочинения текста включите ИИ в настройках.'
            content = self.brain.complete(
                'Write the requested text in the language of the request. Output only the text itself, '
                'ready to paste, without quotes, comments or markdown.', args['prompt'], settings)
            if not content:
                return 'Не получилось сочинить текст.'
            d.type_text(content.strip(), 'paste' if len(content) > 120 else method)
            return 'Готово, текст напечатан.'
        if action == 'selection':
            return self._selection(args, settings)
        return None

    def _selection(self, args, settings):
        text = self.desktop.copy_selection().strip()
        if not text:
            return 'Сначала выделите текст в приложении.'
        mode = args['mode']
        if mode == 'read':
            return text[:1500]
        if self.brain is None:
            return 'Для обработки текста включите ИИ в настройках.'
        task = SELECTION_TASKS[mode].format(language=args.get('language') if args.get('language') not in (None, 'auto') else 'English')
        result = (self.brain.complete(task, text, settings) or '').strip()
        if not result:
            return 'Не удалось обработать текст.'
        if mode == 'summary':
            return result
        self.desktop.paste(result)
        return {'translate': 'Перевёл выделенный текст.', 'fix': 'Исправил выделенный текст.',
                'improve': 'Переписал выделенный текст.'}[mode]
