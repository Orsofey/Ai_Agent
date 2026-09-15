; ============================================================
;  Local AI Agent — установщик Windows (Inno Setup 6)
; ============================================================
;  Собирается автоматически из build_windows.bat
;  Требует: dist\LocalAIAgent\LocalAIAgent.exe (результат PyInstaller)
; ============================================================

#define AppName "Local AI Agent"
#define AppVersion "3.0.0"
#define AppPublisher "Local AI Agent"
#define AppExeName "LocalAIAgent.exe"

[Setup]
AppId={{8F2C1B7A-4D3E-4A91-9C7B-1E5A6D2F0C33}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Local AI Agent
DefaultGroupName=Local AI Agent
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir=installer
OutputBaseFilename=LocalAIAgent_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AllowNoIcons=yes
SetupLogging=yes
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"; Flags: checkedonce
Name: "autostart"; Description: "Запускать при входе в Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Files]
Source: "dist\LocalAIAgent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[Registry]
; Автозапуск при входе (если выбрано)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LocalAIAgent"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  // На случай обновления поверх — закрываем работающее приложение
  if CurStep = ssInstall then
    Exec('taskkill.exe', '/IM {#AppExeName} /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
