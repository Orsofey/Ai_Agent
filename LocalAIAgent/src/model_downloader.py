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
    if not _running.acquire(blocking=False):
        return False

    def report(item, stage, detail=None):
        events.emit('download', item=item, stage=stage, detail=detail)

    def run():
        try:
            download(Path(root), [str(i) for i in items][:8], report)
            if on_done:
                on_done()
        finally:
            _running.release()
            events.emit('download', item='all', stage='finished')

    threading.Thread(target=run, daemon=True, name='model-download').start()
    return True
