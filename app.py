"""Authenticated local API shared by the Windows UI, the settings window and the Android remote."""
import json
import logging
import os
import queue
import re
import secrets
import socket
import threading
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, request, jsonify, render_template, session, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from src import autostart
from src.browser_bridge import ExtensionBridge
from src.events import EventBus
from src.local_tts_service import LocalTTSService
from src.passwords import matches as check_password_hash
from src.service import AssistantService, Busy
from src.speech import SpeechService, SpeechError
from src.license import AccountError, LicenseClient
from src.storage import PremiumRequired, Store, SECRET_NAMES

log = logging.getLogger(__name__)

# Пример интеграции: переименуйте в tracker.json и замените адреса на API своего приложения.
EXAMPLE_INTEGRATION = {
    'name': 'Трекер',
    'commands': [
        {'phrases': ['что в трекере( на (?P<day>сегодня|завтра))?', 'мои задачи'],
         'method': 'GET', 'url': 'https://tracker.example/api/tasks?day={day}',
         'headers': {'Authorization': 'Bearer {secret:TRACKER_TOKEN}'}, 'say': 'Задач: {count}. {items[*].title}'},
        {'phrases': ['добавь в трекер (?P<text>.+)'], 'method': 'POST', 'url': 'https://tracker.example/api/tasks',
         'json': {'title': '{text}'}, 'say': 'Добавил в трекер: {text}'},
    ],
    'context': {'phrases': ['трекер', 'задач', 'привычк'], 'file': '~/Documents/tracker-export.json'},
}
VERSION = '7.2'


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'


VIRTUAL_ADAPTERS = re.compile(r'vethernet|virtualbox|vmware|hyper-v|wsl|docker|loopback|vpn|tap|tun|zerotier|'
                              r'tailscale|hamachi|radmin|bluetooth|teredo|isatap', re.I)


def local_ips():
    """Все адреса ПК в локальных сетях: основной первым, затем Wi-Fi/Ethernet, без виртуальных адаптеров.
    Телефон пробует их по очереди — выручает, когда «основной» адрес принадлежит VPN или виртуальной сети."""
    import ipaddress
    import psutil
    main = local_ip()
    found = [main] if main != '127.0.0.1' else []
    virtual = set()
    try:
        stats = psutil.net_if_stats()
        for name, addresses in psutil.net_if_addrs().items():
            if VIRTUAL_ADAPTERS.search(name) or (name in stats and not stats[name].isup):
                virtual.update(a.address for a in addresses)
                continue
            for address in addresses:
                if address.family != socket.AF_INET:
                    continue
                ip = ipaddress.ip_address(address.address)
                if ip.is_private and not ip.is_loopback and not ip.is_link_local and address.address not in found:
                    found.append(address.address)
    except Exception:
        pass
    rank = lambda a: (a in virtual, a != main, not a.startswith('192.168.'), not a.startswith('10.'))  # noqa: E731
    return sorted(found, key=rank) or ['127.0.0.1']


EXTENSION_ORIGINS = ('chrome-extension://', 'moz-extension://', 'safari-web-extension://')


def build_agent(store, events=None):
    """Полный агент: браузер, управление ПК, ИИ."""
    from src.agent import LocalComputerAgent
    from src.brain import Brain
    from src.browser_control import BrowserController
    from src.desktop import DesktopController, DesktopCommands
    from src.browser_bridge import ExtensionBridge
    browser = BrowserController(store.root)
    desktop = DesktopController()
    # Расширение «Андрей» в браузерах пользователя (их может быть несколько): команда идёт в тот, где вы работали.
    browser.bridge = ExtensionBridge(foreground=lambda: dict(desktop.tracker.browsers_seen))
    brain = Brain(store)
    commands = DesktopCommands(desktop, brain=brain, browser=browser, root=store.root)
    from src.integrations import Integrations
    return LocalComputerAgent(browser, brain=brain, desktop_commands=commands, integrations=Integrations(store.root))


