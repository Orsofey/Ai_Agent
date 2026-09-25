"""Copy downloaded models into the onedir build so the installer works fully offline.

После установки пользователю ничего не нужно скачивать: распознавание речи,
голоса, движок llama.cpp и нейросеть уже внутри программы.

Какая нейросеть попадёт в установщик — переменная BUNDLE_LLM (по умолчанию qwen3-4b):
    set BUNDLE_LLM=qwen3-1.7b   (установщик меньше на ~1,4 ГБ)
    set BUNDLE_LLM=none          (без нейросети — докачается при первом запуске)
"""
from pathlib import Path
import os
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.storage import data_root

source = data_root() / 'models'
root = Path(__file__).resolve().parents[1]
# Windows: dist/LocalAIAgent/models; macOS: BUNDLE_TARGET=dist/Андрей.app/Contents/Resources/models
target = Path(os.getenv('BUNDLE_TARGET') or root / 'dist' / 'LocalAIAgent' / 'models')
bundle_llm = os.getenv('BUNDLE_LLM', 'qwen3-4b')
folders = ['silero-vad', 'parakeet-tdt-0.6b-v3', 'gigaam-v3-e2e-rnnt', 'piper', 'small', 'whisper-large-v3-turbo',
           'llama.cpp']
if bundle_llm != 'none':
    folders.append('llm/' + bundle_llm)
ignore = shutil.ignore_patterns('.cache', '*.lock', '*.part', '*.download', '*.zip')
copied = []
for name in folders:
    folder = source / name
    if folder.is_dir() and any(folder.iterdir()):
        shutil.copytree(folder, target / name, dirs_exist_ok=True, ignore=ignore)
        copied.append(name)
if not any(n in copied for n in ('parakeet-tdt-0.6b-v3', 'gigaam-v3-e2e-rnnt', 'small')):
    raise SystemExit('Run SETUP_WINDOWS.bat (SETUP_MAC.sh on Mac) first; no speech recognition model is downloaded.')
if bundle_llm != 'none' and ('llm/' + bundle_llm not in copied or 'llama.cpp' not in copied):
    print('WARNING: local AI model or llama.cpp is not downloaded; it will be downloaded on first launch.')
size = sum(f.stat().st_size for f in target.rglob('*') if f.is_file()) / 1e9
print('Bundled models: ' + ', '.join(copied) + f' ({size:.1f} GB)')
