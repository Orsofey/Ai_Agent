"""Own browser profile, serial Playwright worker. Never touches unrelated tabs."""
from concurrent.futures import Future, TimeoutError
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
                future.set_result(getattr(self, '_'+method)(*args))
            except Exception as exc:
                future.set_result('Браузер: '+str(exc)[:600])

    def call(self, method, *args):
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

    def _open(self, url):
        self.valid_url(url)
        self._ensure()
        page = self.context.new_page()
        self.current = page
        # Запоминаем вкладку как активную при любом взаимодействии с ней
        try:
            page.on('focus', lambda p=page: setattr(self, 'current', p))
        except Exception:
            pass
        page.goto(url, wait_until='domcontentloaded')
        page.bring_to_front()
        name = self._site_name(url)
        return 'Открываю '+name

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
