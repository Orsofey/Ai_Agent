"""Desktop entry point: single instance, background voice, tray icon, settings window."""
import ctypes
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

from src.storage import Store

TITLE = 'Local AI Agent'
OWNER = 'device:desktop'


def message(text):
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)
    elif sys.platform == 'darwin':
        import subprocess
        safe = text.replace('\\', '').replace('"', "'")
        subprocess.run(['osascript', '-e', f'display alert "{TITLE}" message "{safe}"'], timeout=60)
    else:
        print(text, file=sys.stderr)


def focus_existing():
    if sys.platform == 'darwin':
        import subprocess
        return subprocess.run(['osascript', '-e', f'tell application "{TITLE}" to activate'], timeout=10).returncode == 0
    if sys.platform != 'win32':
        return False
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    hwnd = u.FindWindowW(None, TITLE)
    if hwnd:
        u.ShowWindow(hwnd, 9)
        u.SetForegroundWindow(hwnd)
        return True
    return False


class DesktopUI:
    """Главное окно (pywebview); настройки открываются в нём же отдельной страницей."""

    def __init__(self, base_url, store):
        self.base_url = base_url
        self.store = store
        self.main = None
        self.settings_window = None
        self.quitting = False
        self.lock = threading.Lock()
        self.extra = []          # окошко диктовки: закрывается вместе с приложением

    def url(self, path=''):
        return f'{self.base_url}{path}#token={self.store.meta("pairing_token")}'

    def create_main(self, hidden=False):
        import webview
        self.main = webview.create_window(TITLE, self.url('/'), width=1180, height=820, min_size=(820, 600),
                                          background_color='#0b1020', hidden=hidden)
        self.main.events.closing += self._on_closing
        return self.main

    def _on_closing(self):
        # Крестик прячет окно в трей: агент продолжает слушать голосовые команды.
        settings = self.store.settings(OWNER)
        if not self.quitting and settings.get('minimize_to_tray', True) and self.tray_available:
            self.main.hide()
            return False
        self.quitting = True
        for window in [self.settings_window] + self.extra:
            if window is not None:
                try:
                    window.destroy()
                except Exception:
                    pass
        return True

    tray_available = False

    def open_settings(self, section=''):
        """Настройки — страница в главном окне (из трея и голосом тоже), отдельного окна больше нет."""
        path = '/settings' + ('?section=' + section if section else '')
        with self.lock:
            if self.main is None:
                return
            try:
                self.main.load_url(self.url(path))
            except Exception:
                return
        self.show_main()

    def show_main(self):
        if self.main is not None:
            self.main.show()
            self.main.restore()
            focus_existing()

    def quit(self):
        self.quitting = True
        if self.main is not None:
            self.main.destroy()


def start_tray(ui, voice, store, dictation=None):
    """Иконка в области уведомлений: открыть, настройки, слушать, диктовка, выход."""
    if sys.platform == 'darwin':
        return None  # на Mac меню строки требует главного потока, который занят окном; есть иконка в Dock
    try:
        import pystray
        from PIL import Image
    except Exception:
        return None
    from pathlib import Path
    icon_path = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'static' / 'icon-192.png'

    def listening(_item):
        return bool(store.settings(OWNER).get('voice_enabled', True))

    def toggle_listening(_icon, _item):
        value = not listening(None)
        settings = store.save_settings(OWNER, {'voice_enabled': value})
        voice.apply_settings(settings)

    def dictating(_item):
        return bool(store.settings(OWNER).get('dictation_enabled', True))

    def toggle_dictation(_icon, _item):
        settings = store.save_settings(OWNER, {'dictation_enabled': not dictating(None)})
        if dictation is not None:
            dictation.apply_settings(settings)

    menu = pystray.Menu(
        pystray.MenuItem('Открыть', lambda: ui.show_main(), default=True),
        pystray.MenuItem('Настройки', lambda: ui.open_settings()),
        pystray.MenuItem('Слушать команды', toggle_listening, checked=listening),
        pystray.MenuItem('Сказать команду (Ctrl+Alt+Пробел)', lambda: voice.listen_once()),
        pystray.MenuItem('Диктовка по клавише', toggle_dictation, checked=dictating),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Выход', lambda icon: (icon.stop(), ui.quit())),
    )
    icon = pystray.Icon('LocalAIAgent', Image.open(icon_path), TITLE, menu)
    threading.Thread(target=icon.run, daemon=True, name='tray').start()
    ui.tray_available = True
    return icon


