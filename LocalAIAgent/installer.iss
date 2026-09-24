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
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Files]
Source: "dist\LocalAIAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
[Registry]
; Main.py enables startup on first launch. Delete the entry on uninstall only.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "LocalAIAgent"; Flags: uninsdeletevalue
[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Local AI Agent"; Flags: nowait postinstall skipifsilent
