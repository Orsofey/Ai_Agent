"""Сценарии (как «Режимы» Bixby): «Работа», «Учёба», «Игра»… и блокировка сайтов и приложений на время.

«Андрей, включи сценарий работа на 2 часа», «заблокируй ютуб на 30 минут», «разблокируй всё», «сколько осталось».

Как блокируется:
- сайты — через расширение «Андрей» (вкладка заменяется страницей «Сайт заблокирован»); без расширения
  на Windows закрывается вкладка, в заголовке которой есть название сайта, на Mac — вкладки с этим адресом;
- приложения — окно закрывается штатно, как крестиком (без принудительного завершения процесса).
Состояние хранится в базе, поэтому блокировка продолжается после перезапуска ассистента.
"""
import json
import logging
import re
import subprocess
import sys
import threading
import time

from .brain.numbers import plural, words_to_digits

log = logging.getLogger(__name__)

DISTRACTING = ['youtube.com', 'vk.com', 'instagram.com', 'tiktok.com', 'twitch.tv', 'dzen.ru', 'reddit.com',
               'x.com', 'pinterest.com', 'kinopoisk.ru']
DEFAULT_SCENARIOS = [
    {'name': 'Работа', 'sites': DISTRACTING[:7], 'apps': ['steam', 'epicgameslauncher', 'discord'],
     'minutes': 90, 'grayscale': False, 'open': []},
    {'name': 'Учёба', 'sites': list(DISTRACTING), 'apps': ['steam', 'epicgameslauncher', 'discord', 'telegram'],
     'minutes': 45, 'grayscale': True, 'open': []},
    {'name': 'Игра', 'sites': [], 'apps': [], 'minutes': 120, 'grayscale': False, 'open': ['steam', 'discord']},
    {'name': 'Отдых', 'sites': [], 'apps': ['outlook', 'teams', 'slack'], 'minutes': 60, 'grayscale': False, 'open': []},
    {'name': 'Сон', 'sites': list(DISTRACTING), 'apps': ['steam', 'epicgameslauncher'], 'minutes': 480,
     'grayscale': True, 'open': []},
]
MAX_MINUTES = 24 * 60
CHECK_EVERY = 2.0


# ---------------- разбор фраз ----------------
def parse_minutes(text):
    """«30 минут», «тридцать минут», «час», «полчаса», «полтора часа», «2 часа 15 минут» → минуты или None."""
    value = str(text or '').casefold().replace('ё', 'е').strip()
    if not value:
        return None
    if re.fullmatch(r'пол\s*часа|полчаса', value):
        return 30
    if re.fullmatch(r'(?:один\s+)?час(?:ик)?|часок', value):
        return 60
    value = words_to_digits(value)
    total, found = 0.0, False
    for amount, unit in re.findall(r'(\d+(?:[.,]\d+)?)?\s*(час\w*|ч\b|мин\w*|м\b)', value):
        number = float(amount.replace(',', '.')) if amount else 1.0
        total += number * (60 if unit.startswith(('час', 'ч')) else 1)
        found = True
    if not found and re.fullmatch(r'\d+', value.strip()):
        total, found = float(value.strip()), True  # «на 30» — минуты
    minutes = int(round(total))
    return minutes if found and 1 <= minutes <= MAX_MINUTES else None


def say_minutes(minutes):
    minutes = max(1, int(round(minutes)))
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f'{hours} {plural(hours, "час", "часа", "часов")}')
    if rest:
        parts.append(f'{rest} {plural(rest, "минуту", "минуты", "минут")}')
    return ' '.join(parts)


