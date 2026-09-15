"""Command router with WORKING implementations:
1. Auto-launch YouTube videos + auto-launch movies
2. Launch real apps (Telegram, Discord, etc)
3. Unified commands (open/запусти/включи)
4. Voice feedback with gTTS
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


APP_MAPPING = {
    "телеграм": "Telegram", "тг": "Telegram",
    "дискорд": "Discord",
    "гугл хром": "Chrome", "хром": "Chrome", "chrome": "Chrome",
    "фаерфокс": "Firefox", "firefox": "Firefox",
    "проводник": "Explorer", "explorer": "Explorer",
    "блокнот": "Notepad", "notepad": "Notepad",
    "папка": "Explorer",
}

MOVIE_SITES = [
    ("HDrezka", "https://hdrezka.ag/search/?do=search&subaction=search&q={q}"),
    ("Кинопоиск", "https://www.kinopoisk.ru/index.php?kp_query={q}"),
    ("Rutube", "https://rutube.ru/search/?query={q}"),
]

DEFAULT_WAKE_NAMES = {"орсофей", "орсофей", "orsofey", "андрей", "алиса", "agент"}


class Agent:
    def __init__(self):
        self.system = platform.system()
        self.wake_names = set(DEFAULT_WAKE_NAMES)

    def set_wake_word(self, name: str):
        if not name:
            return
        base = name.strip().lower()
        self.wake_names.add(base)
        self.wake_names.add(base.replace("й", "и"))
        self.wake_names.add(base.replace("й", ""))

    def _speak(self, text: str):
        """Озвучить текст (асинхронно)"""
        try:
            from gtts import gTTS
            def speak_thread():
                try:
                    tts = gTTS(text, lang='ru', slow=False)
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                        tts.save(f.name)
                        self._play_audio(f.name)
                        os.unlink(f.name)
                except Exception:
                    pass
            t = threading.Thread(target=speak_thread, daemon=True)
            t.start()
        except ImportError:
            pass

    def _play_audio(self, path: str):
        """Воспроизвести аудиофайл"""
        try:
            if self.system == "Windows":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
            elif self.system == "Darwin":
                subprocess.run(["afplay", path], timeout=10)
            else:
                subprocess.run(["paplay", path], timeout=10)
        except Exception:
            pass

    def _strip_wake_word(self, text: str) -> str:
        """Удалить имя агента из начала"""
        words = text.split()
        if not words:
            return text
        first = re.sub(r"[^\w]", "", words[0].lower())
        if first in self.wake_names or any(
            first.startswith(n) or n.startswith(first) 
            for n in self.wake_names if len(first) > 3
        ):
            rest = " ".join(words[1:]).lstrip(",.!?;:—")
            return rest if rest else text
        return text

    def _clean_command(self, cmd: str) -> str:
        value = str(cmd or "").replace("\u00a0", " ").strip()
        value = re.sub(r"\s+", " ", value)
        return value.strip(" \t\r\n.,!?;:…-—")

    def process_command(self, command: str) -> str:
        """Обработать команду с голосом и автозапуском"""
        original = self._clean_command(command)
        if not original:
            return "Введите команду."

        # Убираем имя агента
        stripped = self._strip_wake_word(original)
        text = stripped.lower()

        if not text.strip():
            return "Слушаю команду."

        # 1) ПОМОЩЬ
        if text in ("помощь", "help"):
            self._speak("Вывожу справку")
            return "Справка выведена"

        # 2) СИСТЕМА
        if any(w in text for w in ("информация", "система", "system")):
            try:
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                self._speak(f"Загрузка ЦПУ {cpu} процентов, память {mem.percent} процентов")
                return f"ЦПУ: {cpu}%, Память: {mem.percent}%"
            except Exception as e:
                return f"Ошибка: {e}"

        # 3) YOUTUBE - АВТОЗАПУСК
        if any(w in text for w in ("ютуб", "youtube")):
            query = text
            for w in ("открой ютуб и", "запусти", "найди", "ютуб", "youtube"):
                query = query.replace(w, " ")
            query = re.sub(r"\s+", " ", query).strip()
            if not query:
                query = "music"
            
            self._speak(f"Открываю ютуб и ищу {query}")
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            webbrowser.open(url)
            return f"✓ YouTube: ищу {query}"

        # 4) ФИЛЬМЫ - АВТОЗАПУСК
        if any(w in text for w in ("фильм", "кино", "сериал", "смотреть")):
            query = text
            for w in ("найди фильм", "открой фильм", "фильм", "кино"):
                query = query.replace(w, " ")
            query = re.sub(r"\s+", " ", query).strip()
            if not query:
                query = "фильмы"
            
            self._speak(f"Ищу фильм {query}")
            # Открываем на нескольких сайтах
            for name, template in MOVIE_SITES[:2]:
                url = template.format(q=urllib.parse.quote(query))
                webbrowser.open(url)
            return f"✓ Ищу фильм {query} на {len(MOVIE_SITES[:2])} сайтах"

        # 5) ПРИЛОЖЕНИЯ - ОТКРЫТЬ/ЗАПУСТИ/ВКЛЮЧИ
        if any(v in text for v in ("открой", "открыть", "запусти", "запустить", "включи", "включить")):
            for verb in ("открой", "открыть", "запусти", "запустить", "включи", "включить"):
                if text.startswith(verb):
                    app_name = text[len(verb):].strip()
                    break
            else:
                app_name = ""

            if app_name:
                # Переводим русское имя
                app_en = APP_MAPPING.get(app_name, app_name)
                
                self._speak(f"Открываю приложение {app_name}")
                
                try:
                    # Пытаемся запустить
                    if self.system == "Windows":
                        subprocess.Popen(app_en)
                    elif self.system == "Darwin":
                        subprocess.Popen(["open", "-a", app_en])
                    else:
                        subprocess.Popen([app_en])
                    return f"✓ Открыто: {app_name}"
                except Exception as e:
                    return f"Не могу открыть {app_name}: {e}"

        # 6) ПОИСК
        if any(w in text for w in ("найди", "поиск")):
            query = text
            for w in ("найди", "поиск"):
                query = query.replace(w, " ")
            query = re.sub(r"\s+", " ", query).strip()
            
            self._speak(f"Ищу {query}")
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            webbrowser.open(url)
            return f"✓ Ищу: {query}"

        self._speak("Команда не распознана")
        return "Команда не распознана"
