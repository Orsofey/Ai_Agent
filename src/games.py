"""Голосовое управление играми: «прыжок», «перезарядка», «инвентарь», «беги вперёд» — без имени ассистента.

«Андрей, включи игровой режим» (или «игровой режим для Майнкрафта») — пока режим включён, короткие игровые фразы
сразу нажимают клавиши в игре; остальную речь (разговор с друзьями) ассистент игнорирует. «Андрей, выключи игровой
режим» — обычная работа. Профиль выбирается по запущенной игре (Minecraft, CS2, Dota 2…) или «Общий».

Клавиши нажимаются аппаратными скан-кодами — их видят игры на DirectInput/Raw Input. Профили редактируются в
Настройки → «Игры» строками вида «фраза = клавиши»:
    прыжок = space
    беги вперёд = hold shift+w 2
    стреляй = click left
    сохранись = f5
    напиши в чат гг = chat t гг

Важно: в сетевых играх с античитом используйте только в одиночных режимах или там, где макросы разрешены.
"""
import json
import logging
import re
import sys
import threading
import time

log = logging.getLogger(__name__)

DEFAULT_PROFILES = {
    'Общий': '''прыжок | прыгни = space
присесть | пригнись = ctrl
перезарядка | перезаряди = r
инвентарь | рюкзак = i
карта = m
меню | пауза = esc
используй | подбери | действие = e
фонарик = f
вперёд | иди вперёд = hold w 1.5
назад | иди назад = hold s 1.2
влево | иди влево = hold a 1
вправо | иди вправо = hold d 1
беги | беги вперёд = hold shift+w 2.5
стреляй | огонь = click left
прицел | целься = click right
граната = g
аптечка | лечись = h
оружие один | первое оружие = 1
оружие два | второе оружие = 2
оружие три | третье оружие = 3
быстрое сохранение | сохранись = f5
быстрая загрузка | загрузись = f9
скриншот = f12''',
    'Minecraft': '''прыжок | прыгни = space
присесть | крадись = hold shift 1.5
инвентарь = e
выбросить | выкинь = q
чат = t
копай | ломай = hold click left 1.5
поставь | используй = click right
беги | беги вперёд = hold ctrl+w 2.5
вперёд = hold w 1.5
назад = hold s 1.2
камера | вид = f5
скриншот = f2
слот один = 1
слот два = 2
слот три = 3
слот четыре = 4
слот пять = 5''',
    'Counter-Strike 2': '''купить | закупка = b
перезарядка | перезаряди = r
основное оружие = 1
пистолет = 2
нож = 3
граната = 4
бомба = 5
выбросить = g
прыжок = space
присесть = hold ctrl 1.5
стреляй | огонь = click left
прицел = click right
счёт | таблица = hold tab 2''',
    'Dota 2': '''первый скилл = q
второй скилл = w
третий скилл = e
ульта | ультимейт = r
стоп = s
держи позицию = h
магазин = f4
курьер = f3
выбрать героя = f1''',
}
GAME_PROCESSES = {'javaw.exe': 'Minecraft', 'minecraft.windows.exe': 'Minecraft', 'minecraft': 'Minecraft',
                  'cs2.exe': 'Counter-Strike 2', 'csgo.exe': 'Counter-Strike 2', 'dota2.exe': 'Dota 2'}
GAME_NAMES = {'майнкрафт': 'Minecraft', 'minecraft': 'Minecraft', 'кс': 'Counter-Strike 2', 'контр': 'Counter-Strike 2',
              'cs': 'Counter-Strike 2', 'дот': 'Dota 2', 'dota': 'Dota 2'}
ON = re.compile(r'^(?:включи|запусти|активируй)\s+(?:игровой режим|режим игры|управление игрой)(?:\s+(?:для|в)\s+(?P<game>.+))?$|'
                r'^игровой режим(?:\s+(?:для|в)\s+(?P<game2>.+))?$', re.I)
OFF = re.compile(r'^(?:выключи|отключи|останови|выйди из)\s+(?:игров\w+ режим\w*|режим\w* игры|управлени\w+ игрой)$', re.I)


