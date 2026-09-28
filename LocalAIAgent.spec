# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas = [(str(root / 'static'), 'static'), (str(root / 'templates'), 'templates'),
         (str(root / 'browser_extension'), 'browser_extension')]
binaries = []
MAC = sys.platform == 'darwin'
if MAC:
    hiddenimports = ['webview.platforms.cocoa', 'waitress', 'sqlite3', 'PIL.Image', 'Quartz', 'AppKit',
                     'ApplicationServices', 'segno']
else:
    hiddenimports = ['webview.platforms.edgechromium', 'waitress', 'sqlite3', 'clr', 'winreg', 'segno',
                     'pystray._win32', 'PIL.Image', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5']
packages = ('onnx_asr', 'onnxruntime', 'faster_whisper', 'ctranslate2', 'av', 'tokenizers', 'playwright',
            'webview', 'piper', 'sounddevice', '_sounddevice_data', 'ddgs', 'primp', 'pyperclip',
            'huggingface_hub', 'yt_dlp', 'segno', 'cryptography', 'pypdf')
packages += ('Quartz', 'AppKit', 'ApplicationServices') if MAC else ('pythonnet', 'clr_loader', 'pystray')
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
icns = root / 'build' / 'icon.icns'  # BUILD_MAC.sh делает его из static/icon-512.png
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LocalAIAgent',
          debug=False, strip=False, upx=False, console=False,
          icon=(str(icns) if icns.exists() else None) if MAC else str(root / 'static/icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LocalAIAgent')
if MAC:
    app = BUNDLE(coll, name='Андрей.app', icon=str(icns) if icns.exists() else None,
                 bundle_identifier='ru.andrey.assistant',
                 info_plist={
                     'CFBundleName': 'Андрей', 'CFBundleDisplayName': 'Андрей',
                     'CFBundleShortVersionString': '5.0', 'LSMinimumSystemVersion': '12.0',
                     'NSHighResolutionCapable': True,
                     'NSMicrophoneUsageDescription': 'Андрей слушает голосовые команды. Речь распознаётся на этом Mac и никуда не отправляется.',
                     'NSAppleEventsUsageDescription': 'Андрей открывает, переключает и закрывает приложения по вашей команде.',
                 })
