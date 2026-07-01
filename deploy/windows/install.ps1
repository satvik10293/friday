<#
    deploy/windows/install.ps1 — FRIDAY V3 (RC1) Windows installer

    A self-contained installer for FRIDAY that needs no external tooling (no Inno Setup /
    NSIS). Run it from the unzipped FRIDAY package. It:
        1. shows a welcome banner + license,
        2. asks for an installation directory,
        3. copies the runtime files (excluding vcs / venv / data / caches / secrets),
        4. creates the config folder + provisions an isolated .venv (dependencies),
        5. creates Desktop + Start-Menu shortcuts,
        6. registers an uninstall entry (Add/Remove Programs, per-user),
        7. verifies the installation, and
        8. optionally launches FRIDAY.

    Usage (interactive):   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
    Usage (silent):        ... -InstallDir "C:\Apps\FRIDAY" -Silent -NoLaunch
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "FRIDAY"),
    [switch]$Silent,
    [switch]$NoLaunch,
    [switch]$NoDeps
)

$ErrorActionPreference = "Stop"
$AppName = "FRIDAY"
$Source  = Split-Path (Split-Path $PSScriptRoot)   # package root = two levels up

function Write-Head($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }
function Write-Ok($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Warn2($t){ Write-Host "  [!] $t"  -ForegroundColor Yellow }

# ── 1. welcome + license ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  FRIDAY — Release Candidate installer" -ForegroundColor Cyan
Write-Host "  A local-first Cognitive Operating System." -ForegroundColor DarkCyan
Write-Host ""
$license = Join-Path $Source "LICENSE"
if (Test-Path $license) {
    Write-Head "License"
    Get-Content $license -TotalCount 8 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    if (-not $Silent) {
        $ok = Read-Host "  Accept the license and continue? [y/N]"
        if ($ok -notmatch '^[Yy]') { Write-Warn2 "Installation cancelled."; exit 2 }
    }
}

# ── 2. installation directory ────────────────────────────────────────────────────
Write-Head "Installation directory"
if (-not $Silent) {
    $entered = Read-Host "  Install location [$InstallDir]"
    if ($entered) { $InstallDir = $entered }
}
Write-Host "  Installing to: $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# ── 3. copy runtime files ────────────────────────────────────────────────────────
Write-Head "Copying files"
$exclude = @(".git", ".venv", "venv", "__pycache__", ".pytest_cache", "data", "dist",
             "build", ".idea", ".vscode")
$excludeFiles = @(".env", "friday_config.local.json")
robocopy $Source $InstallDir /E /NFL /NDL /NJH /NJS /NP `
    /XD ($exclude | ForEach-Object { Join-Path $Source $_ }) `
    /XF $excludeFiles | Out-Null
if ($LASTEXITCODE -ge 8) { throw "file copy failed (robocopy $LASTEXITCODE)" }
Write-Ok "runtime files copied"

# ── 4. config folder + venv provisioning ─────────────────────────────────────────
Write-Head "Configuration + environment"
$dataDir = Join-Path $InstallDir "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
if (-not (Test-Path (Join-Path $InstallDir "friday_config.json"))) {
    Copy-Item (Join-Path $Source "friday_config.json") (Join-Path $InstallDir "friday_config.json") -ErrorAction SilentlyContinue
}
Write-Ok "config folder ready"

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    Write-Warn2 "System Python not found on PATH. Install Python 3.10+ then re-run, or run deploy\bootstrap.py manually."
} elseif ($NoDeps) {
    Write-Warn2 "Skipping dependency provisioning (-NoDeps)."
} else {
    Write-Host "  Provisioning virtual environment (this can take several minutes)..."
    Push-Location $InstallDir
    try {
        & $python (Join-Path $InstallDir "deploy\bootstrap.py") --provision-only
        if ($LASTEXITCODE -eq 0) { Write-Ok "environment provisioned" }
        else { Write-Warn2 "provisioning reported issues; FRIDAY may run degraded" }
    } finally { Pop-Location }
}

# ── 5. shortcuts (Desktop + Start Menu) ──────────────────────────────────────────
Write-Head "Shortcuts"
$launcher = Join-Path $InstallDir "Launch-FRIDAY.bat"
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"),
                   (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    try {
        $lnk = $shell.CreateShortcut((Join-Path $dir "$AppName.lnk"))
        $lnk.TargetPath = $launcher
        $lnk.WorkingDirectory = $InstallDir
        $lnk.IconLocation = $launcher
        $lnk.Description = "Launch FRIDAY"
        $lnk.Save()
        Write-Ok "shortcut: $dir"
    } catch { Write-Warn2 "could not create shortcut in $dir" }
}

# ── 6. uninstall entry (per-user Add/Remove Programs) ────────────────────────────
Write-Head "Registering uninstall"
try {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FRIDAY"
    New-Item -Path $key -Force | Out-Null
    $uninst = "powershell -ExecutionPolicy Bypass -File `"$([IO.Path]::Combine($InstallDir,'deploy','windows','uninstall.ps1'))`" -InstallDir `"$InstallDir`""
    Set-ItemProperty $key DisplayName    "FRIDAY (Release Candidate)"
    Set-ItemProperty $key DisplayVersion "0.20.0-rc1"
    Set-ItemProperty $key Publisher      "Satvik"
    Set-ItemProperty $key InstallLocation $InstallDir
    Set-ItemProperty $key UninstallString $uninst
    Set-ItemProperty $key NoModify 1 -Type DWord
    Set-ItemProperty $key NoRepair 1 -Type DWord
    Write-Ok "uninstall entry registered"
} catch { Write-Warn2 "could not register uninstall entry" }

# ── 7. verify ────────────────────────────────────────────────────────────────────
Write-Head "Verifying"
$venvPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
$verified = (Test-Path (Join-Path $InstallDir "friday_launch.py")) -and (Test-Path $launcher)
if ($verified) { Write-Ok "installation verified" } else { Write-Warn2 "verification incomplete" }
if (Test-Path $venvPy) { Write-Ok ".venv interpreter present" }

# ── 8. launch ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  FRIDAY installed to $InstallDir" -ForegroundColor Green
if (-not $NoLaunch) {
    $go = if ($Silent) { "n" } else { Read-Host "  Launch FRIDAY now? [y/N]" }
    if ($go -match '^[Yy]') { Start-Process -FilePath $launcher -WorkingDirectory $InstallDir }
}
Write-Host ""
exit 0
