"""Voice synthesis module for command feedback.

Uses Yandex SpeechKit API (free tier) or gTTS for offline TTS.
Falls back to silent mode if no service is available.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

try:
    import requests
except ImportError:
    requests = None


class VoiceFeedback:
    """Generates and plays voice responses for commands."""
    
    def __init__(self, lang: str = "ru"):
        self.lang = lang
        self.enabled = True
        self.use_gtts = bool(gTTS)
        self.cache_dir = Path.home() / ".local" / "share" / "LocalAIAgent" / "voice_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def speak(self, text: str, voice_name: str = "default") -> bool:
        """Generate and play speech for text."""
        if not self.enabled or not text.strip():
            return False
        
        # Generate audio file
        audio_file = self._get_or_generate_audio(text, voice_name)
        if not audio_file or not audio_file.exists():
            return False
        
        # Play audio
        return self._play_audio(str(audio_file))
    
    def _get_or_generate_audio(self, text: str, voice_name: str) -> Path | None:
        """Get cached audio or generate new one."""
        # Cache key based on text hash
        import hashlib
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        cache_file = self.cache_dir / f"{voice_name}_{text_hash}.mp3"
        
        if cache_file.exists():
            return cache_file
        
        # Generate using gTTS (free, offline after first use)
        try:
            if self.use_gtts:
                tts = gTTS(text, lang=self.lang, slow=False)
                tts.save(str(cache_file))
                return cache_file
        except Exception as e:
            print(f"[Voice] Generation failed: {e}")
            return None
        
        return None
    
    def _play_audio(self, filepath: str) -> bool:
        """Play audio file using system player."""
        try:
            if sys.platform == "win32":
                # Windows: use winsound
                import winsound
                winsound.PlaySound(filepath, winsound.SND_FILENAME)
                return True
            elif sys.platform == "darwin":
                # macOS: use afplay
                subprocess.run(["afplay", filepath], check=False, timeout=30)
                return True
            else:
                # Linux: try paplay or aplay
                try:
                    subprocess.run(["paplay", filepath], check=False, timeout=30)
                    return True
                except FileNotFoundError:
                    subprocess.run(["aplay", filepath], check=False, timeout=30)
                    return True
        except Exception as e:
            print(f"[Voice] Playback failed: {e}")
            return False
    
    def disable(self):
        """Disable voice feedback."""
        self.enabled = False
    
    def enable(self):
        """Enable voice feedback."""
        self.enabled = True


# Global instance
_voice = None


def get_voice_feedback() -> VoiceFeedback:
    """Get the global voice feedback instance."""
    global _voice
    if _voice is None:
        _voice = VoiceFeedback()
    return _voice


def speak(text: str, voice_name: str = "default") -> None:
    """Play voice feedback for a command response."""
    voice = get_voice_feedback()
    voice.speak(text, voice_name)
