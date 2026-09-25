"""Wake-word matching on recognized text, tolerant to recognition errors.

«Андрей, напиши…», «Эй, Андрей…», «Андрэй», «Andrey» — всё считается обращением.
"""
import re
from difflib import SequenceMatcher

FILLERS = {'эй', 'ну', 'слушай', 'окей', 'ок', 'ok', 'hey', 'хей', 'привет', 'а', 'алло', 'так'}

_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z',
    'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def normalize(word):
    return word.casefold().replace('ё', 'е').strip("-'")


def translit(word):
    return ''.join(_TRANSLIT.get(ch, ch) for ch in normalize(word))


def variants(wake_word, aliases=''):
    names = [wake_word] + [a for a in re.split(r'[,;]', aliases or '') if a.strip()]
    result = set()
    for name in names:
        base = normalize(' '.join(name.split()))
        if not base:
            continue
        result.add(base)
        result.add(translit(base))
        if re.search(r'[а-я]', base):
            result.add(base.replace('ей', 'эй'))
            if base.endswith('й'):
                result.add(base[:-1])
            if translit(base).endswith('y'):
                result.add(translit(base)[:-1] + 'i')
    return sorted(result, key=len, reverse=True)


def _similar(word, variant):
    if word == variant:
        return True
    if len(variant) >= 4 and word.startswith(variant) and len(word) - len(variant) <= 2:
        return True  # «Андрея», «Андрею»
    threshold = 0.8 if len(variant) >= 5 else 0.86
    return len(word) >= 3 and SequenceMatcher(None, word, variant).ratio() >= threshold


def match(text, wake_word, aliases=''):
    """Вернуть (найдено, команда_без_имени)."""
    value = str(text or '').strip()
    tokens = list(re.finditer(r"[\w'-]+", value))
    if not tokens:
        return False, ''
    names = variants(wake_word, aliases)
    words = [normalize(t[0]) for t in tokens]

    def check(i):
        for variant in names:
            size = len(variant.split())
            candidate = ' '.join(words[i:i + size])
            if size == 1 and _similar(candidate, variant) or size > 1 and candidate == variant:
                return size
        return 0

    # Имя в начале (после слов-паразитов): «Эй, Андрей, открой…»
    for i in range(min(len(words), 4)):
        size = check(i)
        if size:
            rest = value[tokens[i + size - 1].end():] if i + size <= len(tokens) else ''
            return True, rest.strip(' ,.:;!?—-')
        if words[i] not in FILLERS:
            break
    # Имя в конце: «Открой калькулятор, Андрей»
    for size_back in (1, 2):
        i = len(words) - size_back
        if i > 0 and check(i) == size_back:
            return True, value[:tokens[i].start()].strip(' ,.:;!?—-')
    return False, ''