def self_test():
    """Проверка собранного приложения: все модули грузятся (без окна, микрофона и моделей)."""
    import importlib
    names = ['app', 'waitress', 'webview', 'numpy', 'onnxruntime', 'onnx_asr', 'sounddevice', 'src.speech.voice_loop',
             'src.dictation', 'src.dictation.insert', 'src.dictation.popup', 'src.coach', 'src.coach_popup',
             'src.updates', 'src.approvals', 'src.user_facts', 'src.local_tts_service', 'src.brain']
    if sys.platform == 'darwin':
        names += ['Quartz', 'AppKit', 'src.macos', 'src.desktop.macapi']
    for name in names:
        importlib.import_module(name)
    if sys.stdout is not None:
        print('self-test ok:', len(names), 'modules')
    return 0


def main():
    if '--self-test' in sys.argv:
        sys.exit(self_test())
    store = Store()
    logs = store.root / 'logs'
    logs.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                        handlers=[RotatingFileHandler(logs / 'agent.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')])
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(logs / 'native-errors.log', 'a', encoding='utf-8')
    from filelock import FileLock, Timeout
    lock = FileLock(str(store.root / 'instance.lock'))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        if not focus_existing():
            message('Приложение уже запущено или ещё загружается.')
        return
    tray = None
    try:
        from waitress import create_server
        from app import create_app, build_agent
        from src import autostart
        from src.events import EventBus
        from src.local_tts_service import LocalTTSService
        from src.speech import SpeechService
        from src.speech.voice_loop import VoiceAssistant
        from src.tts_player import TTSPlayer
        from src.desktop.hotkey import GlobalHotkey
        from src.dictation import Dictation

        settings = store.settings(OWNER)
        events = EventBus()
        speech = SpeechService(store.root, settings)
        speech.warmup()  # модель грузится, пока открывается окно
        agent = build_agent(store, events)
        player = TTSPlayer(LocalTTSService(store.root), events)
        voice_ref = {}
        app = create_app(store, speech, agent, events=events, player=player,
                         voice=_LazyVoice(voice_ref), background=True)
        service = app.extensions['service']
        voice = VoiceAssistant(speech, service, events, lambda: store.settings(OWNER), OWNER,
                               player=player, desktop_commands=agent.desktop_commands,
                               gate=app.extensions['voice_gate'])
        voice_ref['voice'] = voice
        agent.desktop_commands.desktop.start()  # запоминание последнего активного окна
        # Диктовка как в Aqua Voice: держите правый Alt, говорите — текст вставляется туда, где курсор.
        dictation = Dictation(speech, events, lambda: store.settings(OWNER), store.root, voice=voice, player=player)
        dictation.desktop = agent.desktop_commands.desktop
        agent.dictation = dictation
        app.extensions['dictation'] = dictation

        hotkey = {'current': None}

        def bind_hotkey(value):
            spec = value.get('hotkey') or 'ctrl+alt+space'
            current = hotkey['current']
            if current is not None and current.spec == spec:
                return
            if current is not None:
                current.stop()
                import time
                time.sleep(0.2)  # дать Windows освободить старое сочетание
            hotkey['current'] = GlobalHotkey(spec, voice.listen_once)
            hotkey['current'].start()

        bind_hotkey(settings)
        local_llm = agent.brain.local
        app.extensions['on_settings'] += [voice.apply_settings, bind_hotkey, local_llm.apply_settings,
                                          dictation.apply_settings]
        # Подписка: продление и окончание проверяются в фоне, лицензия работает и офлайн.
        app.extensions['license'].start_background_refresh(app.extensions['account_changed'])
        if settings.get('llm_provider') == 'local':
            # Нейросеть загружается заранее, системная подсказка уже посчитана. При автозапуске Windows — через
            # 40 секунд: 2–3 ГБ модели не должны тормозить вход в систему (первый же вопрос запустит её сразу).
            if '--minimized' in sys.argv:
                timer = threading.Timer(40.0, lambda: agent.brain.warm(store.settings(OWNER)))
                timer.daemon = True
                timer.start()
            else:
                agent.brain.warm(settings)

        if sys.platform == 'win32' and (store.meta('startup_initialized') is None or autostart.enabled()):
            autostart.configure(settings.get('autostart', True))
            store.set_meta('startup_initialized', '1')

        port = int(os.getenv('LOCAL_AI_PORT', '5000'))
        host = os.getenv('LOCAL_AI_HOST', '0.0.0.0')
        server = create_server(app, host=host, port=port, threads=16, max_request_body_size=12 * 1024 * 1024,
                               channel_timeout=300)
        threading.Thread(target=server.run, daemon=True, name='http-server').start()
        voice.start()
        voice.prewarm()  # «Секунду, сэр» звучит без задержки
        dictation.apply_settings(settings)

        # Если модели не встроены в установщик и ещё не скачаны — докачиваем их сами при первом запуске.
        from src.model_downloader import missing_items, start_download
        missing = missing_items(store.root, settings)
        if missing:
            def models_ready():
                current = store.settings(OWNER)
                speech.configure(current)
                if current.get('llm_provider') == 'local':
                    agent.brain.warm(current)
            logging.info('First run: downloading %s', missing)
            start_download(store.root, missing, events, on_done=models_ready)

        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True
        ui = DesktopUI(f'http://127.0.0.1:{port}', store)
        app.extensions['ui'] = ui
        agent.desktop_commands.show_self = ui.show_main   # «Андрей, разверни себя»
        tray = start_tray(ui, voice, store, dictation)

        def quit_for_update():
            # 7.2: установщик обновления запущен — закрываемся, чтобы он заменил файлы (и запустил новую версию).
            if tray is not None:
                try:
                    tray.stop()
                except Exception:
                    pass
            ui.quit()
        app.extensions['updater'].on_quit = quit_for_update
        # При автозапуске Windows агент стартует в трее и сразу слушает.
        ui.create_main(hidden='--minimized' in sys.argv and ui.tray_available)
        from src.dictation import popup as dictation_popup
        dictation.popup = dictation_popup.create(webview, ui.url('/dictation'))
        if dictation.popup is not None:
            ui.extra.append(dictation.popup.window)
            dictation.popup.previous_foreground = ctypes.windll.user32.GetForegroundWindow()
        # 7.0: наставник — персонаж поверх всех окон в правом нижнем углу (на Mac — карточка в окне Андрея).
        from src import coach_popup
        coach = app.extensions['coach']
        coach.popup = coach_popup.create(webview, ui.url('/coach'))
        if coach.popup is not None:
            ui.extra.append(coach.popup.window)
            coach.popup.previous_foreground = ctypes.windll.user32.GetForegroundWindow()
        if sys.platform == 'darwin':
            from src.desktop.macapi import request_permissions
            request_permissions()  # «Универсальный доступ» для печати текста в другие приложения
        webview.start(gui='edgechromium' if sys.platform == 'win32' else None, debug=False,
                      private_mode=False, storage_path=str(store.root / 'webview_profile'))
        voice.stop()
        dictation.stop()
        app.extensions['coach'].stop()
        local_llm.stop()
        if hotkey['current']:
            hotkey['current'].stop()
        browser = agent.browser
        if browser.context is not None:
            browser.call('close_browser')
        server.close()
    except Exception as exc:
        logging.exception('Desktop startup failed')
        message('Не удалось запустить приложение: ' + str(exc) + '\n\nЖурнал: ' + str(logs / 'agent.log') +
                '\nДля Windows требуется WebView2 Runtime.')
    finally:
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        lock.release()


class _LazyVoice:
    """Голосовой цикл создаётся после приложения; API обращается к нему через эту обёртку."""

    def __init__(self, ref):
        self.ref = ref

    def __getattr__(self, name):
        return getattr(self.ref['voice'], name)


if __name__ == '__main__':
    main()
