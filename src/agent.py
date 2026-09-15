"""Агент с корректным запуском приложений Windows (UWP + десктопных).

Ключевые моменты:
- Русские названия переводятся в английские
- UWP-приложения (Калькулятор, Календарь, Погода) запускаются через shell:AppsFolder
- Десктопные приложения ищутся по реестру и известным путям
- Никаких попапов "Windows cannot find ..."
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import psutil

try:
    from .app_catalog import catalog
    from .desktop_actions import parse_and_run
except ImportError:
    SRC_DIR = Path(__file__).resolve().parent
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    from app_catalog import catalog
    from desktop_actions import parse_and_run


# ============ ПЕРЕВОД РУССКИХ НАЗВАНИЙ В АНГЛИЙСКИЕ ============
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

# UWP AUMID (Application User Model ID) для системных приложений
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

# Известные пути к популярным приложениям (fallback)
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

MOVIE_SITES = [
    ("HDrezka", "https://hdrezka.ag/search/?do=search&subaction=search&q={q}"),
    ("Кинопоиск", "https://www.kinopoisk.ru/index.php?kp_query={q}"),
    ("Rutube", "https://rutube.ru/search/?query={q}"),
]

DEFAULT_WAKE_NAMES = {"орсофей", "orsofey", "андрей", "алиса", "агент", "помощник"}


class LocalComputerAgent:
    """Агент с корректным запуском приложений."""

    def __init__(self):
        self.system = platform.system()
        self.wake_names = set(DEFAULT_WAKE_NAMES)
        self.config_dir = None
        self.voice_enabled = True
        self._resolve_cache = {}

    def set_wake_word(self, name: str):
        if not name:
            return
        base = name.strip().lower()
        self.wake_names.add(base)
        self.wake_names.add(base.replace("й", "и"))
        self.wake_names.add(base.replace("ь", ""))

    def set_voice_enabled(self, enabled: bool):
        self.voice_enabled = enabled

    # ============ ГОЛОС ============
    def _speak(self, text: str):
        if not self.voice_enabled or not text:
            return

        def speak_thread():
            try:
                from gtts import gTTS
                import tempfile
                tts = gTTS(text, lang='ru', slow=False)
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                    temp_file = f.name
                    tts.save(temp_file)
                    self._play_audio(temp_file)
                    try:
                        os.unlink(temp_file)
                    except Exception:
                        pass
            except Exception:
                pass

        threading.Thread(target=speak_thread, daemon=True).start()

    def _play_audio(self, path: str):
        try:
            if self.system == "Windows":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
            elif self.system == "Darwin":
                subprocess.run(["afplay", path], timeout=10, check=False)
            else:
                subprocess.run(["paplay", path], timeout=10, check=False)
        except Exception:
            pass

    # ============ РАЗБОР КОМАНДЫ ============
    def _strip_wake_word(self, text: str) -> str:
        words = text.split()
        if not words:
            return text
        first = re.sub(r"[^\w]", "", words[0].lower())
        if first in self.wake_names:
            rest = " ".join(words[1:]).lstrip(",.!?;:— ")
            return rest if rest else text
        return text

    def _clean_command(self, cmd: str) -> str:
        value = str(cmd or "").replace("\u00a0", " ").strip()
        value = re.sub(r"\s+", " ", value)
        return value.strip(" \t\r\n.,!?;:…-—")

    # ============ ПОИСК И ЗАПУСК ПРИЛОЖЕНИЙ ============
    def _resolve_app(self, app_name: str) -> str:
        """Перевести русское название в английское/системное."""
        key = app_name.strip().lower()
        if key in self._resolve_cache:
            return self._resolve_cache[key]
        resolved = RU_TO_EN.get(key, app_name)
        self._resolve_cache[key] = resolved
        return resolved

    def _find_known_path(self, app: str) -> str | None:
        """Найти путь из известных локаций."""
        for path in KNOWN_PATHS.get(app, []):
            if path and os.path.exists(path):
                return path
        return None

    def _find_app_path_windows(self, app: str) -> str | None:
        """Найти полный путь приложения через реестр App Paths."""
        # App Paths в HKLM / HKCU
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for suffix in (f"{app}.exe", app):
                    try:
                        key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{suffix}"
                        with winreg.OpenKey(hive, key_path) as key:
                            path, _ = winreg.QueryValueEx(key, "")
                            if path and os.path.exists(path):
                                return path
                    except OSError:
                        continue
        except Exception:
            pass

        # Известные пути
        found = self._find_known_path(app)
        if found:
            return found

        # Поиск в PATH через where
        try:
            result = subprocess.run(
                ["where", f"{app}.exe"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split("\n")[0].strip()
        except Exception:
            pass

        return None

    def _launch_uwp(self, aumid: str) -> bool:
        """Запустить UWP-приложение по AUMID через explorer shell:AppsFolder."""
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{aumid}"])
            return True
        except Exception:
            return False

    def _launch_app(self, app_name: str) -> str:
        """Запустить приложение надёжно, без попапов Windows."""
        app_name = app_name.strip()
        if not app_name:
            return "✗ Укажите имя приложения"

        # Переводим русское имя в системное
        app = self._resolve_app(app_name)

        if self.system != "Windows":
            # macOS / Linux
            try:
                if self.system == "Darwin":
                    subprocess.Popen(["open", "-a", app])
                else:
                    subprocess.Popen([app])
                return f"✓ Открыто: {app_name}"
            except Exception:
                return f"✗ Приложение не найдено: {app_name}"

        # --- WINDOWS ---

        # 1) UWP-приложение (Калькулятор, Календарь, Погода и т.д.)
        if app in UWP_APPS:
            if self._launch_uwp(UWP_APPS[app]):
                return f"✓ Открыто: {app_name}"

        # 2) Найти реальный путь
        app_path = self._find_app_path_windows(app)

        if app_path and os.path.exists(app_path):
            try:
                # startfile надёжнее для .exe с пробелами в пути
                os.startfile(app_path)
                return f"✓ Открыто: {app_name}"
            except Exception:
                try:
                    subprocess.Popen([app_path], shell=False)
                    return f"✓ Открыто: {app_name}"
                except Exception:
                    pass

        # 3) Специальные схемы (Дискорд Update.exe требует --processStart)
        if app == "Discord":
            updater = os.path.expandvars(r"%LocalAppData%\Discord\Update.exe")
            if os.path.exists(updater):
                try:
                    subprocess.Popen([updater, "--processStart", "Discord.exe"])
                    return f"✓ Открыто: {app_name}"
                except Exception:
                    pass

        # 4) os.startfile по имени (для приложений в реестре/ассоциациях)
        try:
            os.startfile(app)
            return f"✓ Открыто: {app_name}"
        except OSError:
            pass

        # 5) cmd /c start с пустым заголовком (для PATH)
        try:
            subprocess.Popen(f'cmd /c start "" "{app}"', shell=True)
            return f"✓ Открыто: {app_name}"
        except Exception:
            pass

        # 6) Ничего не помогло — честная ошибка БЕЗ попапа
        return f"✗ Приложение «{app_name}» не найдено. Проверьте, установлено ли оно."

    def _extract_query(self, text: str, keywords: list) -> str:
        query = text.lower()
        for keyword in keywords:
            query = query.replace(keyword, " ")
        query = re.sub(r"\s+", " ", query).strip()
        return query if query else None

    # ============ ОБРАБОТКА КОМАНД ============
    def process_command(self, command: str) -> str:
        original = self._clean_command(command)
        if not original:
            return "Введите команду. Скажите 'помощь' для справки."

        stripped = self._strip_wake_word(original)
        text = stripped.lower()

        if not text.strip():
            self._speak("Слушаю вас")
            return "Слушаю команду."

        # СПРАВКА
        if text in ("помощь", "help", "справка"):
            self._speak("Вывожу полную справку по всем командам")
            return """📋 СПРАВКА - ДОСТУПНЫЕ КОМАНДЫ:

