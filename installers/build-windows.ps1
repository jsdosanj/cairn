<#
.SYNOPSIS
    Build the Cairn Windows distributables.

.DESCRIPTION
    - Builds cairn.exe via PyInstaller + installers/cairn.spec
    - Stages a release folder (cairn.exe + config.example.yaml + README-INSTALL.txt)
    - Zips it to cairn-windows-x64.zip

    A maintainer with Inno Setup installed can additionally build a full
    installer .exe from installers/windows-setup.iss.

.PARAMETER Version
    Version string for the artifacts. Defaults to 1.0.0.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installers/build-windows.ps1 1.0.0
#>
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = 'Stop'

# Resolve repo root regardless of where the script is invoked from.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir   = Split-Path -Parent $ScriptDir

$Spec          = Join-Path $ScriptDir "cairn.spec"
$DistDir       = Join-Path $RootDir "dist"
$BuildDir      = Join-Path $RootDir "build"
$OutDir        = Join-Path $RootDir "installers\output"
$ConfigSample  = Join-Path $RootDir "config.example.yaml"

Write-Host "==> Building Cairn $Version for Windows"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "==> Running PyInstaller"
Push-Location $RootDir
try {
    pyinstaller --noconfirm --clean --distpath $DistDir --workpath $BuildDir $Spec
}
finally {
    Pop-Location
}

$Exe = Join-Path $DistDir "cairn.exe"
if (-not (Test-Path $Exe)) {
    Write-Error "Expected binary not found at $Exe"
}

# ---------------------------------------------------------------------------
# Stage release folder
# ---------------------------------------------------------------------------
Write-Host "==> Staging release folder"
$ReleaseDir = Join-Path $BuildDir "release-windows"
if (Test-Path $ReleaseDir) {
    Remove-Item -Recurse -Force $ReleaseDir
}
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Copy-Item $Exe -Destination (Join-Path $ReleaseDir "cairn.exe")
Copy-Item $ConfigSample -Destination (Join-Path $ReleaseDir "config.example.yaml")

$ReadmePath = Join-Path $ReleaseDir "README-INSTALL.txt"
@"
Cairn for Windows
=================

1. Copy cairn.exe to a directory on your PATH (or use the Inno Setup
   installer, which places it under Program Files and adds it to PATH).
2. Copy config.example.yaml to config.yaml and edit it with your
   MDM/EDR and Snipe-IT credentials.
3. Run:  cairn --config config.yaml

For automated builds and the Inno Setup installer, see installers/README.md.
"@ | Set-Content -Encoding UTF8 $ReadmePath

# ---------------------------------------------------------------------------
# Zip
# ---------------------------------------------------------------------------
Write-Host "==> Creating zip"
$Zip = Join-Path $OutDir "cairn-windows-x64.zip"
if (Test-Path $Zip) {
    Remove-Item -Force $Zip
}
Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $Zip
Write-Host "    wrote $Zip"

Write-Host "==> Windows build complete. Artifacts:"
Write-Host "    $Zip"
