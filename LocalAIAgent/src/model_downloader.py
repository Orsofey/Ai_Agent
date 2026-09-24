"""One-time model downloads (Hugging Face). Runtime recognition never goes online."""
import logging
import re
import sys
import os
import shutil
import threading
import time
from pathlib import Path

from .speech.engines import ONNX_MODELS, VAD_MODEL, WHISPER_MODELS, find_model, models_dir

log = logging.getLogger(__name__)
_running = threading.Lock()
PIPER_DEFAULT = ('irina', 'denis', 'amy')


def status(root):
    from .local_tts_service import voice_files, PIPER_VOICES
    result = {'stt': {}, 'piper': {}}
    for key, info in ONNX_MODELS.items():
        result['stt'][key] = dict(title=info['title'], size_mb=info['size_mb'],
                                  installed=find_model(root, info['folder']) is not None)
    result['stt']['whisper'] = dict(title='Whisper (резерв, видеокарта NVIDIA)', size_mb=1600,
                                    installed=any(find_model(root, m['folder'], 'model.bin') for m in WHISPER_MODELS.values()))
    result['vad'] = dict(title='Silero VAD', size_mb=VAD_MODEL['size_mb'],
                         installed=find_model(root, VAD_MODEL['folder'], 'silero_vad.onnx') is not None)
    for name, info in PIPER_VOICES.items():
        result['piper'][name] = dict(title=info['title'], installed=voice_files(name, root)[0] is not None)
    from .brain.local_llm import LOCAL_MODELS, find_model as find_llm, find_binary
    result['llm'] = {key: dict(title=info['title'], size_mb=info['size_mb'], ram_gb=info['ram_gb'],
                               installed=find_llm(root, key) is not None) for key, info in LOCAL_MODELS.items()}
    result['llama'] = {flavor: dict(installed=find_binary(root, flavor == 'vulkan')[1] in (flavor, 'system'))
                       for flavor in ('cpu', 'vulkan')}
    result['downloading'] = _running.locked()
    return result


def _fresh_dir(target):
    tmp = target.with_name(target.name + '.download')
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    return tmp


def download_onnx(key, root):
    import onnx_asr
    info = ONNX_MODELS[key]
    target = models_dir(root) / info['folder']
    if find_model(root, info['folder']):
        return target
    tmp = _fresh_dir(target)
    try:
        onnx_asr.load_model(info['name'], str(tmp), quantization='int8')
    except Exception as exc:
        log.info('int8 variant unavailable for %s (%s), downloading full precision', key, exc)
        shutil.rmtree(tmp, ignore_errors=True)
        onnx_asr.load_model(info['name'], str(tmp))
    shutil.rmtree(tmp / '.cache', ignore_errors=True)
    os.replace(tmp, target)
    return target


def download_vad(root):
    import onnx_asr
    target = models_dir(root) / VAD_MODEL['folder']
    if find_model(root, VAD_MODEL['folder'], 'silero_vad.onnx'):
        return target
    tmp = _fresh_dir(target)
    onnx_asr.load_vad('silero', str(tmp))
    shutil.rmtree(tmp / '.cache', ignore_errors=True)
    os.replace(tmp, target)
    return target


def download_whisper(root, gpu=None):
    from huggingface_hub import snapshot_download
    if gpu is None:
        from .speech.engines import WhisperEngine
        gpu = WhisperEngine._cuda()
    info = WHISPER_MODELS['gpu' if gpu else 'cpu']
    target = models_dir(root) / info['folder']
    if (target / 'model.bin').exists():
        return target
    snapshot_download(info['repo'], local_dir=str(target), allow_patterns=['*.json', '*.bin', '*.txt'])
    return target


GITHUB_RELEASE = 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'
GITHUB_LATEST_PAGE = 'https://github.com/ggml-org/llama.cpp/releases/latest'
GITHUB_DOWNLOAD = 'https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-{flavor}-x64.zip'
HF_API = 'https://huggingface.co/api/models/{repo}'
HF_FILE = 'https://huggingface.co/{repo}/resolve/main/{file}'
RUNTIME_ASSETS = {'cpu': ('bin-win-cpu-x64.zip', 'bin-win-avx2-x64.zip'), 'vulkan': ('bin-win-vulkan-x64.zip',)}
USER_AGENT = 'LocalAIAgent/5.0 (+https://github.com/Orsofey/Ai_Agent)'


