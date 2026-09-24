"""One-time model downloads (Hugging Face). Runtime recognition never goes online."""
import logging
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
RUNTIME_ASSETS = {'cpu': ('bin-win-cpu-x64.zip', 'bin-win-avx2-x64.zip'), 'vulkan': ('bin-win-vulkan-x64.zip',)}


def pick_asset(assets, flavor):
    """Выбрать архив llama.cpp для Windows из списка файлов релиза."""
    for suffix in RUNTIME_ASSETS[flavor]:
        for asset in assets:
            name = asset.get('name', '')
            if name.endswith(suffix) and name.startswith('llama-'):
                return asset
    return None


def download_llama_runtime(root, flavor='cpu', session=None):
    """Скачать официальный llama-server (llama.cpp) с GitHub и распаковать."""
    import sys
    import zipfile
    from .brain.local_llm import runtime_dir, BINARY
    target = runtime_dir(root, flavor == 'vulkan')
    if next(iter(target.rglob(BINARY)), None) if target.is_dir() else None:
        return target
    if sys.platform != 'win32':
        raise RuntimeError('Автоматическая установка llama.cpp — только для Windows. '
                           'На других системах установите llama-server и добавьте его в PATH.')
    import requests
    session = session or requests.Session()
    release = session.get(GITHUB_RELEASE, timeout=20, headers={'Accept': 'application/vnd.github+json'}).json()
    asset = pick_asset(release.get('assets', []), flavor)
    if asset is None:
        raise RuntimeError('В последнем релизе llama.cpp не найден архив для Windows (' + flavor + ').')
    archive = target.with_name(target.name + '.zip')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with session.get(asset['browser_download_url'], stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(archive, 'wb') as file:
            for chunk in response.iter_content(1 << 20):
                file.write(chunk)
    tmp = _fresh_dir(target)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(tmp)
    archive.unlink()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)
    return target


def download_llm(root, key):
    """Скачать GGUF-модель Qwen (Q4_K_M) с Hugging Face."""
    from huggingface_hub import list_repo_files, hf_hub_download
    from .brain.local_llm import LOCAL_MODELS, find_model, llm_dir
    info = LOCAL_MODELS[key]
    if find_model(root, key):
        return find_model(root, key)
    files = [f for f in list_repo_files(info['repo']) if f.endswith(info['pattern']) and '/' not in f]
    if not files:
        raise RuntimeError('В репозитории модели не найден файл ' + info['pattern'])
    target = llm_dir(root) / key
    tmp = _fresh_dir(target)
    tmp.mkdir(parents=True, exist_ok=True)
    hf_hub_download(info['repo'], files[0], local_dir=str(tmp))
    shutil.rmtree(tmp / '.cache', ignore_errors=True)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)
    return target / files[0]


def download(root, items, report=print):
    from .local_tts_service import ensure_piper_voice
    ok = True
    for item in items:
        started = time.monotonic()
        report(item, 'start')
        try:
            if item == 'vad':
                download_vad(root)
            elif item in ONNX_MODELS:
                download_onnx(item, root)
            elif item == 'whisper':
                download_whisper(root)
            elif item.startswith('llama:'):
                download_llama_runtime(root, item.split(':', 1)[1])
            elif item.startswith('llm:'):
                download_llm(root, item.split(':', 1)[1])
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
