"""Стили голоса поверх лицензированных голосов Piper: «Джарвис», «Пятница», «Диктор», «Робот», «Трейлер».

Это обработка звука (высота, «цифровой» оттенок, пространство), а не копия голоса реального
актёра: клонировать голоса знаменитостей без их согласия нельзя — это нарушает их права,
а в платном приложении — и закон.
"""
import numpy as np

PRESETS = {
    'classic': {'title': 'Обычный', 'voice': None, 'pitch': 1.0, 'fx': None,
                'note': 'Выбранный голос без обработки'},
    'jarvis': {'title': 'Джарвис', 'voice': 'denis', 'pitch': 0.93, 'fx': 'ai',
               'note': 'Мужской: спокойный, низкий, с цифровым оттенком ИИ-дворецкого'},
    'friday': {'title': 'Пятница', 'voice': 'irina', 'pitch': 1.02, 'fx': 'ai_light',
               'note': 'Женский: мягкий, с лёгкой цифровой окраской ИИ-ассистентки'},
    'narrator': {'title': 'Диктор', 'voice': 'denis', 'pitch': 0.88, 'fx': 'warm',
                 'note': 'Низкий бархатный голос, как у диктора документального кино'},
    'trailer': {'title': 'Трейлер', 'voice': 'denis', 'pitch': 0.82, 'fx': 'epic',
                'note': 'Эпичный голос из киноанонса с большим залом'},
    'robot': {'title': 'Робот', 'voice': 'denis', 'pitch': 0.95, 'fx': 'robot',
              'note': 'Металлический голос андроида'},
}


MAIN = ('jarvis', 'friday')  # два основных голоса в настройках; остальные — для совместимости


def preset(name):
    return PRESETS.get(name) or PRESETS['classic']


def _delay(x, samples):
    out = np.zeros_like(x)
    if 0 < samples < len(x):
        out[samples:] = x[:-samples]
    return out


def _reverb(x, rate, taps):
    y = x.copy()
    for ms, gain in taps:
        y += _delay(x, int(rate * ms / 1000)) * gain
    return y


def _smooth(x, width):
    if width <= 1:
        return x
    kernel = np.ones(width) / width
    return np.convolve(x, kernel, mode='same')


def pitch_shift(x, factor):
    """Растянуть сигнал в 1/factor раз: при той же частоте дискретизации тон ниже (factor < 1)."""
    if abs(factor - 1.0) < 1e-3:
        return x
    length = int(len(x) / factor)
    return np.interp(np.linspace(0, len(x) - 1, length), np.arange(len(x)), x)


def apply(audio, rate, name):
    """Обработать int16-звук Piper по стилю. Тон уже учтён скоростью синтеза (см. length_scale)."""
    info = preset(name)
    x = audio.astype(np.float32) / 32768.0
    x = pitch_shift(x, info['pitch'])
    t = np.arange(len(x)) / rate
    fx = info['fx']
    if fx in ('ai', 'ai_light'):
        depth = 0.10 if fx == 'ai' else 0.05
        x = x * (1 - depth + depth * np.sin(2 * np.pi * 55 * t))           # лёгкая «цифровая» модуляция
        x = x + 0.35 * _delay(x, int(rate * 0.006)) - 0.15 * _delay(x, int(rate * 0.012))  # металлический отзвук
        x = x - 0.5 * _smooth(x, 24)                                          # чуть «радийный» верх
        x = _reverb(x, rate, [(37, 0.18), (61, 0.12), (89, 0.08)])
    elif fx == 'warm':
        x = _smooth(x, 3)
        x = _reverb(x, rate, [(29, 0.12), (53, 0.08)])
    elif fx == 'epic':
        x = _smooth(x, 2)
        x = _reverb(x, rate, [(70, 0.35), (130, 0.28), (190, 0.2), (260, 0.14), (340, 0.09)])
    elif fx == 'robot':
        x = x * np.sin(2 * np.pi * 90 * t)
        x = x + 0.5 * _delay(x, int(rate * 0.004)) + 0.25 * _delay(x, int(rate * 0.008))
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0:
        x = x / peak * 0.9
    return (x * 32767).astype(np.int16)
