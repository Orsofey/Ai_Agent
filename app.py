"""Local AI Agent - локальный Flask-сервер с поддержкой LAN и PWA.

Особенности:
- Доступ с телефона по локальной сети (host=0.0.0.0)
- Раздача PWA (manifest.json + service worker)
- Автозапуск с Windows (через реестр)
- Корректные импорты platform и winreg
"""
from datetime import datetime
import hashlib
import json
import os
import platform
import secrets
import socket
import sys
import uuid
from pathlib import Path

# Делаем корень проекта импортируемым и из исходников, и из PyInstaller.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template, request, send_from_directory, session

from src.agent import LocalComputerAgent
from src.app_catalog import catalog

if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path(sys.executable).parent)) / "LocalAIAgent" / "data"
else:
    RESOURCE_DIR = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"
CHATS_FILE = DATA_DIR / "chats.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
app.secret_key = os.environ.get("LOCAL_AI_SECRET", "change-this-local-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
agent = LocalComputerAgent()


def ensure_json(path, default):
    if not path.exists():
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path, default):
    ensure_json(path, default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return f"{salt}${digest}"


def password_matches(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
        return secrets.compare_digest(check, digest)
    except ValueError:
        return False


def signed_in():
    return bool(session.get("storage_key"))


def display_name():
    return session.get("display_name", "Гость")


def storage_key():
    return session.get("storage_key", "")


def default_settings():
    return {
        "voice_enabled": True,
        "voice_language": "ru-RU",
        "theme": "light",
        "notifications": True,
        "wake_word": "Орсофей",
        "microphone": "",
        "autostart": False,
    }


def local_ip():
    """Определить локальный IP для доступа с телефона."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


for path in (USERS_FILE, CHATS_FILE, SETTINGS_FILE):
    ensure_json(path, {})


# ============ PWA ============
@app.get("/manifest.json")
def manifest():
    return send_from_directory(str(RESOURCE_DIR / "static"), "manifest.json", mimetype="application/manifest+json")


@app.get("/service-worker.js")
def service_worker():
    response = send_from_directory(str(RESOURCE_DIR / "static"), "service-worker.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    return response


# ============ СТРАНИЦЫ ============
@app.get("/")
def index():
    if not signed_in():
        return render_template("login.html")
    return render_template(
        "index.html",
        username=display_name(),
        guest=bool(session.get("guest")),
        server_ip=local_ip(),
        server_port=request.host.split(":")[-1] if ":" in request.host else "5000",
    )


@app.get("/favicon.ico")
def favicon():
    return (("", 204))


@app.get("/health")
def health():
    return jsonify(ok=True, application="Local AI Agent", version="3.0", ip=local_ip())


# ============ АУТЕНТИФИКАЦИЯ ============
@app.post("/guest")
def guest():
    session.clear()
    session["guest"] = True
    session["display_name"] = "Гость"
    session["storage_key"] = "guest_" + uuid.uuid4().hex
    return jsonify(success=True, message="Продолжено без аккаунта")


@app.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    email = str(data.get("email", "")).strip()
    if not 3 <= len(username) <= 40:
        return jsonify(success=False, message="Имя пользователя: от 3 до 40 символов")
    if len(password) < 6:
        return jsonify(success=False, message="Пароль должен содержать минимум 6 символов")
    users = read_json(USERS_FILE, {})
    if username.casefold() in {key.casefold() for key in users}:
        return jsonify(success=False, message="Пользователь уже существует")
    users[username] = {
        "password": password_hash(password),
        "email": email,
        "created_at": datetime.now().isoformat(),
    }
    write_json(USERS_FILE, users)
    return jsonify(success=True, message="Регистрация успешна")


@app.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    record = read_json(USERS_FILE, {}).get(username)
    if not record or not password_matches(password, record.get("password", "")):
        return jsonify(success=False, message="Неверное имя пользователя или пароль")
    session.clear()
    session["display_name"] = username
    session["storage_key"] = username
    session["guest"] = False
    return jsonify(success=True, message="Вход выполнен")


@app.post("/logout")
def logout():
    session.clear()
    return jsonify(success=True)


# ============ ЧАТ ============
@app.post("/chat")
def chat():
    if not signed_in():
        return jsonify(success=False, message="Выберите вход или «Продолжить как гость»"), 401
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    if not message:
        return jsonify(success=False, message="Введите команду")

    # Передаём кастомное имя агента в роутер
    try:
        stored = read_json(SETTINGS_FILE, {}).get(storage_key(), {})
        wake = stored.get("wake_word")
        if wake:
            agent.set_wake_word(wake)
        agent.set_voice_enabled(bool(stored.get("voice_enabled", True)))
    except Exception:
        pass

    response = agent.process_command(message)
    chats = read_json(CHATS_FILE, {})
    key = storage_key()
    chats.setdefault(key, []).append({
        "user": message,
        "agent": response,
        "timestamp": datetime.now().isoformat(),
    })
    chats[key] = chats[key][-500:]
    write_json(CHATS_FILE, chats)
    return jsonify(success=True, response=response)


@app.get("/history")
def history():
    if not signed_in():
        return jsonify(success=False, message="Требуется вход или гостевой режим"), 401
    return jsonify(success=True, history=read_json(CHATS_FILE, {}).get(storage_key(), []))


@app.post("/clear_history")
def clear_history():
    if not signed_in():
        return jsonify(success=False, message="Требуется вход или гостевой режим"), 401
    chats = read_json(CHATS_FILE, {})
    chats[storage_key()] = []
    write_json(CHATS_FILE, chats)
    return jsonify(success=True, message="История очищена")


@app.post("/voice")
def voice():
    """Озвучить текст (для мобильного клиента, где Web Speech TTS недоступен)."""
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify(success=False, message="Пустой текст")
    try:
        agent._speak(text)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, message=str(e))


# ============ НАСТРОЙКИ ============
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not signed_in():
        return jsonify(success=False, message="Требуется вход или гостевой режим"), 401
    settings_data = read_json(SETTINGS_FILE, {})
    key = storage_key()
    if request.method == "GET":
        result = default_settings()
        result.update(settings_data.get(key, {}))
        return jsonify(success=True, settings=result)

    incoming = request.get_json(silent=True) or {}
    result = default_settings()
    result.update({item: incoming[item] for item in result if item in incoming})
    settings_data[key] = result
    write_json(SETTINGS_FILE, settings_data)

    # Автозапуск с Windows
    if platform.system() == "Windows":
        try:
            import winreg
            run_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            if result.get("autostart"):
                exe_path = sys.executable
                winreg.SetValueEx(run_key, "LocalAIAgent", 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(run_key, "LocalAIAgent")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(run_key)
        except Exception:
            pass

    return jsonify(success=True, message="Настройки сохранены", settings=result)


# ============ ПРИЛОЖЕНИЯ ============
@app.get("/apps")
def apps():
    if not signed_in():
        return jsonify(success=False, message="Требуется вход или гостевой режим"), 401
    return jsonify(success=True, applications=catalog.list_applications(force=True))


@app.post("/apps/launch")
def launch_app():
    if not signed_in():
        return jsonify(success=False, message="Требуется вход или гостевой режим"), 401
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify(success=False, message="Не указано имя приложения")
    try:
        catalog.launch_app(name)
        return jsonify(success=True, response=f"✓ Открыто: {name}")
    except Exception as e:
        return jsonify(success=False, message=str(e))


# ============ СЕТЬ ============
@app.get("/network")
def network():
    """Инфо для подключения телефона."""
    if not signed_in():
        return jsonify(success=False, message="Требуется вход или гостевой режим"), 401
    port = request.host.split(":")[-1] if ":" in request.host else "5000"
    return jsonify(success=True, ip=local_ip(), port=port, url=f"http://{local_ip()}:{port}")