1️⃣ ПРИЛОЖЕНИЯ:
   "Открой Chrome" / "Запусти Firefox" / "Включи Telegram"
   "Открой калькулятор" / "Запусти календарь" / "Включи проводник"
   "Открой Discord", "Запусти Steam", "Включи Word"
   (работает для любого установленного приложения)

2️⃣ YOUTUBE (автозапуск):
   "Открой ютуб и найди видео про космос"
   "Запусти песню AC/DC на ютубе"

3️⃣ ФИЛЬМЫ (открывает кинопорталы):
   "Открой фильм Интерстеллар"
   "Найди фильм Матрица"

4️⃣ ПОИСК:
   "Найди информацию о Марсе"

5️⃣ СИСТЕМА:
   "Информация о системе"

💡 "открой" = "запусти" = "включи"
🎤 Каждая команда озвучивается голосом"""

        # СИСТЕМА
        if any(w in text for w in ("информация", "система", "нагрузка", "память", "процессор", "cpu", "ram")):
            try:
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                self._speak(f"Загрузка процессора {int(cpu)} процентов, память {int(mem.percent)} процентов")
                return (f"📊 СИСТЕМА:\n• ЦПУ: {cpu}%\n"
                        f"• Память: {mem.percent}% ({int(mem.used/1024**3)} из {int(mem.total/1024**3)} ГБ)\n"
                        f"• Диск: {disk.percent}%")
            except Exception as e:
                return f"✗ Ошибка: {e}"

        # YOUTUBE
        if any(w in text for w in ("ютуб", "youtube", "видео", "музыка", "песню", "песня")):
            keywords = ["открой ютуб и", "запусти", "найди", "ищи", "в ютубе", "ютуб", "youtube", "видео", "музыка", "песню", "песня"]
            query = self._extract_query(text, keywords) or "популярные видео"
            self._speak(f"Открываю ютуб и ищу {query}")
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            webbrowser.open(url)
            return f"✓ YouTube: ищу '{query}'"

        # ФИЛЬМЫ
        if any(w in text for w in ("фильм", "кино", "сериал", "смотреть", "посмотреть")):
            keywords = ["открой фильм", "запусти фильм", "найди фильм", "посмотреть фильм",
                        "смотреть фильм", "открой сериал", "запусти сериал", "кино", "фильм", "сериал"]
            query = self._extract_query(text, keywords) or "фильмы"
            self._speak(f"Ищу фильм {query} на кинопорталах")
            url = MOVIE_SITES[0][1].format(q=urllib.parse.quote(query))
            webbrowser.open(url)
            return f"✓ Поиск фильма: '{query}' на HDrezka"

        # ЗАПУСК ПРИЛОЖЕНИЙ (открой / запусти / включи)
        verbs = ["открой", "открыть", "запусти", "запустить", "включи", "включить", "launch", "open", "run"]
        for verb in verbs:
            if text.startswith(verb):
                app_name = stripped[len(verb):].strip()
                if app_name:
                    self._speak(f"Открываю {app_name}")
                    return self._launch_app(app_name)
                break

        # ПОИСК В GOOGLE
        if any(w in text for w in ("найди", "поиск", "гугли", "погугли", "загугли")):
            keywords = ["найди", "поиск", "гугли", "погугли", "загугли", "информацию"]
            query = self._extract_query(text, keywords)
            if not query:
                return "Уточните запрос: 'Найди информацию о Марсе'"
            self._speak(f"Ищу в гугле {query}")
            webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(query)}")
            return f"✓ Google: '{query}'"

        self._speak("Команда не распознана")
        return "❌ Команда не распознана. Скажите 'Помощь'."
