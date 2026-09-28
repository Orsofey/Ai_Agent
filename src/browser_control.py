"""Own browser profile, serial Playwright worker. Never touches unrelated tabs."""
from concurrent.futures import Future, TimeoutError
import logging
import os
import queue
import re
import threading
from urllib.parse import quote, urlparse


# ProgId из реестра → канал Playwright. Порядок важен: сначала браузеры, которые ставят пользователи.
PROGID_CHANNELS = [
    ('yandexbrowser', 'yandex'), ('yandex', 'yandex'), ('browser.exe', 'yandex'),
    ('chromehtml', 'chrome'), ('chrome.exe', 'chrome'),
    ('msedgehtm', 'msedge'), ('microsoftedge', 'msedge'), ('msedge.exe', 'msedge'),
    ('firefoxurl', None), ('firefox.exe', None),
    ('operastable', 'opera'), ('opera.exe', 'opera'),
    ('bravehtml', 'brave'), ('brave.exe', 'brave'),
    ('vivaldi', 'vivaldi'),
]

# Порядок попыток запуска, если реестр недоступен. Яндекс — первым, т.к. часто дефолтный в РФ.
log = logging.getLogger(__name__)
CHANNEL_ORDER = ['yandex', 'chrome', 'msedge', 'brave', 'opera', 'vivaldi', None]


def _progid_values():
    """Read the actual Windows HTTP/HTTPS UserChoice values."""
    import winreg
    sep=chr(92)
    base='Software'+sep+'Microsoft'+sep+'Windows'+sep+'Shell'+sep+'Associations'+sep+'UrlAssociations'
    values=[]
    for scheme in ('http','https'):
        try:
            key=winreg.OpenKey(winreg.HKEY_CURRENT_USER, base+sep+scheme+sep+'UserChoice')
            value,_=winreg.QueryValueEx(key,'ProgId')
            winreg.CloseKey(key)
            if value: values.append(str(value))
        except OSError: pass
    try:
        key=winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Software'+sep+'Classes'+sep+'http'+sep+'shell'+sep+'open'+sep+'command')
        value,_=winreg.QueryValueEx(key,'')
        winreg.CloseKey(key)
        if value: values.append(str(value))
    except OSError: pass
    return values


def detect_default_browser():
    """Return Playwright channel matching the Windows default HTTP browser."""
    if os.name!='nt': return None
    try: values=_progid_values()
    except Exception: return None
    for raw in values:
        low=raw.casefold()
        for marker,channel in PROGID_CHANNELS:
            if marker.casefold() in low: return channel
    return None


def build_channel_order():
    """Список каналов для перебора: сначала браузер по умолчанию, потом остальные."""
    order = []
    default = detect_default_browser()
    if default is not None:
        order.append(default)
    elif os.name == 'nt':
        # Браузер по умолчанию не распознан как Chromium — всё равно начнём с Яндекс/Chrome,
        # затем Edge, затем встроенный Chromium Playwright.
        pass
    for channel in CHANNEL_ORDER:
        if channel not in order:
            order.append(channel)
    return order


