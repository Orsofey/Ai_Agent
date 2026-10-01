"""Настройки ассистента для телефона: те же разделы и подписи, что в окне настроек на ПК.

Телефон рисует экран по этой схеме и меняет настройки ПК-ассистента (владелец «device:desktop»).
"""

THEMES = [('aurora', 'Аврора'), ('cyberpunk', 'Киберпанк'), ('sakura', 'Сакура'), ('ocean', 'Бездна'),
          ('luxe', 'Люкс'), ('gzhel', 'Гжель'), ('slavic', 'Славянская'), ('glass', 'Стекло'), ('glassdark', 'Стекло: ночь'), ('dark', 'Тёмная'), ('light', 'Светлая')]


def schema(voices=()):
    voice_options = [(v['id'], v['title']) for v in voices] or [('jarvis', 'Джарвис'), ('friday', 'Пятница')]
    return [
        {'id': 'general', 'title': 'Общие', 'icon': 'person', 'fields': [
            {'key': 'wake_word', 'type': 'text', 'label': 'Имя ассистента', 'hint': '«Андрей, открой калькулятор»'},
            {'key': 'address', 'type': 'select', 'label': 'Обращение к вам',
             'options': [('сэр', 'Сэр'), ('мадам', 'Мадам'), ('босс', 'Босс'), ('none', 'Без обращения')]},
            {'key': 'butler', 'type': 'bool', 'label': 'Отвечать как дворецкий'},
            {'key': 'ack', 'type': 'bool', 'label': 'Отвечать «Секунду, сэр»'},
            {'key': 'voice_language', 'type': 'select', 'label': 'Язык речи',
             'options': [('auto', 'Русский + английский'), ('ru', 'Только русский'), ('en', 'Только английский')]},
            {'key': 'city', 'type': 'text', 'label': 'Ваш город', 'hint': 'Для погоды'},
            {'key': 'autostart', 'type': 'bool', 'label': 'Запускать вместе с Windows'},
        ]},
        {'id': 'voice', 'title': 'Голос и микрофон', 'icon': 'mic', 'fields': [
            {'key': 'voice_enabled', 'type': 'bool', 'label': 'Слушать команды на ПК'},
            {'key': 'vad_sensitivity', 'type': 'range', 'label': 'Чувствительность микрофона', 'min': 10, 'max': 90, 'step': 5},
            {'key': 'silence_ms', 'type': 'range', 'label': 'Пауза конца фразы, мс', 'min': 250, 'max': 2000, 'step': 50},
            {'key': 'follow_up_seconds', 'type': 'range', 'label': 'Продолжение разговора, с', 'min': 0, 'max': 15, 'step': 1},
            {'key': 'voice_id', 'type': 'bool', 'label': 'Слушать только знакомые голоса'},
            {'key': 'voice_id_strictness', 'type': 'range', 'label': 'Строгость узнавания, %', 'min': 30, 'max': 80, 'step': 5},
        ]},
        {'id': 'speech', 'title': 'Озвучка', 'icon': 'volume', 'premium': True, 'fields': [
            {'key': 'tts_enabled', 'type': 'bool', 'label': 'Озвучивать ответы'},
            {'key': 'voice_preset', 'type': 'select', 'label': 'Голос ассистента', 'options': voice_options},
            {'key': 'tts_rate', 'type': 'range', 'label': 'Скорость речи, %', 'min': 60, 'max': 200, 'step': 5},
        ]},
        {'id': 'ai', 'title': 'ИИ и ответы', 'icon': 'sparkle', 'fields': [
            {'key': 'llm_provider', 'type': 'select', 'label': 'Нейросеть',
             'options': [('local', 'Локальная на ПК'), ('openai', 'Другой сервер'), ('off', 'Выключена')]},
            {'key': 'local_model', 'type': 'select', 'label': 'Модель',
             'options': [('qwen3-4b', 'Qwen3 4B — быстрая'), ('qwen2.5-7b', 'Qwen2.5 7B — точнее'),
                         ('qwen3-1.7b', 'Qwen3 1.7B — для слабых ПК')]},
            {'key': 'memory_mode', 'type': 'select', 'label': 'Режим памяти',
             'options': [('auto', 'Авто'), ('economy', 'Экономный'), ('balanced', 'Сбалансированный'), ('max', 'Максимум')]},
            {'key': 'answer_style', 'type': 'select', 'label': 'Длина ответов',
             'options': [('short', 'Коротко'), ('detailed', 'Подробнее')]},
            {'key': 'llm_web_search', 'type': 'bool', 'label': 'Справка из Википедии'},
        ]},
        {'id': 'control', 'title': 'Управление ПК', 'icon': 'desktop', 'fields': [
            {'key': 'type_method', 'type': 'select', 'label': 'Способ ввода текста',
             'options': [('auto', 'Авто'), ('keys', 'Печатать по буквам'), ('paste', 'Через буфер')]},
            {'key': 'messenger_autosend', 'type': 'bool', 'label': 'Сразу отправлять сообщения'},
            {'key': 'browser_mode', 'type': 'select', 'label': 'Где открывать сайты',
             'options': [('user', 'В моём браузере'), ('agent', 'В браузере агента')]},
            {'key': 'video_source', 'type': 'select', 'label': 'Видео по умолчанию',
             'options': [('youtube', 'YouTube'), ('rutube', 'Rutube')]},
        ]},
        {'id': 'appearance', 'title': 'Оформление', 'icon': 'palette', 'premium': True, 'fields': [
            {'key': 'theme', 'type': 'select', 'label': 'Тема', 'options': THEMES},
            {'key': 'animations', 'type': 'bool', 'label': 'Анимации'},
        ]},
        {'id': 'phone', 'title': 'Телефон', 'icon': 'phone', 'fields': [
            {'key': 'remote_access', 'type': 'bool', 'label': 'Доступ через интернет',
             'hint': 'Управлять ПК из любой сети. После включения отсканируйте QR-код заново.'},
        ]},
    ]


def as_json(voices=()):
    result = []
    for section in schema(voices):
        fields = []
        for field in section['fields']:
            item = dict(field)
            if 'options' in item:
                item['options'] = [{'value': v, 'label': t} for v, t in item['options']]
            fields.append(item)
        result.append(dict(section, fields=fields))
    return result