class DownloadError(RuntimeError):
    pass


def _session(session=None):
    if session is not None:
        return session
    import requests
    session = requests.Session()
    session.headers['User-Agent'] = USER_AGENT
    return session


def http_download(url, destination, session=None, progress=None):
    """Скачать файл с докачкой (.part) и прогрессом. Возвращает путь к файлу."""
    session = _session(session)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + '.part')
    done = part.stat().st_size if part.exists() else 0
    headers = {'Range': f'bytes={done}-'} if done else {}
    with session.get(url, stream=True, timeout=(20, 120), headers=headers, allow_redirects=True) as response:
        if response.status_code == 416:  # файл уже докачан целиком
            os.replace(part, destination)
            return destination
        if response.status_code == 404:
            raise DownloadError('файл не найден на сервере: ' + url)
        response.raise_for_status()
        if response.status_code == 200:
            done = 0  # сервер не поддержал докачку — начинаем заново
        total = int(response.headers.get('Content-Length') or 0) + done
        last = 0.0
        with open(part, 'ab' if done else 'wb') as file:
            for block in response.iter_content(1 << 20):
                file.write(block)
                done += len(block)
                if progress and total and time.monotonic() - last > 0.5:
                    last = time.monotonic()
                    progress(done, total)
    if total and done < total:
        raise DownloadError('загрузка прервалась — нажмите «Скачать» ещё раз, она продолжится с того же места')
    os.replace(part, destination)
    return destination


def pick_asset(assets, flavor):
    """Выбрать архив llama.cpp для Windows из списка файлов релиза."""
    for suffix in RUNTIME_ASSETS[flavor]:
        for asset in assets:
            name = asset.get('name', '')
            if name.endswith(suffix) and name.startswith('llama-'):
                return asset
    return None


def llama_asset_url(session, flavor):
    """Адрес архива: через GitHub API, а при ограничении API — по странице последнего релиза."""
    try:
        response = session.get(GITHUB_RELEASE, timeout=20, headers={'Accept': 'application/vnd.github+json'})
        if response.ok:
            asset = pick_asset(response.json().get('assets', []), flavor)
            if asset:
                return asset['browser_download_url']
    except Exception as exc:
        log.info('GitHub API unavailable: %s', exc)
    response = session.get(GITHUB_LATEST_PAGE, timeout=20, allow_redirects=False)
    location = response.headers.get('Location', '') or getattr(response, 'url', '')
    match = re.search(r'/releases/tag/([\w.-]+)', location)
    if not match:
        raise DownloadError('не удалось узнать последнюю версию llama.cpp на GitHub')
    return GITHUB_DOWNLOAD.format(tag=match[1], flavor=flavor)


def download_llama_runtime(root, flavor='cpu', session=None, progress=None):
    """Скачать официальный llama-server (llama.cpp) с GitHub и распаковать."""
    import zipfile
    from .brain.local_llm import runtime_dir, BINARY
    target = runtime_dir(root, flavor == 'vulkan')
    if target.is_dir() and next(iter(target.rglob(BINARY)), None):
        return target
    if sys.platform != 'win32':
        raise DownloadError('автоматическая установка llama.cpp — только для Windows; '
                           'на других системах установите llama-server и добавьте его в PATH')
    session = _session(session)
    archive = http_download(llama_asset_url(session, flavor), target.with_name(target.name + '.zip'), session, progress)
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    except zipfile.BadZipFile:
        archive.unlink(missing_ok=True)
        raise DownloadError('архив llama.cpp повреждён — скачайте ещё раз')
    archive.unlink(missing_ok=True)
    if not next(iter(target.rglob(BINARY)), None):
        raise DownloadError('в архиве нет ' + BINARY + ' — возможно, файл удалил антивирус. '
                            'Добавьте папку ' + str(target) + ' в исключения и повторите')
    return target