def install_chromium():
    """Скачать встроенный Chromium Playwright (≈150 МБ) — работает и в собранном приложении."""
    import subprocess
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver = compute_driver_executable()
        command = list(driver) if isinstance(driver, (tuple, list)) else [str(driver)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        return subprocess.run(command + ['install', 'chromium'], env=get_driver_env(), timeout=600,
                              capture_output=True, creationflags=flags).returncode == 0
    except Exception:
        return False


class BrowserController:
    def __init__(self, root):
        self.root = root
        self.jobs = queue.Queue()
        self.context = None
        self.current = None
        self.channel = None
        self.worker = threading.Thread(target=self._worker, daemon=True, name='agent-browser')
        self.worker.start()

    def _worker(self):
        while True:
            method, args, future = self.jobs.get()
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(self._run(method, args))
            except Exception as exc:
                future.set_result('Браузер: '+str(exc)[:300])

    @staticmethod
    def _is_closed_error(exc):
        text = str(exc)
        return any(marker in text for marker in ('has been closed', 'Target closed', 'Browser closed',
                                                 'Connection closed', 'browser has disconnected'))

    def _run(self, method, args):
        """Выполнить действие; если пользователь закрыл окно браузера — перезапустить и повторить."""
        if method == 'open':
            method = 'focus_or_open'  # уже открытый сайт — переключаемся на его вкладку
        try:
            return getattr(self, '_'+method)(*args)
        except Exception as exc:
            if not self._is_closed_error(exc):
                raise
            self._reset()
            if method in ('close_site', 'url', 'player'):
                return '' if method == 'url' else None
            if method in ('close_browser', 'close_tab', 'tabs', 'media'):
                return 'Браузер агента уже закрыт.'
            return getattr(self, '_'+method)(*args)

    def _via_extension(self, bridge, method, args):
        """Выполнить действие в открытом браузере пользователя через расширение «Андрей»."""
        if method == 'open':
            url = self.valid_url(args[0])
            result = bridge.send('open', url=url) or {}
            name = self._site_name(url)
            return ('Переключаюсь на ' if result.get('focused') else 'Открываю ') + (name if name != 'сайт' else url)
        if method == 'url':
            return bridge.send('url') or ''
        if method == 'tabs':
            tabs = bridge.send('tabs') or []
            return '\n'.join(f"{i + 1}. {t.get('title') or t.get('url')}" for i, t in enumerate(tabs)) or 'Вкладок нет.'
        if method == 'close_tab':
            bridge.send('close_tab')
            return 'Вкладка закрыта.'
        if method == 'close_site':
            closed = bridge.send('close_site', url=args[0]) or 0
            return ('Закрываю ' + self._site_name(args[0]) + '.') if closed else None
        if method in ('media', 'player'):
            action = args[0] if method == 'media' else 'play'
            done = bridge.send('media', action=action)
            if method == 'player' and not done:
                return None
            return ('Пауза.' if action == 'pause' else 'Продолжаю воспроизведение.') if done else 'Не нашёл плеер на открытых вкладках.'
        if method == 'video':
            query, source = args[0], (args[1] if len(args) > 1 else 'youtube')
            if re.match(r'^https?://', query, re.I):
                bridge.send('navigate', url=self.valid_url(query))
                return 'Открываю видео.'
            if source == 'rutube':
                bridge.send('navigate', url='https://rutube.ru/search/?query=' + quote(query))
                return f'Ищу на Rutube: {query}'
            bridge.send('navigate', url='https://www.youtube.com/results?search_query=' + quote(query))
            picked = bridge.send('youtube', timeout=30, action='pick', arg=1)
            return f'Включаю «{query}» на YouTube.' if picked else f'Ищу на YouTube: {query}'
        if method == 'youtube':
            action, arg = args[0], (args[1] if len(args) > 1 else None)
            if action == 'search':
                bridge.send('navigate', url='https://www.youtube.com/results?search_query=' + quote(arg))
                return 'Ищу на YouTube: ' + arg
            result = bridge.send('youtube', timeout=30, action=action, arg=arg)
            if action == 'pick':
                if not result:
                    return 'Не нашёл видео на странице. Откройте YouTube или поиск и повторите.'
                return f'Открываю видео номер {arg}.' if arg > 0 else 'Открываю последнее видео.'
            return {'next': 'Включаю следующее видео.', 'back': 'Возвращаюсь назад.', 'fullscreen': 'Готово.',
                    'seek': f'Перематываю {"назад" if (arg or 0) < 0 else "вперёд"} на {abs(arg or 0)} секунд.'}.get(action, 'Готово.')
        if method == 'music':
            query, service = args[0], (args[1] if len(args) > 1 else None)
            current = bridge.send('url') or ''
            info = next((m for m in self.MUSIC if m[0] == service), None) or self._music_service(current) or self.MUSIC[0]
            played = bridge.send('music', timeout=40, url=info[2].format(q=quote(query)))
            if not played:
                return f'Нашёл «{query}» в {info[1]}. Нажмите на трек — сервис может требовать вход в аккаунт.'
            return f'Включаю «{query}» в {info[1]}.'
        raise RuntimeError('Неизвестное действие')

    def _focus_or_open(self, url):
        """«Открой YouTube»: если сайт уже открыт во вкладке — переключиться на неё, а не открывать заново."""
        self.valid_url(url)
        if self.context is None:
            return self._open(url)  # браузер ещё не запущен — открывать нечего, _open его запустит
        target = urlparse(url)
        host = (target.hostname or '').removeprefix('www.')
        path = target.path.rstrip('/')
        try:
            pages = [p for p in self.context.pages if not p.is_closed()]
        except Exception as exc:
            if self._is_closed_error(exc):
                raise  # окно закрыто пользователем — _run перезапустит браузер
            pages = []
        for page in pages:
            current = urlparse(page.url)
            if (current.hostname or '').removeprefix('www.') == host and (not path or current.path.startswith(path)):
                page.bring_to_front()
                self.current = page
                return 'Переключаюсь на ' + self._site_name(url)
        return self._open(url)

    def _reset(self):
        self.context = None
        self.current = None
        if getattr(self, 'pw', None) is not None:
            try:
                self.pw.stop()
            except Exception:
                pass
            self.pw = None

    # Команды, которые умеет выполнять расширение в браузере пользователя.
    EXTENSION_METHODS = {'open', 'video', 'youtube', 'media', 'close_tab', 'close_site', 'url', 'player', 'music', 'tabs'}

    def call(self, method, *args):
        bridge = getattr(self, 'bridge', None)
        if bridge is not None and bridge.connected and method in self.EXTENSION_METHODS:
            try:
                return self._via_extension(bridge, method, args)
            except Exception as exc:  # расширение отвалилось — работаем своим браузером
                log.info('Extension bridge failed (%s): %s', method, exc)
        future = Future()
        self.jobs.put((method, args, future))
        try:
            return future.result(timeout=100)
        except TimeoutError:
            future.cancel()
            return 'Браузер не ответил вовремя. Действие могло начаться; проверьте окно перед повтором.'

    def _ensure(self):
        if self.context is not None:
            return
        from playwright.sync_api import sync_playwright
        if getattr(self, 'pw', None) is not None:
            self.pw.stop()
        self.pw = sync_playwright().start()
        profile = str(self.root / 'browser_profile')
        errors = []
        # Открываем сайты в браузере по умолчанию (из настроек Windows), затем по остальным.
        for channel in build_channel_order():
            try:
                options = dict(user_data_dir=profile, headless=False,
                    args=['--autoplay-policy=no-user-gesture-required'], viewport=None)
                if channel:
                    options['channel'] = channel
                self.context = self.pw.chromium.launch_persistent_context(**options)
                self.context.set_default_timeout(8000)
                self.context.set_default_navigation_timeout(25000)
                self.context.on('close', self._closed)
                self.context.expose_binding('__agent_focus', lambda source: setattr(self, 'current', source['page']))
                self.context.add_init_script("window.addEventListener('focus', () => window.__agent_focus().catch(()=>{}));")
                self.channel = channel
                return
            except Exception as exc:
                errors.append((channel or 'chromium')+': '+str(exc)[:80])
                if channel is None and 'playwright install' in str(exc) and install_chromium():
                    # Первый запуск на компьютере без Chrome/Edge: встроенный Chromium скачан — пробуем снова.
                    try:
                        self.context = self.pw.chromium.launch_persistent_context(**options)
                        self.context.set_default_timeout(8000)
                        self.context.set_default_navigation_timeout(25000)
                        self.context.on('close', self._closed)
                        self.channel = None
                        return
                    except Exception as retry:
                        errors.append('chromium: ' + str(retry)[:80])
        self.pw.stop()
        self.pw = None
        raise RuntimeError('Браузер не запустился. Установите Яндекс.Браузер, Chrome или Edge, '
                           'либо выполните: python -m playwright install chromium. ' + '; '.join(errors))

    def _closed(self, *args):
        self.context = None
        self.current = None

    @staticmethod
    def valid_url(url):
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Разрешены только обычные http/https ссылки без пароля.')
        return url

    def _open(self, url, new_tab=False):
        """Открыть ссылку. По умолчанию — в текущей вкладке агента, чтобы всё шло в одном окне."""
        self.valid_url(url)
        self._ensure()
        page = None
        if not new_tab:
            pages = [p for p in self.context.pages if not p.is_closed()]
            page = self.current if self.current in pages else (pages[-1] if pages else None)
        if page is None:
            page = self.context.new_page()
            try:
                page.on('focus', lambda p=page: setattr(self, 'current', p))
            except Exception:
                pass
        self.current = page
        page.goto(url, wait_until='domcontentloaded')
        page.bring_to_front()
        return 'Открываю ' + self._site_name(url)

    # ---- YouTube / Rutube в том же окне ----
    PICK_SCRIPT = """(skip) => {
        const seen = new Set(), links = [];
        for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href || '';
            const m = href.match(/youtube\\.com\\/(?:watch\\?v=|shorts\\/)([\\w-]{11})/) || href.match(/rutube\\.ru\\/video\\/(\\w+)/);
            if (!m || m[1] === skip || seen.has(m[1])) continue;
            const box = a.getBoundingClientRect();
            if (!box.width || !box.height || a.closest('#masthead, ytd-masthead, [hidden]')) continue;
            seen.add(m[1]);
            links.push(href);
        }
        return links;
    }"""

    def _youtube(self, action, arg=None):
        if action == 'search':
            if self.context is not None and self.current is not None and 'rutube' in (self.current.url or ''):
                return self._open('https://rutube.ru/search/?query=' + quote(arg)).replace('Открываю', 'Ищу на') + ': ' + arg
            self._open('https://www.youtube.com/results?search_query=' + quote(arg))
            return 'Ищу на YouTube: ' + arg
        if self.context is None:
            if action == 'pick':
                self._open('https://www.youtube.com')
            else:
                raise RuntimeError('Сначала откройте YouTube: скажите «Запусти ютуб».')
        page = self._active()
        if action == 'pick':
            current = re.search(r'[?&]v=([\w-]{11})', page.url or '')
            try:
                page.wait_for_selector('a[href*="/watch?v="], a[href*="/video/"]', timeout=10000)
            except Exception:
                pass
            links = page.evaluate(self.PICK_SCRIPT, current[1] if current else '')
            if not links:
                return 'Не нашёл видео на странице. Откройте YouTube или поиск и повторите.'
            index = arg - 1 if arg > 0 else len(links) + arg
            if not 0 <= index < len(links):
                return f'На странице только {len(links)} видео.'
            page.goto(links[index], wait_until='domcontentloaded')
            try:
                page.wait_for_selector('video', timeout=10000)
            except Exception:
                pass
            self._media('play')
            return f'Открываю видео номер {arg}.' if arg > 0 else 'Открываю последнее видео.'
        if action == 'next':
            page.keyboard.press('Shift+N')
            return 'Включаю следующее видео.'
        if action == 'back':
            page.go_back(wait_until='domcontentloaded')
            return 'Возвращаюсь назад.'
        if action == 'fullscreen':
            page.keyboard.press('f')
            return 'Готово.'
        if action == 'seek':
            page.evaluate('s => { const v = document.querySelector("video"); if (v) v.currentTime = Math.max(0, v.currentTime + s); }', arg)
            return f'Перематываю {"назад" if arg < 0 else "вперёд"} на {abs(arg)} секунд.'
        raise RuntimeError('Неизвестное действие с видео.')

    @staticmethod
    def _site_name(url):
        low = url.lower()
        if 'youtube' in low or 'youtu.be' in low: return 'Ютуб'
        if 'rutube' in low: return 'РуТуб'
        if 'google' in low: return 'поиск Google'
        if 'ya.ru' in low or 'yandex' in low: return 'Яндекс'
        if 'vk.com' in low: return 'ВКонтакте'
        if 'music.' in low: return 'музыку'
        return 'сайт'

    def _active(self):
        if self.context is None:
            raise RuntimeError('Нет управляемых вкладок. Сначала откройте видео или сайт через агента.')
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            raise RuntimeError('Нет открытых вкладок.')
        # 1) Текущая вкладка, если она жива и пользователь на ней
        if self.current is not None and self.current in pages:
            try:
                if self.current.evaluate('document.hasFocus()'):
                    return self.current
            except Exception:
                pass
        # 2) Любая вкладка в фокусе окна
        for page in pages:
            try:
                if page.evaluate('document.hasFocus()'):
                    self.current = page
                    return page
            except Exception:
                pass
        # 3) Последняя сохранённая, если жива
        if self.current in pages:
            return self.current
        # 4) Активная вкладка контекста Playwright
        try:
            for p in pages:
                if p == self.context.pages[-1]:
                    self.current = p
                    return p
        except Exception:
            pass
        self.current = pages[-1]
        return self.current

    def _video(self, query, source='youtube'):
        if re.match(r'^https?://', query, re.I):
            self._open(query)
        elif source == 'rutube':
            self._open('https://rutube.ru/search/?query='+quote(query))
            page = self._active()
            link = page.locator('a[href*="/video/"]')
            link.first.wait_for(state='attached', timeout=15000)
            hrefs = link.evaluate_all('(items) => items.map(x => x.href)')
            url = next((u for u in hrefs if re.search(r'rutube.ru/video/[a-zA-Z0-9]+/?', u)), None)
            if not url:
                return 'Rutube не вернул доступное видео. Выберите результат вручную или передайте прямую ссылку.'
            page.goto(url, wait_until='domcontentloaded')
        else:
            # yt-dlp resolves a real video ID, not a search-page URL. No media download.
            import yt_dlp
            options = {'quiet': True, 'no_warnings': True, 'skip_download': True,
                'extract_flat': True, 'socket_timeout': 12, 'retries': 1,
                'extractor_retries': 1, 'playlistend': 1}
            with yt_dlp.YoutubeDL(options) as ydl:
                result = ydl.extract_info('ytsearch1:'+query, download=False)
            entries = [x for x in (result or {}).get('entries', []) if x]
            if not entries or not re.fullmatch(r'[A-Za-z0-9_-]{11}', entries[0].get('id', '')):
                return 'YouTube не вернул видео. Возможны ограничения сервиса; попробуйте прямую ссылку.'
            self._open('https://www.youtube.com/watch?v='+entries[0]['id'])
        page = self._active()
        try:
            page.wait_for_selector('video,audio', timeout=10000)
        except Exception:
            pass
        return 'Открыта страница конкретного видео. '+self._media('play')

    def _media(self, action):
        page = self._active()
        script = """async action => {
            let ok=0, denied=0, found=0;
            const tryMedia = async (m) => {
                try {
                    if (action === 'pause') { if (!m.paused) { m.pause(); } ok++; }
                    else {
                        if (m.paused) {
                            await Promise.race([m.play(),
                                new Promise((_,rej)=>setTimeout(()=>rej(new Error('t')),3000))]);
                        }
                        ok++;
                    }
                } catch(e) { denied++; }
            };
            for (const m of document.querySelectorAll('video,audio')) { found++; await tryMedia(m); }
            if (!ok && document.querySelector('.html5-video-player')) {
                const v = document.querySelector('video.html5-main-video') || document.querySelector('video');
                if (v) { found++; await tryMedia(v); }
                if (!ok) {
                    try {
                        const p = document.querySelector('#movie_player');
                        if (p && p.playVideo && p.pauseVideo) {
                            action === 'pause' ? p.pauseVideo() : p.playVideo(); ok++;
                        }
                    } catch(e) {}
                }
                if (!ok) {
                    const b = document.querySelector('.ytp-play-button');
                    if (b) { try { b.click(); ok++; } catch(e) { denied++; } }
                }
            }
            if (!ok) {
                const words = action === 'pause' ? ['pause','пауза','приостанов']
                                                  : ['play','воспроизв','играть'];
                for (const b of document.querySelectorAll('button,[role=button]')) {
                    const al = ((b.getAttribute('aria-label')||'')+' '+(b.getAttribute('title')||'')).toLowerCase();
                    if (words.some(w=>al.includes(w)) && b.offsetParent !== null) {
                        try { b.click(); ok++; break; } catch(e) { denied++; }
                    }
                }
            }
            return {ok, denied, found};
        }"""
        changed = denied = found = 0
        for frame in page.frames:
            try:
                r = frame.evaluate(script, action)
                changed += r['ok']; denied += r['denied']; found += r['found']
            except Exception:
                pass
        if changed:
            return 'Пауза установлена.' if action == 'pause' else 'Воспроизведение запущено.'
        if denied:
            return 'Сайт заблокировал автозапуск. Нажмите Play в плеере один раз.'
        if found:
            return 'Плеер найден, но управление недоступно. Нажмите Play вручную.'
        return 'Не нашёл плеер видео. Сайт может требовать вход или согласие. Откройте ролик и повторите команду.'

    def _close_tab(self):
        page = self._active()
        page.close(run_before_unload=True)
        self.current = None
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            return 'Вкладка закрыта. Больше вкладок нет.'
        try:
            self.current = self._active()
        except Exception:
            self.current = pages[-1]
        return 'Вкладка закрыта. Осталось: '+str(len(pages))+'.'

    # ---- Музыкальные сервисы: «Включи Imagine Dragons», «Запусти плеер» ----
    MUSIC = [
        ('music.yandex', 'Яндекс Музыке', 'https://music.yandex.ru/search?text={q}'),
        ('music.youtube', 'YouTube Music', 'https://music.youtube.com/search?q={q}'),
        ('open.spotify', 'Spotify', 'https://open.spotify.com/search/{q}'),
        ('vk.com', 'VK Музыке', 'https://vk.com/audio?q={q}&section=search'),
        ('zvuk.com', 'Звуке', 'https://zvuk.com/search?query={q}'),
        ('soundcloud', 'SoundCloud', 'https://soundcloud.com/search?q={q}'),
    ]
    PLAY_FIRST = """() => {
        const bar = 'header, nav, footer, [class*="PlayerBar"], [class*="player-bar"], [class*="PlayerControls"], [data-testid="now-playing-bar"], ytmusic-player-bar, [class*="audio_page_player"]';
        const words = ['воспроизв', 'play', 'слушать', 'играть'];
        const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < innerHeight; };
        const main = document.querySelector('main, [role=main], #content, #main') || document;
        const buttons = [...main.querySelectorAll('button, [role=button], a[aria-label]'), ...document.querySelectorAll('button, [role=button]')];
        for (const b of buttons) {
            const label = ((b.getAttribute('aria-label') || '') + ' ' + (b.getAttribute('title') || '') + ' ' + (b.dataset.testid || '')).toLowerCase();
            if (!words.some(w => label.includes(w)) || label.includes('pause') || label.includes('пауз')) continue;
            if (b.closest(bar) || !visible(b)) continue;
            b.click();
            return label.trim().slice(0, 80) || 'play';
        }
        const link = [...document.querySelectorAll('a[href*="/track/"], a[href*="/watch?v="], a[href*="/song/"]')].find(visible);
        if (link) { link.click(); return 'link'; }
        return '';
    }"""

    def _music_service(self, url):
        return next((m for m in self.MUSIC if m[0] in (url or '')), None)

    def _music(self, query, service=None):
        """Найти песню или исполнителя в текущем музыкальном сервисе (или Яндекс Музыке) и включить."""
        current = self._url()
        info = next((m for m in self.MUSIC if m[0] == service), None) or self._music_service(current) or self.MUSIC[0]
        self._open(info[2].format(q=quote(query)))
        page = self._active()
        clicked = ''
        for _ in range(12):  # результаты поиска подгружаются скриптами
            page.wait_for_timeout(500)
            clicked = page.evaluate(self.PLAY_FIRST)
            if clicked:
                break
        if clicked == 'link':
            page.wait_for_timeout(1500)
            self._media('play')
        if not clicked:
            return f'Нашёл «{query}» в {info[1]}. Нажмите на трек — сервис может требовать вход в аккаунт.'
        return f'Включаю «{query}» в {info[1]}.'

    def _player(self):
        """«Запусти плеер»: продолжить музыку или видео на текущей вкладке."""
        if self.context is None:
            return None
        return self._media('play')

    def _close_site(self, url):
        """«Закрой YouTube»: закрыть вкладки этого сайта в браузере агента. None — таких вкладок нет."""
        if self.context is None:
            return None
        host = urlparse(url).hostname or ''
        site = host.removeprefix('www.').split('.')[0]
        pages = [p for p in self.context.pages if not p.is_closed() and site and site in (urlparse(p.url).hostname or '')]
        for page in pages:
            page.close(run_before_unload=True)
        if not pages:
            return None
        self.current = None
        return 'Закрываю ' + self._site_name(url) + '.'

    def _url(self):
        """Адрес текущей вкладки, не запуская браузер."""
        if self.context is None:
            return ''
        pages = [p for p in self.context.pages if not p.is_closed()]
        page = self.current if self.current in pages else (pages[-1] if pages else None)
        return page.url if page else ''

    def _close_browser(self):
        if self.context is None:
            return 'Управляемый браузер уже закрыт.'
        self.context.close()
        self.context = None
        self.pw.stop()
        self.pw = None
        return 'Закрыт только браузер агента. Другие окна браузеров не затронуты.'

    def _tabs(self):
        if self.context is None:
            return 'Управляемых вкладок нет.'
        return '\n'.join(f'{i+1}. {p.url}' for i,p in enumerate(self.context.pages))
