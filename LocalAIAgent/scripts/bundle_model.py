"""Copy downloaded models into the onedir build for an offline end-user install."""
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.storage import data_root

source = data_root() / 'models'
root = Path(__file__).resolve().parents[1]
target = root / 'dist' / 'LocalAIAgent' / 'models'
folders = ['silero-vad', 'parakeet-tdt-0.6b-v3', 'gigaam-v3-e2e-rnnt', 'piper', 'small', 'whisper-large-v3-turbo']
copied = []
for name in folders:
    folder = source / name
    if folder.is_dir() and any(folder.iterdir()):
        shutil.copytree(folder, target / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.cache', '*.lock', '*.part'))
        copied.append(name)
if not any(n in copied for n in ('parakeet-tdt-0.6b-v3', 'gigaam-v3-e2e-rnnt', 'small')):
    raise SystemExit('Run SETUP_WINDOWS.bat first; no speech recognition model is downloaded.')
print('Bundled models: ' + ', '.join(copied))
