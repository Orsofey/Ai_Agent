"""Per-user startup: Windows Run key or a macOS LaunchAgent."""
import os
from pathlib import Path
import sys

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'LocalAIAgent'


LAUNCH_AGENT = Path.home() / 'Library' / 'LaunchAgents' / 'ru.andrey.assistant.plist'


def _mac_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--minimized']
    return [sys.executable, str(Path(__file__).resolve().parents[1] / 'main.py'), '--minimized']


def _configure_mac(value):
    import plistlib
    if not value:
        LAUNCH_AGENT.unlink(missing_ok=True)
        return
    LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT.write_bytes(plistlib.dumps({'Label': 'ru.andrey.assistant', 'ProgramArguments': _mac_command(),
                                             'RunAtLoad': True, 'ProcessType': 'Interactive'}))


def enabled():
    if sys.platform == 'darwin':
        return LAUNCH_AGENT.exists()
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            return bool(winreg.QueryValueEx(key, NAME)[0])
    except OSError:
        return False


def configure(value):
    if sys.platform == 'darwin':
        return _configure_mac(value)
    if sys.platform != 'win32':
        if value:
            raise ValueError('Автозапуск реализован для Windows и macOS.')
        return
    import winreg
    if getattr(sys, 'frozen', False):
        command = '"'+sys.executable+'" --minimized'
    else:
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        if not pythonw.exists():
            raise ValueError('pythonw.exe не найден. Соберите EXE или используйте стандартный Python для Windows.')
        main = Path(__file__).resolve().parents[1] / 'main.py'
        command = f'"{pythonw}" "{main}" --minimized'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        if value:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