def gguf_files(session, repo, pattern):
    response = session.get(HF_API.format(repo=repo), timeout=20)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    names = [s.get('rfilename', '') for s in response.json().get('siblings', [])]
    return [n for n in names if n.casefold().endswith(pattern.casefold()) and '/' not in n and '-of-' not in n]


def download_llm(root, key, session=None, progress=None):
    """Скачать GGUF-модель Qwen (Q4_K_M) с Hugging Face; при недоступности — из запасного репозитория."""
    from .brain.local_llm import LOCAL_MODELS, find_model, llm_dir
    info = LOCAL_MODELS[key]
    existing = find_model(root, key)
    if existing:
        return existing
    session = _session(session)
    errors = []
    for repo in info['repos']:
        try:
            files = gguf_files(session, repo, info['pattern'])
            if not files:
                errors.append(repo + ': нет файла ' + info['pattern'])
                continue
            return http_download(HF_FILE.format(repo=repo, file=files[0]), llm_dir(root) / key / files[0],
                                 session, progress)
        except DownloadError:
            raise
        except Exception as exc:
            errors.append(f'{repo}: {exc}'[:160])
    raise DownloadError('не удалось скачать модель. ' + '; '.join(errors))


def missing_items(root, settings):
    """Что нужно докачать, чтобы всё работало (для автоматической загрузки при первом запуске)."""
    from .brain.local_llm import find_binary, find_model as find_llm
    from .local_tts_service import voice_files
    items = []
    if not find_model(root, VAD_MODEL['folder'], 'silero_vad.onnx'):
        items.append('vad')
    stt = [k for k in ONNX_MODELS if find_model(root, ONNX_MODELS[k]['folder'])]
    if not stt:
        items.append('gigaam' if settings.get('voice_language') == 'ru' else 'parakeet')
    if not any(voice_files(name, root)[0] for name in PIPER_DEFAULT):
        items.append('piper')
    if settings.get('llm_provider', 'local') == 'local':
        gpu = bool(settings.get('llm_gpu'))
        if find_binary(root, gpu)[1] not in (('vulkan', 'system') if gpu else ('cpu', 'vulkan', 'system')):
            items.append('llama:' + ('vulkan' if gpu else 'cpu'))
        if not find_llm(root, settings.get('local_model', 'qwen3-4b')):
            items.append('llm:' + settings.get('local_model', 'qwen3-4b'))
    return items


def download(root, items, report=print):
    from .local_tts_service import ensure_piper_voice
    ok = True
    for item in items:
        started = time.monotonic()
        report(item, 'start')

        def progress(done, total, item=item):
            report(item, 'progress', dict(percent=round(done * 100 / total), done_mb=done >> 20, total_mb=total >> 20))
        try:
            if item == 'vad':
                download_vad(root)
            elif item in ONNX_MODELS:
                download_onnx(item, root)
            elif item == 'whisper':
                download_whisper(root)
            elif item.startswith('llama:'):
                download_llama_runtime(root, item.split(':', 1)[1], progress=progress)
            elif item.startswith('llm:'):
                download_llm(root, item.split(':', 1)[1], progress=progress)
            elif item == 'piper':
                for name in PIPER_DEFAULT:
                    if not ensure_piper_voice(name, root)[0]:
                        raise RuntimeError('голос ' + name + ' не скачан')
            else:
                raise ValueError('Неизвестная модель: ' + item)
            report(item, 'done', round(time.monotonic() - started, 1))
        except Exception as exc:
            ok = False
            log.exception('Download failed: %s', item)
            report(item, 'error', str(exc)[:300])
    return ok


def start_download(root, items, events, on_done=None):
    items = [str(i) for i in items if isinstance(i, str) and len(i) < 40]
    if not _running.acquire(blocking=False):
        return False

    def report(item, stage, detail=None):
        events.emit('download', item=item, stage=stage, detail=detail)

    def run():
        try:
            download(Path(root), items[:8], report)
            if on_done:
                on_done()
        finally:
            _running.release()
            events.emit('download', item='all', stage='finished')

    threading.Thread(target=run, daemon=True, name='model-download').start()
    return True
