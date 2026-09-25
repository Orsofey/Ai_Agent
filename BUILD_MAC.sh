#!/bin/bash
# Сборка «Андрей.app» и образа диска «Andrey.dmg» со всеми моделями внутри (работает без интернета).
#   BUNDLE_LLM=qwen3-1.7b ./BUILD_MAC.sh   — образ меньше на ~1,4 ГБ
#   BUNDLE_LLM=none ./BUILD_MAC.sh         — без нейросети (скачается при первом запуске)
set -e
cd "$(dirname "$0")"
./SETUP_MAC.sh
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
# Подпись: без Apple Developer ID — ad-hoc (при первом запуске: правый клик → «Открыть»).
codesign --force --deep --sign "${MAC_SIGN_IDENTITY:--}" "dist/Андрей.app"
rm -f dist/Andrey.dmg
hdiutil create -volname "Андрей" -srcfolder "dist/Андрей.app" -ov -format UDZO dist/Andrey.dmg
echo "Готово: dist/Andrey.dmg (перетащите «Андрей» в «Программы»)."
echo "Для раздачи без предупреждений подпишите Developer ID и нотарифицируйте: xcrun notarytool submit dist/Andrey.dmg …"
