"""Чёрно-белый экран: «Андрей, включи чёрно-белый режим» / «верни цвета».

Windows 10/11 — системные «Цветовые фильтры» (Параметры → Специальные возможности → Цветовые фильтры).
macOS — «Универсальный доступ → Дисплей → Цветовые фильтры → Оттенки серого».
"""
import ctypes
import re
import subprocess
import sys
import time

WIN_KEY = r'Software\Microsoft\ColorFiltering'
GRAYSCALE = 0  # FilterType: 0 — оттенки серого


def parse(text):
    """True — включить ч/б, False — вернуть цвета, 'toggle' — переключить, None — не эта команда."""
    lower = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?').casefold().replace('ё', 'е')
    lower = lower.replace('черно-бел', 'черно бел').replace('ч/б', 'чб').replace('ч б', 'чб')
    bw = r'(?:чб|черно бел\w*|черноб\w*|сер\w*|монохром\w*|оттенк\w* серого)'
    if re.fullmatch(r'(?:верни|включи|сделай)\s+(?:обратно\s+)?(?:цвет\w*|цветной\s+(?:экран|режим))(?:\s+экран\w*)?', lower) \
            or re.fullmatch(r'(?:выключи|отключи|убери|сними)\s+(?:режим\s+)?' + bw + r'(?:\s+(?:режим|экран|фильтр))?', lower):
        return False
    if re.fullmatch(r'(?:включи|сделай|переведи|поставь|запусти)\s+(?:экран\s+)?(?:в\s+)?(?:режим\s+)?' + bw +
                    r'(?:\s+(?:режим|экран|вид|фильтр))?', lower) \
            or re.fullmatch(r'(?:сделай|переведи)\s+экран\s+(?:в\s+)?' + bw + r'(?:\s+(?:режим|вид))?', lower):
        return True
    if re.fullmatch(r'переключи\s+(?:режим\s+)?' + bw + r'(?:\s+режим)?', lower):
        return 'toggle'
    return None


# ---------------- Windows ----------------
def _win_state():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_KEY) as key:
            return bool(winreg.QueryValueEx(key, 'Active')[0])
    except OSError:
        return False


def _win_prepare():
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, WIN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, 'FilterType', 0, winreg.REG_DWORD, GRAYSCALE)
        winreg.SetValueEx(key, 'HotkeyEnabled', 0, winreg.REG_DWORD, 1)


def _win_toggle():
    """Переключить фильтр: через atbroker (как сочетание Win+Ctrl+C), при неудаче — самим сочетанием."""
    before = _win_state()
    try:
        subprocess.run(['atbroker.exe', '/colorfiltershortcut', '/resettransferkeys'], timeout=10,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        pass
    for _ in range(10):
        time.sleep(0.15)
        if _win_state() != before:
            return
    from .desktop import winapi
    winapi.release_modifiers()
    winapi.hotkey('win', 'ctrl', 'c')


def _windows(on):
    _win_prepare()
    if on == 'toggle':
        on = not _win_state()
    if _win_state() != on:
        _win_toggle()
    return on


# ---------------- macOS ----------------
MA_SYSTEM_FILTER = 1   # MADisplayFilterPrefSystemFilter
MA_GRAYSCALE = 1       # тип фильтра «Оттенки серого»


def _mac_libs():
    ua = ma = None
    try:
        ua = ctypes.cdll.LoadLibrary('/System/Library/PrivateFrameworks/UniversalAccess.framework/UniversalAccess')
    except OSError:
        pass
    try:
        ma = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/MediaAccessibility.framework/MediaAccessibility')
    except OSError:
        pass
    return ua, ma


def _mac_state(ua, ma):
    if ma is not None and hasattr(ma, 'MADisplayFilterPrefGetCategoryEnabled'):
        ma.MADisplayFilterPrefGetCategoryEnabled.restype = ctypes.c_bool
        ma.MADisplayFilterPrefGetType.restype = ctypes.c_int
        return bool(ma.MADisplayFilterPrefGetCategoryEnabled(MA_SYSTEM_FILTER)) and \
            ma.MADisplayFilterPrefGetType(MA_SYSTEM_FILTER) == MA_GRAYSCALE
    if ua is not None and hasattr(ua, 'UAGrayscaleIsEnabled'):
        ua.UAGrayscaleIsEnabled.restype = ctypes.c_bool
        return bool(ua.UAGrayscaleIsEnabled())
    return False


def _mac(on):
    ua, ma = _mac_libs()
    if on == 'toggle':
        on = not _mac_state(ua, ma)
    done = False
    if ma is not None and hasattr(ma, 'MADisplayFilterPrefSetCategoryEnabled'):
        if on:
            ma.MADisplayFilterPrefSetType(MA_SYSTEM_FILTER, MA_GRAYSCALE)
        ma.MADisplayFilterPrefSetCategoryEnabled(MA_SYSTEM_FILTER, ctypes.c_bool(on))
        if ua is not None and hasattr(ua, '_UniversalAccessDStart'):
            ua._UniversalAccessDStart(0)  # применить настройку сразу
        done = True
    if ua is not None and hasattr(ua, 'UAGrayscaleSetEnabled'):
        ua.UAGrayscaleSetEnabled(ctypes.c_bool(on))
        done = True
    if not done:
        raise RuntimeError('macOS не дал переключить фильтр')
    return on


def set_grayscale(on):
    """Включить (True), выключить (False) или переключить ('toggle'). Вернуть ответ для пользователя."""
    try:
        if sys.platform == 'win32':
            state = _windows(on)
        elif sys.platform == 'darwin':
            state = _mac(on)
        else:
            return 'Чёрно-белый режим доступен на Windows и macOS.'
    except Exception:
        if sys.platform == 'darwin':
            return ('Не получилось переключить цвета. Включите вручную: Системные настройки → Универсальный доступ → '
                    'Дисплей → Цветовые фильтры → «Оттенки серого».')
        return 'Не получилось переключить цвета. Нажмите Win+Ctrl+C или включите «Цветовые фильтры» в Параметрах.'
    return 'Экран чёрно-белый.' if state else 'Цвета вернул.'


def is_grayscale():
    try:
        if sys.platform == 'win32':
            return _win_state()
        if sys.platform == 'darwin':
            return _mac_state(*_mac_libs())
    except Exception:
        pass
    return False
