"""Зрение: навёл мышку или обвёл область — «Андрей» говорит, что видит.

«Что это?», «что здесь написано?», «что под курсором?» — снимок области вокруг курсора;
«сейчас обведу», «что в этой области?» — вы выделяете область мышкой (Windows: «Ножницы», macOS: выбор области);
«что на экране?», «опиши экран» — весь экран.

Описание делает локальная модель зрения Qwen3-VL (llama.cpp, без интернета; скачивается один раз в
Настройки → ИИ → «Зрение»). Пока её нет, на Windows работает встроенное распознавание текста Windows (OCR):
«Андрей» прочитает, что написано. Снимки экрана никуда не отправляются.
"""
import base64
import hashlib
import io
import logging
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import oshelp

log = logging.getLogger(__name__)

VISION_MODELS = {
    'qwen3-vl-2b': {
        'repos': ['Qwen/Qwen3-VL-2B-Instruct-GGUF', 'ggml-org/Qwen3-VL-2B-Instruct-GGUF', 'unsloth/Qwen3-VL-2B-Instruct-GGUF'],
        'title': 'Qwen3-VL 2B — зрение (описывает экран и картинки)', 'size_mb': 2000, 'license': 'Apache 2.0',
    },
    'qwen3-vl-4b': {
        'repos': ['Qwen/Qwen3-VL-4B-Instruct-GGUF', 'ggml-org/Qwen3-VL-4B-Instruct-GGUF', 'unsloth/Qwen3-VL-4B-Instruct-GGUF'],
        'title': 'Qwen3-VL 4B — точнее, нужно 8+ ГБ ОЗУ', 'size_mb': 3400, 'license': 'Apache 2.0',
    },
}
DEFAULT_VISION = 'qwen3-vl-2b'
AROUND = (720, 460)          # область вокруг курсора, пикселей
IDLE_UNLOAD = 300            # модель зрения выгружается после 5 минут без вопросов

CURSOR = re.compile(r'^(?:а\s+)?(?:что|чё|че)\s+(?:это(?:\s+такое)?|здесь|тут|под курсором|под мышкой|под мышью|я показываю|'
                    r'на этой картинке|на картинке|вот это)(?:\s+(?P<q>(?:написано|нарисовано|изображено|показано)\b.*))?$|'
                    r'^(?:посмотри|глянь|взгляни)\s+(?:сюда|вот сюда|на это)(?:\s+и\s+(?P<q2>.+))?$|'
                    r'^(?:прочитай|переведи|объясни)\s+(?:что\s+)?(?:здесь|тут|под курсором)(?:\s+написано)?$', re.I)
AREA = re.compile(r'^(?:сейчас\s+)?(?:обведу|выделю|обвожу|выделяю)\s+(?:область|участок|кусок|фрагмент)?.*$|'
                  r'^(?:что|чё)\s+в\s+(?:этой\s+|выделенной\s+)?(?:области|рамке|выделении)(?:\s+(?P<q>.+))?$|'
                  r'^(?:опиши|посмотри на|прочитай|распознай)\s+(?:эту\s+|выделенную\s+)?область$', re.I)
SCREEN = re.compile(r'^(?:что|чё)\s+(?:на экране|ты видишь|видно на экране)$|^(?:опиши|посмотри на|прочитай)\s+(?:весь\s+)?экран$',
                    re.I)


def parse(text):
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('?!.')
    match = AREA.match(value)
    if match:
        return 'area', (match.groupdict().get('q') or '').strip()
    if SCREEN.match(value):
        return 'screen', ''
    match = CURSOR.match(value)
    if match:
        question = next((g for g in (match.groupdict().get('q'), match.groupdict().get('q2')) if g), '')
        if value.casefold().startswith(('прочитай', 'переведи', 'объясни')):
            question = value
        return 'cursor', question.strip()
    return None


# ---------------- снимки ----------------
def cursor_position():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        point = wintypes.POINT()
        user32 = ctypes.windll.user32
        # «Физические» координаты — те же, что у снимка экрана при масштабе 125–200%.
        getter = getattr(user32, 'GetPhysicalCursorPos', user32.GetCursorPos)
        getter(ctypes.byref(point))
        return point.x, point.y
    if sys.platform == 'darwin':
        import Quartz
        location = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return int(location.x), int(location.y)
    raise RuntimeError('Снимок экрана доступен на Windows и macOS.')


def grab_around(size=AROUND):
    """Область вокруг курсора; курсор отмечен перекрестьем, чтобы модель знала, куда смотреть."""
    from PIL import ImageDraw, ImageGrab
    x, y = cursor_position()
    w, h = size
    box = (x - w // 2, y - h // 2, x + w // 2, y + h // 2)
    image = ImageGrab.grab(bbox=box, all_screens=True) if sys.platform == 'win32' else ImageGrab.grab(bbox=box)
    draw = ImageDraw.Draw(image)
    cx, cy = w // 2, h // 2
    draw.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), outline=(255, 40, 60), width=3)
    return image


def grab_screen():
    from PIL import ImageGrab
    return ImageGrab.grab()


