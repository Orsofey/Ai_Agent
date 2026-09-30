"""macOS: ввод текста и клавиш через Quartz (CGEvent), окна через NSWorkspace и AppleScript.

Тот же набор функций, что и в winapi.py, поэтому команды («напиши…», «скопируй», мессенджеры)
работают без изменений. «Окно» здесь — PID активного приложения.

Нужны разрешения: Системные настройки → Конфиденциальность и безопасность →
«Универсальный доступ» и «Мониторинг ввода» для приложения «Андрей» (или Терминала при запуске из исходников).
Сочетания с Ctrl автоматически превращаются в ⌘: «Скопируй» → ⌘C.
"""
import os
import subprocess
import time

# Виртуальные коды клавиш macOS (Carbon HIToolbox/Events.h).
KEYCODES = {
    'a': 0, 's': 1, 'd': 2, 'f': 3, 'h': 4, 'g': 5, 'z': 6, 'x': 7, 'c': 8, 'v': 9, 'b': 11, 'q': 12, 'w': 13,
    'e': 14, 'r': 15, 'y': 16, 't': 17, '1': 18, '2': 19, '3': 20, '4': 21, '6': 22, '5': 23, '9': 25, '7': 26,
    '8': 28, '0': 29, ']': 30, 'o': 31, '[': 33, 'u': 32, 'i': 34, 'p': 35, 'l': 37, 'j': 38, 'k': 40, 'n': 45, 'm': 46,
    'enter': 36, 'tab': 48, 'space': 49, 'backspace': 51, 'esc': 53, 'delete': 117, 'home': 115, 'end': 119,
    'pageup': 116, 'pagedown': 121, 'left': 123, 'right': 124, 'down': 125, 'up': 126,
    'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118, 'f5': 96, 'f6': 97, 'f7': 98, 'f8': 100, 'f9': 101, 'f10': 109,
    'f11': 103, 'f12': 111,
}
# Медиаклавиши macOS отправляются как системные события NX_KEYTYPE_*.
MEDIA = {'volume_up': 0, 'volume_down': 1, 'volume_mute': 7, 'media_play_pause': 16, 'media_next': 17,
         'media_prev': 18}
MODIFIER_FLAGS = {'shift': 1 << 17, 'ctrl': 1 << 18, 'alt': 1 << 19, 'cmd': 1 << 20}
# Windows-сочетания в привычные для Mac: Ctrl+C → ⌘C, Win → ⌘.
TRANSLATE = {'ctrl': 'cmd', 'win': 'cmd', 'control': 'ctrl'}
# Сочетания Windows, у которых на Mac другой смысл.
COMBOS = {('win', 'd'): ('cmd', 'f3'), ('alt', 'f4'): ('cmd', 'q'), ('alt', 'tab'): ('cmd', 'tab'),
          ('ctrl', 'y'): ('cmd', 'shift', 'z'), ('ctrl', 'shift', 'esc'): ('cmd', 'alt', 'esc'),
          ('alt', 'left'): ('cmd', '['), ('alt', 'right'): ('cmd', ']'), ('f5',): ('cmd', 'r')}


def _quartz():
    import Quartz  # pyobjc-framework-Quartz
    return Quartz


def _post(event):
    from .. import abort
    abort.check()  # «Андрей, стоп» прерывает печать и макросы
    Q = _quartz()
    Q.CGEventPost(Q.kCGHIDEventTap, event)


def release_modifiers(wait=1.0):
    """Подождать, пока пользователь отпустит ⌘/⌥/⇧/⌃ после горячей клавиши."""
    Q = _quartz()
    deadline = time.monotonic() + wait
    mask = sum(MODIFIER_FLAGS.values())
    while time.monotonic() < deadline:
        if not Q.CGEventSourceFlagsState(Q.kCGEventSourceStateHIDSystemState) & mask:
            return
        time.sleep(0.03)


def _media(key):
    from AppKit import NSEvent  # pyobjc-framework-Cocoa
    code = MEDIA[key]
    for down in (True, False):
        event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            14, (0, 0), 0xa00 if down else 0xb00, 0, 0, None, 8, (code << 16) | ((0xa if down else 0xb) << 8), -1)
        _post(event.CGEvent())