def parse(text):
    """Команда сценариев: ('start', имя, мин) | ('stop', имя) | ('block', что, мин) | ('unblock', что) | ('status',)."""
    raw = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    lower = raw.casefold().replace('ё', 'е')
    if lower in ('что заблокировано', 'какой сценарий включен', 'какой режим включен', 'сколько осталось',
                 'сколько осталось блокировки', 'сколько еще блокировка', 'статус сценария', 'какие блокировки'):
        return ('status',)
    m = re.fullmatch(r'(?:включи|запусти|активируй|начни|поставь)\s+(?:сценарий|режим)\s+(.+?)(?:\s+на\s+(.+))?', lower)
    if m:
        return 'start', m[1].strip(' «»"'), parse_minutes(m[2]) if m[2] else None
    m = re.fullmatch(r'(?:выключи|останови|заверши|отключи|закончи|отмени)\s+(?:сценарий|режим)(?:\s+(.+))?', lower)
    if m:
        return 'stop', (m[1] or '').strip(' «»"')
    m = re.fullmatch(r'(?:разблокируй|разблокировать|сними блокировку(?:\s+с)?|отмени блокировку(?:\s+с)?)(?:\s+(.+))?', lower)
    if m:
        what = (m[1] or '').strip(' «»"')
        return 'unblock', '' if what in ('', 'все', 'всё', 'сайты', 'все сайты', 'приложения', 'все приложения') else what
    m = re.fullmatch(r'(?:заблокируй|блокируй|запрети|закрой доступ к)\s+(?:сайт\s+|приложение\s+|программу\s+)?(.+?)'
                     r'(?:\s+на\s+(.+))?', lower)
    if m and m[1] not in ('компьютер', 'экран', 'пк', 'ноутбук', 'windows', 'систему'):
        minutes = parse_minutes(m[2]) if m[2] else 60
        if m[2] and minutes is None:
            return None
        return 'block', m[1].strip(' «»"'), minutes
    return None


def clean_domain(value):
    value = re.sub(r'^\w+://', '', str(value).strip().casefold())
    value = value.split('/')[0].split('?')[0]
    return re.sub(r'^www\.', '', value)


def _norm_list(items, limit=60, domains=False):
    if isinstance(items, str):
        items = re.split(r'[,\n;]+', items)
    out = []
    for item in items or []:
        value = clean_domain(item) if domains else re.sub(r'\s+', ' ', str(item)).strip()
        if not value or len(value) > 80:
            continue
        if domains and not re.fullmatch(r'[\w.-]+\.[\w-]{2,}', value):
            raise ValueError(f'Неверный адрес сайта: {item}')
        if value not in out:
            out.append(value)
    return out[:limit]


def validate(scenarios):
    if not isinstance(scenarios, list) or len(scenarios) > 20:
        raise ValueError('Нужен список сценариев (до 20)')
    result, names = [], set()
    for item in scenarios:
        name = re.sub(r'\s+', ' ', str((item or {}).get('name', ''))).strip()
        if not 1 <= len(name) <= 40:
            raise ValueError('Название сценария: 1–40 символов')
        if name.casefold() in names:
            raise ValueError('Сценарии с одинаковым названием: ' + name)
        names.add(name.casefold())
        minutes = int(item.get('minutes') or 60)
        if not 1 <= minutes <= MAX_MINUTES:
            raise ValueError('Время сценария: от 1 минуты до 24 часов')
        result.append({'name': name, 'sites': _norm_list(item.get('sites'), domains=True),
                       'apps': _norm_list(item.get('apps'), 30), 'open': _norm_list(item.get('open'), 10),
                       'minutes': minutes, 'grayscale': bool(item.get('grayscale'))})
    return result


