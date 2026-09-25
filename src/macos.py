"""macOS: запуск, активация и вежливое закрытие приложений («Открой Telegram», «Закрой Safari»)."""
import re
import subprocess

# Идентификатор из app_aliases.RU_TO_EN (или то, что сказал пользователь) → имя приложения macOS.
MAC_APPS = {
    'calc': 'Calculator', 'калькулятор': 'Calculator', 'notepad': 'TextEdit', 'блокнот': 'TextEdit',
    'ms-settings': 'System Settings', 'настройки': 'System Settings', 'explorer': 'Finder', 'проводник': 'Finder',
    'finder': 'Finder', 'outlookcal': 'Calendar', 'календарь': 'Calendar', 'msnweather': 'Weather',
    'hxoutlook': 'Mail', 'почта': 'Mail', 'bingmaps': 'Maps', 'карты': 'Maps', 'ms-photos': 'Photos',
    'windows.camera': 'Photo Booth', 'ms-clock': 'Clock', 'msnotes': 'Notes', 'записки': 'Notes', 'заметки': 'Notes',
    'mspaint': 'Preview', 'msedge': 'Safari', 'браузер': 'Safari', 'safari': 'Safari', 'сафари': 'Safari',
    'chrome': 'Google Chrome', 'firefox': 'Firefox', 'opera': 'Opera', 'browser': 'Yandex',
    'telegram': 'Telegram', 'whatsapp': 'WhatsApp', 'discord': 'Discord', 'skype': 'Skype', 'viber': 'Viber',
    'slack': 'Slack', 'winword': 'Microsoft Word', 'excel': 'Microsoft Excel', 'powerpnt': 'Microsoft PowerPoint',
    'outlook': 'Microsoft Outlook', 'wmplayer': 'Music', 'музыка': 'Music', 'плеер': 'Music', 'vlc': 'VLC',
    'spotify': 'Spotify', 'steam': 'Steam', 'minecraft': 'Minecraft', 'code': 'Visual Studio Code',
    'cmd': 'Terminal', 'wt': 'Terminal', 'powershell': 'Terminal', 'терминал': 'Terminal',
    'app store': 'App Store', 'facetime': 'FaceTime', 'сообщения': 'Messages', 'messages': 'Messages',
    'зум': 'zoom.us', 'zoom': 'zoom.us',
}
PROTECTED = {'finder', 'dock', 'loginwindow', 'systemuiserver', 'windowserver', 'andrey', 'local ai agent'}


def mac_name(name):
    """«телеграм» → «Telegram», «калькулятор» → «Calculator»; неизвестное — как сказано, с заглавной."""
    from .app_control import normalize, resolve
    key = normalize(name)
    alias = resolve(key)
    for candidate in (key, alias.casefold()):
        if candidate in MAC_APPS:
            return MAC_APPS[candidate]
    if not re.fullmatch(r'[\w .+&-]{1,60}', alias):
        return None
    return alias if alias[:1].isupper() else alias.title()


def _osascript(script):
    return subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=10)


def _quoted(value):
    return value.replace('\\', '').replace('"', '')


def is_running(app):
    result = _osascript(f'application "{_quoted(app)}" is running')
    return result.stdout.strip() == 'true'


def activate_running(name):
    app = mac_name(name)
    if not app or not is_running(app):
        return False
    return _osascript(f'tell application "{_quoted(app)}" to activate').returncode == 0


def launch(name):
    app = mac_name(name)
    if not app:
        return 'Укажите имя приложения.'
    result = subprocess.run(['open', '-a', app], capture_output=True, text=True, timeout=15)
    if result.returncode == 0:
        return 'Открываю ' + name
    return f'Приложение не найдено: {name}. Проверьте, что оно установлено в «Программы».'


def close_application(name):
    app = mac_name(name)
    if not app or app.casefold() in PROTECTED:
        return 'Не удалось закрыть: укажите конкретное приложение.'
    if not is_running(app):
        return 'Закрываю ' + name + ': приложение не запущено'
    # quit — как ⌘Q: приложение само спросит о несохранённых документах.
    _osascript(f'tell application "{_quoted(app)}" to quit')
    return 'Закрываю ' + name
