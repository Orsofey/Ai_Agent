"""Скачать голоса Piper (Ирина, Денис, Amy). Оставлен для совместимости: см. download_model.py."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model_downloader import download
from src.storage import data_root

if __name__ == '__main__':
    download(data_root(), ['piper'], lambda item, stage, detail=None: print(item, stage, detail or ''))
