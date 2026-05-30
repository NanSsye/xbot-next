$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:XBOT_REPO_URL) { $env:XBOT_REPO_URL } else { "https://github.com/NanSsye/xbot-next.git" }
$Branch = if ($env:XBOT_BRANCH) { $env:XBOT_BRANCH } else { "main" }
$InstallDir = if ($env:XBOT_INSTALL_DIR) { $env:XBOT_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".xbot\xbot-next" }
$BinDir = if ($env:XBOT_BIN_DIR) { $env:XBOT_BIN_DIR } else { Join-Path $env:USERPROFILE ".xbot\bin" }

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3.11")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Missing Python 3.11+. Please install Python 3.11 or newer."
}

Require-Command git
$Python = Get-PythonCommand
$PythonExe = $Python[0]
$PythonBaseArgs = @($Python | Select-Object -Skip 1)

& $PythonExe @PythonBaseArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11+ is required."
}

New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir -Parent), $BinDir | Out-Null

if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Host "Updating xbot-next in $InstallDir"
    git -C $InstallDir fetch --depth 1 origin $Branch
    git -C $InstallDir checkout $Branch
    git -C $InstallDir pull --ff-only origin $Branch
} else {
    Write-Host "Installing xbot-next to $InstallDir"
    if (Test-Path $InstallDir) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    }
    git clone --depth 1 --branch $Branch $RepoUrl $InstallDir
}

Set-Location $InstallDir

& $PythonExe @PythonBaseArgs -m venv .venv
$VenvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
& $VenvPython -m pip install -U pip
& $VenvPython -m pip install -e .

if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created $InstallDir\.env from .env.example"
}

try {
    & $VenvPython -m playwright install chromium
} catch {
    Write-Warning "Playwright chromium install failed: $($_.Exception.Message)"
}

$CmdPath = Join-Path $BinDir "xbot.cmd"
$CmdContent = @"
@echo off
cd /d "$InstallDir"
"$InstallDir\.venv\Scripts\xbot.exe" %*
"@
Set-Content -LiteralPath $CmdPath -Value $CmdContent -Encoding ASCII

if ($env:XBOT_SKIP_SETUP -ne "1") {
    Write-Host ""
    Write-Host "Starting xbot setup..."
    & (Join-Path $InstallDir ".venv\Scripts\xbot.exe") setup
}

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathParts = @()
if ($UserPath) {
    $PathParts = $UserPath -split ";"
}
if ($PathParts -notcontains $BinDir) {
    $NextPath = if ($UserPath) { "$UserPath;$BinDir" } else { $BinDir }
    [Environment]::SetEnvironmentVariable("Path", $NextPath, "User")
    $env:Path = "$env:Path;$BinDir"
    Write-Host "Added $BinDir to user PATH"
}

Write-Host ""
Write-Host "xbot installed."
Write-Host "Install dir: $InstallDir"
Write-Host "Command: $CmdPath"
Write-Host "Upgrade: iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.ps1)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit $InstallDir\.env if needed"
Write-Host "  2. Open a new terminal if xbot is not on PATH yet"
Write-Host "  3. Run: xbot        # enter TUI"
Write-Host "  4. Run: xbot run    # start backend service"
