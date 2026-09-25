"""«Включи Imagine Dragons», «включи песню Believer на яндекс музыке», «Запусти плеер»."""
import re

SERVICES = {
    r'яндекс\s*музык\w*|yandex\s*music': 'music.yandex',
    r'ютуб\s*музык\w*|youtube\s*music|ютуб\s*мьюзик': 'music.youtube',
    r'спотиф\w*|spotify': 'open.spotify',
    r'вк\s*музык\w*|vk\s*музык\w*|вконтакте': 'vk.com',
    r'звук\w*|zvuk': 'zvuk.com',
    r'саундклауд\w*|soundcloud': 'soundcloud',
}
_SERVICE_RE = '|'.join(SERVICES)
_KIND = r'(?:песн[юи]|трек|музыку|альбом|группу|исполнителя|плейлист|композицию|мелодию|артиста)'
_PLAY = r'(?:включи|поставь|запусти|играй|сыграй|найди|врубай|вруби)'
_PATTERN = re.compile(r'^' + _PLAY + r'\s+(?:(?P<kind>' + _KIND + r')\s+)?(?P<q>.+?)(?:\s+(?:на|в|во)\s+(?P<svc>' + _SERVICE_RE + r'))?$', re.I)
PLAYER = {'запусти плеер', 'включи плеер', 'плеер', 'продолжи плеер', 'включи музыку', 'запусти музыку',
          'продолжи музыку', 'продолжи воспроизведение', 'воспроизведение', 'играй', 'включи воспроизведение'}


def service_key(text):
    for pattern, key in SERVICES.items():
        if re.fullmatch(pattern, text, re.I):
            return key
    return None


def parse(text, on_music_page=False):
    """('player',) | ('play', запрос, сервис|None) | None.

    Без слов «песню/трек…» и без названия сервиса фраза считается музыкой, только если открыт
    музыкальный сервис: иначе «Включи Telegram» остаётся запуском программы.
    """
    original = re.sub(r'\s+', ' ', str(text)).strip().strip('.!?')
    if original.casefold().replace('ё', 'е') in PLAYER:
        return ('player',)
    match = _PATTERN.match(original)
    if not match:
        return None
    query = match['q'].strip(' «»"')
    if match['kind'] and query.casefold() in ('', 'дальше'):
        return ('player',)
    explicit = bool(match['kind'] or match['svc'])
    if not explicit and not on_music_page:
        return None
    if re.match(r'^(?:видео|ролик|клип|фильм)\b', query, re.I) or not query:
        return None
    return ('play', query, service_key(match['svc']) if match['svc'] else None)
