"""Voice control of YouTube (and Rutube) in the same agent browser window.

«Запусти ютуб» → «Открой первое видео» → «Следующее видео» → «Перемотай на 30 секунд».
"""
import re

ORDINALS = {
    'перв': 1, 'втор': 2, 'трет': 3, 'четв': 4, 'пят': 5, 'шест': 6, 'седьм': 7, 'восьм': 8, 'девят': 9, 'десят': 10,
    'последн': -1,
}
_ORD = r'(?:\d+(?:-?(?:е|й|ое|ый|ую))?|перв\w*|втор\w*|трет\w*|четв\w*|пят\w*|шест\w*|седьм\w*|восьм\w*|девят\w*|десят\w*|последн\w*)'
_YT = r'(?:ютуб\w*|youtube|you tube|ю туб\w*)'


def ordinal(word):
    word = word.casefold()
    m = re.match(r'\d+', word)
    if m:
        return int(m[0])
    for stem, value in ORDINALS.items():
        if word.startswith(stem):
            return value
    return None


def youtube_command(text):
    """Вернуть кортеж аргументов для BrowserController._youtube или None."""
    value = re.sub(r'\s+', ' ', str(text)).strip().strip('.,!?…').casefold().replace('ё', 'е')
    m = re.match(r'^(?:открой|включи|запусти|покажи|поставь|выбери|воспроизведи)\s+(' + _ORD +
                 r')\s+(?:видео|ролик|результат|клип)(?:\s+на\s+' + _YT + r')?$', value) or \
        re.match(r'^(?:открой|включи|запусти|покажи|поставь)\s+(?:видео|ролик)\s+(?:номер\s+)?(' + _ORD + r')$', value) or \
        re.match(r'^(' + _ORD + r')\s+(?:видео|ролик)$', value)
    if m and ordinal(m[1]):
        return ('pick', ordinal(m[1]))
    m = re.match(r'^(?:найди|поищи|ищи|найти)\s+(?:на|в)\s+' + _YT + r'\s+(.+)$', value) or \
        re.match(r'^(?:найди|поищи|ищи)\s+(.+?)\s+(?:на|в)\s+' + _YT + r'$', value)
    if m:
        return ('search', m[1].strip())
    if value in ('следующее видео', 'следующий ролик', 'дальше видео', 'другое видео', 'следующий клип'):
        return ('next',)
    if value in ('предыдущее видео', 'прошлое видео', 'вернись к прошлому видео', 'назад к результатам'):
        return ('back',)
    if value in ('видео на весь экран', 'полноэкранный режим', 'выйди из полноэкранного режима', 'видео во весь экран'):
        return ('fullscreen',)
    m = re.match(r'^(?:перемотай|промотай|отмотай)\s*(вперед|назад)?\s+на\s+(\d+|одну|две|пять|десять)\s*(секунд\w*|сек|минут\w*|мин)?'
                 r'(?:\s+(вперед|назад))?$', value)
    if m:
        amount = {'одну': 1, 'две': 2, 'пять': 5, 'десять': 10}.get(m[2]) or int(m[2])
        if m[3] and m[3].startswith('мин'):
            amount *= 60
        backwards = 'назад' in (m[1] or '', m[4] or '') or value.startswith('отмотай')
        return ('seek', -amount if backwards else amount)
    return None
