"""One explicit download of speech models; runtime recognition never goes online.

По умолчанию: Silero VAD + Parakeet v3 (RU+EN) + GigaAM v3 (RU) + голоса Piper +
локальная нейросеть для ответов (llama.cpp + Qwen3 4B, ≈2,5 ГБ). Всё бесплатно, без ключей.
Примеры:
    python scripts/download_model.py
    python scripts/download_model.py parakeet vad
    python scripts/download_model.py whisper      # резервный Whisper (для видеокарт NVIDIA)
    python scripts/download_model.py llm:qwen2.5-7b llama:vulkan   # точнее модель + ускорение видеокартой
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model_downloader import download
from src.storage import data_root

DEFAULT = ['vad', 'parakeet', 'gigaam', 'piper', 'llama:cpu', 'llm:qwen3-4b']


def main():
    items = sys.argv[1:] or DEFAULT
    root = data_root()
    print('Папка моделей: ' + str(root / 'models'))
    print('Интернет нужен один раз. Parakeet ≈ 670 МБ, GigaAM ≈ 230 МБ, голоса ≈ 60 МБ, нейросеть Qwen3 ≈ 2,5 ГБ.')

    shown = {}

    def report(item, stage, detail=None):
        if stage == 'progress':
            step = detail['percent'] // 10
            if shown.get(item) != step:
                shown[item] = step
                print(f"  {item}: {detail['percent']}% ({detail['done_mb']} из {detail['total_mb']} МБ)", flush=True)
            return
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
