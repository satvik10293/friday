<#
    deploy/windows/uninstall.ps1 - FRIDAY V3 (RC1)

    Removes a FRIDAY installation: shortcuts, the per-user uninstall registry entry, and
    (optionally) the installation directory. By default it PRESERVES user data (data\,
    .env, friday_config.json) unless -Purge is given, so a reinstall keeps your history.

    Usage:  powershell -ExecutionPolicy Bypass -File uninstall.ps1 -InstallDir "<dir>" [-Purge]
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [switch]$Purge,
    [switch]$Silent
)

$ErrorActionPreference = "SilentlyContinue"
$AppName = "FRIDAY"

Write-Host ""
Write-Host "  Uninstalling FRIDAY from $InstallDir" -ForegroundColor Cyan

# shortcuts
foreach ($dir in @([Environment]::GetFolderPath("Desktop"),
                   (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = Join-Path $dir "$AppName.lnk"
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "  removed shortcut: $dir" }
}

# uninstall registry entry
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FRIDAY" -Recurse -Force
Write-Host "  removed uninstall entry"

# files
if (Test-Path $InstallDir) {
    if ($Purge) {
        if (-not $Silent) {
            $ok = Read-Host "  -Purge will DELETE all data (history, config, .env). Continue? [y/N]"
            if ($ok -notmatch '^[Yy]') { Write-Host "  cancelled."; exit 2 }
        }
        Remove-Item $InstallDir -Recurse -Force
        Write-Host "  removed installation directory (purged)"
    } else {
        # keep user data; remove code + venv only
        foreach ($item in @("core", "deploy", "docs", ".venv", "tests")) {
            Remove-Item (Join-Path $InstallDir $item) -Recurse -Force
        }
        Get-ChildItem $InstallDir -Filter *.py | Remove-Item -Force
        Write-Host "  removed program files (data\, .env, config preserved)"
    }
}

Write-Host "  FRIDAY uninstalled." -ForegroundColor Green
Write-Host ""
exit 0
