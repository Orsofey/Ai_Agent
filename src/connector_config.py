"""Ключи приложений для кнопок «Подключить» (Настройки → «Интеграции»).

Их получает РАЗРАБОТЧИК один раз (см. docs/INTEGRATIONS_OAUTH.md) и вписывает сюда перед сборкой —
тогда пользователи просто нажимают «Подключить» и входят в свой аккаунт. Это не секреты пользователей:
для настольных приложений Google и GitHub считают такие ключи публичными.
Можно задать и переменными окружения (удобно для проверки).
"""
import os

# Адрес вашего Трекера (сервер с API из docs/TRACKER_API.md), например https://tracker.example.ru
TRACKER_URL = os.getenv('ANDREY_TRACKER_URL', '')

# GitHub: Settings → Developer settings → OAuth Apps → New → включить «Device Flow».
GITHUB_CLIENT_ID = os.getenv('ANDREY_GITHUB_CLIENT_ID', '')

# Google Cloud Console → APIs & Services → Credentials → OAuth client ID → «Desktop app».
GOOGLE_CLIENT_ID = os.getenv('ANDREY_GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('ANDREY_GOOGLE_CLIENT_SECRET', '')

# Miro: miro.com/app/settings/user-profile/apps → Create new app; Redirect URI — см. документацию.
MIRO_CLIENT_ID = os.getenv('ANDREY_MIRO_CLIENT_ID', '')
MIRO_CLIENT_SECRET = os.getenv('ANDREY_MIRO_CLIENT_SECRET', '')
