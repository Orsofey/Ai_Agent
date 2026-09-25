#!/bin/bash
# Подписать «Андрей.app» и упаковать в dist/Andrey.dmg (со ссылкой на «Программы»).
#
# Без переменных — подпись ad-hoc: при первом запуске друг один раз нажимает «Всё равно открыть».
# С Apple Developer ID (99 $ в год) — подпись и нотаризация, приложение открывается двойным щелчком:
#   MAC_SIGN_IDENTITY="Developer ID Application: Имя (TEAMID)"
#   APPLE_ID=… APPLE_TEAM_ID=… APPLE_APP_PASSWORD=…   (пароль приложения с appleid.apple.com)
set -euo pipefail
cd "$(dirname "$0")/../.."
APP="dist/Андрей.app"
IDENTITY="${MAC_SIGN_IDENTITY:--}"
ENTITLEMENTS="packaging/macos/entitlements.plist"
[ -d "$APP" ] || { echo "Нет $APP — сначала PyInstaller"; exit 1; }

# Скачанные файлы (llama.cpp и др.) могли получить карантин — снимаем.
xattr -cr "$APP"

sign() {
  if [ "$IDENTITY" = "-" ]; then
    codesign --force --sign - "$@"
  else
    codesign --force --options runtime --timestamp --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$@"
  fi
}
# Сначала все программы и библиотеки внутри (в том числе llama.cpp в Resources), затем само приложение.
find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) -print0 |
  while IFS= read -r -d '' file; do
    if file "$file" | grep -q "Mach-O"; then sign "$file"; fi
  done
sign "$APP"
codesign --verify --deep --strict "$APP" && echo "Подпись проверена"

STAGE="build/dmg"
rm -rf "$STAGE" dist/Andrey.dmg
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Программы"
hdiutil create -volname "Андрей" -srcfolder "$STAGE" -ov -format UDZO dist/Andrey.dmg

if [ "$IDENTITY" != "-" ] && [ -n "${APPLE_ID:-}" ]; then
  sign dist/Andrey.dmg
  xcrun notarytool submit dist/Andrey.dmg --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple dist/Andrey.dmg
  echo "Нотаризация пройдена: открывается двойным щелчком без предупреждений"
fi
ls -lh dist/Andrey.dmg
