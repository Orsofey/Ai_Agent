"""Windows app launch and graceful window close. Never TerminateProcess."""
import ctypes
from ctypes import wintypes
import os
import re
import shutil
import subprocess
import sys
import time
import psutil
from .app_aliases import RU_TO_EN, UWP_APPS, KNOWN_PATHS

EXTRA = {
    'блокнот': ['notepad.exe'], 'notepad': ['notepad.exe'],
    'калькулятор': ['calculatorapp.exe', 'calculator.exe', 'calc.exe'],
    'calc': ['calculatorapp.exe', 'calculator.exe', 'calc.exe'],
    'настройки': ['systemsettings.exe'], 'ms-settings': ['systemsettings.exe'],
    'фотографии': ['photos.exe', 'microsoft.photos.exe'],
    'mspaint': ['mspaint.exe', 'paintstudio.view.exe'],
}
PROTECTED = {'system', 'registry', 'csrss.exe', 'winlogon.exe', 'lsass.exe',
    'services.exe', 'svchost.exe', 'dwm.exe', 'explorer.exe', 'sihost.exe',
    'python.exe', 'pythonw.exe', 'localaiagent.exe', 'cmd.exe', 'powershell.exe',
    'pwsh.exe', 'javaw.exe', 'applicationframehost.exe'}


def normalize(name):
    value = re.sub(r'^(?:приложение|программу|окно)\s+', '', name.strip(), flags=re.I)
    return value.strip(' «»\".,!?').casefold()


def resolve(name):
    name = normalize(name)
    return RU_TO_EN.get(name, name)


def targets(name):
    key = normalize(name)
    alias = resolve(key).casefold()
    if key in EXTRA or alias in EXTRA:
        return EXTRA.get(key, EXTRA.get(alias))
    if not re.fullmatch(r'[a-z0-9_.+ -]+', alias):
        return []
    return [alias if alias.endswith('.exe') else alias + '.exe']


def launch(name):
    if sys.platform != 'win32':
        return 'Открытие приложений в этой сборке поддерживается на Windows.'
    app = resolve(name)
    if not app or len(app) > 150:
        return 'Укажите имя приложения.'
    # Если приложение уже открыто - делаем его окно активным, а не запускаем второй экземпляр
    if activate_running(name):
        return 'Открываю ' + name
    try:
        if app == 'ms-settings':
            os.startfile('ms-settings:')
            return 'Открываю настройки'
        if app == 'explorer':
            subprocess.Popen(['explorer.exe'], creationflags=subprocess.CREATE_NO_WINDOW)
            return 'Открываю Проводник'
        path = next((p for p in KNOWN_PATHS.get(app, []) if os.path.isfile(p)), None)
        if not path and re.fullmatch(r'[\w.+ -]+', app):
            path = shutil.which(app if app.lower().endswith('.exe') else app+'.exe')
        if path:
            args = [path]
            if app == 'Discord' and PathName(path) == 'update.exe':
                args += ['--processStart', 'Discord.exe']
            subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
            return 'Открываю ' + name
        # Registry App Paths is a trusted source of installed executable paths.
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, 'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\'+app+'.exe') as key:
                    path = winreg.QueryValue(key, None).strip('"')
                if os.path.isfile(path):
                    subprocess.Popen([path], creationflags=subprocess.CREATE_NO_WINDOW)
                    return 'Открываю '+name
            except OSError:
                pass
        if app in UWP_APPS:
            subprocess.Popen(['explorer.exe', 'shell:AppsFolder\\'+UWP_APPS[app]], creationflags=subprocess.CREATE_NO_WINDOW)
            return 'Открываю '+name
        return 'Приложение не найдено: '+name+'. Попробуйте системное имя, например notepad.'
    except OSError as exc:
        return 'Не удалось запустить приложение: '+str(exc)


def PathName(path):
    return os.path.basename(path).casefold()



def _find_windows(pids):
    """Возвращает список HWND видимых окон для набора PID (включая UWP-фреймы)."""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    found = []
    def pid_of(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    @callback_type
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        match = pid_of(hwnd) in pids
        if not match:
            child_pids = set()
            @callback_type
            def child(ch, _):
                child_pids.add(pid_of(ch)); return True
            user32.EnumChildWindows(hwnd, child, 0)
            match = bool(child_pids & pids)
        if match:
            found.append(hwnd)
        return True
    user32.EnumWindows(visit, 0)
    return found


def activate_running(name):
    """Если приложение уже запущено - разворачивает и выводит его окно вперёд.
    Возвращает True, если окно найдено и активировано."""
    if sys.platform != 'win32':
        return False
    names = set(targets(name))
    if not names:
        return False
    pids = set()
    for process in psutil.process_iter(['pid', 'name', 'username']):
        try:
            if (process.info['name'] or '').casefold() in names:
                pids.add(process.pid)
        except psutil.Error:
            pass
    if not pids:
        return False
    windows = _find_windows(pids)
    if not windows:
        return False
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    hwnd = windows[0]
    try:
        # SW_RESTORE = 9: разворачивает свёрнутое окно, не трогая размеры развёрнутого
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def close_application(name):
    if sys.platform != 'win32':
        return 'Безопасное закрытие окон поддерживается только на Windows.'
    names = set(targets(name))
    if not names or names & PROTECTED:
        return 'Не удалось закрыть: укажите конкретное приложение.'
    me = psutil.Process()
    protected = {me.pid}
    try:
        protected.update(p.pid for p in me.parents())
        protected.update(p.pid for p in me.children(recursive=True) if p.name().casefold() == 'msedgewebview2.exe')
    except psutil.Error:
        pass
    pids = set()
    for process in psutil.process_iter(['pid', 'name', 'username']):
        try:
            if process.pid not in protected and process.info['username'] == me.username() and (process.info['name'] or '').casefold() in names:
                pids.add(process.pid)
        except psutil.Error:
            pass
    if not pids:
        return 'Закрываю '+name+': приложение не запущено'
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    windows = []
    def pid_of(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    @callback_type
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        match = pid_of(hwnd) in pids
        if not match:
            # Older UWP apps: visible frame belongs to ApplicationFrameHost.
            child_pids = set()
            @callback_type
            def child(ch, _):
                child_pids.add(pid_of(ch)); return True
            user32.EnumChildWindows(hwnd, child, 0)
            match = bool(child_pids & pids)
        if match and pid_of(hwnd) not in protected:
            windows.append(hwnd)
        return True
    user32.EnumWindows(visit, 0)
    sent = sum(bool(user32.PostMessageW(hwnd, 0x0010, 0, 0)) for hwnd in windows)
    if not sent:
        return 'Закрываю ' + name + ': открытое окно не найдено.'
    return 'Закрываю ' + name
