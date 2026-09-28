#define AppName "Local AI Agent"
#define AppExe "LocalAIAgent.exe"
[Setup]
AppId={{8F2C1B7A-4D3E-4A91-9C7B-1E5A6D2F0C33}
AppName={#AppName}
AppVersion=5.0.0
DefaultDirName={localappdata}\Programs\LocalAIAgent
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=LocalAIAgent_Setup
SetupIconFile=static\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
; Bundled AI models take ~4 GB, so the installer is split into ~2 GB parts:
; LocalAIAgent_Setup.exe + LocalAIAgent_Setup-1.bin, -2.bin... Distribute them together (one folder or archive).
DiskSpanning=yes
DiskSliceSize=2000000000
SlicesPerDisk=1
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
CloseApplications=yes
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Files]
; Program files are compressed; models are already compressed, so they are stored as is (much faster build).
Source: "dist\LocalAIAgent\*"; DestDir: "{app}"; Excludes: "\models\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\LocalAIAgent\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs nocompression skipifsourcedoesntexist
[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
[Registry]
; Main.py enables startup on first launch. Delete the entry on uninstall only.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "LocalAIAgent"; Flags: uninsdeletevalue
[Run]
; Телефон в той же сети Wi-Fi: разрешить входящие подключения к ассистенту (Windows спросит подтверждение).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Andrey phone"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private,public,domain"; Verb: runas; Description: "Разрешить подключение с телефона (брандмауэр Windows)"; Flags: shellexec runhidden waituntilterminated postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Description: "Launch Local AI Agent"; Flags: nowait postinstall skipifsilent
