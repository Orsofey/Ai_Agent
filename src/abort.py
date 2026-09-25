"""Прерывание уже идущих действий: печать текста, макросы мессенджеров и Discord.

Каждая команда запоминает «поколение». «Стоп» и «останови все команды» увеличивают его,
и действия старого поколения останавливаются на ближайшей проверке check().
"""
import threading


class Aborted(Exception):
    pass


_state = {'generation': 0}
_local = threading.local()


def begin():
    """Вызывается в потоке команды перед выполнением."""
    _local.generation = _state['generation']


def abort_all():
    _state['generation'] += 1


def check():
    generation = getattr(_local, 'generation', None)
    if generation is not None and generation != _state['generation']:
        raise Aborted()
