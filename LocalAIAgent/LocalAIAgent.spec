# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas = [(str(root / 'static'), 'static'), (str(root / 'templates'), 'templates')]
binaries = []
hiddenimports = ['webview.platforms.edgechromium', 'waitress', 'sqlite3', 'clr', 'winreg',
                 'pystray._win32', 'PIL.Image', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5']
packages = ('onnx_asr', 'onnxruntime', 'faster_whisper', 'ctranslate2', 'av', 'tokenizers', 'playwright',
            'webview', 'pythonnet', 'clr_loader', 'piper', 'sounddevice', '_sounddevice_data', 'anthropic',
            'ddgs', 'primp', 'pystray', 'pyperclip', 'huggingface_hub', 'yt_dlp')
for package in packages:
    try:
        data, binary, hidden = collect_all(package)
    except Exception:
        continue
    datas += data
    binaries += binary
    hiddenimports += hidden

a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=['pytest', 'torch', 'torchaudio', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LocalAIAgent',
          debug=False, strip=False, upx=False, console=False,
          icon=str(root / 'static/icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LocalAIAgent')
