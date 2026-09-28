"""Authenticated local API shared by the Windows UI, the settings window and the Android remote."""
import json
import logging
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
from src.events import EventBus
from src.local_tts_service import LocalTTSService
from src.passwords import matches as check_password_hash
from src.service import AssistantService, Busy
from src.speech import SpeechService, SpeechError
from src.license import AccountError, LicenseClient
from src.storage import PremiumRequired, Store, SECRET_NAMES

log = logging.getLogger(__name__)

VOICE_IDS = ('irina', 'denis', 'amy')
VERSION = '5.3'


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'


def build_agent(store, events=None):
    """Полный агент: браузер, управление ПК, ИИ."""
    from src.agent import LocalComputerAgent
    from src.brain import Brain
    from src.browser_control import BrowserController
    from src.desktop import DesktopController, DesktopCommands
    browser = BrowserController(store.root)
    brain = Brain(store)
    desktop = DesktopController()
    commands = DesktopCommands(desktop, brain=brain, browser=browser, root=store.root)
    return LocalComputerAgent(browser, brain=brain, desktop_commands=commands)


def create_app(store=None, recognizer=None, agent=None, *, events=None, player=None, voice=None, license=None):
    root = Path(__file__).resolve().parent
    store = store or Store()
    events = events or EventBus()
    speech = recognizer or SpeechService(store.root, store.settings('device:desktop'))
    agent = agent or build_agent(store, events)
    local_tts = LocalTTSService(store.root)
    service = AssistantService(store, agent, events, player)
    license = license or LicenseClient(store)
    store.premium = license.is_premium
    app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
    app.secret_key = store.meta('session_secret')
    app.config.update(MAX_CONTENT_LENGTH=12 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', PERMANENT_SESSION_LIFETIME=timedelta(days=365),
                      SEND_FILE_MAX_AGE_DEFAULT=0)
    app.extensions.update(store=store, speech=speech, agent=agent, local_tts=local_tts, events=events,
                          service=service, player=player, voice=voice, ui=None, on_settings=[],
                          license=license)
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, owner TEXT, result TEXT)')

    def owner():
        device = request.headers.get('X-Device-ID', 'desktop')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', device):
            raise ValueError('Неверный идентификатор устройства')
        return 'user:' + session['user'] if session.get('user') else 'device:' + device

    def is_desktop():
        return request.headers.get('X-Device-ID', 'desktop') == 'desktop'

    def settings_changed(value):
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

    @app.before_request
    def authenticate():
        if request.path.startswith('/api/'):
            origin = request.headers.get('Origin')
            if origin and urlparse(origin).netloc != request.host:
                return jsonify(success=False, message='Чужой Origin запрещён'), 403
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
        return jsonify(success=True, provider=settings['llm_provider'], local=local)

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

    # ---------------- история ----------------
    @app.get('/api/history')
    def history():
        return jsonify(success=True, history=store.history(owner(), limit=300))

    @app.post('/api/history/clear')
    def clear():
        store.clear(owner())
        brain = getattr(agent, 'brain', None)
        if brain is not None and hasattr(brain, 'forget'):
            brain.forget(owner())
        return jsonify(success=True)

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
        result, spoken = service.run(message, who, store.settings(who), source='text', speak=is_desktop())
        finish(ident, result)
        return jsonify(success=True, response=result, spoken=spoken)

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
        channel = queue.Queue()

        def work():
            try:
                if existing:
                    channel.put({'type': 'done', 'response': existing[1] or 'Команда уже принята.', 'duplicate': True})
                    return
                result, spoken = service.run(message, who, settings, source='text', speak=desktop,
                                             on_text=lambda chunk: channel.put({'type': 'delta', 'text': chunk}))
                finish(ident, result)
                channel.put({'type': 'done', 'response': result, 'spoken': spoken})
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
        return jsonify(success=True, voices=local_tts.available_voices())

    @app.post('/api/ai/synthesize_local')
    def synthesize_local():
        data = request.get_json(silent=True) or {}
        text = str(data.get('text', '')).strip()
        if not 1 <= len(text) <= 2000:
            return jsonify(success=False, error='Text 1-2000 chars')
        voice_id = str(data.get('voice', 'irina'))
        if voice_id not in VOICE_IDS:
            voice_id = 'irina'
        try:
            audio_path = local_tts.synthesize(text, voice_id, preset=store.settings(owner()).get('voice_preset', 'classic'))
        except Exception as exc:
            return jsonify(success=False, error=str(exc))
        if not audio_path:
            return jsonify(success=False, error='Fallback to system')
        return jsonify(success=True, audio_url='/tts_audio/' + Path(audio_path).name)

    @app.get('/tts_audio/<filename>')
    def serve_tts_audio(filename):
        if not re.fullmatch(r'[0-9a-f]{20}\.wav', filename):
            return 'Not found', 404
        audio_file = Path(local_tts.cache) / filename
        if not audio_file.exists():
            return 'Not found', 404
        return send_file(str(audio_file), mimetype='audio/wav')

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

    # ---------------- подключение и профили ----------------
    @app.get('/api/connection')
    def connection():
        return jsonify(success=True, ip=local_ip(), port=request.host.split(':')[-1],
                       storage=str(store.root), token=store.meta('pairing_token'), user=session.get('user'))

    def phone_link(device='iphone'):
        port = request.host.split(':')[-1]
        return f"http://{local_ip()}:{port}/#token={store.meta('pairing_token')}&device={device}"

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

    return app
