"""Поиск программ в меню «Пуск» по произнесённому имени: «Юнити» → Unity Hub, «обс» → OBS Studio.

Ярлыки меню «Пуск» — надёжный список установленных программ пользователя, поэтому команда
«Открой …» находит приложения, которых нет во встроенном словаре.
"""
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

_TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                     ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't',
                      'u', 'f', 'h', 'ts', 'ch', 'sh', 'sch', '', 'y', '', 'e', 'yu', 'ya']))
# Ярлыки, которые не нужно запускать по голосу.
SKIP = re.compile(r'uninstall|удал|readme|help|справк|documentation|license|лиценз|release notes|website', re.I)
_cache = {'time': 0.0, 'items': []}


def phonetic(text):
    """Грубое звучание латиницей: «Юнити хаб» и «Unity Hub» → «uniti hab» / «uniti hub»."""
    value = ''.join(_TRANSLIT.get(c, c) for c in str(text).casefold())
    value = re.sub(r'[^a-z0-9 ]+', ' ', value)
    for old, new in (('yu', 'u'), ('ya', 'a'), ('kh', 'h'), ('ck', 'k'), ('ph', 'f'), ('th', 't'), ('w', 'v'),
                     ('ea', 'i'), ('ee', 'i'), ('oo', 'u'), ('ey', 'e'), ('ei', 'e'), ('ai', 'e'), ('ay', 'e'),
                     ('y', 'i'), ('c', 'k'), ('q', 'k'), ('x', 'ks')):
        value = value.replace(old, new)
    value = re.sub(r'(.)\1+', r'\1', value)  # двойные буквы
    return ' '.join(value.split())


def folders():
    roots = [os.environ.get('APPDATA', ''), os.environ.get('PROGRAMDATA', '')]
    return [Path(r) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' for r in roots if r]


def shortcuts(roots=None, max_age=300):
    """Список (имя, путь) ярлыков .lnk/.url; кешируется на 5 минут."""
    if roots is None and time.monotonic() - _cache['time'] < max_age and _cache['items']:
        return _cache['items']
    items = []
    for root in roots or folders():
        if not Path(root).is_dir():
            continue
        for path in Path(root).rglob('*'):
            if path.suffix.casefold() in ('.lnk', '.url') and not SKIP.search(path.stem):
                items.append((path.stem, str(path)))
    if roots is None:
        _cache.update(time=time.monotonic(), items=items)
    return items


def score(spoken, name):
    a, b = phonetic(spoken), phonetic(name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    words, size = b.split(), len(a.split())
    best = SequenceMatcher(None, a, b).ratio()
    # Совпадение с частью названия: «фотошоп» ~ «Adobe Photoshop 2024», «юнити» ~ «Unity Hub».
    for start in range(len(words)):
        part = ' '.join(words[start:start + size])
        best = max(best, SequenceMatcher(None, a, part).ratio() * (0.97 if start == 0 else 0.93))
    if b.startswith(a + ' ') or (len(a) >= 3 and b.startswith(a)):
        best = max(best, 0.9)
    return best


def find(spoken, roots=None, threshold=0.78):
    """Лучший ярлык для произнесённого имени или None. При равенстве — более короткое имя (Unity Hub, а не Unity 2022.3)."""
    best, best_key = None, (0.0, 0)
    for name, path in shortcuts(roots):
        value = score(spoken, name)
        key = (round(value, 3), -len(name))
        if value >= threshold and key > best_key:
            best, best_key = path, key
    return best


def exact(spoken, roots=None):
    """Ярлык, название которого звучит в точности как сказанное («телеграм» = Telegram), или None."""
    key = phonetic(spoken)
    return next((path for name, path in shortcuts(roots) if key and phonetic(name) == key), None)