def hotkey(*keys):
    """hotkey('ctrl', 'v') → ⌘V."""
    Q = _quartz()
    keys = tuple(k.casefold() for k in keys)
    keys = list(COMBOS[keys]) if keys in COMBOS else [TRANSLATE.get(k, k) for k in keys]
    if len(keys) == 1 and keys[0] in MEDIA:
        return _media(keys[0])
    flags = 0
    for key in keys[:-1]:
        if key not in MODIFIER_FLAGS:
            raise ValueError('Неизвестный модификатор: ' + key)
        flags |= MODIFIER_FLAGS[key]
    main = keys[-1]
    if main not in KEYCODES:
        raise ValueError('Неизвестная клавиша: ' + main)
    for down in (True, False):
        event = Q.CGEventCreateKeyboardEvent(None, KEYCODES[main], down)
        Q.CGEventSetFlags(event, flags)
        _post(event)
        time.sleep(0.01)


def press(key, times=1):
    for _ in range(times):
        hotkey(key)


MODIFIER_KEYCODES = {'shift': 56, 'ctrl': 59, 'alt': 58, 'cmd': 55}


def key_state(key, down):
    """Нажать или отпустить одну клавишу (игры: «держи W две секунды»). Ctrl здесь — настоящий Control."""
    Q = _quartz()
    key = key.casefold()
    code = MODIFIER_KEYCODES.get(key, KEYCODES.get(key))
    if code is None:
        raise ValueError('Неизвестная клавиша: ' + key)
    _post(Q.CGEventCreateKeyboardEvent(None, code, down))


def mouse_button(button, down):
    """Кнопка мыши в текущей позиции курсора."""
    Q = _quartz()
    location = Q.CGEventGetLocation(Q.CGEventCreate(None))
    kinds = {'left': (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGMouseButtonLeft),
             'right': (Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, Q.kCGMouseButtonRight),
             'middle': (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, Q.kCGMouseButtonCenter)}
    press_kind, release_kind, number = kinds.get(button, kinds['left'])
    _post(Q.CGEventCreateMouseEvent(None, press_kind if down else release_kind, location, number))


def type_unicode(text, newline=('enter',)):
    """Печать любого текста (кириллица, эмодзи) порциями по 16 символов."""
    Q = _quartz()
    lines = str(text).split('\n')
    for index, line in enumerate(lines):
        for start in range(0, len(line), 16):
            chunk = line[start:start + 16]
            for down in (True, False):
                event = Q.CGEventCreateKeyboardEvent(None, 0, down)
                Q.CGEventKeyboardSetUnicodeString(event, len(chunk.encode('utf-16-le')) // 2, chunk)
                _post(event)
            time.sleep(0.004)
        if index < len(lines) - 1:
            hotkey(*newline)


def _workspace():
    from AppKit import NSWorkspace
    return NSWorkspace.sharedWorkspace()


def foreground():
    app = _workspace().frontmostApplication()
    return int(app.processIdentifier()) if app else 0


def window_pid(handle):
    return handle


def _app(pid):
    from AppKit import NSRunningApplication
    return NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)


def window_title(handle):
    app = _app(handle)
    return str(app.localizedName()) if app else ''


def process_name(handle):
    """Имя в стиле Windows («telegram.exe»), чтобы работали общие таблицы мессенджеров и браузеров."""
    app = _app(handle)
    if not app:
        return ''
    name = str(app.localizedName() or '').casefold()
    return {'google chrome': 'chrome', 'microsoft edge': 'msedge', 'yandex': 'browser'}.get(name, name) + '.exe'


def is_window(handle):
    return _app(handle) is not None


def focus(handle):
    app = _app(handle)
    return bool(app and app.activateWithOptions_(1 << 1))  # NSApplicationActivateIgnoringOtherApps


def osascript(script):
    return subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=10)


def show(handle, command):
    if command == 'minimize':
        hotkey('cmd', 'm')
    elif command in ('maximize', 'restore'):
        osascript('tell application "System Events" to tell (first process whose frontmost is true) '
                  'to click (first button of front window whose subrole is "AXFullScreenButton")')
    elif command == 'desktop':
        hotkey('cmd', 'f3')
    return True


def close(handle):
    hotkey('cmd', 'w')
    return True


def lock_workstation():
    osascript('tell application "System Events" to keystroke "q" using {control down, command down}')
    return True


def own_pid():
    return os.getpid()


def request_permissions():
    """Попросить у macOS разрешение «Универсальный доступ» (один раз, системный диалог)."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    except Exception:
        return False
