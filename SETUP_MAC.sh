#!/bin/bash
# Установка на macOS 12+ (Apple Silicon или Intel): зависимости и модели, один раз.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3.12 || command -v python3.11 || command -v python3 || true)
if [ -z "$PY" ]; then
  echo "Установите Python 3.12 с python.org (или: brew install python@3.12)"; exit 1
fi
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt -r requirements-mac.txt
# Браузер для YouTube и сайтов: Google Chrome/Edge, а если их нет — встроенный Chromium.
if [ ! -d "/Applications/Google Chrome.app" ] && [ ! -d "/Applications/Microsoft Edge.app" ]; then
  .venv/bin/python -m playwright install chromium
fi
# Распознавание речи (Parakeet v3, GigaAM v3, Silero VAD), голоса Piper, llama.cpp (Metal) и Qwen3 4B.
.venv/bin/python scripts/download_model.py
echo
echo "Готово. Запуск: двойной щелчок по START_MAC.command"
echo "При первом запуске разрешите «Микрофон», «Универсальный доступ» и «Мониторинг ввода»"
echo "(Системные настройки → Конфиденциальность и безопасность)."
