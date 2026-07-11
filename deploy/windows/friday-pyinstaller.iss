; deploy/windows/friday-pyinstaller.iss - FRIDAY Windows installer (PyInstaller build)
;
; Packages a compiled PyInstaller one-dir build (dist\FRIDAY\) into a standard
; graphical Windows installation wizard: directory selection page, desktop
; shortcut task, Start Menu entries, clean uninstall, optional launch on finish.
;
; This is the FROZEN-APP path. The source-tree + bootstrap installer
; (deploy/windows/friday.iss) remains available; the two are alternatives.
;
; Build pipeline (from the repo root):
;
;   1. Freeze the app (one-dir mode; one-file is too slow to start for an app
;      of this size and breaks relative data paths):
;
;        pyinstaller friday_launch.py --name FRIDAY --onedir --noconfirm ^
;            --collect-all faster_whisper --collect-all sentence_transformers
;
;      (add `--icon deploy\windows\friday.ico` once an icon file exists)
;
;      Result: dist\FRIDAY\FRIDAY.exe plus its support tree.
;
;   2. Compile this script with Inno Setup 6+ (https://jrsoftware.org/isinfo.php):
;
;        iscc deploy\windows\friday-pyinstaller.iss
;
;      Result: dist\FRIDAY-Setup-<version>.exe - the wizard users run.

#define AppName        "FRIDAY"
#define AppVersion     "0.35.0"
#define AppPublisher   "Satvik"
#define AppURL         "https://github.com/satvik10293/friday"
#define AppExeName     "FRIDAY.exe"
#define SourceDist     "..\..\dist\FRIDAY"

[Setup]
; Unique application GUID - never change it between releases, or upgrades
; will install side-by-side instead of in place.
AppId={{B7E4D3A1-52C9-4F8E-9D06-8A1C33F4E7B2}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; {autopf}: Program Files when elevated, %LOCALAPPDATA%\Programs when not.
; lowest + override: installs per-user by default (the app writes runtime data
; under its own tree, which Program Files forbids without elevation), while
; still letting an administrator choose an all-users install from the wizard.
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

OutputDir=..\..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
LicenseFile=..\..\LICENSE
; Custom installer icon is optional: drop friday.ico beside this script to use
; it. Absent, Inno's default is used and the compile still succeeds.
#if FileExists("friday.ico")
SetupIconFile=friday.ico
#endif

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
  GroupDescription: "Additional icons:"
Name: "startupicon"; Description: "Start {#AppName} automatically when Windows starts"; \
  GroupDescription: "Startup:"; Flags: unchecked

[Files]
; The entire compiled PyInstaller output tree, verbatim.
Source: "{#SourceDist}\*"; DestDir: "{app}"; \
  Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{#AppName} Diagnostics"; Filename: "{app}\{#AppExeName}"; \
  Parameters: "--diagnostics"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
  WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
  WorkingDir: "{app}"; Tasks: startupicon

[Run]
; Optional clean post-install launch - unchecked-by-default is rude, so it is
; offered checked on the finish page and skipped entirely for silent installs.
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Remove runtime artifacts the app creates inside its own tree. User knowledge
; vaults (C:\VAULT\*) live outside {app} and are deliberately never touched.
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\logs"
