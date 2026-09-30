"""Добавление новых голосов: каталог всех голосов Piper (десятки языков) и загрузка своих файлов.

Настройки → «Озвучка» → «Добавить голос»: выберите язык — появится список голосов с лицензией и качеством,
кнопка «Установить» скачает его в models/voices, и голос появится среди голосов ассистента. Свой голос (.onnx +
.onnx.json, обученный или купленный с правами) можно загрузить кнопкой «Загрузить файлы голоса».

Лицензии у голосов разные: у каждого показывается карточка модели — перед коммерческим использованием проверьте её.
"""
import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)

HF_BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/'
CATALOG_URL = HF_BASE + 'voices.json'
CACHE_DAYS = 7
NAME = re.compile(r'^[a-z]{2,3}_[A-Z]{2}-[\w]+-(?:x_low|low|medium|high)$')
QUALITY = {'x_low': 'очень простое', 'low': 'простое', 'medium': 'хорошее', 'high': 'высокое'}


def voices_dir(root):
    folder = Path(root) / 'models' / 'voices'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def load_catalog(root, session=None, refresh=False):
    """Каталог rhasspy/piper-voices (кешируется на неделю)."""
    cache = Path(root) / 'models' / 'piper_catalog.json'
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < CACHE_DAYS * 86400:
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except ValueError:
            pass
    import requests
    session = session or requests.Session()
    response = session.get(CATALOG_URL, timeout=30)
    response.raise_for_status()
    data = response.json()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data


def languages(catalog):
    found = {}
    for info in catalog.values():
        lang = info.get('language') or {}
        code = lang.get('family') or (lang.get('code') or '')[:2]
        if code:
            found[code] = lang.get('name_native') or lang.get('name_english') or code
    first = ('ru', 'en', 'uk', 'kk')
    return dict(sorted(found.items(), key=lambda x: (first.index(x[0]) if x[0] in first else 9, x[1])))


def list_voices(catalog, language='ru', root=None):
    installed = {p.stem for p in voices_dir(root).glob('*.onnx')} if root else set()
    result = []
    for key, info in catalog.items():
        lang = info.get('language') or {}
        if (lang.get('family') or (lang.get('code') or '')[:2]) != language:
            continue
        size = sum(f.get('size_bytes', 0) for name, f in (info.get('files') or {}).items() if name.endswith('.onnx'))
        result.append({'key': key, 'name': str(info.get('name', key)).replace('_', ' ').title(),
                       'quality': QUALITY.get(info.get('quality'), info.get('quality')),
                       'speakers': info.get('num_speakers', 1), 'size_mb': round(size / 2 ** 20),
                       'language': lang.get('name_native') or language, 'installed': key in installed})
    return sorted(result, key=lambda v: (v['installed'] is False, v['name']))


def install(root, key, catalog, session=None, progress=None):
    """Скачать голос в models/voices (onnx, json с понятным названием, карточка модели)."""
    if not NAME.match(key) or key not in catalog:
        raise ValueError('Неизвестный голос')
    from .model_downloader import http_download
    info = catalog[key]
    files = {Path(name).name: name for name in (info.get('files') or {})}
    onnx_path = next((p for n, p in files.items() if n.endswith('.onnx')), None)
    json_path = next((p for n, p in files.items() if n.endswith('.onnx.json')), None)
    if not onnx_path or not json_path:
        raise ValueError('В каталоге нет файлов этого голоса')
    folder = voices_dir(root)
    target = folder / f'{key}.onnx'
    config = folder / f'{key}.onnx.json'
    http_download(HF_BASE + json_path, config, session, None)
    http_download(HF_BASE + onnx_path, target, session, progress)
    card = next((p for n, p in files.items() if n.upper() == 'MODEL_CARD'), None)
    if card:
        try:
            http_download(HF_BASE + card, folder / f'{key}.MODEL_CARD.txt', session, None)
        except Exception as exc:
            log.info('Model card unavailable: %s', exc)
    lang = (info.get('language') or {}).get('name_native', '')
    data = json.loads(config.read_text(encoding='utf-8'))
    data['title'] = f"{str(info.get('name', key)).replace('_', ' ').title()} ({lang}, {QUALITY.get(info.get('quality'), '')})"
    config.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return {'id': 'custom:' + key, 'title': data['title']}


def import_files(root, files):
    """Свой голос: пара файлов <имя>.onnx и <имя>.onnx.json (из формы загрузки)."""
    onnx = next((f for f in files if f.filename.casefold().endswith('.onnx')), None)
    config = next((f for f in files if f.filename.casefold().endswith('.onnx.json')), None)
    if onnx is None or config is None:
        raise ValueError('Нужны два файла голоса Piper: «имя.onnx» и «имя.onnx.json».')
    stem = re.sub(r'[^\w.-]+', '_', Path(onnx.filename).stem)[:60] or 'voice'
    raw = config.read()
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ValueError('Файл .onnx.json повреждён.')
    if 'audio' not in data and 'phoneme_id_map' not in data:
        raise ValueError('Это не файл настроек голоса Piper.')
    folder = voices_dir(root)
    onnx.save(str(folder / f'{stem}.onnx'))
    data.setdefault('title', stem.replace('_', ' '))
    (folder / f'{stem}.onnx.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return {'id': 'custom:' + stem, 'title': data['title']}


def remove(root, voice_id):
    stem = str(voice_id).split(':', 1)[-1]
    if not re.fullmatch(r'[\w.-]{1,80}', stem):
        raise ValueError('Неизвестный голос')
    removed = False
    for suffix in ('.onnx', '.onnx.json', '.MODEL_CARD.txt'):
        path = voices_dir(root) / (stem + suffix)
        if path.exists():
            path.unlink()
            removed = True
    return removed
