"""Vosk-based offline speech recognition module."""
import json
import sys
from pathlib import Path

try:
    from vosk import Model, KaldiRecognizer
    import sounddevice as sd
    import queue
except ImportError:
    print("⚠ Vosk не установлен. Используется Web Speech API браузера.")
    VOSK_AVAILABLE = False
else:
    VOSK_AVAILABLE = True


class VoskRecognizer:
    """Offline speech recognition using Vosk."""
    
    def __init__(self, lang="ru"):
        self.lang = lang
        self.model = None
        self.recognizer = None
        self.audio_queue = queue.Queue()
        
        if not VOSK_AVAILABLE:
            return
        
        try:
            # Скачиваем модель если её нет
            model_path = self._get_model_path()
            if not model_path.exists():
                self._download_model()
            
            self.model = Model(str(model_path))
            self.recognizer = KaldiRecognizer(self.model, 16000)
        except Exception as e:
            print(f"Ошибка инициализации Vosk: {e}")
            self.model = None
    
    def _get_model_path(self):
        """Получить путь к модели Vosk."""
        if self.lang == "ru":
            model_name = "vosk-model-ru-0.42-big"
        else:
            model_name = "vosk-model-en-us-0.42-big"
        
        models_dir = Path.home() / ".vosk-models"
        return models_dir / model_name
    
    def _download_model(self):
        """Скачать модель Vosk."""
        import urllib.request
        import tarfile
        
        model_path = self._get_model_path()
        model_path.parent.mkdir(parents=True, exist_ok=True)
        
        if self.lang == "ru":
            url = "https://alphacephei.com/vosk/models/vosk-model-ru-0.42-big.zip"
        else:
            url = "https://alphacephei.com/vosk/models/vosk-model-en-us-0.42-big.zip"
        
        print(f"Загружаю модель {self.lang}... это может занять несколько минут.")
        try:
            urllib.request.urlretrieve(url, str(model_path.parent / "model.zip"))
            print("Модель загружена, распаковываю...")
            # Распаковка
        except Exception as e:
            print(f"Ошибка загрузки модели: {e}")
    
    def recognize_audio(self, audio_data):
        """Распознать речь из аудио данных."""
        if not self.recognizer:
            return None
        
        try:
            if self.recognizer.AcceptWaveform(audio_data):
                result = json.loads(self.recognizer.Result())
                return result.get("result", [{}])[0].get("conf", 0), " ".join(r.get("conf", 0) for r in result.get("result", []))
            else:
                partial = json.loads(self.recognizer.PartialResult())
                return 0, partial.get("partial", "")
        except Exception as e:
            print(f"Ошибка распознавания: {e}")
            return None
    
    def is_available(self):
        """Проверить доступность Vosk."""
        return VOSK_AVAILABLE and self.model is not None


def get_recognizer(lang="ru"):
    """Получить распознаватель речи."""
    if VOSK_AVAILABLE:
        return VoskRecognizer(lang)
    return None
