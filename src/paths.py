"""Где лежат встроенные модели: рядом с EXE (Windows), в Contents/Resources (macOS .app) или в папке проекта."""
import sys
from pathlib import Path


def app_base():
    if getattr(sys, 'frozen', False):
        executable = Path(sys.executable).resolve()
        if sys.platform == 'darwin' and executable.parent.name == 'MacOS':
            return executable.parents[1] / 'Resources'
        return executable.parent
    return Path(__file__).resolve().parents[1]