def parse_keys(spec):
    """«hold shift+w 2» → {'kind': 'hold', 'keys': ['shift','w'], 'seconds': 2.0}."""
    parts = spec.strip().split()
    if not parts:
        return None
    kind = 'tap'
    if parts[0] in ('hold', 'держи', 'зажми'):
        kind, parts = 'hold', parts[1:]
    if parts and parts[0] == 'chat' and len(parts) >= 3:
        return {'kind': 'chat', 'keys': [parts[1]], 'text': ' '.join(parts[2:])}
    if parts and parts[0] == 'click':
        button = parts[1] if len(parts) > 1 and parts[1] in ('left', 'right', 'middle') else 'left'
        seconds = _num(parts[-1]) if kind == 'hold' else 0
        return {'kind': 'hold_click' if kind == 'hold' else 'click', 'button': button, 'seconds': seconds or 1.0}
    if not parts:
        return None
    keys = [k for k in parts[0].casefold().split('+') if k]
    seconds = _num(parts[1]) if len(parts) > 1 else None
    return {'kind': kind, 'keys': keys, 'seconds': seconds or (1.0 if kind == 'hold' else 0)}


def _num(value):
    try:
        return max(0.05, min(10.0, float(str(value).replace(',', '.'))))
    except ValueError:
        return None


def parse_profile(text):
    """Строки «фраза | синоним = клавиши» → {нормализованная фраза: действие}."""
    actions = {}
    for line in str(text or '').splitlines():
        phrases, sep, spec = line.partition('=')
        if not sep:
            continue
        action = parse_keys(spec)
        if not action:
            continue
        for phrase in phrases.split('|'):
            key = normalize(phrase)
            if key:
                actions[key] = dict(action, phrase=phrase.strip())
    return actions


def normalize(text):
    value = re.sub(r'[^\w\s+]', ' ', str(text).casefold().replace('ё', 'е'))
    return re.sub(r'\s+', ' ', value).strip()


# ---------------- нажатия ----------------
class Keys:
    """Скан-коды (Windows) — игры их видят; macOS — Quartz."""

    def down(self, key):
        self._key(key, True)

    def up(self, key):
        self._key(key, False)

    def _key(self, key, down):
        if sys.platform == 'win32':
            from .desktop import winapi
            vk = winapi.vk_of(key)
            scan = winapi.user32.MapVirtualKeyW(vk, 0)
            flags = 0x0008 | (0 if down else winapi.KEYEVENTF_KEYUP)          # KEYEVENTF_SCANCODE
            if key in winapi.EXTENDED:
                flags |= winapi.KEYEVENTF_EXTENDEDKEY
            winapi._send([winapi._key_input(0, scan, flags)])
        elif sys.platform == 'darwin':
            from .desktop import macapi
            macapi.key_state(key, down)
        else:
            raise RuntimeError('Управление играми доступно на Windows и macOS.')

    def mouse(self, button, down):
        if sys.platform == 'win32':
            import ctypes
            flags = {('left', True): 0x0002, ('left', False): 0x0004, ('right', True): 0x0008,
                     ('right', False): 0x0010, ('middle', True): 0x0020, ('middle', False): 0x0040}[(button, down)]
            ctypes.windll.user32.mouse_event(flags, 0, 0, 0, 0)
        elif sys.platform == 'darwin':
            from .desktop import macapi
            macapi.mouse_button(button, down)
        else:
            raise RuntimeError('Управление играми доступно на Windows и macOS.')

    def type_text(self, text):
        from .desktop import winapi
        winapi.type_unicode(text)


