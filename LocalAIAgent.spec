# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
import runpy
source_check = runpy.run_path(str(root / 'scripts' / 'check_source.py'))['check'](root)
if source_check:
    missing = '\n'.join(f"{item['file']}:{item['line']}: {item['missing']}" for item in source_check)
    raise RuntimeError('Incomplete application source; restore these files before packaging:\n' + missing)
import re
VERSION = re.search(r"^VERSION = '([\d.]+)'", (root / 'app.py').read_text(encoding='utf-8'), re.M).group(1)
datas = [(str(root / 'static'), 'static'), (str(root / 'templates'), 'templates'),
         (str(root / 'browser_extension'), 'browser_extension')]
binaries = []
for folder in ('voice_packs', 'voices'):
    voices = root / 'models' / folder
    if voices.is_dir():
        datas.append((str(voices), 'models/' + folder))
MAC = sys.platform == 'darwin'
if MAC:
    hiddenimports = ['webview.platforms.cocoa', 'waitress', 'sqlite3', 'PIL.Image', 'Quartz', 'AppKit',
                     'ApplicationServices', 'segno', 'src.connectors_apps', 'imaplib', 'zoneinfo']
else:
    hiddenimports = ['webview.platforms.edgechromium', 'waitress', 'sqlite3', 'clr', 'winreg', 'segno',
                     'pystray._win32', 'PIL.Image', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5',
                     'src.connectors_apps', 'imaplib', 'zoneinfo', 'tzdata',
                     # 6.6: диктовка по клавише — модули грузятся по ходу работы
                     'src.dictation', 'src.dictation.insert', 'src.dictation.popup', 'src.dictation.keys',
                     'src.dictation.recorder', 'src.dictation.text',
                     # 7.0: окошко наставника поверх всех окон
                     'src.coach', 'src.coach_popup', 'src.updates']
packages = ('onnx_asr', 'onnxruntime', 'av', 'tokenizers', 'playwright',
            'webview', 'piper', 'sounddevice', '_sounddevice_data', 'ddgs', 'primp', 'pyperclip',
            'huggingface_hub', 'yt_dlp', 'segno', 'cryptography', 'pypdf', 'websocket',
            # 6.9: звонки — только если поставлены SETUP_CALLS.bat (иначе пропускаются)
            'discord', 'nacl', 'davey', 'telethon', 'pytgcalls', 'ntgcalls')
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
             # 6.4: резервный Whisper не входит в установщик (облегчение); если он стоит в среде сборки — не тянем.
             excludes=['pytest', 'torch', 'torchaudio', 'tkinter', 'faster_whisper', 'ctranslate2'])
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
                     'CFBundleShortVersionString': VERSION, 'CFBundleVersion': VERSION, 'LSMinimumSystemVersion': '12.0',
                     'NSHighResolutionCapable': True,
                     'NSMicrophoneUsageDescription': 'Андрей слушает голосовые команды. Речь распознаётся на этом Mac и никуда не отправляется.',
                     'NSAppleEventsUsageDescription': 'Андрей открывает, переключает и закрывает приложения по вашей команде.',
                 })

