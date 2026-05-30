$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:XBOT_REPO_URL) { $env:XBOT_REPO_URL } else { "https://github.com/NanSsye/xbot-next.git" }
$Branch = if ($env:XBOT_BRANCH) { $env:XBOT_BRANCH } else { "main" }
$InstallDir = if ($env:XBOT_INSTALL_DIR) { $env:XBOT_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".xbot\xbot-next" }
$BinDir = if ($env:XBOT_BIN_DIR) { $env:XBOT_BIN_DIR } else { Join-Path $env:USERPROFILE ".xbot\bin" }

if ($env:XBOT_PROXY) {
    $env:HTTP_PROXY = $env:XBOT_PROXY
    $env:HTTPS_PROXY = $env:XBOT_PROXY
    $env:ALL_PROXY = $env:XBOT_PROXY
    Write-Host "Using proxy from XBOT_PROXY: $env:XBOT_PROXY"
}

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

function Invoke-OptionalNative {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Optional command failed, continuing: $FilePath $($Arguments -join ' ')"
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

function Invoke-Git {
    param(
        [string[]]$Arguments = @()
    )
    Invoke-Native "git" $Arguments
}

function Invoke-GitNetwork {
    param(
        [string[]]$Arguments = @()
    )
    try {
        Invoke-Native "git" $Arguments
    } catch {
        Write-Host ""
        Write-Warning "GitHub 连接失败。国内网络通常需要代理。"
        Write-Host "PowerShell 示例："
        Write-Host '  $env:XBOT_PROXY="http://127.0.0.1:7897"; iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.ps1)'
        Write-Host ""
        throw
    }
}

function Update-InstallRepo {
    Write-Host "Updating xbot-next in $InstallDir"
    Invoke-GitNetwork @("-C", $InstallDir, "fetch", "--depth", "1", "origin", $Branch)

    $RemoteRef = "origin/$Branch"
    $LocalHead = (& git -C $InstallDir rev-parse HEAD).Trim()
    $RemoteHead = (& git -C $InstallDir rev-parse $RemoteRef).Trim()
    $Status = (& git -C $InstallDir status --porcelain)

    if (($LocalHead -ne $RemoteHead) -or $Status) {
        $BackupBranch = "xbot-local-backup-$(Get-Date -Format 'yyyyMMddHHmmss')"
        Invoke-Git @("-C", $InstallDir, "branch", $BackupBranch, "HEAD")
        Write-Warning "安装目录存在本地改动或分叉提交，已备份到分支 $BackupBranch，然后按远端 $RemoteRef 升级。"
        if ($Status) {
            Invoke-Git @("-C", $InstallDir, "stash", "push", "-m", "xbot install backup before upgrade")
        }
        Invoke-Git @("-C", $InstallDir, "reset", "--hard")
    }

    Invoke-Git @("-C", $InstallDir, "checkout", "-B", $Branch, $RemoteRef)
}

Require-Command git
$Python = Get-PythonCommand
$PythonExe = $Python[0]
$PythonBaseArgs = @($Python | Select-Object -Skip 1)

$VersionArgs = @($PythonBaseArgs) + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
Invoke-Native $PythonExe $VersionArgs

New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir -Parent), $BinDir | Out-Null

if (Test-Path (Join-Path $InstallDir ".git")) {
    Update-InstallRepo
} else {
    Write-Host "Installing xbot-next to $InstallDir"
    if (Test-Path $InstallDir) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    }
    Invoke-GitNetwork @("clone", "--depth", "1", "--branch", $Branch, $RepoUrl, $InstallDir)
}

Set-Location $InstallDir

$VenvArgs = @($PythonBaseArgs) + @("-m", "venv", ".venv")
Invoke-Native $PythonExe $VenvArgs
$VenvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
Invoke-Native $VenvPython @("-m", "pip", "install", "-U", "pip")
Invoke-OptionalNative $VenvPython @("-m", "pip", "install", "-U", "setuptools", "wheel")
Invoke-Native $VenvPython @("-m", "pip", "install", "--no-build-isolation", "-e", ".")

if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created $InstallDir\.env from .env.example"
}

try {
    Invoke-Native $VenvPython @("-m", "playwright", "install", "chromium")
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
    Invoke-Native (Join-Path $InstallDir ".venv\Scripts\xbot.exe") @("setup")
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
Write-Host 'Upgrade with proxy: $env:XBOT_PROXY="http://127.0.0.1:7897"; iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.ps1)'
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit $InstallDir\.env if needed"
Write-Host "  2. Open a new terminal if xbot is not on PATH yet"
Write-Host "  3. Run: xbot        # enter TUI"
Write-Host "  4. Run: xbot run    # start backend service"
