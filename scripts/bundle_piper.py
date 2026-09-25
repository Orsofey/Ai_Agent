"""Скопировать голоса Piper в onedir-сборку для офлайн-установки.

Не падает, если голоса не скачаны: тогда офлайн-сборка использует Silero.
"""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.local_tts_service import PIPER_VOICES, piper_models_dir
from src.storage import data_root

root = Path(__file__).resolve().parents[1]
source = piper_models_dir(data_root())
target = root / 'dist' / 'LocalAIAgent' / 'models' / 'piper'

copied = 0
if source.is_dir():
    for info in PIPER_VOICES.values():
        onnx = source / info['file']
        config = source / (info['file'] + '.json')
        if onnx.is_file() and config.is_file():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(onnx, target / info['file'])
            shutil.copy2(config, target / config.name)
            copied += 1

if copied:
    print(f'Bundled Piper voices: {copied} -> {target}')
else:
    print('Piper voices not found; build will use the Windows system voice.')
