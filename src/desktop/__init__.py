"""Control of any Windows application: typing, hotkeys, windows, messengers."""
from .controller import DesktopController, WindowTracker
from .commands import DesktopCommands, parse
from .winapi import DesktopUnavailable

__all__ = ['DesktopController', 'WindowTracker', 'DesktopCommands', 'parse', 'DesktopUnavailable']
