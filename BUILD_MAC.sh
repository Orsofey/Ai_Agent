#!/bin/bash
# Сборка «Андрей.app» и образа диска «Andrey.dmg» со всеми моделями внутри (работает без интернета).
#   BUNDLE_LLM=qwen3-1.7b ./BUILD_MAC.sh   — образ меньше на ~1,4 ГБ
#   BUNDLE_LLM=none ./BUILD_MAC.sh         — без нейросети (скачается при первом запуске)
set -e
cd "$(dirname "$0")"
./SETUP_MAC.sh
# На Mac с M1–M5 Python должен быть arm64, иначе получится Intel-приложение (через Rosetta, медленно).
PY_ARCH=$(.venv/bin/python -c "import platform; print(platform.machine())")
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ] && [ "$PY_ARCH" != "arm64" ]; then
  echo "Python собран для $PY_ARCH, а Mac на Apple Silicon. Установите Python 3.12 с python.org"
  echo "(universal2) или brew в /opt/homebrew, удалите папку .venv и запустите сборку снова."; exit 1
fi
.venv/bin/python -m unittest discover -s tests
# Иконка .icns из PNG
mkdir -p build/icon.iconset
for size in 16 32 64 128 256 512; do
  sips -z $size $size static/icon-512.png --out build/icon.iconset/icon_${size}x${size}.png >/dev/null
  sips -z $((size*2)) $((size*2)) static/icon-512.png --out build/icon.iconset/icon_${size}x${size}@2x.png >/dev/null
done
iconutil -c icns build/icon.iconset -o build/icon.icns
.venv/bin/python -m PyInstaller --noconfirm --clean LocalAIAgent.spec
BUNDLE_TARGET="dist/Андрей.app/Contents/Resources/models" .venv/bin/python scripts/bundle_model.py
# Подпись (ad-hoc или Developer ID) и образ диска со ссылкой на «Программы».
packaging/macos/package.sh
echo "Готово: dist/Andrey.dmg — отправьте другу. Инструкция: docs/MAC_FOR_FRIEND.md"
