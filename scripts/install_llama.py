"""Установить llama.cpp из вручную скачанного архива (если автоматическая загрузка недоступна).

    python scripts\\install_llama.py llama-b11165-bin-win-cpu-x64.zip
    python scripts\\install_llama.py llama-b11165-bin-win-vulkan-x64.zip   (для видеокарты)
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model_downloader import install_llama_zip
from src.storage import data_root

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    archive = Path(sys.argv[1])
    flavor = 'vulkan' if 'vulkan' in archive.name.casefold() else 'cpu'
    print('Установлено: ' + str(install_llama_zip(data_root(), archive, flavor)))
