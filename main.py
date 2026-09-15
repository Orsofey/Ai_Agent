"""Desktop entry point for Local AI Agent.

Запускает Flask-сервер в фоновом потоке, ждёт готовности, открывает UI.
Использует нативное окно (pywebview), иначе — браузер.

Важно: сервер слушает 0.0.0.0, чтобы к нему можно было подключиться
с телефона по локальной сети (PWA). Сам UI на ПК открывается на 127.0.0.1.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Пути: работают и из исходников, и из собранного PyInstaller-бандла.
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

HOST = "0.0.0.0"          # слушаем все интерфейсы (доступ с телефона)
OPEN_HOST = "127.0.0.1"   # локальное окно/браузер
PORT = int(os.environ.get("LOCAL_AI_PORT", "5000"))
URL = f"http://{OPEN_HOST}:{PORT}"


def local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _port_is_open(host: str, port: int, timeout: float = 0.3) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _find_free_port(start: int) -> int:
    port = start
    for _ in range(20):
        if not _port_is_open(OPEN_HOST, port):
            return port
        port += 1
    return start


def start_server() -> None:
    """Запустить Flask в daemon-потоке."""
    from app import app  # импорт поздний, чтобы пути уже были готовы

    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


def wait_for_server(timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_is_open(OPEN_HOST, PORT):
            return True
        time.sleep(0.2)
    return False


def open_in_window() -> bool:
    """Открыть UI в нативном окне через pywebview."""
    try:
        import webview  # type: ignore
    except ImportError:
        return False

    webview.create_window(
        "Local AI Agent",
        URL,
        width=1280,
        height=860,
        min_size=(900, 600),
    )
    webview.start()
    return True


def main() -> int:
    global PORT, URL

    if not _port_is_open(OPEN_HOST, PORT):
        PORT = _find_free_port(PORT)
        URL = f"http://{OPEN_HOST}:{PORT}"

    server = threading.Thread(target=start_server, name="flask-server", daemon=True)
    server.start()

    if not wait_for_server():
        print("Не удалось запустить локальный сервер. Закройте программу и попробуйте снова.")
        try:
            input("Нажмите Enter для выхода...")
        except EOFError:
            pass
        return 1

    ip = local_ip()
    print("=" * 60)
    print("  Local AI Agent запущен")
    print("=" * 60)
    print(f"  На этом компьютере:  {URL}")
    print(f"  С телефона (Wi-Fi):  http://{ip}:{PORT}")
    print()
    print("  Чтобы подключить телефон:")
    print("  1. Подключите телефон к той же Wi-Fi сети")
    print(f"  2. Откройте в браузере: http://{ip}:{PORT}")
    print("  3. Меню браузера → «Установить приложение» / «На главный экран»")
    print("=" * 60)
    print()

    if not open_in_window():
        webbrowser.open(URL)
        try:
            while server.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
