"""Per-user Windows startup, no .bat/cmd launcher."""
import os
from pathlib import Path
import sys

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'LocalAIAgent'


def enabled():
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            return bool(winreg.QueryValueEx(key, NAME)[0])
    except OSError:
        return False


def configure(value):
    if sys.platform != 'win32':
        if value:
            raise ValueError('Автозапуск реализован для Windows.')
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
