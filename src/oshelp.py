"""Системные операции для файловых команд: выделенные файлы в Проводнике/Finder, файл в буфер обмена,
удаление в Корзину (с возможностью восстановить), «показать в папке». Windows и macOS.

На других системах функции возвращают пустой результат — логику команд можно тестировать на Linux.
"""
import base64
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def powershell(script, timeout=30):
    """Windows PowerShell 5.1 с UTF-8 выводом. Возвращает (код, stdout, stderr)."""
    code = '[Console]::OutputEncoding=[Text.Encoding]::UTF8\n$ErrorActionPreference="Stop"\n' + script
    encoded = base64.b64encode(code.encode('utf-16-le')).decode()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-EncodedCommand', encoded], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    return result.returncode, result.stdout.decode('utf-8', 'replace').strip(), result.stderr.decode('utf-8', 'replace')


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def osascript(script, timeout=30):
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def as_string(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


# ---------------- выделенные файлы ----------------
EXPLORER_SELECTION = r'''
$sh = New-Object -ComObject Shell.Application
$want = [int64]{hwnd}
$all = @()
foreach ($w in $sh.Windows()) {{
  try {{
    if ($w.FullName -notlike '*explorer.exe') {{ continue }}
    $items = @($w.Document.SelectedItems() | ForEach-Object {{ $_.Path }})
    if ($items.Count -eq 0) {{ continue }}
    if ([int64]$w.HWND -eq $want) {{ $items; exit }}
    $all += ,$items
  }} catch {{ }}
}}
if ($all.Count -eq 1) {{ $all[0] }}
'''


def selected_files(hwnd=0):
    """Файлы, выделенные в Проводнике (окно hwnd, иначе единственное окно с выделением) или в Finder."""
    try:
        if IS_WINDOWS:
            code, out, err = powershell(EXPLORER_SELECTION.format(hwnd=int(hwnd or 0)), timeout=15)
            lines = out.splitlines() if code == 0 else []
        elif IS_MAC:
            code, out, err = osascript('tell application "Finder"\nset out to ""\nrepeat with f in (get selection)\n'
                                       'set out to out & POSIX path of (f as alias) & linefeed\nend repeat\nreturn out\nend tell')
            lines = out.splitlines() if code == 0 else []
        else:
            return []
    except (OSError, subprocess.SubprocessError) as exc:
        log.info('Selection unavailable: %s', exc)
        return []
    return [Path(line.strip()) for line in lines if line.strip() and Path(line.strip()).exists()]


# ---------------- буфер обмена ----------------
def copy_files(paths):
    """Положить файлы в буфер обмена как файлы — вставляются Ctrl+V в мессенджер, письмо, папку."""
    paths = [str(Path(p).resolve()) for p in paths]
    if not paths:
        return False
    try:
        if IS_WINDOWS:
            code, _, err = powershell('Set-Clipboard -LiteralPath ' + ','.join(ps_string(p) for p in paths), timeout=15)
            return code == 0
        if IS_MAC:
            files = ', '.join(f'POSIX file {as_string(p)}' for p in paths)
            code, _, _ = osascript(f'set the clipboard to {{{files}}}' if len(paths) > 1 else
                                   f'set the clipboard to (POSIX file {as_string(paths[0])})')
            return code == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log.info('Clipboard failed: %s', exc)
    return False


# ---------------- корзина ----------------
def to_trash(paths):
    """Удалить в Корзину (файлы можно восстановить). Возвращает список удалённых путей."""
    done = []
    for path in [Path(p) for p in paths]:
        if not path.exists():
            continue
        try:
            if IS_WINDOWS:
                code, _, _ = powershell('Add-Type -AssemblyName Microsoft.VisualBasic\n'
                                        '[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(' + ps_string(path) +
                                        ", 'OnlyErrorDialogs', 'SendToRecycleBin')", timeout=30)
            elif IS_MAC:
                code, _, _ = osascript(f'tell application "Finder" to delete (POSIX file {as_string(path)} as alias)')
            else:
                trash = Path.home() / '.local/share/Trash/files'
                trash.mkdir(parents=True, exist_ok=True)
                os.replace(path, trash / path.name)
                code = 0
        except (OSError, subprocess.SubprocessError) as exc:
            log.info('Trash failed for %s: %s', path, exc)
            continue
        if code == 0 and not path.exists():
            done.append(path)
    return done


def reveal(path):
    """Показать файл в Проводнике/Finder."""
    path = Path(path)
    try:
        if IS_WINDOWS:
            subprocess.Popen(['explorer.exe', '/select,', str(path)])
            return True
        if IS_MAC:
            subprocess.Popen(['open', '-R', str(path)])
            return True
    except OSError:
        pass
    return False


def open_path(path):
    from .web_services import system_open
    return system_open(str(path))


def foreground_window():
    """Окно, где был пользователь (для выбора Проводника), или 0."""
    if not IS_WINDOWS:
        return 0
    try:
        from .desktop import winapi
        return winapi.foreground() or 0
    except Exception:
        return 0
