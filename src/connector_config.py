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

# «Дом с Алисой» (лампы, розетки, телевизоры): приложение на oauth.yandex.ru с доступами iot:view и iot:control.
YANDEX_IOT_CLIENT_ID = os.getenv('ANDREY_YANDEX_IOT_CLIENT_ID', '')

# Яндекс ID (Диск, Календарь, Почта): oauth.yandex.ru → «Создать приложение» → «Веб-сервисы»,
# доступы: cloud_api:disk.read, cloud_api:disk.write, cloud_api:disk.info, calendar:all, mail:imap_ro, login:email, login:info.
YANDEX_CLIENT_ID = os.getenv('ANDREY_YANDEX_CLIENT_ID', '')
YANDEX_CLIENT_SECRET = os.getenv('ANDREY_YANDEX_CLIENT_SECRET', '')

# Microsoft 365 / Outlook.com: entra.microsoft.com → App registrations → «Личные и рабочие аккаунты»,
# платформа «Mobile and desktop applications», Redirect URI http://localhost:5000/oauth/microsoft/callback.
MS_CLIENT_ID = os.getenv('ANDREY_MS_CLIENT_ID', '')

# Notion: notion.so/profile/integrations → «Публичная интеграция» (OAuth). Без неё — вход по ключу внутренней интеграции.
NOTION_CLIENT_ID = os.getenv('ANDREY_NOTION_CLIENT_ID', '')
NOTION_CLIENT_SECRET = os.getenv('ANDREY_NOTION_CLIENT_SECRET', '')

# Spotify: developer.spotify.com/dashboard → Create app → Web API; Redirect URI http://127.0.0.1:5000/oauth/spotify/callback.
SPOTIFY_CLIENT_ID = os.getenv('ANDREY_SPOTIFY_CLIENT_ID', '')

# Dropbox: dropbox.com/developers/apps → Scoped access → Full Dropbox; Redirect URI http://127.0.0.1:5000/oauth/dropbox/callback.
DROPBOX_APP_KEY = os.getenv('ANDREY_DROPBOX_APP_KEY', '')

# Расширение «Андрей» в магазинах (после публикации кнопка «Подключить браузер» ведёт сразу на «Установить»):
# Chrome Web Store (подходит и для Яндекс Браузера, Opera, Brave) и Microsoft Edge Add-ons.
EXTENSION_STORE_CHROME = os.getenv('ANDREY_EXTENSION_STORE_CHROME', '')
EXTENSION_STORE_EDGE = os.getenv('ANDREY_EXTENSION_STORE_EDGE', '')