# ---------------- менеджер ----------------
class ScenarioManager:
    def __init__(self, store, browser=None, desktop=None, notify=None, clock=time.time):
        self.store = store
        self.browser = browser
        self.desktop = desktop
        self.notify = notify
        self.clock = clock
        self.lock = threading.RLock()
        self.thread = None
        self.synced = None      # что последний раз отправили расширению
        self.synced_at = 0.0
        self.state = self._load_state()

    # ---- хранение ----
    def scenarios(self):
        raw = self.store.meta('scenarios')
        if raw:
            try:
                return validate(json.loads(raw))
            except (ValueError, TypeError):
                log.warning('Broken scenarios in storage, using defaults')
        return validate(DEFAULT_SCENARIOS)

    def save(self, scenarios):
        value = validate(scenarios)
        self.store.set_meta('scenarios', json.dumps(value, ensure_ascii=False))
        return value

    def _load_state(self):
        try:
            state = json.loads(self.store.meta('scenario_state') or '{}')
        except ValueError:
            state = {}
        return {'scenario': state.get('scenario'), 'until': state.get('until'),
                'grayscale_restore': state.get('grayscale_restore'), 'blocks': list(state.get('blocks') or [])}

    def _save_state(self):
        self.store.set_meta('scenario_state', json.dumps(self.state, ensure_ascii=False))

    def find(self, name):
        from .start_menu import phonetic
        from difflib import SequenceMatcher
        key = phonetic(name)
        best, score = None, 0.0
        for item in self.scenarios():
            ratio = SequenceMatcher(None, key, phonetic(item['name'])).ratio()
            if ratio > score:
                best, score = item, ratio
        return best if score >= 0.75 else None

    # ---- действия ----
    def start(self, name, minutes=None):
        scenario = self.find(name) if isinstance(name, str) else name
        if scenario is None:
            names = ', '.join(s['name'] for s in self.scenarios())
            return f'Нет сценария «{name}». Есть: {names}. Изменить их можно в Настройках → «Сценарии».'
        minutes = minutes or scenario['minutes']
        with self.lock:
            if self.state['scenario']:
                self._stop_scenario(silent=True)
            until = self.clock() + minutes * 60
            source = scenario['name']
            self.state['blocks'] = [b for b in self.state['blocks'] if b.get('source') != source]
            self.state['blocks'] += [{'kind': 'site', 'value': d, 'until': until, 'source': source} for d in scenario['sites']]
            self.state['blocks'] += [{'kind': 'app', 'value': a, 'until': until, 'source': source} for a in scenario['apps']]
            self.state.update(scenario=source, until=until)
            if scenario['grayscale']:
                from . import display
                self.state['grayscale_restore'] = display.is_grayscale()
                display.set_grayscale(True)
            self._save_state()
        for app in scenario['open']:
            self._launch(app)
        self.enforce(force_sync=True)
        self.ensure_thread()
        parts = []
        if scenario['sites']:
            parts.append(f"{len(scenario['sites'])} {plural(len(scenario['sites']), 'сайт', 'сайта', 'сайтов')}")
        if scenario['apps']:
            parts.append(f"{len(scenario['apps'])} {plural(len(scenario['apps']), 'приложение', 'приложения', 'приложений')}")
        blocked = ('Заблокировано: ' + ' и '.join(parts) + '.') if parts else ''
        extra = ' Экран чёрно-белый.' if scenario['grayscale'] else ''
        opened = (' Запускаю: ' + ', '.join(scenario['open']) + '.') if scenario['open'] else ''
        return f"Сценарий «{source}» включён на {say_minutes(minutes)}. {blocked}{extra}{opened}".replace('  ', ' ').strip()

    def stop(self, name=''):
        with self.lock:
            if not self.state['scenario']:
                return 'Сейчас ни один сценарий не включён.'
            current = self.state['scenario']
            if name and self.find(name) and self.find(name)['name'] != current:
                return f'Сейчас включён сценарий «{current}», а не «{name}».'
            self._stop_scenario()
        self.enforce(force_sync=True)
        return f'Сценарий «{current}» выключен, блокировки сняты.'

    def _stop_scenario(self, silent=False):
        source = self.state['scenario']
        self.state['blocks'] = [b for b in self.state['blocks'] if b.get('source') != source]
        restore = self.state.get('grayscale_restore')
        self.state.update(scenario=None, until=None, grayscale_restore=None)
        self._save_state()
        if restore is not None:
            from . import display
            display.set_grayscale(bool(restore))
        if not silent and self.notify:
            self.notify(f'Сценарий «{source}» завершён.')

    def block(self, what, minutes=60):
        target = self.resolve_target(what)
        if target is None:
            return f'Не понял, что заблокировать: «{what}». Назовите сайт (ютуб, вк) или программу (Steam).'
        kind, value = target
        with self.lock:
            until = self.clock() + minutes * 60
            self.state['blocks'] = [b for b in self.state['blocks'] if not (b['kind'] == kind and b['value'] == value)]
            self.state['blocks'].append({'kind': kind, 'value': value, 'until': until, 'source': None})
            self._save_state()
        self.enforce(force_sync=True)
        self.ensure_thread()
        label = 'сайт' if kind == 'site' else 'приложение'
        return f'Заблокировал {label} {value} на {say_minutes(minutes)}.'

    def unblock(self, what=''):
        with self.lock:
            if not what:
                had = bool(self.state['blocks']) or bool(self.state['scenario'])
                if self.state['scenario']:
                    self._stop_scenario(silent=True)
                self.state['blocks'] = []
                self._save_state()
                result = 'Все блокировки сняты.' if had else 'Сейчас ничего не заблокировано.'
            else:
                target = self.resolve_target(what)
                before = len(self.state['blocks'])
                if target:
                    self.state['blocks'] = [b for b in self.state['blocks']
                                            if not (b['kind'] == target[0] and b['value'] == target[1])]
                self._save_state()
                result = f'Разблокировал {target[1]}.' if target and len(self.state['blocks']) < before \
                    else f'«{what}» не был заблокирован.'
        self.enforce(force_sync=True)
        return result

    def status(self):
        with self.lock:
            self._expire()
            now = self.clock()
            if not self.state['blocks'] and not self.state['scenario']:
                return 'Сейчас ничего не заблокировано и сценарии выключены.'
            lines = []
            if self.state['scenario']:
                lines.append(f"Сценарий «{self.state['scenario']}»: осталось {say_minutes((self.state['until'] - now) / 60)}.")
            own = [b for b in self.state['blocks'] if not b.get('source')]
            for item in own[:6]:
                lines.append(f"{item['value']} — ещё {say_minutes((item['until'] - now) / 60)}.")
            return ' '.join(lines)

    def summary(self):
        """Для окна настроек."""
        with self.lock:
            self._expire()
            now = self.clock()
            return {'scenario': self.state['scenario'],
                    'left': round((self.state['until'] - now) / 60) if self.state['until'] else None,
                    'blocks': [{'kind': b['kind'], 'value': b['value'], 'source': b.get('source'),
                                'left': round((b['until'] - now) / 60)} for b in self.state['blocks']]}

    @staticmethod
    def resolve_target(what):
        from . import sites
        from .app_control import targets
        value = str(what).strip(' «»"').casefold()
        value = re.sub(r'^(?:сайт|приложение|программу)\s+', '', value)
        if not value:
            return None
        url = sites.find(value, threshold=0.85)
        if url and 'duckduckgo' not in url:
            return 'site', clean_domain(url)
        if re.fullmatch(r'[\w-]+(?:\.[\w-]+)+', value):
            return 'site', clean_domain(value)
        if sys.platform == 'darwin' or targets(value):
            return 'app', value
        return None

    # ---- исполнение ----
    def active_blocks(self):
        with self.lock:
            self._expire()
            return list(self.state['blocks'])

    def _expire(self):
        now = self.clock()
        if self.state['scenario'] and self.state['until'] and self.state['until'] <= now:
            self._stop_scenario()
        before = len(self.state['blocks'])
        self.state['blocks'] = [b for b in self.state['blocks'] if b['until'] > now]
        if len(self.state['blocks']) != before:
            self._save_state()

    def enforce(self, force_sync=False):
        blocks = self.active_blocks()
        domains = sorted({b['value'] for b in blocks if b['kind'] == 'site'})
        apps = sorted({b['value'] for b in blocks if b['kind'] == 'app'})
        synced = self._sync_extension(domains, force_sync)
        if domains and not synced:
            self._close_blocked_tabs(domains)
        for app in apps:
            self._close_app(app)
        return bool(blocks)

    def _sync_extension(self, domains, force):
        bridge = getattr(self.browser, 'bridge', None)
        if bridge is None or getattr(bridge, 'connected', False) is not True:
            self.synced = None
            return False
        if not force and self.synced == domains and self.clock() - self.synced_at < 30:
            return True
        try:
            bridge.send('block', timeout=5, domains=domains)
        except Exception as exc:
            log.info('Extension block sync failed: %s', exc)
            return False
        self.synced, self.synced_at = domains, self.clock()
        return True

    def _close_blocked_tabs(self, domains):
        if sys.platform == 'darwin':
            return self._mac_close_tabs(domains)
        try:
            from .desktop import winapi
            from .desktop.controller import BROWSER_PROCESSES
            from .desktop.navigation import title_markers, title_matches
            if not winapi.supported():
                return
            hwnd = winapi.foreground()
            if not hwnd or winapi.process_name(hwnd) not in BROWSER_PROCESSES:
                return
            title = winapi.window_title(hwnd)
            for domain in domains:
                if title_matches(title, title_markers('https://www.' + domain) + title_markers('https://' + domain)):
                    winapi.hotkey('ctrl', 'w')
                    self._say_once('site:' + domain, f'{domain} заблокирован — закрыл вкладку.', every=20)
                    return
        except Exception as exc:
            log.debug('Tab check failed: %s', exc)

    @staticmethod
    def _mac_close_tabs(domains):
        from . import macos
        from .desktop.navigation import MAC_BROWSER_APPS
        for app in MAC_BROWSER_APPS:
            try:
                if not macos.is_running(app):
                    continue
                condition = ' or '.join(f'URL contains "{d.replace(chr(34), "")}"' for d in domains)
                script = f'tell application "{app}" to close (every tab of every window whose {condition})'
                subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5)
            except Exception:
                pass

    def _close_app(self, name):
        try:
            import psutil
            from .app_control import close_application, targets
            if sys.platform == 'darwin':
                from . import macos
                app = macos.mac_name(name)
                if app and macos.is_running(app):
                    macos.close_application(name)
                return
            names = set(targets(name))
            if not names or not any((p.info['name'] or '').casefold() in names for p in psutil.process_iter(['name'])):
                return
            # Окна закрываем штатно; приложение в трее (Steam, Discord) остаётся, но его окно не откроется надолго.
            result = close_application(name)
            if 'не найдено' not in result and 'не запущено' not in result:
                self._say_once('app:' + name, f'{name} заблокирован — закрыл окно.')
        except Exception as exc:
            log.debug('App block failed: %s', exc)

    def _say_once(self, key, text, every=60):
        """Не повторять одно и то же уведомление чаще раза в минуту."""
        now = self.clock()
        said = getattr(self, '_said', {})
        if self.notify and now - said.get(key, 0) >= every:
            said[key] = now
            self._said = said
            self.notify(text)

    @staticmethod
    def _launch(name):
        try:
            from .app_control import launch
            launch(name)
        except Exception:
            log.exception('Scenario launch failed: %s', name)

    # ---- фоновая проверка ----
    def ensure_thread(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            if not self.state['blocks'] and not self.state['scenario']:
                return
            self.thread = threading.Thread(target=self._run, daemon=True, name='scenarios')
            self.thread.start()

    def _run(self):
        while True:
            try:
                if not self.enforce():
                    with self.lock:
                        if not self.state['blocks'] and not self.state['scenario']:
                            self.enforce(force_sync=True)  # снять блокировку в расширении
                            self.thread = None
                            return
            except Exception:
                log.exception('Scenario enforcement failed')
            time.sleep(CHECK_EVERY)

    # ---- голос ----
    def handle(self, text):
        request = parse(text)
        if request is None:
            return None
        kind = request[0]
        if kind == 'status':
            return self.status()
        if kind == 'start':
            return self.start(request[1], request[2])
        if kind == 'stop':
            return self.stop(request[1])
        if kind == 'unblock':
            return self.unblock(request[1])
        if kind == 'block':
            return self.block(request[1], request[2])
        return None
