"""One explicit download of speech models; runtime recognition never goes online.

По умолчанию: Silero VAD + Parakeet v3 (RU+EN) + GigaAM v3 (RU) + голоса Piper.
Примеры:
    python scripts/download_model.py
    python scripts/download_model.py parakeet vad
    python scripts/download_model.py whisper      # резервный Whisper (для видеокарт NVIDIA)
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model_downloader import download
from src.storage import data_root

DEFAULT = ['vad', 'parakeet', 'gigaam', 'piper']


def main():
    items = sys.argv[1:] or DEFAULT
    root = data_root()
    print('Папка моделей: ' + str(root / 'models'))
    print('Интернет нужен один раз. Parakeet ≈ 670 МБ, GigaAM ≈ 230 МБ, голоса ≈ 60 МБ каждый.')

    def report(item, stage, detail=None):
        text = {'start': 'скачиваю…', 'done': f'готово ({detail} с)', 'error': f'ОШИБКА: {detail}'}[stage]
        print(f'  {item}: {text}', flush=True)

    ok = download(root, items, report)
    # Хотя бы одна модель распознавания обязательна; голоса — нет (есть системный голос).
    from src.speech import SpeechService
    installed = SpeechService(root).installed()
    if not installed:
        print('Не установлено ни одной модели распознавания. Проверьте интернет и повторите.')
        raise SystemExit(1)
    print('Модели распознавания: ' + ', '.join(sorted(installed)) + ('' if ok else ' (часть загрузок не удалась)'))


if __name__ == '__main__':
    main()
