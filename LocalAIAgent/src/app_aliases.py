"""Application aliases migrated from the original project."""

import os

RU_TO_EN = {
    # Системные UWP
    "калькулятор": "calc",
    "календарь": "outlookcal",
    "погода": "msnweather",
    "почта": "hxoutlook",
    "карты": "bingmaps",
    "фотографии": "ms-photos",
    "камера": "windows.camera",
    "часы": "ms-clock",
    "будильник": "ms-clock",
    "записки": "msnotes",
    "настройки": "ms-settings",
    "проводник": "explorer",
    "блокнот": "notepad",
    "паинт": "mspaint",
    "пэйнт": "mspaint",
    "paint": "mspaint",
    # Браузеры
    "браузер": "msedge",
    "хром": "chrome",
    "гугл хром": "chrome",
    "фаерфокс": "firefox",
    "мозилла": "firefox",
    "опера": "opera",
    "яндекс браузер": "browser",
    "эдж": "msedge",
    "edge": "msedge",
    # Мессенджеры
    "телеграм": "Telegram",
    "телеграмм": "Telegram",
    "тг": "Telegram",
    "ватсап": "WhatsApp",
    "ватсапп": "WhatsApp",
    "дискорд": "Discord",
    "скайп": "Skype",
    # Офис
    "ворд": "WINWORD",
    "word": "WINWORD",
    "эксель": "EXCEL",
    "excel": "EXCEL",
    "пауэрпоинт": "POWERPNT",
    "powerpoint": "POWERPNT",
    "пауэр поинт": "POWERPNT",
    "аутлук": "OUTLOOK",
    "outlook": "OUTLOOK",
    "блокнот+": "notepad++",
    # Медиа
    "медиаплеер": "wmplayer",
    "плеер": "wmplayer",
    "vlc": "vlc",
    "влс": "vlc",
    "спотифай": "Spotify",
    "spotify": "Spotify",
    # Игры
    "стим": "steam",
    "steam": "steam",
    "дота": "dota2",
    "дота 2": "dota2",
    "майнкрафт": "Minecraft",
    "дискорд": "Discord",
    # Разработка
    "вс код": "code",
    "vs code": "code",
    "visual studio code": "code",
    "вижуал студио": "devenv",
    "студия": "devenv",
    "питон": "python",
    "консоль": "cmd",
    "терминал": "wt",
    "командная строка": "cmd",
    "повершелл": "powershell",
}

UWP_APPS = {
    "calc": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "outlookcal": "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.calendar",
    "msnweather": "Microsoft.BingWeather_8wekyb3d8bbwe!App",
    "hxoutlook": "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.mail",
    "bingmaps": "Microsoft.WindowsMaps_8wekyb3d8bbwe!App",
    "ms-photos": "Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
    "windows.camera": "Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
    "ms-clock": "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
    "msmoney": "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App",
    "ms-settings": "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel",
    "notepad": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
    "mspaint": "Microsoft.Paint_8wekyb3d8bbwe!App",
}

KNOWN_PATHS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "msedge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "opera": [
        os.path.expandvars(r"%LocalAppData%\Programs\Opera\opera.exe"),
        r"C:\Program Files\Opera\opera.exe",
    ],
    "Telegram": [
        os.path.expandvars(r"%AppData%\Telegram Desktop\Telegram.exe"),
        os.path.expandvars(r"%LocalAppData%\Telegram\Telegram.exe"),
    ],
    "Discord": [
        os.path.expandvars(r"%LocalAppData%\Discord\Update.exe"),
    ],
    "steam": [
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
    ],
    "code": [
        os.path.expandvars(r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "vlc": [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ],
    "Spotify": [
        os.path.expandvars(r"%AppData%\Spotify\Spotify.exe"),
    ],
    "dota2": [
        r"C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\bin\win64\dota2.exe",
    ],
    "Minecraft": [
        os.path.expandvars(r"%AppData%\.minecraft\launcher\minecraft.exe"),
    ],
}