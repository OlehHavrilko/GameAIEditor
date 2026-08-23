; Inno Setup script for Game AI Editor.
; Builds a per-user installer (no admin rights required) because the app
; reads/writes its input/work/output folders relative to its own install dir.
;
; Build with:
;   "D:\Tools\InnoSetup\ISCC.exe" packaging\installer.iss
;
; Prerequisite: run PyInstaller first so dist\game_ai_editor\ exists
; (see docs\PACKAGING.md).

#define MyAppName "Game AI Editor"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Game AI Editor"
#define MyAppExeName "game_ai_editor.exe"
#define MyAppSourceDir "..\dist\game_ai_editor"

[Setup]
AppId={{B4C2E6A0-6E6E-4B6B-9F0A-6C2C6B6E6A01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=GameAIEditor-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\input"
Name: "{app}\work"
Name: "{app}\output"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "desktop"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "desktop"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
function IsFfmpegAvailable(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C where ffmpeg >nul 2>nul', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function IsOllamaAvailable(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C where ollama >nul 2>nul', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Msg: String;
begin
  if CurPageID = wpReady then
  begin
    Msg := '';
    if not IsFfmpegAvailable() then
      Msg := Msg + '- FFmpeg/FFprobe not found on PATH. Required for video processing.' + #13#10
        + '  Download: https://www.gyan.dev/ffmpeg/builds/' + #13#10#13#10;
    if not IsOllamaAvailable() then
      Msg := Msg + '- Ollama not found on PATH. Optional, enables local AI Vision analysis.' + #13#10
        + '  Download: https://ollama.com/download' + #13#10#13#10;
    if Msg <> '' then
      WizardForm.ReadyMemo.Lines.Add(#13#10 + 'Warnings:' + #13#10 + Msg);
  end;
end;