def _clipboard_image_hash():
    from PIL import ImageGrab
    try:
        image = ImageGrab.grabclipboard()
    except Exception:
        return None
    if image is None or isinstance(image, list):
        return None
    return hashlib.md5(image.tobytes()).hexdigest()


def grab_area(timeout=60):
    """Пользователь выделяет область мышкой. Windows — «Ножницы» (снимок в буфер), macOS — screencapture -i."""
    from PIL import Image, ImageGrab
    if sys.platform == 'darwin':
        path = Path(tempfile.gettempdir()) / f'andrey-area-{int(time.time())}.png'
        subprocess.run(['screencapture', '-i', '-x', str(path)], timeout=timeout)
        if not path.exists():
            return None
        image = Image.open(path)
        image.load()
        path.unlink(missing_ok=True)
        return image
    if sys.platform != 'win32':
        raise RuntimeError('Выделение области доступно на Windows и macOS.')
    before = _clipboard_image_hash()
    oshelp.open_path('ms-screenclip:')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.4)
        image = ImageGrab.grabclipboard()
        if image is not None and not isinstance(image, list) and hashlib.md5(image.tobytes()).hexdigest() != before:
            return image
    return None


def png_bytes(image, max_side=1280):
    image = image.convert('RGB')
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


# ---------------- распознавание текста Windows ----------------
WINDOWS_OCR = r'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime]
$asTask=([System.WindowsRuntimeSystemExtensions].GetMethods()|?{$_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0]
function Await($op,$type){$t=$asTask.MakeGenericMethod($type).Invoke($null,@($op));$t.Wait(-1)|Out-Null;$t.Result}
$file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync(PATH)) ([Windows.Storage.StorageFile])
$stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$result.Lines|%{$_.Text}
'''


def windows_ocr(image):
    if sys.platform != 'win32':
        return ''
    path = Path(tempfile.gettempdir()) / f'andrey-ocr-{int(time.time() * 1000)}.png'
    path.write_bytes(png_bytes(image, 2400))
    try:
        code, out, err = oshelp.powershell(WINDOWS_OCR.replace('PATH', oshelp.ps_string(path)), timeout=40)
        return out if code == 0 else ''
    except Exception as exc:
        log.info('Windows OCR failed: %s', exc)
        return ''
    finally:
        path.unlink(missing_ok=True)


# ---------------- модель зрения ----------------
def vision_dir(root, key):
    return Path(root) / 'models' / 'vision' / key


def find_vision(root, key=None):
    """(модель, mmproj) или (None, None)."""
    for name in ([key] if key else []) + list(VISION_MODELS):
        folder = vision_dir(root, name)
        if not folder.is_dir():
            continue
        models = sorted(p for p in folder.glob('*.gguf') if not p.name.casefold().startswith('mmproj'))
        projectors = sorted(folder.glob('mmproj*.gguf'))
        if models and projectors:
            return models[0], projectors[0]
    return None, None


def pick_files(names):
    """Из файлов репозитория выбрать веса (Q4_K_M, иначе Q8_0) и проектор изображений (F16/Q8_0)."""
    ggufs = [n for n in names if n.casefold().endswith('.gguf') and '/' not in n and '-of-' not in n]
    projectors = [n for n in ggufs if n.casefold().startswith('mmproj')]
    weights = [n for n in ggufs if n not in projectors]
    model = next((n for pattern in ('q4_k_m', 'q5_k_m', 'q8_0', 'f16') for n in weights if pattern in n.casefold()), None)
    projector = next((n for pattern in ('f16', 'q8_0', 'bf16', '') for n in projectors if pattern in n.casefold()), None)
    return model, projector


def download_vision(root, key=DEFAULT_VISION, session=None, progress=None):
    from .model_downloader import HF_API, HF_FILE, DownloadError, _session, http_download
    key = key if key in VISION_MODELS else DEFAULT_VISION
    found = find_vision(root, key)
    if found[0]:
        return found
    session = _session(session)
    errors = []
    for repo in VISION_MODELS[key]['repos']:
        try:
            response = session.get(HF_API.format(repo=repo), timeout=20)
            if response.status_code == 404:
                errors.append(repo + ': нет репозитория')
                continue
            response.raise_for_status()
            model, projector = pick_files([s.get('rfilename', '') for s in response.json().get('siblings', [])])
            if not model or not projector:
                errors.append(repo + ': нет GGUF и mmproj')
                continue
            folder = vision_dir(root, key)
            http_download(HF_FILE.format(repo=repo, file=projector), folder / projector, session, progress)
            http_download(HF_FILE.format(repo=repo, file=model), folder / model, session, progress)
            return find_vision(root, key)
        except DownloadError:
            raise
        except Exception as exc:
            errors.append(f'{repo}: {exc}'[:160])
    raise DownloadError('не удалось скачать модель зрения. ' + '; '.join(errors))


class VisionServer:
    """Отдельный llama-server с моделью зрения: запускается по первому вопросу, выгружается при простое."""

    def __init__(self, root, session=None):
        self.root = Path(root)
        self.process = None
        self.port = None
        self.lock = threading.Lock()
        self.last_used = 0.0
        self._session = session
        threading.Thread(target=self._idle, daemon=True, name='vision-idle').start()

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.trust_env = False
        return self._session

    def installed(self, key=None):
        return find_vision(self.root, key)[0] is not None

    def running(self):
        return self.process is not None and self.process.poll() is None

    def ensure(self, key=None, wait=120):
        from .brain.local_llm import find_binary, free_port
        with self.lock:
            if not self.running():
                model, projector = find_vision(self.root, key)
                if model is None:
                    raise RuntimeError('Модель зрения не установлена: Настройки → ИИ → «Зрение».')
                binary, flavor = find_binary(self.root)
                if binary is None:
                    raise RuntimeError('Не найден llama-server. Откройте Настройки → ИИ → «Скачать нейросеть».')
                self.port = free_port()
                args = [str(binary), '-m', str(model), '--mmproj', str(projector), '--host', '127.0.0.1',
                        '--port', str(self.port), '-c', '4096', '-np', '1', '--jinja']
                if sys.platform == 'darwin' or flavor == 'vulkan':
                    args += ['-ngl', '99']
                logs = self.root / 'logs'
                logs.mkdir(parents=True, exist_ok=True)
                self.process = subprocess.Popen(args, stdout=open(logs / 'vision-server.log', 'ab'),
                                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(binary.parent),
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not self.running():
                raise RuntimeError('Модель зрения не запустилась (logs/vision-server.log). Обновите llama.cpp в '
                                   'Настройки → ИИ → «Скачать нейросеть».')
            try:
                if self.session.get(f'http://127.0.0.1:{self.port}/health', timeout=1.5).status_code == 200:
                    self.last_used = time.monotonic()
                    return f'http://127.0.0.1:{self.port}/v1'
            except Exception:
                pass
            time.sleep(0.4)
        raise RuntimeError('Модель зрения ещё загружается — повторите через несколько секунд.')

    def describe(self, png, prompt, key=None):
        base = self.ensure(key)
        image = 'data:image/png;base64,' + base64.b64encode(png).decode()
        body = {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': image}},
                                                          {'type': 'text', 'text': prompt}]}],
                'max_tokens': 220, 'temperature': 0.2}
        response = self.session.post(base + '/chat/completions', json=body, timeout=120)
        response.raise_for_status()
        self.last_used = time.monotonic()
        text = response.json()['choices'][0]['message']['content'] or ''
        return re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()

    def stop(self):
        with self.lock:
            if self.running():
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None

    def _idle(self):
        while True:
            time.sleep(30)
            if self.running() and time.monotonic() - self.last_used > IDLE_UNLOAD:
                log.info('Vision model unloaded after idle')
                self.stop()


PROMPTS = {
    'cursor': 'Пользователь навёл курсор (красный кружок) на эту часть экрана и спрашивает: «{q}». '
              'Ответь по-русски в 1–3 предложениях: что это. Если там текст — перескажи главное или прочитай его.',
    'area': 'Пользователь выделил эту область экрана и спрашивает: «{q}». Ответь по-русски в 1–3 предложениях. '
            'Если там текст — перескажи главное или прочитай его.',
    'screen': 'Это снимок экрана пользователя. Вопрос: «{q}». Кратко по-русски (2–3 предложения): что открыто и что видно.',
}


class Vision:
    def __init__(self, root, server=None, grabber=None, ocr=None):
        self.root = Path(root)
        self.server = server or VisionServer(root)
        self.grabber = grabber or {'cursor': grab_around, 'area': grab_area, 'screen': grab_screen}
        self.ocr = ocr or windows_ocr

    def look(self, mode, question='', settings=None):
        image = self.grabber[mode]()
        if image is None:
            return 'Область не выделена.'
        question = question or ('что это' if mode != 'screen' else 'что на экране')
        key = (settings or {}).get('vision_model', DEFAULT_VISION)
        if self.server.installed(key):
            try:
                answer = self.server.describe(png_bytes(image), PROMPTS[mode].format(q=question), key)
                if answer:
                    return answer
            except Exception as exc:
                log.info('Vision model failed: %s', exc)
                error = str(exc)
            else:
                error = ''
        else:
            error = ''
        text = self.ocr(image)
        if text.strip():
            lines = [line for line in text.splitlines() if line.strip()]
            short = ' '.join(lines)[:600]
            return f'Вижу текст: {short}' + ('' if self.server.installed(key) else
                                             ' (чтобы я описывал и картинки, установите «Зрение» в Настройки → ИИ).')
        if error:
            return error
        return ('Чтобы я видел экран, установите модель зрения: Настройки → ИИ → «Зрение» (≈2 ГБ, один раз). '
                'Текст на Windows я уже умею читать — наведите на надпись.')

    def handle(self, text, settings=None):
        request = parse(text)
        if request is None:
            return None
        try:
            return self.look(request[0], request[1], settings)
        except RuntimeError as exc:
            return str(exc)