class Games:
    def __init__(self, store, keys=None, process=None):
        self.store = store
        self.keys = keys or Keys()
        self.process = process or _foreground_process
        self.active = False
        self.forced = None       # профиль, названный голосом
        self.lock = threading.Lock()
        self.last = None

    # ---- профили ----
    def profiles(self):
        raw = self.store.meta('game_profiles')
        try:
            saved = json.loads(raw) if raw else {}
        except ValueError:
            saved = {}
        return {**DEFAULT_PROFILES, **{k: v for k, v in saved.items() if isinstance(v, str)}}

    def save_profiles(self, profiles):
        clean = {}
        for name, text in (profiles or {}).items():
            name = str(name).strip()[:40]
            if name and isinstance(text, str) and len(text) < 20000:
                parse_profile(text)  # проверка формата
                clean[name] = text
        self.store.set_meta('game_profiles', json.dumps(clean, ensure_ascii=False))
        return self.profiles()

    def current_profile(self):
        if self.forced:
            return self.forced
        name = (self.process() or '').casefold()
        return GAME_PROCESSES.get(name, 'Общий')

    def status(self):
        return {'active': self.active, 'profile': self.current_profile() if self.active else None,
                'profiles': self.profiles(), 'last': self.last}

    # ---- выполнение ----
    def match(self, text):
        actions = parse_profile(self.profiles().get(self.current_profile(), ''))
        if self.current_profile() != 'Общий':
            actions = {**parse_profile(DEFAULT_PROFILES['Общий']), **actions}
        key = normalize(text)
        if key in actions:
            return actions[key]
        # «прыжок прыжок», «давай прыжок» — ищем фразу в конце или начале короткой реплики.
        if len(key.split()) <= 4:
            for phrase, action in sorted(actions.items(), key=lambda x: -len(x[0])):
                if key.endswith(' ' + phrase) or key.startswith(phrase + ' '):
                    return action
        return None

    def run_phrase(self, text):
        """Для голосового цикла: True — фраза была игровой командой и выполнена."""
        if not self.active:
            return False
        action = self.match(text)
        if action is None:
            return False
        threading.Thread(target=self.perform, args=(action,), daemon=True, name='game-key').start()
        self.last = action.get('phrase')
        return True

    def perform(self, action):
        with self.lock:
            kind = action['kind']
            try:
                if kind == 'tap':
                    for key in action['keys']:
                        self.keys.down(key)
                    time.sleep(0.04)
                    for key in reversed(action['keys']):
                        self.keys.up(key)
                elif kind == 'hold':
                    for key in action['keys']:
                        self.keys.down(key)
                    time.sleep(action['seconds'])
                    for key in reversed(action['keys']):
                        self.keys.up(key)
                elif kind == 'click':
                    self.keys.mouse(action['button'], True)
                    time.sleep(0.04)
                    self.keys.mouse(action['button'], False)
                elif kind == 'hold_click':
                    self.keys.mouse(action['button'], True)
                    time.sleep(action['seconds'])
                    self.keys.mouse(action['button'], False)
                elif kind == 'chat':
                    self.keys.down(action['keys'][0])
                    self.keys.up(action['keys'][0])
                    time.sleep(0.25)
                    self.keys.type_text(action['text'])
                    self.keys.down('enter')
                    self.keys.up('enter')
            except Exception as exc:
                log.info('Game key failed: %s', exc)

    # ---- голос: включить/выключить ----
    def handle(self, text):
        value = re.sub(r'\s+', ' ', str(text)).strip().strip('.!')
        match = ON.match(value)
        if match:
            game = (match['game'] or match['game2'] or '').casefold()
            self.forced = next((v for k, v in GAME_NAMES.items() if game.startswith(k)), None) if game else None
            if game and self.forced is None:
                self.forced = next((name for name in self.profiles() if name.casefold().startswith(game[:5])), None)
            self.active = True
            profile = self.current_profile()
            examples = ', '.join(list(parse_profile(self.profiles()[profile]))[:4])
            return (f'Игровой режим включён, профиль «{profile}». Говорите без имени: {examples}. '
                    '«Андрей, выключи игровой режим» — выход.')
        if OFF.match(value):
            self.active = False
            self.forced = None
            return 'Игровой режим выключен.'
        if self.active:
            action = self.match(value)
            if action is not None:
                threading.Thread(target=self.perform, args=(action,), daemon=True).start()
                return f'«{action["phrase"]}».'
        return None


def _foreground_process():
    try:
        from .desktop import winapi
        return winapi.process_name(winapi.foreground())
    except Exception:
        return ''