def create_app(store=None, recognizer=None, agent=None, *, events=None, player=None, voice=None, license=None,
               background=False):
    root = Path(__file__).resolve().parent
    store = store or Store()
    events = events or EventBus()
    # Автономный режим ставится первым — до проверки лицензии и любых запросов в интернет.
    from src.network import Network, OfflineBrowser
    network = Network(store, events)
    speech = recognizer or SpeechService(store.root, store.settings('device:desktop'))
    agent = agent or build_agent(store, events)
    local_tts = LocalTTSService(store.root)
    from src import journal as journal_mod
    journal = journal_mod.install(Path(store.root) / 'logs')     # Настройки → «Журнал»
    journal.on_record = lambda entry: events.emit('journal', status=entry.get('status'), kind=entry.get('kind'))
    service = AssistantService(store, agent, events, player, journal=journal)
    license = license or LicenseClient(store)
    store.premium = license.is_premium
    app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
    app.extensions['journal'] = journal
    app.secret_key = store.meta('session_secret')
    app.config.update(MAX_CONTENT_LENGTH=12 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', PERMANENT_SESSION_LIFETIME=timedelta(days=365),
                      SEND_FILE_MAX_AGE_DEFAULT=0)
    app.extensions.update(store=store, speech=speech, agent=agent, local_tts=local_tts, events=events,
                          service=service, player=player, voice=voice, ui=None, on_settings=[],
                          license=license, network=network)
    agent.network = network
    if getattr(agent, 'browser', None) is not None and not isinstance(agent.browser, OfflineBrowser):
        agent.browser = OfflineBrowser(agent.browser)
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, owner TEXT, result TEXT)')

    def notify(text):
        """Сообщение ассистента без команды пользователя (сценарий закончился, вкладка заблокирована)."""
        message_id = store.add('device:desktop', 'agent', text)
        events.emit('message', role='agent', text=text, source='system', owner='device:desktop', spoken=False,
                    id=message_id)

    from src.chat_tools import ChatTools
    chat_tools = ChatTools(store, events, brain=getattr(agent, 'brain', None))
    agent.chat = chat_tools

    from src.checklist import Checklist
    from src.skills import Skills
    checklist = Checklist(store.root, root, events=events)
    skills = Skills(store.root, events=events, brain=getattr(agent, 'brain', None), checklist=checklist,
                    runner=lambda command, settings, who: agent.process_command(command, dict(settings, _trusted=True),
                                                                                owner=who))
    agent.skills = skills

    # Саморазвитие: выученные фразы, уроки из ошибок, самонастройка, новые скиллы, версии с откатом.
    from src.learning import Learning
    learning = Learning(store, events, agent=agent, skills=skills, background=background, app_version=VERSION)
    learning.service = service
    service.learning = learning
    try:
        agent.learning = learning
    except AttributeError:
        pass
    app.extensions['learning'] = learning

    # 6.7: память о вас — что вы рассказали о себе («запомни, что…», «меня зовут…»), с «Забыть» в настройках.
    from src.user_facts import UserFacts
    memory = UserFacts(store.root, events)
    try:
        agent.memory = memory
    except AttributeError:
        pass
    app.extensions['memory'] = memory

    def skill_context(question='', who='default'):
        # Уроки первыми: они меняются редко, и локальная модель не пересчитывает эту часть подсказки.
        return '\n\n'.join(part for part in (learning.prompt(), memory.prompt(), skills.prompt(question, who)) if part)
    if getattr(agent, 'brain', None) is not None and hasattr(agent.brain, 'skill_context'):
        agent.brain.skill_context = skill_context

    from src.scenarios import ScenarioManager
    from src.tracker import TrackerClient
    scenarios = ScenarioManager(store, browser=getattr(agent, 'browser', None), notify=notify)

    # «Скачать расширение?» в чате: первый выход Агента в браузер и блокировка сайтов без расширения.
    from src.browser_setup import ExtensionOffer

    def extension_connected():
        found = getattr(getattr(agent, 'browser', None), 'bridge', None)
        return bool(found is not None and getattr(found, 'connected', False) is True)
    ext_offer = ExtensionOffer(store, events, connected=extension_connected)
    if background:                      # в тестах и без окна предложения не нужны
        scenarios.on_needs_extension = ext_offer.maybe
        from src import browser_setup as _setup
        threading.Thread(target=lambda: _setup.chrome_published(_setup.store_ids()[0]), daemon=True,
                         name='store-check').start()   # опубликовано ли расширение — узнаём заранее
    if getattr(agent, 'browser', None) is not None and background:
        inner = getattr(agent.browser, '_browser', agent.browser)   # под обёрткой автономного режима
        if hasattr(type(inner), 'on_missing_extension'):
            inner.on_missing_extension = ext_offer.maybe
    tracker = TrackerClient(store)
    agent.scenarios = scenarios
    agent.tracker = tracker

    def open_link(url):
        from src.web_services import system_open
        system_open(url)

    from src.connectors import Connectors
    connectors = Connectors(store, tracker=tracker, opener=open_link)
    agent.connectors = connectors
    scenarios.ensure_thread()  # блокировки, начатые до перезапуска, продолжают действовать

    def speak(text):
        """Озвучить без команды пользователя (напоминание)."""
        if player is not None and getattr(player, 'available', False):
            settings = store.settings('device:desktop')
            if hasattr(player, 'beep'):
                player.beep('listen')
            player.say(text, settings)

    from src.reminders import Reminders
    reminders = Reminders(store, notify=notify, speak=speak, background=background)
    agent.reminders = reminders
    reminders.ensure_thread()

    from src.relay_client import RelayClient
    relay = RelayClient(store, app, license)
    app.extensions['relay'] = relay
    if background:
        relay.start()  # телефон через интернет: ПК сам держит связь с сервером аккаунтов

    # 6.9: «Поделись ходом решения» — живая страница по ссылке с комментариями (src/share.py).
    from src.share import ShareHub
    shares = ShareHub(store, events, license, sync=background)
    app.extensions['shares'] = shares

    def add_handler(handler):
        handlers = getattr(agent, 'extra_handlers', None)
        if isinstance(handlers, list):
            handlers.append(handler)

    add_handler(shares)

    # 6.9: звонки — кнопка «Позвонить» на телефоне, Discord, Telegram, номер телефона (src/calls).
    from src.calls import CallManager
    from src.calls.discord_voice import DiscordVoice
    from src.calls.telegram_calls import TelegramCalls
    calls = CallManager(store, speech, service, local_tts, events, license, relay)
    calls.discord = DiscordVoice(calls)
    calls.telegram = TelegramCalls(calls)
    app.extensions['calls'] = calls
    add_handler(calls)
    if background:
        threading.Thread(target=lambda: (calls.discord.start(), calls.telegram.start()), daemon=True,
                         name='calls-start').start()

    from src.power import Power
    agent.power = Power(notify=notify, speak=speak)

    from src.macros import Macros
    # Шаги макросов и скиллов вы составили сами — подтверждения «Отправить…?» для них не нужны.
    macros = Macros(store, runner=lambda command, settings, who: agent.process_command(command, dict(settings, _trusted=True),
                                                                                       owner=who))
    agent.macros = macros

    from src.speech.speaker import SpeakerGate
    gate = SpeakerGate(store)
    app.extensions['voice_gate'] = gate

    from src.files import FileStudy
    files = FileStudy(store, events, brain=getattr(agent, 'brain', None), notify=notify, speak=speak)
    agent.files = files

    # ---- 6.0 ----
    from src import oshelp
    from src.documents import Documents
    from src.file_index import FileIndex, FileSearch
    from src.doc_qa import DocumentQA
    from src.file_ops import FileOps
    from src.vision import Vision
    from src.games import Games
    from src.booking import Booking
    from src.smarthome import SmartHome
    from src.support import Support
    desktop = getattr(getattr(agent, 'desktop_commands', None), 'desktop', None)
    documents = Documents(store, events, desktop=desktop, root=store.root)
    files.publish = lambda path, text: documents.publish(path, text)
    file_index = FileIndex(store.root, background=background)
    agent.documents = documents
    connectors.documents = documents   # «загрузи этот файл на Яндекс Диск / в Dropbox / в OneDrive»
    agent.file_search = FileSearch(file_index, publish=lambda path, text: documents.publish(path, text),
                                   opener=oshelp.open_path, revealer=oshelp.reveal)
    agent.doc_qa = DocumentQA(file_index, brain=getattr(agent, 'brain', None), documents=documents)
    agent.file_ops = FileOps(store, documents=documents, events=events, notify=notify)
    agent.vision = Vision(store.root)
    agent.games = Games(store)
    agent.booking = Booking(open_link, settings=lambda: store.settings('device:desktop'))
    smarthome = SmartHome(store, opener=open_link)
    agent.smarthome = smarthome
    smarthome.documents = documents   # снимки с камер Home Assistant — карточкой в чат
    support = Support(store, license, VERSION, opener=open_link, events=events)
    agent.support = support
    app.extensions.update(documents=documents, file_index=file_index, smarthome=smarthome, support=support)

    def owner():
        device = request.headers.get('X-Device-ID', 'desktop')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', device):
            raise ValueError('Неверный идентификатор устройства')
        return 'user:' + session['user'] if session.get('user') else 'device:' + device

    def is_desktop():
        return request.headers.get('X-Device-ID', 'desktop') == 'desktop'

    def apply_browser_mode(value):
        browser = getattr(agent, 'browser', None)
        if isinstance(getattr(browser, 'bridge', None), ExtensionBridge):
            browser.mode = value.get('browser_mode', 'user')

    apply_browser_mode(store.settings('device:desktop'))

    def settings_changed(value):
        apply_browser_mode(value)
        if hasattr(speech, 'configure'):
            try:
                speech.configure(value)
            except Exception:
                log.exception('Speech reconfigure failed')
        for callback in app.extensions['on_settings']:
            try:
                callback(value)
            except Exception:
                log.exception('Settings callback failed')
        events.emit('settings', settings=value)

    learning.on_settings = settings_changed   # Агент сам поменял настройку — применить, как из окна

    # 6.7: «Отправить …? Скажите «да», «нет» или «всегда»» перед отправкой сообщений, закрытием программ, удалением.
    from src.approvals import Approvals
    approvals = Approvals(save=lambda changes: settings_changed(store.save_settings('device:desktop', changes)),
                          window_title=getattr(desktop, 'peek_title', None))
    try:
        agent.approvals = approvals
    except AttributeError:
        pass
    app.extensions['approvals'] = approvals
    if getattr(agent, 'file_ops', None) is not None:
        agent.file_ops.approvals = approvals          # «удали файл …», «удали дубликаты»

    # 6.9: автоматизации n8n для бизнеса — каталог, установка, пульт голосом, PostyBirb (src/automations).
    from src.automations import AutomationHub
    automations = AutomationHub(store, events, approvals)
    app.extensions['automations'] = automations
    add_handler(automations)

    # 7.0: персональный наставник — анимированный персонаж поверх всех окон (src/coach.py, окошко /coach).
    from src.coach import CoachHub

    def coach_foreground():
        from src.desktop import winapi
        if not winapi.supported():
            return None
        hwnd = winapi.foreground()
        if not hwnd or winapi.window_pid(hwnd) == winapi.own_pid():
            return None
        return winapi.window_title(hwnd), winapi.process_name(hwnd)

    def coach_open():
        ui = app.extensions.get('ui')
        if ui is not None and hasattr(ui, 'open_settings'):
            ui.open_settings('coach')

    coach = CoachHub(store, events, notify=notify, speak=speak, scenario=lambda: scenarios.state.get('scenario'),
                     foreground=coach_foreground if background else None, background=background)
    coach.ui_open = coach_open
    app.extensions['coach'] = coach
    add_handler(coach)

    # 7.2: обновление программы изнутри — проверка, одно уведомление о версии, загрузка с проверкой SHA-256, установка.
    from src.updates import Updater, UpdateError
    updater = Updater(store, license, VERSION, events=events, notify=notify, background=background)
    app.extensions['updater'] = updater
    add_handler(updater)

    @app.before_request
    def authenticate():
        if request.path.startswith('/api/'):
            origin = request.headers.get('Origin')
            # 7.1: панель Андрея в расширении браузера ходит ко всему API (переписка, голос, события) — с тем же
            # кодом подключения. Страницы сайтов (http/https Origin) по-прежнему не пускаем.
            extension = str(origin).startswith(EXTENSION_ORIGINS)
            if origin and not extension and urlparse(origin).netloc != request.host:
                return jsonify(success=False, message='Чужой Origin запрещён'), 403
            if request.path == '/api/ext/pair-request':
                if not str(origin).startswith(EXTENSION_ORIGINS):
                    return jsonify(success=False, message='Только для расширения «Андрей»'), 403
                return None     # код ещё не известен расширению — подтверждение в окне ассистента
            token = request.headers.get('X-Agent-Token', '')
            if request.path == '/api/events' and not token:
                token = request.args.get('token', '')  # EventSource не умеет заголовки
            if not secrets.compare_digest(token, store.meta('pairing_token')):
                return jsonify(success=False, message='Нужен код подключения из окна приложения на ПК'), 401

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(success=False, message=exc.description), exc.code
        if isinstance(exc, SpeechError):
            return jsonify(success=False, message=str(exc)), exc.code
        if isinstance(exc, PremiumRequired):
            return jsonify(success=False, message=str(exc), premium_required=True), 402
        if isinstance(exc, AccountError):
            return jsonify(success=False, message=str(exc)), exc.code
        if isinstance(exc, Busy):
            return jsonify(success=False, message=str(exc)), 429
        if isinstance(exc, ValueError):
            return jsonify(success=False, message=str(exc)), 400
        app.logger.exception('Request failed')
        return jsonify(success=False, message='Ошибка сервера. Подробности в logs/agent.log на ПК.'), 500

    # ---------------- страницы ----------------
    @app.get('/')
    def index():
        return render_template('index.html', version=VERSION)

    @app.get('/settings')
    def settings_page():
        return render_template('settings.html', version=VERSION)

    @app.get('/dictation')
    def dictation_page():
        # Окошко диктовки поверх всех окон (main.py): что записывается и что распознано.
        return render_template('dictation.html')

    @app.get('/coach')
    def coach_page():
        # Окошко наставника поверх всех окон (main.py) — персонаж, фраза и кнопки.
        return render_template('coach.html', version=VERSION)

    @app.get('/health')
    def health():
        return jsonify(ok=True, application='Local AI Agent', version=VERSION)

    # ---------------- настройки ----------------
    @app.get('/api/settings')
    def get_settings():
        value = store.settings(owner())
        value['autostart'] = autostart.enabled() if autostart_supported() else value['autostart']
        return jsonify(success=True, settings=value, secrets=store.secrets_status(), premium=store.is_premium())

    def autostart_supported():
        import sys
        return sys.platform in ('win32', 'darwin')

    @app.post('/api/settings')
    def save_settings():
        incoming = request.get_json()
        if not isinstance(incoming, dict):
            raise ValueError('Нужен объект настроек')
        previous = store.settings(owner())
        value = store.save_settings(owner(), incoming)
        if 'autostart' in incoming and autostart_supported():
            try:
                autostart.configure(value['autostart'])
            except Exception:
                store.save_settings(owner(), previous)
                raise
        if owner() == 'device:desktop' or is_desktop():
            settings_changed(value)
        return jsonify(success=True, settings=value, secrets=store.secrets_status())

    @app.get('/api/network')
    def network_get():
        return jsonify(success=True, **network.status())

    @app.post('/api/network')
    def network_set():
        data = request.get_json(silent=True) or {}
        return jsonify(success=True, **network.set(bool(data.get('online', True)), 'settings'))

    @app.get('/api/secrets')
    def get_secrets():
        return jsonify(success=True, secrets=store.secrets_status())

    @app.post('/api/secrets')
    def save_secret():
        data = request.get_json() or {}
        name = str(data.get('name', ''))
        if name not in SECRET_NAMES:
            raise ValueError('Неизвестный ключ')
        store.set_secret(name, data.get('value', ''))
        return jsonify(success=True, secrets=store.secrets_status())

    @app.get('/api/ai/status')
    def ai_status():
        brain = getattr(agent, 'brain', None)
        settings = store.settings(owner())
        local = brain.local.status(settings) if brain is not None and hasattr(brain, 'local') else None
        timing = getattr(brain, 'last_timing', None)
        return jsonify(success=True, provider=settings['llm_provider'], local=local,
                       timing=timing if isinstance(timing, dict) else None)

    @app.post('/api/ai/test')
    def ai_test():
        brain = getattr(agent, 'brain', None)
        if brain is None:
            raise ValueError('ИИ не подключён')
        settings = store.settings(owner())
        started = time.monotonic()
        from src.brain import LLMError
        try:
            text = brain.complete('Reply with one short friendly Russian sentence.', 'Скажи, что связь работает.', settings)
        except LLMError as exc:
            return jsonify(success=False, message=str(exc)), 400
        if not text:
            return jsonify(success=False, message='ИИ выключен в настройках.'), 400
        return jsonify(success=True, response=text, elapsed=round(time.monotonic() - started, 2))

    @app.post('/api/ai/benchmark')
    def ai_benchmark():
        """Замер скорости нейросети на этом ПК: через сколько приходит первое слово и сколько слов в секунду."""
        brain = getattr(agent, 'brain', None)
        if brain is None or not hasattr(brain, 'benchmark'):
            raise ValueError('ИИ не подключён')
        from src.brain import LLMError
        try:
            return jsonify(success=True, **brain.benchmark(store.settings(owner())))
        except LLMError as exc:
            return jsonify(success=False, message=str(exc)), 400

    # ---------------- журнал: все команды и ошибки (Настройки → «Журнал») ----------------
    @app.get('/api/journal')
    def journal_list():
        kind = request.args.get('kind', 'all')
        kind = kind if kind in ('all', 'errors', 'commands') else 'all'
        limit = min(max(int(request.args.get('limit', 200) or 200), 1), 1000)
        return jsonify(success=True, entries=journal.read(limit, kind, request.args.get('q', '')[:100]),
                       stats=journal.stats(), path=str(journal.folder))

    @app.post('/api/journal/clear')
    def journal_clear():
        journal.clear()
        return jsonify(success=True)

    @app.get('/api/journal/export')
    def journal_export():
        """Журнал текстом — приложить к письму в поддержку."""
        import time as _time
        lines = []
        for entry in reversed(journal.read(1000)):
            stamp = _time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime(entry.get('time', 0)))
            head = f"[{stamp}] {entry.get('status', '').upper():9} "
            if entry.get('kind') == 'command':
                head += f"{entry.get('source', '')}: «{entry.get('text', '')}» → {entry.get('result', '')} " \
                        f"({entry.get('duration', 0)} с)"
            else:
                head += f"{entry.get('source', '')}: {entry.get('text', '')}"
            lines.append(head)
            lines += ['    ' + d.replace('\n', '\n    ') for d in entry.get('details') or []]
        return Response('\n'.join(lines) + '\n', mimetype='text/plain; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="andrey-journal.txt"'})

    @app.post('/api/journal/open-folder')
    def journal_open_folder():
        from src.web_services import system_open
        opened = is_desktop() and system_open(str(journal.folder))
        return jsonify(success=True, opened=bool(opened), path=str(journal.folder))

    # ---------------- история ----------------
    @app.get('/api/history')
    def history():
        return jsonify(success=True, history=store.history(owner(), limit=300))

    @app.post('/api/history/clear')
    def clear():
        who = owner()
        batch = chat_tools.clear(who)
        return jsonify(success=True, batch=batch)

    @app.post('/api/history/restore')
    def history_restore():
        data = request.get_json(silent=True) or {}
        batch = str(data.get('batch') or '')[:40]
        if batch and not re.fullmatch(r'(?:all|one):[0-9a-f]{12}', batch):
            raise ValueError('Неверная метка')
        return jsonify(success=True, restored=chat_tools.restore(owner(), batch or None))

    @app.post('/api/history/<int:message_id>/delete')
    def history_delete(message_id):
        batch = store.delete_message(owner(), message_id)
        if batch is None:
            return jsonify(success=False, message='Сообщение уже удалено'), 404
        return jsonify(success=True, batch=batch)

    @app.post('/api/history/<int:message_id>/react')
    def history_react(message_id):
        from src.chat_tools import REACTIONS
        emoji = str((request.get_json(silent=True) or {}).get('emoji') or '')
        if emoji and emoji not in REACTIONS:
            raise ValueError('Такой реакции нет в наборе')
        who = owner()
        reactions = store.react(who, message_id, 'user', emoji)
        if reactions is None:
            return jsonify(success=False, message='Сообщение не найдено'), 404
        events.emit('reaction', id=message_id, reactions=reactions, owner=who)
        if emoji and reactions.get('user') == emoji:
            try:
                learning.on_reaction(who, message_id, emoji)   # 🤔 на ответ — повод разобрать ошибку
            except Exception:
                log.exception('Learning reaction hook failed')
        return jsonify(success=True, reactions=reactions)

    @app.get('/api/export')
    def export():
        response = jsonify(store.export(owner()))
        response.headers['Content-Disposition'] = 'attachment; filename=LocalAIAgent-data.json'
        return response

    # ---------------- команды ----------------
    def validate_command(data):
        message = str((data or {}).get('message', '')).strip()
        ident = str((data or {}).get('id', ''))
        if not 1 <= len(message) <= 2000 or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', ident):
            raise ValueError('Нужны команда (до 2000 символов) и уникальный id')
        return message, ident

    def claim(ident, who):
        """Идемпотентность: повтор того же id не выполняет команду второй раз."""
        with store.connect() as db:
            existing = db.execute('SELECT owner,result FROM commands WHERE id=?', (ident,)).fetchone()
            if not existing:
                db.execute('INSERT INTO commands VALUES (?,?,NULL)', (ident, who))
        if existing and existing[0] != who:
            raise ValueError('Идентификатор уже занят')
        return existing

    def command_source():
        # 7.1: из панели в браузере — окно Андрея показывает такие сообщения с пометкой «🌐 из браузера».
        return 'browser' if request.headers.get('X-Agent-Client') == 'extension' else 'text'

    def finish(ident, result):
        with store.connect() as db:
            db.execute('UPDATE commands SET result=? WHERE id=?', (result, ident))

    @app.post('/api/chat')
    def chat():
        message, ident = validate_command(request.get_json())
        who = owner()
        stopped = service.control(message, store.settings(who))
        if stopped:
            return jsonify(success=True, response=stopped, spoken=False)
        if service.lock.locked():
            return jsonify(success=False, message='Выполняется предыдущая команда. Повторите позже.'), 429
        existing = claim(ident, who)
        if existing:
            return jsonify(success=True, response=existing[1] or 'Команда уже принята. После сбоя автоматически не повторяется.', duplicate=True)
        result, spoken = service.run(message, who, store.settings(who), source=command_source(), speak=is_desktop())
        finish(ident, result)
        user_id, agent_id = service.last_ids.get(who, (None, None))
        if is_desktop() and voice is not None and getattr(agent, 'awaiting', None) and agent.awaiting(who) is True:
            try:
                voice.expect_answer()  # «Во сколько вы встаёте?» — ответить можно голосом без имени
            except Exception:
                pass
        return jsonify(success=True, response=result, spoken=spoken, id=agent_id, user_id=user_id)

    @app.post('/api/chat/stream')
    def chat_stream():
        message, ident = validate_command(request.get_json())
        who = owner()
        stopped = service.control(message, store.settings(who))
        if stopped:
            reply = 'data: ' + json.dumps({'type': 'done', 'response': stopped}, ensure_ascii=False) + '\n\n'
            return Response(reply, mimetype='text/event-stream')
        if service.lock.locked():
            return jsonify(success=False, message='Выполняется предыдущая команда. Повторите позже.'), 429
        existing = claim(ident, who)
        settings = store.settings(who)
        desktop = is_desktop()
        source = command_source()
        channel = queue.Queue()

        def work():
            try:
                if existing:
                    channel.put({'type': 'done', 'response': existing[1] or 'Команда уже принята.', 'duplicate': True})
                    return
                result, spoken = service.run(message, who, settings, source=source, speak=desktop,
                                             on_text=lambda chunk: channel.put({'type': 'delta', 'text': chunk}))
                finish(ident, result)
                user_id, agent_id = service.last_ids.get(who, (None, None))
                channel.put({'type': 'done', 'response': result, 'spoken': spoken, 'id': agent_id, 'user_id': user_id,
                             'user_reactions': (store.message_reactions(user_id) if user_id else {})})
            except Exception as exc:
                log.exception('Stream command failed')
                channel.put({'type': 'error', 'message': str(exc) if isinstance(exc, (Busy, ValueError)) else 'Ошибка выполнения команды.'})
            finally:
                channel.put(None)

        threading.Thread(target=work, daemon=True, name='chat-stream').start()

        def generate():
            while True:
                item = channel.get()
                if item is None:
                    break
                yield 'data: ' + json.dumps(item, ensure_ascii=False) + '\n\n'
        return Response(generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.get('/api/events')
    def events_stream():
        return Response(events.stream(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    # ---------------- голос ----------------
    @app.get('/api/voice/status')
    def voice_status():
        state = voice.status() if voice is not None else dict(state='off', running=False)
        return jsonify(success=True, native=voice is not None, voice=state, speech=speech.status(),
                       speaking=bool(player and player.speaking))

    @app.get('/api/voice/diagnostics')
    def voice_diagnostics():
        # «Почему не сработало»: последние услышанные фразы и что с ними стало.
        if voice is None or not hasattr(voice, 'diagnostics'):
            return jsonify(success=True, native=False, status=dict(state='off', running=False), items=[], counts={},
                           wake_word=store.settings(owner()).get('wake_word', 'Андрей'), settings={})
        return jsonify(success=True, native=True, speech=speech.status(), **voice.diagnostics())

    @app.post('/api/voice/diagnostics/clear')
    def voice_diagnostics_clear():
        if voice is not None and hasattr(voice, 'journal'):
            voice.journal.clear()
        return jsonify(success=True)

    @app.post('/api/voice/test')
    def voice_sound_test():
        if voice is None or not hasattr(voice, 'sound_test'):
            return jsonify(success=False, native=False, message='Проверка звука работает в приложении на ПК.'), 409
        return jsonify(success=True, **voice.sound_test(3.0))

    @app.post('/api/voice/listen')
    def voice_listen():
        if voice is None:
            return jsonify(success=False, native=False, message='Фоновое прослушивание недоступно на этом устройстве.'), 409
        voice.listen_once()
        return jsonify(success=True)

    @app.post('/api/cancel')
    def cancel():
        """Кнопка «Пауза»: прервать текущую команду и замолчать."""
        was_running = service.cancel()
        if voice is not None and hasattr(voice, 'reset'):
            voice.reset()
        return jsonify(success=True, cancelled=was_running)

    @app.post('/api/voice/stop-speaking')
    def voice_stop_speaking():
        if player is not None:
            player.stop()
        return jsonify(success=True)

    @app.post('/api/tts/speak')
    def tts_speak():
        text = str((request.get_json() or {}).get('text', '')).strip()
        if not 1 <= len(text) <= 2000:
            raise ValueError('Текст 1–2000 символов')
        if player is None or not player.available:
            return jsonify(success=False, native=False)
        player.stop()
        player.say(text, store.settings(owner()))
        return jsonify(success=True, native=True)

    @app.get('/api/audio/devices')
    def audio_devices():
        from src.speech.microphone import list_devices
        return jsonify(success=True, devices=list_devices())

    @app.get('/api/speech/status')
    def speech_status():
        return jsonify(success=True, **speech.status())

    @app.post('/api/speech/load')
    def speech_load():
        speech.warmup()
        return jsonify(success=True, **speech.status())

    @app.post('/api/transcribe')
    def transcribe():
        if 'audio' not in request.files:
            raise ValueError('Нужно multipart-поле audio')
        data = request.files['audio'].read(12 * 1024 * 1024 + 1)
        if not data or len(data) > 12 * 1024 * 1024:
            raise ValueError('Пустой или слишком большой файл')
        language = request.form.get('language', 'ru')
        return jsonify(success=True, **speech.transcribe(data, language))

    # ---------------- модели ----------------
    @app.get('/api/models/status')
    def models_status():
        from src.model_downloader import status as model_status
        return jsonify(success=True, **model_status(store.root))

    @app.post('/api/models/download')
    def models_download():
        from src.model_downloader import start_download
        items = (request.get_json() or {}).get('items') or ['vad', 'parakeet', 'gigaam', 'piper', 'llama:cpu', 'llm:qwen3-4b']
        if not isinstance(items, list):
            raise ValueError('items должен быть списком')

        def done():
            settings = store.settings('device:desktop')
            speech.configure(settings)
            brain = getattr(agent, 'brain', None)
            if brain is not None and hasattr(brain, 'local') and settings['llm_provider'] == 'local':
                brain.local.warmup(settings)
        started = start_download(store.root, items, events, on_done=done)
        return jsonify(success=True, started=started)

    @app.get('/api/licenses')
    def licenses():
        from src.licenses import collect
        return jsonify(success=True, **collect(store.root))

    # ---------------- синтез для телефона ----------------
    @app.get('/api/ai/voices')
    def list_voices():
        return jsonify(success=True, voices=local_tts.available_voices(), assistant=local_tts.assistant_voices())

    @app.post('/api/voices/open-folder')
    def open_voice_folder():
        """Папка своих голосов (models/voices): положите туда .onnx и .onnx.json голоса Piper."""
        from src.local_tts_service import custom_voice_dirs
        from src.web_services import system_open
        folder = custom_voice_dirs(store.root)[0]
        folder.mkdir(parents=True, exist_ok=True)
        opened = is_desktop() and system_open(str(folder))
        return jsonify(success=True, opened=bool(opened), path=str(folder))

    from src.tts_api import register_tts_routes
    register_tts_routes(app, local_tts, store, owner)

    # ---------------- окна ----------------
    @app.post('/api/ui/open-settings')
    def open_settings():
        ui = app.extensions.get('ui')
        if ui is None:
            return jsonify(success=True, opened=False)
        section = str((request.get_json(silent=True) or {}).get('section', ''))
        ui.open_settings(section if re.fullmatch(r'[a-z]{0,20}', section) else '')
        return jsonify(success=True, opened=True)

    @app.post('/api/ui/show-main')
    def show_main():
        ui = app.extensions.get('ui')
        if ui is not None:
            ui.show_main()
        return jsonify(success=True, opened=ui is not None)

    # ---------------- звонки (6.9) ----------------
    @app.get('/api/calls')
    def calls_status():
        return jsonify(success=True, **calls.status())

    @app.post('/api/call/hello')
    def call_hello():
        return jsonify(success=True, **calls.hello())

    @app.post('/api/call/turn')
    def call_turn():
        import base64
        import binascii
        data = request.get_json(silent=True) or {}
        try:
            audio = base64.b64decode(str(data.get('audio') or ''), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError('Неверный звук')
        if not audio:
            raise ValueError('Пустой звук')
        return jsonify(success=True, **calls.phone_turn(audio, str(data.get('call') or '')[:40]))

    @app.post('/api/call/text')
    def call_text():
        data = request.get_json(silent=True) or {}
        return jsonify(success=True, **calls.telephony.text_turn(data.get('text', ''), data.get('caller', '')))

    @app.get('/api/calls/qr')
    def calls_qr():
        import io
        import segno
        link = calls.call_link()
        if not link:
            raise ValueError('Сначала укажите сервер аккаунтов и включите «Доступ через интернет»')
        buffer = io.BytesIO()
        segno.make(link, error='m').save(buffer, kind='svg', scale=6, border=2, dark='#0b1020', light='#ffffff')
        return Response(buffer.getvalue(), mimetype='image/svg+xml', headers={'Cache-Control': 'no-store'})

    @app.get('/api/calls/scenario')
    def calls_scenario():
        return jsonify(success=True, scenario=calls.telephony.scenario(request.args.get('voice', 'male')))

    @app.post('/api/calls/discord/start')
    def calls_discord_start():
        started = calls.discord.start()
        return jsonify(success=True, started=started, **calls.status())

    @app.post('/api/calls/telegram/code')
    def calls_telegram_code():
        return jsonify(success=True, message=calls.telegram.send_code((request.get_json(silent=True) or {}).get('phone')))

    @app.post('/api/calls/telegram/login')
    def calls_telegram_login():
        data = request.get_json(silent=True) or {}
        return jsonify(success=True, message=calls.telegram.confirm_code(data.get('code', ''), data.get('password', '')))

    @app.get('/call')
    def call_page():
        # Страница звонка. В локальной сети микрофон в браузере телефона не работает (нужен HTTPS) — тогда она
        # предлагает ссылку через сервер аккаунтов; на самом ПК (localhost) работает сразу.
        page = (Path(__file__).resolve().parent / 'static' / 'call.html').read_text(encoding='utf-8')
        return Response(page, mimetype='text/html', headers={'Cache-Control': 'no-store'})

    # ---------------- обновление (7.2) ----------------
    def update_reply(action):
        try:
            result = action()
        except UpdateError as exc:
            return jsonify(success=False, message=str(exc), **updater.status()), 400
        return jsonify(success=True, message=result if isinstance(result, str) else '', **updater.status())

    @app.get('/api/update')
    def update_status():
        return jsonify(success=True, **updater.status())

    @app.post('/api/update/check')
    def update_check():
        return update_reply(updater.check)

    @app.post('/api/update/download')
    def update_download():
        return update_reply(updater.download)

    @app.post('/api/update/install')
    def update_install():
        if not is_desktop():
            raise ValueError('Установить обновление можно только на самом компьютере')
        return update_reply(updater.install)

    # ---------------- наставник (7.0) ----------------
    @app.get('/api/coach')
    def coach_status():
        return jsonify(success=True, **coach.status())

    @app.post('/api/coach/goals')
    def coach_goals():
        data = request.get_json(silent=True) or {}
        op = str(data.get('op') or 'add')
        if op == 'add':
            from src.coach import split_goals
            items = split_goals(str(data.get('text') or '')[:600])
            if not items:
                raise ValueError('Напишите цель')
            coach.set_goals(items, replace=False)
        elif op in ('done', 'undo', 'remove'):
            index = data.get('index')
            if not isinstance(index, int) or not 0 <= index < len(coach.goals()):
                raise ValueError('Нет такой цели')
            if op == 'remove':
                coach.remove(index)
            else:
                all_done = coach.mark(index, op == 'done')
                if op == 'done':
                    coach.say('all_done' if all_done else 'goal_done', voice=None if all_done else False)
        elif op == 'clear':
            coach.clear_goals()
        else:
            raise ValueError('Неизвестное действие')
        return jsonify(success=True, **coach.status())

    @app.post('/api/coach/action')
    def coach_action():
        data = request.get_json(silent=True) or {}
        text = coach.action(str(data.get('id') or ''))
        return jsonify(success=True, text=text)

    @app.post('/api/coach/pomodoro')
    def coach_pomodoro():
        data = request.get_json(silent=True) or {}
        if data.get('stop'):
            coach.stop_pomodoro()
        else:
            minutes = data.get('minutes')
            if minutes is not None and (not isinstance(minutes, int) or not 1 <= minutes <= 180):
                raise ValueError('От 1 до 180 минут')
            pomo = coach.start_pomodoro(minutes)
            coach.say('pomo_start', minutes=pomo['minutes'], voice=False)
        return jsonify(success=True, **coach.status())

    @app.post('/api/coach/preview')
    def coach_preview():
        data = request.get_json(silent=True) or {}
        from src.coach import MOODS
        mood = str(data.get('mood') or 'whip')
        if mood not in MOODS:
            raise ValueError('Неизвестное настроение')
        return jsonify(success=True, **coach.preview(str(data.get('character') or ''), mood))

    # ---------------- автоматизации n8n (6.9) ----------------
    @app.get('/api/automations')
    def automations_status():
        return jsonify(success=True, **automations.status())

    @app.post('/api/automations/refresh')
    def automations_refresh():
        return jsonify(success=True, items=automations.refresh())

    @app.post('/api/automations/start')
    def automations_start():
        from src.automations.n8n import N8nError
        try:
            message = automations.start_n8n()
        except N8nError as exc:
            raise ValueError(str(exc))
        return jsonify(success=True, message=message, **automations.status())

    @app.post('/api/automations/install')
    def automations_install():
        from src.automations.n8n import N8nError
        data = request.get_json(silent=True) or {}
        params = data.get('params') if isinstance(data.get('params'), dict) else {}
        try:
            item = automations.install(str(data.get('template') or ''), params, str(data.get('client') or ''),
                                       bot_token=data.get('bot_token') or None)
        except N8nError as exc:
            raise ValueError(str(exc))
        return jsonify(success=True, item=item)

    @app.post('/api/automations/remote')
    def automations_remote():
        from src.automations.n8n import N8nError
        data = request.get_json(silent=True) or {}
        try:
            item = automations.add_remote(data.get('title'), data.get('control_url'), data.get('key'), data.get('client'))
        except N8nError as exc:
            raise ValueError(str(exc))
        return jsonify(success=True, item=item)

    @app.post('/api/automations/<iid>/<action>')
    def automations_action(iid, action):
        from src.automations.n8n import N8nError
        try:
            if action in ('pause', 'resume'):
                return jsonify(success=True, item=automations.set_paused(iid, action == 'pause'))
            if action == 'delete':
                automations.remove(iid, bool((request.get_json(silent=True) or {}).get('n8n', True)))
                return jsonify(success=True)
        except KeyError as exc:
            return jsonify(success=False, message=str(exc.args[0])), 404
        except N8nError as exc:
            raise ValueError(str(exc))
        return jsonify(success=False, message='Неизвестное действие'), 404

    @app.get('/api/automations/<iid>/errors')
    def automations_errors(iid):
        from src.automations.n8n import N8nError
        try:
            return jsonify(success=True, errors=automations.failures(iid))
        except KeyError as exc:
            return jsonify(success=False, message=str(exc.args[0])), 404
        except N8nError as exc:
            raise ValueError(str(exc))

    @app.get('/api/automations/proposal')
    def automations_proposal():
        from src.automations.templates import BY_ID
        template = request.args.get('template', '')
        if template not in BY_ID:
            raise ValueError('Нет такой автоматизации')
        return jsonify(success=True, text=automations.proposal(template, str(request.args.get('client') or '')[:80]))

    # ---------------- трансляция хода решения (6.9) ----------------
    @app.get('/api/share')
    def share_status():
        return jsonify(success=True, **shares.status())

    @app.post('/api/share/start')
    def share_start():
        data = request.get_json(silent=True) or {}
        share = shares.start(owner(), str(data.get('title') or ''))
        from src.share import copy_to_clipboard
        link = shares.link(share)
        return jsonify(success=True, copied=bool(data.get('copy')) and copy_to_clipboard(link), **shares.status())

    @app.post('/api/share/stop')
    def share_stop():
        shares.stop()
        return jsonify(success=True, **shares.status())

    @app.post('/api/share/note')
    def share_note():
        shares.note((request.get_json(silent=True) or {}).get('text', ''))
        return jsonify(success=True, **shares.status())

    @app.get('/s/<sid>')
    def share_page(sid):
        try:
            shares.get(sid)
        except KeyError:
            return Response('Трансляция не найдена', status=404, mimetype='text/plain; charset=utf-8')
        page = (Path(__file__).resolve().parent / 'static' / 'share.html').read_text(encoding='utf-8')
        return Response(page, mimetype='text/html', headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex',
                                                             'Referrer-Policy': 'no-referrer'})

    @app.get('/share/<sid>/feed')
    def share_feed(sid):
        try:
            data = shares.feed(sid, request.args.get('after', 0), request.args.get('wait', 0),
                               request.args.get('vid', ''))
        except KeyError as exc:
            return jsonify(success=False, message=str(exc.args[0])), 404
        return jsonify(success=True, **data)

    share_hits = {}

    @app.post('/share/<sid>/comment')
    def share_comment(sid):
        data = request.get_json(silent=True) or {}
        if data.get('website'):
            return jsonify(success=True)
        now, who = time.time(), request.remote_addr or ''
        recent = [t for t in share_hits.get(who, []) if t > now - 60]
        if len(recent) >= 6:
            return jsonify(success=False, message='Слишком много комментариев подряд — подождите минуту'), 429
        share_hits[who] = recent + [now]
        try:
            shares.comment(sid, data.get('name'), data.get('text'), source='lan')
        except KeyError as exc:
            return jsonify(success=False, message=str(exc.args[0])), 404
        return jsonify(success=True)

    # ---------------- подключение и профили ----------------
    @app.get('/api/connection')
    def connection():
        return jsonify(success=True, ip=local_ip(), ips=local_ips(), port=request.host.split(':')[-1],
                       storage=str(store.root), token=store.meta('pairing_token'), user=session.get('user'),
                       relay=relay.status(), firewall=firewall_status())

    def phone_link(device='iphone'):
        """Ссылка для телефона: все адреса ПК в локальной сети и (если включено) мост через интернет."""
        from urllib.parse import quote
        port = request.host.split(':')[-1]
        ips = local_ips()
        link = f"http://{ips[0]}:{port}/#token={store.meta('pairing_token')}&device={device}"
        if len(ips) > 1:
            link += '&hosts=' + ','.join(ips[1:4])
        if relay.enabled():
            link += f"&relay={quote(relay.server(), safe='')}&rid={relay.rid()}"
        return link

    @app.get('/api/connection/qr')
    def connection_qr():
        """QR-код для телефона: камера iPhone/Android открывает уже подключённое приложение."""
        import io
        import segno
        buffer = io.BytesIO()
        segno.make(phone_link(), error='m').save(buffer, kind='svg', scale=6, border=2, dark='#0b1020', light='#ffffff')
        return Response(buffer.getvalue(), mimetype='image/svg+xml', headers={'Cache-Control': 'no-store'})

    @app.post('/api/siri')
    def siri():
        """Для «Быстрых команд» iPhone: «Привет, Siri, Андрей» → диктовка → ответ читает Siri."""
        data = request.get_json(silent=True) or {}
        text = str(data.get('text') or data.get('message') or '').strip()
        if not 1 <= len(text) <= 2000:
            raise ValueError('Нужен текст команды')
        if service.lock.locked():
            return jsonify(success=False, response='Секунду, выполняю предыдущую команду.'), 429
        who = 'device:' + re.sub(r'[^\w-]', '', request.headers.get('X-Device-ID', 'siri'))[:80]
        result, _ = service.run(text, who, store.settings('device:desktop'), source='phone', speak=False)
        return jsonify(success=True, response=result)

    @app.post('/api/register')
    def register():
        data = request.get_json()
        name, password = str(data.get('name', '')).strip(), str(data.get('password', ''))
        if not re.fullmatch(r'[\w -]{3,40}', name) or not 8 <= len(password) <= 200:
            raise ValueError('Имя: 3–40 символов; пароль: 8–200 символов')
        with store.connect() as db:
            if db.execute('SELECT 1 FROM users WHERE lower(name)=lower(?)', (name,)).fetchone():
                raise ValueError('Имя уже занято')
            db.execute('INSERT INTO users VALUES (?,?,?)', (name, generate_password_hash(password), str(data.get('email', ''))[:200]))
        return jsonify(success=True)

    @app.post('/api/login')
    def login():
        data = request.get_json()
        with store.connect() as db:
            row = db.execute('SELECT name,password FROM users WHERE lower(name)=lower(?)', (str(data.get('name', '')),)).fetchone()
        if not row or not check_password_hash(row[1], str(data.get('password', ''))):
            return jsonify(success=False, message='Неверное имя или пароль'), 401
        session.clear()
        session['user'] = row[0]
        session.permanent = True
        return jsonify(success=True, user=row[0])

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(success=True)

    # ---------------- аккаунт и подписка ----------------
    def account_changed(status):
        # Подписка включилась или закончилась: платные настройки применяются/сбрасываются сразу.
        settings_changed(store.settings('device:desktop'))
        events.emit('account', account=status)
        return status

    def account_reply(action):
        before = store.is_premium()
        status = action()
        if store.is_premium() != before:
            account_changed(status)
        return jsonify(success=True, account=status)

    app.extensions['account_changed'] = account_changed

    @app.get('/api/account')
    def account():
        return jsonify(success=True, account=license.status())

    @app.post('/api/account/register')
    def account_register():
        data = request.get_json() or {}
        return account_reply(lambda: license.register(str(data.get('email', '')), str(data.get('password', ''))))

    @app.post('/api/account/login')
    def account_login():
        data = request.get_json() or {}
        return account_reply(lambda: license.login(str(data.get('email', '')), str(data.get('password', ''))))

    @app.post('/api/account/logout')
    def account_logout():
        return account_reply(license.logout)

    @app.post('/api/account/delete')
    def account_delete():
        data = request.get_json() or {}
        return account_reply(lambda: license.delete_account(str(data.get('password', ''))))

    # ---------------- политика конфиденциальности ----------------
    @app.get('/api/privacy')
    def privacy():
        from src import privacy_policy
        lang = 'en' if request.args.get('lang') == 'en' else 'ru'
        try:
            status = license.status()
            server_url = status.get('server_url', '') if isinstance(status, dict) else ''
        except Exception:
            server_url = ''
        server_url = server_url if isinstance(server_url, str) else ''
        return jsonify(success=True, html=privacy_policy.render_html(lang, server_url, standalone=False),
                       url=(server_url + ('/privacy/en' if lang == 'en' else '/privacy')) if server_url else '',
                       missing=privacy_policy.missing_fields())

    # ---------------- расширение «Андрей» для браузера ----------------
    def bridge():
        found = getattr(getattr(agent, 'browser', None), 'bridge', None)
        if found is None:
            raise ValueError('Мост к браузеру недоступен')
        return found

    @app.get('/api/ext/next')
    def ext_next():
        """Долгий опрос от расширения: следующая команда или пустой ответ через ~20 секунд."""
        command = bridge().next_command(request.args.get('wait', 20), request.args.get('browser', ''),
                                        request.args.get('client', ''))
        return jsonify(success=True, command=command)

    @app.post('/api/ext/focus')
    def ext_focus():
        """Расширение 1.6+: окно браузера стало активным — следующие команды пойдут в этот браузер."""
        data = request.get_json(silent=True) or {}
        found = bridge()
        if hasattr(found, 'focus'):
            found.focus(str(data.get('browser') or ''), str(data.get('client') or ''), bool(data.get('focused', True)))
        return jsonify(success=True)

    @app.post('/api/ext/result')
    def ext_result():
        data = request.get_json(silent=True) or {}
        bridge().complete(data.get('id'), data.get('ok'), data.get('result'), data.get('error'))
        return jsonify(success=True)

    from src.browser_setup import PairRequests
    pair_requests = PairRequests(events)

    @app.post('/api/ext/connect')
    def ext_connect():
        """Кнопка «Подключить браузер»: расширение с готовым кодом + страница расширений в браузере."""
        from src import browser_setup
        port = int(request.host.rsplit(':', 1)[1]) if ':' in request.host else 80
        pair_requests.expect()
        channel = str((request.get_json(silent=True) or {}).get('browser') or '')
        result = browser_setup.connect(store.root, root, port, store.meta('pairing_token'),
                                       opener=open_link if is_desktop() else None,
                                       channel=channel if channel in browser_setup.BROWSERS else None)
        return jsonify(success=True, **result)

    def connect_browser(channel=''):
        """«Подключи браузер» / «подключи Яндекс Браузер» голосом или в чате."""
        from src import browser_setup
        from src.browser_bridge import ExtensionBridge
        found = getattr(getattr(agent, 'browser', None), 'bridge', None)
        bridge_ok = isinstance(found, ExtensionBridge)
        installed = browser_setup.installed()
        titles = dict(installed)
        key = {'msedge': 'edge'}
        if channel:
            title = browser_setup.BROWSERS[channel][0]
            if bridge_ok and found.matches(key.get(channel, channel)):
                return f'{title} уже подключён.'
            if installed and channel not in titles:
                return f'{title} на этом компьютере не нашёл. Установите его и повторите.'
        else:
            free = [c for c, _ in installed if not (bridge_ok and found.matches(key.get(c, c)))]
            if installed and not free:
                return 'Все браузеры уже подключены: ' + ', '.join(t for _, t in installed) + '.'
            channel = free[0] if free and bridge_ok and found.connected else ''
        port = int(os.getenv('LOCAL_AI_PORT', '5000'))
        pair_requests.expect()
        result = browser_setup.connect(store.root, root, port, store.meta('pairing_token'),
                                       opener=open_link, channel=channel or None)
        return f"Подключаю {result['browser']}. " + ' '.join(result['steps'])

    try:
        agent.connect_browser = connect_browser
    except AttributeError:
        pass

    @app.post('/api/ext/import')
    def ext_import():
        """Расширение 2.0: переписка, которую вели в браузере без ПК-версии, — однократно на ПК (повтор без дублей)."""
        data = request.get_json(silent=True) or {}
        messages = data.get('messages')
        if not isinstance(messages, list) or len(messages) > 500:
            raise ValueError('Нужен список сообщений (до 500)')
        accepted = store.import_messages('device:desktop', messages)
        if accepted:
            events.emit('history', action='imported', owner='device:desktop', imported=len(accepted))
        return jsonify(success=True, accepted=accepted)

    @app.get('/api/ext/browsers')
    def ext_browsers():
        """Настройки: какие браузеры установлены, какие уже подключены, какие ждут «Разрешить»."""
        from src import browser_setup
        from src.browser_bridge import ExtensionBridge, browser_key
        found = getattr(getattr(agent, 'browser', None), 'bridge', None)
        status = found.status() if isinstance(found, ExtensionBridge) else {'connected': False, 'browsers': []}
        online = {item['key']: item for item in status.get('browsers', [])}
        key_of = {'msedge': 'edge'}
        items = []
        for channel, title in browser_setup.installed():
            item = online.pop(key_of.get(channel, channel), None)
            items.append({'channel': channel, 'title': title, 'connected': item is not None,
                          'active': bool(item and item.get('active'))})
        for item in online.values():          # подключён, но не нашли его программу (другая папка, macOS)
            items.append({'channel': item['key'] or '', 'title': item['name'], 'connected': True,
                          'active': bool(item.get('active'))})
        waiting = pair_requests.waiting()
        for item in items:
            item['waiting'] = any(browser_key(name) == key_of.get(item['channel'], item['channel']) for name in waiting)
        return jsonify(success=True, browsers=items, connected=status.get('connected', False),
                       active=status.get('browser', ''), waiting=waiting)

    @app.post('/api/ext/install')
    def ext_install():
        """«Скачать» в чате: открыть расширение в магазине (или папку для режима разработчика) и подключить само."""
        return ext_connect()

    @app.post('/api/ext/offer/dismiss')
    def ext_offer_dismiss():
        ext_offer.dismiss()
        return jsonify(success=True)

    @app.post('/api/ext/pair-request')
    def ext_pair_request():
        data = request.get_json(silent=True) or {}
        allowed = pair_requests.ask(data.get('browser', ''), wait=20)
        if allowed:
            return jsonify(success=True, token=store.meta('pairing_token'))
        if allowed is False:
            return jsonify(success=False, message='Подключение браузера отклонено'), 403
        return jsonify(success=True, pending=True)

    @app.post('/api/ext/pair-answer')
    def ext_pair_answer():
        data = request.get_json(silent=True) or {}
        return jsonify(success=pair_requests.answer(data.get('browser', ''), bool(data.get('allow'))))

    @app.get('/api/ext/status')
    def ext_status():
        from src.browser_bridge import ExtensionBridge
        found = getattr(getattr(agent, 'browser', None), 'bridge', None)
        return jsonify(success=True, **(found.status() if isinstance(found, ExtensionBridge) else {'connected': False}))

    # ---------------- интеграции ----------------
    @app.get('/api/integrations')
    def integrations_status():
        from src.integrations import Integrations
        found = getattr(agent, 'integrations', None)
        return jsonify(success=True, **(found.status() if isinstance(found, Integrations)
                                        else {'items': [], 'errors': [], 'folder': ''}))

    @app.post('/api/integrations/open-folder')
    def integrations_folder():
        """Открыть папку интеграций; при первом открытии кладём туда пример."""
        from src.integrations import folder
        from src.web_services import system_open
        path = folder(store.root)
        path.mkdir(parents=True, exist_ok=True)
        example = path / 'example.json.txt'
        if not any(path.iterdir()):
            example.write_text(json.dumps(EXAMPLE_INTEGRATION, ensure_ascii=False, indent=2), encoding='utf-8')
        opened = is_desktop() and system_open(str(path))
        return jsonify(success=True, opened=bool(opened), path=str(path))

    @app.post('/api/ext/open-folder')
    def ext_open_folder():
        """Папка расширения — её выбирают в chrome://extensions → «Загрузить распакованное»."""
        import sys
        from src.web_services import system_open
        base = Path(getattr(sys, '_MEIPASS', root))
        folder = base / 'browser_extension'
        opened = is_desktop() and folder.is_dir() and system_open(str(folder))
        return jsonify(success=True, opened=bool(opened), path=str(folder))

    @app.post('/api/account/server')
    def account_server():
        return account_reply(lambda: license.set_server((request.get_json() or {}).get('url', '')))

    @app.post('/api/account/promo')
    def account_promo():
        return account_reply(lambda: license.promo((request.get_json() or {}).get('code', '')))

    @app.post('/api/account/check')
    def account_check():
        return account_reply(license.check_payment)

    @app.post('/api/account/checkout')
    def account_checkout():
        data = license.checkout(str((request.get_json() or {}).get('plan', '')))
        opened = False
        if is_desktop():
            from src.web_services import system_open
            try:
                opened = bool(system_open(data['url']))
            except Exception:
                log.exception('Cannot open payment page')
        return jsonify(success=True, url=data['url'], opened=opened)

    # ---------------- сценарии и блокировки ----------------
    @app.get('/api/scenarios')
    def scenarios_list():
        from src.site_groups import GROUPS, ORDER
        groups = [{'id': g, 'title': GROUPS[g]['title'], 'count': len(GROUPS[g]['domains'])} for g in ORDER]
        return jsonify(success=True, scenarios=scenarios.scenarios(), state=scenarios.summary(), groups=groups)

    @app.post('/api/scenarios')
    def scenarios_save():
        saved = scenarios.save((request.get_json() or {}).get('scenarios'))
        return jsonify(success=True, scenarios=saved, state=scenarios.summary())

    @app.post('/api/scenarios/start')
    def scenarios_start():
        data = request.get_json() or {}
        minutes = data.get('minutes')
        minutes = int(minutes) if str(minutes or '').isdigit() else None
        message = scenarios.start(str(data.get('name', '')), minutes)
        return jsonify(success=True, message=message, state=scenarios.summary())

    @app.post('/api/scenarios/stop')
    def scenarios_stop():
        data = request.get_json(silent=True) or {}
        message = scenarios.unblock(str(data.get('value', ''))) if data.get('unblock') else scenarios.stop()
        return jsonify(success=True, message=message, state=scenarios.summary())

    # ---------------- напоминания ----------------
    # ---------------- скиллы и чек-лист нововведений ----------------
    @app.get('/api/skills')
    def skills_list():
        return jsonify(success=True, skills=skills.list(), folder=str(skills.folder),
                       checklist=checklist.summary())

    @app.post('/api/skills')
    def skills_save():
        skill = skills.save(request.get_json(silent=True) or {})
        return jsonify(success=True, skill=skill, skills=skills.list())

    @app.post('/api/skills/<skill_id>/enabled')
    def skills_enabled(skill_id):
        skill = skills.set_enabled(skill_id, bool((request.get_json(silent=True) or {}).get('enabled')))
        if skill is None:
            return jsonify(success=False, message='Скилл не найден'), 404
        return jsonify(success=True, skill=skill)

    @app.post('/api/skills/<skill_id>/delete')
    def skills_delete(skill_id):
        return jsonify(success=skills.delete(skill_id), skills=skills.list())

    @app.post('/api/skills/import')
    def skills_import():
        upload = request.files.get('file')
        if upload is None:
            raise ValueError('Выберите файл скилла (.md)')
        raw = upload.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ValueError('Файл скилла слишком большой (до 64 КБ)')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Файл должен быть в кодировке UTF-8')
        skill = skills.import_text(text, upload.filename or '')
        return jsonify(success=True, skill=skill, skills=skills.list())

    @app.get('/api/skills/<skill_id>/export')
    def skills_export(skill_id):
        from src.skills import to_markdown
        skill = skills.get(skill_id)
        if skill is None:
            return jsonify(success=False, message='Скилл не найден'), 404
        return Response(to_markdown(skill), mimetype='text/markdown; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{skill["id"]}.md"'})

    @app.post('/api/skills/open-folder')
    def skills_open_folder():
        from src.web_services import system_open
        opened = is_desktop() and system_open(str(skills.folder))
        return jsonify(success=True, opened=bool(opened), path=str(skills.folder))

    # ---------------- саморазвитие ----------------
    def proposal_view(item):
        keys = ('id', 'kind', 'title', 'text', 'details', 'status', 'version', 'phrase', 'created')
        return {k: item.get(k) for k in keys}

    def learning_id(value):
        if not re.fullmatch(r'[a-z]{2}[0-9a-f]{10}', str(value)):
            raise ValueError('Неверный идентификатор')
        return value

    @app.get('/api/learning')
    def learning_status():
        return jsonify(success=True, **learning.status())

    @app.get('/api/learning/proposals/<pid>')
    def learning_proposal(pid):
        item = learning.proposal(learning_id(pid))
        if item is None:
            return jsonify(success=False, message='Предложение не найдено'), 404
        return jsonify(success=True, proposal=proposal_view(item), version=learning.version())

    @app.post('/api/learning/proposals/<pid>/<action>')
    def learning_decide(pid, action):
        if action not in ('apply', 'dismiss'):
            raise ValueError('Неизвестное действие')
        data = request.get_json(silent=True) or {}
        phrase = data.get('phrase') if action == 'apply' else None
        item = learning.decide(learning_id(pid), apply=action == 'apply',
                               phrase=str(phrase)[:80] if phrase is not None else None)
        return jsonify(success=True, proposal=proposal_view(item), version=learning.version())

    @app.get('/api/learning/versions/<int:n>')
    def learning_version(n):
        found = next((v for v in learning.data.history if v['n'] == n), None)
        if found is None:
            return jsonify(success=False, message='Такой версии нет'), 404
        return jsonify(success=True, active=bool(found.get('active')), title=found['title'], version=learning.version())

    @app.post('/api/learning/versions/<int:n>/<action>')
    def learning_version_action(n, action):
        if action == 'revert':
            found, notes = learning.revert(n)
            message = f'Отменил: {found["title"]}.' if found else 'Эта версия уже отменена.'
            if notes:
                message += ' Не тронул: ' + '; '.join(notes[:2]) + '.'
        elif action == 'restore':
            found = learning.restore(n)
            message = f'Вернул: {found["title"]}.' if found else (
                'Вернуть не получилось: ' + '; '.join(learning.last_notes[:2]) if learning.last_notes
                else 'Эта версия уже действует.')
        else:
            raise ValueError('Неизвестное действие')
        return jsonify(success=True, message=message, version=learning.version())

    @app.post('/api/learning/rollback')
    def learning_rollback():
        data = request.get_json(silent=True) or {}
        try:
            steps = int(data.get('steps') or 1)
            to = int(data['to']) if data.get('to') is not None else None
        except (TypeError, ValueError):
            raise ValueError('Номер версии — целое число')
        if steps < 1 or steps > 1000 or (to is not None and to < 0):
            raise ValueError('Неверный номер версии')
        versions, notes = learning.rollback(steps=steps, to=to)
        return jsonify(success=True, message=learning._say_rollback(versions, notes, everything=to == 0),
                       version=learning.version())

    @app.post('/api/learning/redo')
    def learning_redo():
        batch = learning.redo()
        message = f'Вернул: {learning._titles(batch)}.' if batch else 'Возвращать нечего: откатов не было.'
        if learning.last_notes:
            message += ' Не тронул: ' + '; '.join(learning.last_notes[:2]) + '.'
        return jsonify(success=True, message=message, version=learning.version())

    @app.post('/api/learning/lessons')
    def learning_add_lesson():
        version = learning.add_lesson(str((request.get_json(silent=True) or {}).get('text') or '')[:300])
        return jsonify(success=True, version=version['n'] if version else learning.version())

    @app.post('/api/learning/lessons/<lid>/delete')
    def learning_delete_lesson(lid):
        return jsonify(success=bool(learning.forget_lesson(learning_id(lid))), version=learning.version())

    @app.post('/api/learning/phrases')
    def learning_add_phrase():
        data = request.get_json(silent=True) or {}
        phrase = str(data.get('phrase') or '').strip()[:80]
        command = str(data.get('command') or '').strip()[:200]
        if not phrase or not command:
            raise ValueError('Нужны фраза и команда')
        if not learning._is_command(command, store.settings('device:desktop')):
            raise ValueError(f'Не знаю команды «{command}». Напишите её так, как я понимаю: «открой ютуб».')
        version = learning.teach_phrase(phrase, command)
        return jsonify(success=True, version=version['n'] if version else learning.version())

    @app.post('/api/learning/phrases/<pid>/delete')
    def learning_delete_phrase(pid):
        return jsonify(success=bool(learning.forget_phrase(learning_id(pid))), version=learning.version())

    @app.post('/api/learning/reflect')
    def learning_reflect():
        return jsonify(success=True, message=learning.reflect_soon())

    @app.post('/api/learning/wipe')
    def learning_wipe():
        learning.wipe()
        return jsonify(success=True, version=learning.version())

    @app.get('/api/checklist')
    def checklist_view():
        return jsonify(success=True, releases=checklist.view())

    @app.post('/api/checklist')
    def checklist_mark():
        data = request.get_json(silent=True) or {}
        mark = checklist.mark(str(data.get('id', '')), str(data.get('status', '')),
                              data.get('note') if 'note' in data else None)
        return jsonify(success=True, mark=mark)

    @app.get('/api/checklist/report')
    def checklist_report():
        return jsonify(success=True, text=checklist.report())

    @app.get('/api/reminders')
    def reminders_list():
        return jsonify(success=True, items=reminders.list(), muted=store.meta('reminders_muted') == '1')

    @app.post('/api/reminders')
    def reminders_save():
        items = reminders.replace((request.get_json() or {}).get('items'))
        return jsonify(success=True, items=items)

    @app.post('/api/reminders/mute')
    def reminders_mute():
        store.set_meta('reminders_muted', '1' if (request.get_json() or {}).get('muted') else None)
        return jsonify(success=True, muted=store.meta('reminders_muted') == '1')

    @app.post('/api/reminders/test')
    def reminders_test():
        item = next((i for i in reminders.list() if i['id'] == (request.get_json() or {}).get('id')), None)
        if item is None:
            raise ValueError('Напоминание не найдено')
        text = reminders.say_text(item, store.settings('device:desktop'))
        speak(text)
        return jsonify(success=True, text=text)

    # ---------------- макросы ----------------
    @app.get('/api/macros')
    def macros_list():
        return jsonify(success=True, items=macros.list())

    @app.post('/api/macros')
    def macros_save():
        return jsonify(success=True, items=macros.save((request.get_json() or {}).get('items')))

    @app.post('/api/macros/run')
    def macros_run():
        """Запуск кнопкой — как голосовая команда «запусти макрос …» (через общую очередь команд)."""
        name = str((request.get_json() or {}).get('name', ''))
        if macros.find(name) is None:
            raise ValueError('Макрос не найден')
        result, _ = service.run('запусти макрос ' + name, 'device:desktop', store.settings('device:desktop'),
                                source='text', speak=is_desktop())
        return jsonify(success=True, message=result)

    # ---------------- узнавание голоса ----------------
    def voice_status():
        loop = getattr(voice, 'target', None) or voice
        enrolling = getattr(loop, 'enroll', None)
        return dict(model_installed=gate.model_installed(), profiles=gate.summary(), has_password=gate.has_password(),
                    enrolling=isinstance(enrolling, dict))

    @app.get('/api/voiceid')
    def voiceid_status():
        return jsonify(success=True, **voice_status())

    @app.post('/api/voiceid/download')
    def voiceid_download():
        from src.model_downloader import start_download
        started = start_download(store.root, ['speaker'], events)
        return jsonify(success=True, started=started)

    @app.post('/api/voiceid/enroll')
    def voiceid_enroll():
        if voice is None or not hasattr(voice, 'start_enroll'):
            raise ValueError('Голосовое управление не запущено')
        name = str((request.get_json() or {}).get('name') or '').strip()[:40]
        message = voice.start_enroll(name or ('Владелец' if not gate.profiles() else f'Голос {len(gate.profiles()) + 1}'))
        return jsonify(success=True, message=message, **voice_status())

    @app.post('/api/voiceid/delete')
    def voiceid_delete():
        gate.delete(str((request.get_json() or {}).get('id', '')))
        return jsonify(success=True, **voice_status())

    @app.post('/api/voiceid/password')
    def voiceid_password():
        gate.set_password(str((request.get_json() or {}).get('password', '')))
        return jsonify(success=True, **voice_status())

    # ---------------- телефон: настройки ПК и голос ПК ----------------
    @app.get('/api/remote/settings')
    def remote_settings():
        """Настройки ассистента на ПК для экрана «Настройки» в приложении телефона."""
        from src.settings_schema import as_json
        return jsonify(success=True, sections=as_json(local_tts.assistant_voices()),
                       values=store.settings('device:desktop'), premium=store.is_premium())

    @app.post('/api/remote/settings')
    def remote_settings_save():
        values = (request.get_json() or {}).get('values') or {}
        if not isinstance(values, dict):
            raise ValueError('Нужны значения настроек')
        value = store.save_settings('device:desktop', values)
        settings_changed(value)
        return jsonify(success=True, values=value)

    # ---------------- все команды ----------------
    @app.get('/api/commands')
    def commands_catalog():
        from src.command_catalog import catalog
        return jsonify(success=True, wake=store.settings('device:desktop').get('wake_word', 'Андрей'), categories=catalog())

    # ---------------- доступ с телефона ----------------
    def firewall_status():
        """Windows: есть ли правило брандмауэра, пускающее телефон к ассистенту."""
        import sys
        if sys.platform != 'win32':
            return None
        import subprocess
        try:
            result = subprocess.run(['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=Andrey phone'],
                                    capture_output=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return store.meta('firewall_rule') == '1'

    @app.post('/api/connection/firewall')
    def connection_firewall():
        """Разрешить входящие подключения телефона (Windows просит подтверждение администратора)."""
        import sys
        if sys.platform != 'win32':
            return jsonify(success=True, message='На этой системе ничего настраивать не нужно.')
        import ctypes
        port = request.host.split(':')[-1]
        program = sys.executable
        args = (f'advfirewall firewall add rule name="Andrey phone" dir=in action=allow protocol=TCP '
                f'localport={port} profile=private,public,domain program="{program}" enable=yes')
        code = ctypes.windll.shell32.ShellExecuteW(None, 'runas', 'netsh', args, None, 0)
        if code <= 32:
            raise ValueError('Windows не разрешил изменить брандмауэр. Подтвердите запрос администратора.')
        store.set_meta('firewall_rule', '1')
        return jsonify(success=True, message='Готово: телефон может подключаться к компьютеру.')

    # ---------------- интеграции ----------------
    from src.connectors import ConnectorError

    @app.errorhandler(ConnectorError)
    def connector_error(exc):
        return jsonify(success=False, message=str(exc)), 400

    @app.get('/api/connectors')
    def connectors_list():
        return jsonify(success=True, items=connectors.status(), tracker_url=connectors.get('tracker').url)

    @app.post('/api/connectors/<connector_id>/connect')
    def connectors_connect(connector_id):
        data = request.get_json(silent=True) or {}
        connector = connectors.get(connector_id)
        if isinstance(data.get('fields'), dict):
            user = connector.use_fields(data['fields'])
            return jsonify(success=True, connected=True, user=user)
        if data.get('token'):
            user = connector.use_token(str(data['token']))
            return jsonify(success=True, connected=True, user=user)
        result = connector.start(request.host_url)
        opened = False
        if result.get('url') and is_desktop():
            open_link(result['url'])
            opened = True
        return jsonify(success=True, opened=opened, **result)

    @app.post('/api/connectors/<connector_id>/poll')
    def connectors_poll(connector_id):
        connector = connectors.get(connector_id)
        return jsonify(success=True, **(connector.poll() if hasattr(connector, 'poll') else {'done': connector.connected()}))

    @app.post('/api/connectors/<connector_id>/disconnect')
    def connectors_disconnect(connector_id):
        connectors.get(connector_id).disconnect()
        return jsonify(success=True, items=connectors.status())

    @app.post('/api/connectors/tracker/url')
    def connectors_tracker_url():
        from src.tracker import check_url
        store.set_meta('tracker_url', check_url((request.get_json() or {}).get('url', '')))
        return jsonify(success=True, items=connectors.status())

    @app.get('/oauth/<connector_id>/callback')
    def oauth_callback(connector_id):
        """Сюда браузер возвращается после входа в аккаунт приложения (Трекер, Google, Miro)."""
        import html
        error = request.args.get('error')
        try:
            if error:
                raise ConnectorError(request.args.get('error_description') or error)
            user = connectors.callback(connector_id, request.args.get('code', ''), request.args.get('state', ''))
            title, text = 'Готово', f'Аккаунт {html.escape(user or "")} подключён к «Андрею». Это окно можно закрыть.'
            events.emit('connectors', id=connector_id, connected=True)
        except ConnectorError as exc:
            title, text = 'Не получилось', html.escape(str(exc))
        page = ('<!doctype html><meta charset="utf-8"><title>Андрей</title><body style="font:18px system-ui;'
                'background:#0b1020;color:#e8ecff;display:grid;place-items:center;height:100vh;margin:0">'
                f'<div style="text-align:center"><h1>{title}</h1><p>{text}</p></div>')
        return Response(page, mimetype='text/html')

    # ---------------- Трекер ----------------
    @app.get('/api/tracker')
    def tracker_status():
        return jsonify(success=True, **tracker.status())

    @app.post('/api/tracker/login')
    def tracker_login():
        from src.tracker import TrackerError
        data = request.get_json() or {}
        try:
            if data.get('token'):
                value = tracker.use_token(data.get('url', ''), data['token'])
            else:
                value = tracker.login(data.get('url', ''), data.get('email', ''), data.get('password', ''))
        except TrackerError as exc:
            raise ValueError(str(exc))
        return jsonify(success=True, **value)

    @app.post('/api/tracker/logout')
    def tracker_logout():
        return jsonify(success=True, **tracker.logout())

    @app.post('/api/tracker/test')
    def tracker_test():
        from datetime import date
        from src.tracker import TrackerError
        try:
            items = tracker.tasks(date.today())
        except TrackerError as exc:
            raise ValueError(str(exc))
        return jsonify(success=True, message=f'Связь есть. Задач на сегодня: {len(items)}.')

    # ---------------- 6.0: поддержка ----------------
    @app.get('/api/support')
    def support_info():
        return jsonify(success=True, **support.info())

    @app.post('/api/support/feedback')
    def support_feedback():
        data = request.get_json(silent=True) or {}
        return jsonify(success=True, **support.send(data.get('text'), data.get('contact', '')))

    @app.post('/api/support/check')
    def support_check():
        return jsonify(success=True, **support.check())

    @app.post('/api/support/telegram')
    def support_telegram():
        data = request.get_json(silent=True) or {}
        return jsonify(success=True, **support.open_telegram(str(data.get('text', ''))[:3000]))

    # ---------------- 6.0: документы в чате ----------------
    @app.post('/api/documents/<doc_id>/<action>')
    def document_action(doc_id, action):
        path = documents.get(doc_id)
        data = request.get_json(silent=True) or {}
        if action == 'open':
            message = documents.open([path])
        elif action == 'reveal':
            message = documents.reveal([path])
        elif action == 'copy':
            message = documents.copy([path])
        elif action == 'telegram':
            who = str(data.get('who', '')).strip()
            if not who:
                raise ValueError('Кому отправить?')
            message = documents.to_messenger([path], str(data.get('app', 'telegram')), who)
        elif action == 'email':
            message = documents.to_email([path], str(data.get('to', '')))
        elif action == 'save':
            message = documents.save_to([path], str(data.get('folder', 'рабочий стол')))
        else:
            raise ValueError('Неизвестное действие')
        return jsonify(success=True, message=message)

    @app.get('/api/documents/<doc_id>/file')
    def document_file(doc_id):
        return send_file(documents.get(doc_id), as_attachment=True)

    # ---------------- 6.0: мгновенный поиск ----------------
    @app.get('/api/files/search')
    def files_search():
        query = request.args.get('q', '').strip()[:200]
        found = file_index.search(query, limit=30) if query else []
        return jsonify(success=True, results=found, elapsed_ms=getattr(file_index, 'last_elapsed', 0),
                       status=file_index.status())

    @app.get('/api/files/status')
    def files_status():
        return jsonify(success=True, status=file_index.status())

    @app.post('/api/files/reindex')
    def files_reindex():
        threading.Thread(target=file_index.scan, daemon=True, name='file-index-manual').start()
        return jsonify(success=True, status=file_index.status())

    @app.post('/api/files/open')
    def files_open():
        data = request.get_json(silent=True) or {}
        path = Path(str(data.get('path', '')))
        if not path.exists() or not file_index.contains(path):
            raise ValueError('Файл не найден')
        (oshelp.reveal if data.get('reveal') else oshelp.open_path)(path)
        return jsonify(success=True)

    # ---------------- 6.0: игры ----------------
    @app.get('/api/games')
    def games_status():
        return jsonify(success=True, **agent.games.status())

    @app.post('/api/games')
    def games_save():
        data = request.get_json(silent=True) or {}
        if 'profiles' in data:
            agent.games.save_profiles(data['profiles'])
        if 'active' in data:
            agent.games.active = bool(data['active'])
            agent.games.forced = data.get('profile') or None
        return jsonify(success=True, **agent.games.status())

    # ---------------- 6.0: голоса ----------------
    @app.get('/api/voices/catalog')
    def voices_catalog():
        from src import voice_catalog
        catalog = voice_catalog.load_catalog(store.root)
        language = request.args.get('lang', 'ru')[:5]
        return jsonify(success=True, languages=voice_catalog.languages(catalog),
                       voices=voice_catalog.list_voices(catalog, language, store.root))

    @app.post('/api/voices/install')
    def voices_install():
        from src import voice_catalog
        key = str((request.get_json(silent=True) or {}).get('key', ''))
        voice = voice_catalog.install(store.root, key, voice_catalog.load_catalog(store.root))
        return jsonify(success=True, voice=voice, assistant=local_tts.assistant_voices())

    @app.post('/api/voices/import')
    def voices_import():
        from src import voice_catalog
        voice = voice_catalog.import_files(store.root, request.files.getlist('files'))
        return jsonify(success=True, voice=voice, assistant=local_tts.assistant_voices())

    @app.post('/api/voices/remove')
    def voices_remove():
        from src import voice_catalog
        voice_catalog.remove(store.root, str((request.get_json(silent=True) or {}).get('id', '')))
        return jsonify(success=True, assistant=local_tts.assistant_voices())

    # ---------------- 6.0: умный дом ----------------
    @app.get('/api/smarthome')
    def smarthome_get():
        from src.connector_config import YANDEX_IOT_CLIENT_ID
        return jsonify(success=True, config=smarthome.public(),
                       yandex_token_url=('https://oauth.yandex.ru/authorize?response_type=token&client_id=' +
                                         YANDEX_IOT_CLIENT_ID) if YANDEX_IOT_CLIENT_ID else '')

    @app.post('/api/smarthome/save')
    def smarthome_save():
        data = request.get_json(silent=True) or {}
        return jsonify(success=True, config=smarthome.save(str(data.get('section', '')), data.get('data') or {}))

    @app.post('/api/smarthome/<action>')
    def smarthome_action(action):
        data = request.get_json(silent=True) or {}
        what = str(data.get('what', ''))
        number = int(data['number']) if str(data.get('number', '')).isdigit() else None
        if action == 'discover':
            return jsonify(success=True, found=smarthome.discover(what))
        if action == 'apps':        # какие приложения для фильмов есть на телевизоре
            found, message = smarthome.detect_tv_apps(number)
            return jsonify(success=True, found=found, message=message, config=smarthome.public())
        if action == 'status':      # какие телевизоры сейчас в сети (выключенные остаются в списке)
            return jsonify(success=True, online={str(k): v for k, v in smarthome.tv_status().items()})
        if action == 'pair':
            message = smarthome.pair(what, number)
            return jsonify(success=True, message=message, config=smarthome.public(),
                           need_code=what == 'tv' and smarthome.waiting_code(number))
        if action == 'code':      # код с экрана телевизора (пульт Google TV), один раз на телевизор
            message = smarthome.submit_tv_code(str(data.get('code', ''))[:80], number)
            return jsonify(success=True, message=message, config=smarthome.public(),
                           need_code=smarthome.waiting_code(number))
        if action == 'test':
            return jsonify(success=True, message=smarthome.test(what, number))
        if action == 'adb':
            from src.smarthome import download_adb
            return jsonify(success=True, message=f'ADB установлен: {download_adb(store.root)}')
        raise ValueError('Неизвестное действие')

    # ---- 6.7: память о вас ----
    def fact_id(value):
        if not re.fullmatch(r'[0-9a-f]{10}', str(value)):
            raise ValueError('Неверный идентификатор')
        return value

    @app.get('/api/memory')
    def memory_list():
        settings = store.settings('device:desktop')
        return jsonify(success=True, facts=memory.public(), auto=settings.get('memory_auto', True))

    @app.post('/api/memory')
    def memory_add():
        text = str((request.get_json(silent=True) or {}).get('text') or '').strip()[:300]
        fact, problem = memory.add(text, source='manual')
        if problem == 'secret':
            raise ValueError('Пароли, коды и номера карт не запоминаю.')
        if fact is None:
            raise ValueError('Напишите, что запомнить: например, «Я люблю кофе без сахара».')
        return jsonify(success=True, fact=fact, facts=memory.public())

    @app.post('/api/memory/<fid>/<action>')
    def memory_action(fid, action):
        if action == 'forget':
            found = memory.forget(fact_id(fid))
        elif action == 'allow':
            found = memory.allow(fact_id(fid))
        else:
            raise ValueError('Неизвестное действие')
        if found is None:
            return jsonify(success=False, message='Такого факта уже нет'), 404
        return jsonify(success=True, facts=memory.public())

    @app.post('/api/memory/clear')
    def memory_clear():
        removed = memory.clear()
        return jsonify(success=True, removed=len(removed), facts=[])

    @app.post('/api/memory/restore')
    def memory_restore():
        back = memory.restore()
        return jsonify(success=True, restored=len(back), facts=memory.public())

    # ---- 6.6: диктовка по клавише (как в Aqua Voice) ----
    def dictation_or_none():
        return app.extensions.get('dictation')

    @app.get('/api/dictation')
    def dictation_status():
        dictation = dictation_or_none()
        if dictation is None:
            settings = store.settings('device:desktop')
            return jsonify(success=True, available=False, enabled=settings.get('dictation_enabled', True),
                           active=False, history=[], error='Диктовка по клавише работает в приложении Агента на ПК.')
        return jsonify(success=True, available=True, **dictation.status())

    def dictation_index():
        try:
            return int((request.get_json(silent=True) or {}).get('index'))
        except (TypeError, ValueError):
            raise ValueError('Номер диктовки — целое число')

    @app.post('/api/dictation/<action>')
    def dictation_action(action):
        dictation = dictation_or_none()
        if dictation is None:
            raise ValueError('Диктовка по клавише работает в приложении Агента на ПК.')
        if action == 'clear':
            dictation.clear_history()
            return jsonify(success=True, history=[])
        if action == 'delete':
            dictation.delete(dictation_index())
            return jsonify(success=True, history=dictation.history())
        if action == 'copy':
            if not dictation.copy(dictation_index()):
                raise ValueError('Буфер обмена занят другой программой — попробуйте ещё раз.')
            return jsonify(success=True, message='Скопировано.')
        raise ValueError('Неизвестное действие')

    return app

