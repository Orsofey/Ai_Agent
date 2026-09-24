"""Compatibility shim: recognition moved to src.speech (Parakeet / GigaAM / Whisper)."""
from .speech import SpeechService as WhisperRecognizer, SpeechError, decode

__all__ = ['WhisperRecognizer', 'SpeechError', 'decode']
