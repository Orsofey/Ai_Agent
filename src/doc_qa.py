"""Вопросы по документам: «Что в договоре сказано про сроки?», «сколько стоит аренда по договору аренды?»,
«о чём этот документ?», «кто подписал акт?».

Документ находится через индекс файлов (имя важнее, свежие выше) или берётся выделенный в Проводнике/последний
из чата. Текст режется на фрагменты, выбираются самые подходящие к вопросу, и локальная нейросеть отвечает
строго по ним — со ссылкой на файл. Без нейросети — показываются найденные фрагменты.
"""
import logging
import re
from pathlib import Path

from .file_index import stem, terms

log = logging.getLogger(__name__)

DOC_WORDS = (r'договор\w*|контракт\w*|документ\w*|файл\w*|отч[её]т\w*|сч[её]т\w*|акт\w*|презентаци\w*|таблиц\w*|'
             r'инструкци\w*|резюме|письм\w*|положени\w*|приказ\w*|устав\w*|смет\w*|коммерческ\w+ предложени\w*|'
             r'справк\w*|pdf|пдф|регламент\w*|политик\w*|оферт\w*|брошюр\w*')
QUESTION = re.compile(r'^(?:что|какие|какой|какая|какое|сколько|когда|где|кто|как|почему|зачем|есть ли|о\s+ч[её]м|'
                      r'расскажи|перескажи|объясни|кратко)\b', re.I)
DOC_REF = re.compile(r'(?:^|\s)(?:в|во|из|по|у|про|о)\s+(?P<this>эт\w+\s+|последн\w+\s+|выделенн\w+\s+)?'
                     r'(?P<noun>' + DOC_WORDS + r')(?P<name>(?:\s+(?!(?:сказано|написано|указано|говорится|про|о|об|насчет|'
                     r'насчёт|по|в|на|есть|за|до|и|или|что|какие|какой|сколько|когда|кто)\b)[«"]?[\w-]+[»"]?){0,3})', re.I)
MARKERS = re.compile(r'\b(?:сказано|написано|указано|говорится|пишут|значится|прописано|предусмотрено)\b', re.I)
CHUNK = 900
OVERLAP = 150
CONTEXT_LIMIT = 3800


def parse(text):
    """{'noun', 'name', 'this', 'question'} или None."""
    value = re.sub(r'\s+', ' ', str(text)).strip()
    if not QUESTION.match(value) and not MARKERS.search(value):
        return None
    match = DOC_REF.search(value)
    if not match:
        return None
    if not (QUESTION.match(value) or MARKERS.search(value)):
        return None
    noun = match['noun'].casefold()
    name = (match['name'] or '').strip(' «»"')
    this = bool(match['this']) or noun.startswith(('этот', 'этом'))
    return {'noun': noun, 'name': name, 'this': this, 'question': value}


def chunks(text, size=CHUNK, overlap=OVERLAP):
    text = re.sub(r'[ \t]+', ' ', text)
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        cut = text.rfind('\n', start + size // 2, end)
        if cut == -1 or end == len(text):
            cut = end
        parts.append(text[start:cut].strip())
        if cut >= len(text):
            break
        start = max(cut - overlap, start + 1)
    return [p for p in parts if p]


def best_chunks(text, question, limit=CONTEXT_LIMIT):
    """Фрагменты с наибольшим числом слов вопроса (по основам), в порядке следования в документе."""
    words = [w for w in terms(question) if len(w) >= 3]
    parts = chunks(text)
    if not parts:
        return []
    scored = []
    for n, part in enumerate(parts):
        low = part.casefold().replace('ё', 'е')
        score = sum(low.count(w) for w in words) + (0.5 if n == 0 else 0)  # начало документа — контекст
        scored.append((score, n, part))
    chosen, total = [], 0
    for score, n, part in sorted(scored, key=lambda x: (-x[0], x[1])):
        if total + len(part) > limit and chosen:
            break
        chosen.append((n, part))
        total += len(part)
    return [part for _, part in sorted(chosen)]


class DocumentQA:
    def __init__(self, index=None, brain=None, documents=None, reader=None):
        self.index = index
        self.brain = brain
        self.documents = documents
        self.reader = reader

    def find_document(self, request):
        if request['this'] and self.documents is not None:
            paths = self.documents.target('этот документ')
            if paths:
                return paths[0]
        if self.index is None:
            return None
        query = ' '.join([stem(request['noun'])] + ([request['name']] if request['name'] else []))
        found = self.index.search(query, limit=5, content=False) or self.index.search(query, limit=5)
        readable = [r for r in found if Path(r['path']).suffix.casefold() in
                    ('.pdf', '.docx', '.txt', '.md', '.rtf', '.odt', '.xlsx', '.csv', '.pptx')]
        return Path(readable[0]['path']) if readable else None

    def read(self, path):
        if self.reader is not None:
            return self.reader(path)
        from .files import kind_of, read_text
        return read_text(path, kind_of(path))

    def answer(self, request, settings=None):
        path = self.find_document(request)
        if path is None:
            return (f'Не нашёл документ «{request["noun"]}{" " + request["name"] if request["name"] else ""}». '
                    'Выделите его в Проводнике и спросите: «что в этом документе сказано про …».')
        try:
            text = self.read(path)
        except Exception as exc:
            return f'Не получилось прочитать {path.name}: {exc}'
        if not text or not text.strip():
            return f'В {path.name} нет текста, который я могу прочитать (возможно, это скан — нужен текстовый PDF).'
        parts = best_chunks(text, request['question'])
        context = '\n---\n'.join(parts)
        if self.brain is not None:
            try:
                reply = self.brain.complete(
                    'Ты отвечаешь на вопрос пользователя строго по тексту документа ниже. Если ответа в тексте нет — '
                    'так и скажи. Отвечай кратко, по-русски, без markdown; при возможности укажи пункт или раздел.',
                    f'Документ: {path.name}\n\nТекст (фрагменты):\n{context}\n\nВопрос: {request["question"]}',
                    dict(settings or {}, llm_web_search=False))
            except Exception as exc:
                log.info('Document QA LLM failed: %s', exc)
                reply = None
            if reply:
                return f'По «{path.name}»: {reply.strip()}'
        snippet = re.sub(r'\s+', ' ', parts[0])[:500] if parts else ''
        return f'Нейросеть выключена — вот подходящий фрагмент из «{path.name}»: …{snippet}…'

    def handle(self, text, settings=None):
        request = parse(text)
        if request is None:
            return None
        return self.answer(request, settings)
