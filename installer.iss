; Установщик «Андрея» (Inno Setup 6). Собирается из BUILD_WINDOWS.bat в двух вариантах:
;
;   ISCC installer.iss                 → installer\LocalAIAgent_Setup.exe — ОДИН ФАЙЛ, его и отправляйте людям.
;                                        Распознавание речи и голоса внутри; нейросеть (~2,5 ГБ) докачается сама
;                                        при первом запуске (src/model_downloader.py).
;   ISCC /DFull installer.iss          → installer\LocalAIAgent_Setup_Full.exe + LocalAIAgent_Setup_Full-1.bin, -2.bin…
;                                        Всё внутри, работает без интернета. Файлов несколько (у Inno Setup предел
;                                        ~2 ГБ на файл), поэтому BUILD_WINDOWS.bat упаковывает их в один
;                                        LocalAIAgent_Setup_Full.zip — отправлять только архив целиком.
;
; Версия берётся из app.py (BUILD_WINDOWS.bat передаёт /DAppVersion=…).
#define AppName "Local AI Agent"
#define AppExe "LocalAIAgent.exe"
#ifndef AppVersion
  #define AppVersion "7.2"
#endif
[Setup]
AppId={{8F2C1B7A-4D3E-4A91-9C7B-1E5A6D2F0C33}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=Orsofey
DefaultDirName={localappdata}\Programs\LocalAIAgent
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
SetupIconFile=static\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
CloseApplications=yes
#ifdef Update
; 7.2: обновление из самой программы — только файлы программы (модели у человека уже стоят; если их нет,
; Андрей докачает их сам при запуске). Публикуется на сервере аккаунтов (/admin → «Выпустить обновление»).
OutputBaseFilename=LocalAIAgent_Update
DiskSpanning=no
Compression=lzma2/fast
SolidCompression=no
#elif defined(Full)
OutputBaseFilename=LocalAIAgent_Setup_Full
; Все модели (~4 ГБ): файл установщика + части по ~1,9 ГБ (меньше предела Telegram в 2 ГБ).
DiskSpanning=yes
DiskSliceSize=1950000000
SlicesPerDisk=1
Compression=lzma2/fast
SolidCompression=no
#else
OutputBaseFilename=LocalAIAgent_Setup
; Один файл: без частей .bin. Нейросеть и запасные модели — не внутри, докачиваются при первом запуске.
DiskSpanning=no
Compression=lzma2/fast
SolidCompression=no
#endif
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Messages]
; Если всё-таки запустили полный установщик без частей .bin — объясняем по-человечески, что положить рядом.
russian.SelectDiskLabel2=Не найдена часть установщика № %1 (файл LocalAIAgent_Setup_Full-%1.bin).%n%nРаспакуйте архив LocalAIAgent_Setup_Full.zip целиком в одну папку и запустите установщик оттуда. Или положите файлы .bin рядом с установщиком и нажмите «OK».%n%nПроще всего — скачать лёгкий установщик LocalAIAgent_Setup.exe: это один файл.
english.SelectDiskLabel2=Setup part %1 (LocalAIAgent_Setup_Full-%1.bin) was not found.%n%nExtract LocalAIAgent_Setup_Full.zip completely into one folder and run setup from there, or put the .bin files next to setup and click OK.
[Files]
; Программа сжимается; модели уже сжаты — кладём как есть (сборка намного быстрее).
Source: "dist\LocalAIAgent\*"; DestDir: "{app}"; Excludes: "\models\*"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef Update
; модели не трогаем
#elif defined(Full)
Source: "dist\LocalAIAgent\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs nocompression skipifsourcedoesntexist
#else
; Лёгкий: VAD, Parakeet (русский + английский), голоса Piper и llama.cpp. Нейросеть (llm), GigaAM и Whisper —
; при первом запуске или в Настройки → «Распознавание» / «ИИ».
Source: "dist\LocalAIAgent\models\*"; DestDir: "{app}\models"; Excludes: "\llm\*,\whisper-large-v3-turbo\*,\small\*,\gigaam-v3-e2e-rnnt\*"; Flags: ignoreversion recursesubdirs createallsubdirs nocompression skipifsourcedoesntexist
#endif
[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
[Registry]
; Main.py enables startup on first launch. Delete the entry on uninstall only.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "LocalAIAgent"; Flags: uninsdeletevalue
[Run]
; Телефон в той же сети Wi-Fi: разрешить входящие подключения к ассистенту (Windows спросит подтверждение).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Andrey phone"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private,public,domain"; Verb: runas; Description: "Разрешить подключение с телефона (брандмауэр Windows)"; Flags: shellexec runhidden waituntilterminated postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Description: "Запустить Андрея"; Flags: nowait postinstall skipifsilent
; Обновление из программы идёт тихо (/SILENT) — после него Андрей запускается сам.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent
