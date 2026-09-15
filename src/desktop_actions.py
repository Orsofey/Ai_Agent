"""Optional desktop actions explicitly requested by the user."""
import re

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import pyperclip
except ImportError:
    pyperclip = None


def parse_and_run(command):
    text = command.strip()
    lowered = text.casefold()
    if not any(marker in lowered for marker in ("нажми", "нажать", "напечатай", "введи", "press", "type")):
        return None
    if pyautogui is None:
        return "Для действий клавиатуры установите дополнительный пакет: python -m pip install pyautogui"
    try:
        type_match = re.search(r"(?:напечатай|введи|type)\s+(.+)$", text, re.IGNORECASE)
        if type_match:
            value = type_match.group(1)
            if any(ord(char) > 127 for char in value):
                if pyperclip is None:
                    return "Для русской раскладки установите дополнительный пакет: python -m pip install pyperclip"
                pyperclip.copy(value)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.write(value, interval=0.01)
            return "Текст напечатан в активном окне."
        key_match = re.search(r"(?:нажми|нажать|press)\s+(.+)$", text, re.IGNORECASE)
        if key_match:
            raw = key_match.group(1).strip().lower().replace(" ", "")
            aliases = {"контрол":"ctrl", "ctrl":"ctrl", "альт":"alt", "alt":"alt", "шифт":"shift", "shift":"shift", "ввод":"enter", "enter":"enter", "эскейп":"esc", "escape":"esc", "таб":"tab", "tab":"tab", "win":"win"}
            keys = [aliases.get(part, part) for part in raw.split("+")]
            if len(keys) > 1:
                pyautogui.hotkey(*keys)
            else:
                pyautogui.press(keys[0])
            return "Комбинация клавиш выполнена в активном окне."
    except Exception as error:
        return f"Не удалось выполнить действие клавиатуры: {error}"
    return "Не понял действие. Примеры: «Нажми Ctrl+L», «Введи Интерстеллар», «Нажми Enter»."
