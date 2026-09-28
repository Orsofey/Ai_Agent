"""Запуск сервера подписки в контейнере (Amvera, любой VPS): waitress на порту PORT (по умолчанию 80)."""
import logging
import os

from waitress import serve

from license_server import create_app

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

if __name__ == '__main__':
    serve(create_app(), host='0.0.0.0', port=int(os.environ.get('PORT', '80')), threads=48)  # долгие опросы моста держат потоки
