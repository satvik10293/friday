; deploy/windows/friday.iss — FRIDAY V3 (RC1) Inno Setup script
;
; Produces a native Windows installer (Setup .exe) from the FRIDAY source tree. Requires
; Inno Setup 6+ (https://jrsoftware.org/isinfo.php). This is the OPTIONAL "compiled
; installer" path — the PowerShell installer (install.ps1) needs no external tooling and
; is the default for RC1. Compile from the repo root:
;
;     iscc deploy\windows\friday.iss
;
; The resulting Setup.exe copies FRIDAY, then provisions an isolated .venv on first run via
; the bootstrap (heavy ML deps are installed into the venv, never frozen into the binary).

#define AppName "FRIDAY"
#define AppVersion "0.20.0-rc1"
#define AppPublisher "Satvik"
#define SourceRoot ".."

[Setup]
AppId={{7F3A9C2E-FRID-AY00-RC01-000000000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=FRIDAY-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; ship the whole source tree except vcs, venv, runtime data, caches, secrets, weights
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs; \
  Excludes: "\.git\*,\.venv\*,venv\*,__pycache__\*,\.pytest_cache\*,data\*,dist\*,build\*,\.idea\*,\.vscode\*,*.env,*.db,*.log,*.gguf,*.safetensors,*.pt,*.pth,*.onnx,*.bin"

[Icons]
Name: "{group}\{#AppName}";        Filename: "{app}\Launch-FRIDAY.bat"; WorkingDir: "{app}"
Name: "{group}\{#AppName} Diagnostics"; Filename: "{app}\Launch-FRIDAY.bat"; Parameters: "--diagnostics"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Launch-FRIDAY.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; provision the venv + dependencies at the end of install (best-effort; user sees progress)
Filename: "{cmd}"; Parameters: "/c python ""{app}\deploy\bootstrap.py"" --provision-only"; \
  WorkingDir: "{app}"; StatusMsg: "Provisioning FRIDAY environment (may take several minutes)..."; \
  Flags: runhidden waituntilterminated
Filename: "{app}\Launch-FRIDAY.bat"; Description: "Launch FRIDAY now"; \
  Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
