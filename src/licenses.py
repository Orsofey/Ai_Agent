"""Third-party components, models and data sources with licenses and attributions.

Этот список показывается на странице «Лицензии» в окне настроек и дублируется
в docs/THIRD_PARTY.md. При добавлении зависимости добавьте её сюда.
"""

SECTIONS = [
    {
        'title': 'Источники данных',
        'note': 'Указание источника обязательно по условиям этих сервисов.',
        'items': [
            {'name': 'Официальные курсы валют', 'author': 'Банк России (cbr.ru)', 'license': 'Открытые данные',
             'url': 'https://www.cbr.ru/development/SXML/', 'attribution': 'Курсы валют: Банк России.'},
            {'name': 'Прогноз погоды Locationforecast', 'author': 'Норвежский метеорологический институт (MET Norway)',
             'license': 'CC BY 4.0 / NLOD 2.0', 'url': 'https://api.met.no/doc/License',
             'attribution': 'Данные о погоде: MET Norway.'},
            {'name': 'Поиск городов Nominatim', 'author': '© участники OpenStreetMap', 'license': 'ODbL 1.0',
             'url': 'https://www.openstreetmap.org/copyright',
             'attribution': 'Геоданные © участники OpenStreetMap, лицензия ODbL.'},
            {'name': 'Википедия', 'author': 'Авторы Википедии', 'license': 'CC BY-SA 4.0',
             'url': 'https://ru.wikipedia.org/wiki/Википедия:Текст_лицензии_Creative_Commons_Attribution-ShareAlike_4.0_International',
             'attribution': 'Справочные сведения: Википедия, CC BY-SA 4.0.'},
            {'name': 'Курсы криптовалют', 'author': 'CoinGecko', 'license': 'Условия CoinGecko API',
             'url': 'https://www.coingecko.com/en/api_terms', 'attribution': 'Data provided by CoinGecko.'},
            {'name': 'Поиск DuckDuckGo (выключен по умолчанию)', 'author': 'DuckDuckGo; библиотека ddgs — deedy5',
             'license': 'ddgs: MIT; сам поиск — неофициальный доступ',
             'url': 'https://duckduckgo.com/terms',
             'attribution': 'Включайте только для личного использования: у DuckDuckGo нет открытого API.'},
        ],
    },
    {
        'title': 'Нейросети',
        'note': 'Модели скачиваются отдельно при установке и не входят в исходный код.',
        'items': [
            {'name': 'Parakeet TDT 0.6B v3 (распознавание речи)', 'author': '© NVIDIA Corporation; ONNX — Илья Ступаков',
             'license': 'CC BY 4.0', 'url': 'https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3'},
            {'name': 'GigaAM v3 (распознавание русской речи)', 'author': '© SberDevices', 'license': 'MIT',
             'url': 'https://github.com/salute-developers/GigaAM'},
            {'name': 'Silero VAD (детектор речи)', 'author': '© Silero Team', 'license': 'MIT',
             'url': 'https://github.com/snakers4/silero-vad'},
            {'name': 'Whisper (резервное распознавание)', 'author': '© OpenAI; CTranslate2-версии — SYSTRAN, Mobius Labs',
             'license': 'MIT', 'url': 'https://github.com/openai/whisper'},
            {'name': 'Qwen3 4B Instruct 2507, Qwen3 1.7B', 'author': '© Alibaba Cloud (Qwen Team); GGUF — bartowski',
             'license': 'Apache 2.0', 'url': 'https://huggingface.co/Qwen'},
            {'name': 'Qwen2.5 7B Instruct', 'author': '© Alibaba Cloud (Qwen Team); GGUF — bartowski',
             'license': 'Apache 2.0', 'url': 'https://huggingface.co/Qwen/Qwen2.5-7B-Instruct'},
            {'name': 'Голоса Piper: Ирина, Денис, Amy', 'author': 'Проект Piper (rhasspy / Open Home Foundation) и авторы датасетов',
             'license': 'У каждого голоса своя — см. карточки голосов ниже',
             'url': 'https://huggingface.co/rhasspy/piper-voices'},
        ],
    },
    {
        'title': 'Программы и библиотеки',
        'note': 'Входят в установщик. Тексты лицензий — в папках библиотек внутри установленной программы.',
        'items': [
            {'name': 'llama.cpp (llama-server)', 'author': '© The ggml authors', 'license': 'MIT',
             'url': 'https://github.com/ggml-org/llama.cpp'},
            {'name': 'ONNX Runtime', 'author': '© Microsoft Corporation', 'license': 'MIT',
             'url': 'https://github.com/microsoft/onnxruntime'},
            {'name': 'onnx-asr', 'author': '© Илья Ступаков', 'license': 'MIT', 'url': 'https://github.com/istupakov/onnx-asr'},
            {'name': 'piper-tts (синтез речи)', 'author': '© Michael Hansen, Open Home Foundation', 'license': 'GPL-3.0-or-later',
             'url': 'https://github.com/OHF-Voice/piper1-gpl',
             'attribution': 'Копилефт: при распространении программы с этим компонентом действуют условия GPL-3.0.'},
            {'name': 'eSpeak NG (фонемы для Piper)', 'author': '© Reece H. Dunn и участники', 'license': 'GPL-3.0-or-later',
             'url': 'https://github.com/espeak-ng/espeak-ng'},
            {'name': 'faster-whisper, CTranslate2', 'author': '© SYSTRAN', 'license': 'MIT',
             'url': 'https://github.com/SYSTRAN/faster-whisper'},
            {'name': 'PyAV', 'author': '© участники PyAV', 'license': 'BSD-3-Clause', 'url': 'https://github.com/PyAV-Org/PyAV'},
            {'name': 'FFmpeg (внутри PyAV)', 'author': '© разработчики FFmpeg', 'license': 'LGPL-2.1-or-later',
             'url': 'https://ffmpeg.org/legal.html'},
            {'name': 'sounddevice', 'author': '© Matthias Geier', 'license': 'MIT',
             'url': 'https://github.com/spatialaudio/python-sounddevice'},
            {'name': 'PortAudio', 'author': '© Ross Bencina, Phil Burk', 'license': 'MIT', 'url': 'https://www.portaudio.com'},
            {'name': 'NumPy', 'author': '© NumPy Developers', 'license': 'BSD-3-Clause', 'url': 'https://numpy.org'},
            {'name': 'Flask, Werkzeug, Jinja', 'author': '© Pallets', 'license': 'BSD-3-Clause', 'url': 'https://palletsprojects.com'},
            {'name': 'Waitress', 'author': '© Zope Foundation and Contributors', 'license': 'ZPL 2.1',
             'url': 'https://github.com/Pylons/waitress'},
            {'name': 'pywebview', 'author': '© Roman Sirokov', 'license': 'BSD-3-Clause', 'url': 'https://pywebview.flowrl.com'},
            {'name': 'Microsoft Edge WebView2 Runtime', 'author': '© Microsoft Corporation', 'license': 'Лицензия Microsoft',
             'url': 'https://developer.microsoft.com/microsoft-edge/webview2/'},
            {'name': 'pystray', 'author': '© Moses Palmér', 'license': 'LGPL-3.0', 'url': 'https://github.com/moses-palmer/pystray'},
            {'name': 'Pillow', 'author': '© Jeffrey A. Clark и участники; © Secret Labs AB, Fredrik Lundh',
             'license': 'MIT-CMU', 'url': 'https://python-pillow.org'},
            {'name': 'psutil', 'author': '© Giampaolo Rodola', 'license': 'BSD-3-Clause', 'url': 'https://github.com/giampaolo/psutil'},
            {'name': 'filelock', 'author': 'tox-dev', 'license': 'Unlicense', 'url': 'https://github.com/tox-dev/filelock'},
            {'name': 'pyttsx3', 'author': '© Natesh M Bhat', 'license': 'MPL-2.0', 'url': 'https://github.com/nateshmbhat/pyttsx3'},
            {'name': 'requests', 'author': '© Kenneth Reitz', 'license': 'Apache 2.0', 'url': 'https://requests.readthedocs.io'},
            {'name': 'pyperclip', 'author': '© Al Sweigart', 'license': 'BSD-3-Clause', 'url': 'https://github.com/asweigart/pyperclip'},
            {'name': 'cryptography (проверка лицензии Ed25519)', 'author': '© Individual contributors', 'license': 'Apache 2.0 / BSD',
             'url': 'https://github.com/pyca/cryptography'},
            {'name': 'segno (QR-код подключения телефона)', 'author': '© Lars Heuer', 'license': 'BSD-3-Clause',
             'url': 'https://github.com/heuer/segno'},
            {'name': 'pypdf (чтение PDF при изучении папок)', 'author': '© Mathieu Fenniak и др.', 'license': 'BSD-3-Clause',
             'url': 'https://github.com/py-pdf/pypdf'},
            {'name': 'PyObjC (только macOS)', 'author': '© Ronald Oussoren и др.', 'license': 'MIT',
             'url': 'https://github.com/ronaldoussoren/pyobjc'},
            {'name': 'huggingface_hub', 'author': '© Hugging Face', 'license': 'Apache 2.0',
             'url': 'https://github.com/huggingface/huggingface_hub'},
            {'name': 'Playwright', 'author': '© Microsoft Corporation', 'license': 'Apache 2.0', 'url': 'https://playwright.dev'},
            {'name': 'yt-dlp', 'author': 'Участники yt-dlp', 'license': 'Unlicense', 'url': 'https://github.com/yt-dlp/yt-dlp'},
            {'name': 'PyInstaller (сборка)', 'author': '© PyInstaller Development Team',
             'license': 'GPL-2.0 с исключением для собранных программ', 'url': 'https://pyinstaller.org'},
            {'name': 'Python', 'author': '© Python Software Foundation', 'license': 'PSF License', 'url': 'https://www.python.org'},
        ],
    },
]


def collect(root):
    """Список для страницы «Лицензии» + карточки установленных голосов Piper."""
    from .local_tts_service import PIPER_VOICES, model_card, voice_files
    cards = []
    for name, info in PIPER_VOICES.items():
        installed = voice_files(name, root)[0] is not None
        cards.append({'voice': name, 'title': info['title'], 'installed': installed, 'trial': bool(info.get('trial')),
                      'card': model_card(name, root) if installed else None})
    return {'sections': SECTIONS, 'voices': cards}
