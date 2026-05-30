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

function Install-BuildTools {
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath
    )
    $Packages = @("setuptools", "wheel")
    try {
        Invoke-Native -FilePath $PythonPath -Arguments (@("-m", "pip", "install", "-U") + $Packages)
        return
    } catch {
        Write-Warning "当前 pip 源安装 setuptools/wheel 失败，改用 PyPI 官方源重试。"
    }

    try {
        Invoke-Native -FilePath $PythonPath -Arguments (@("-m", "pip", "install", "-U", "--index-url", "https://pypi.org/simple") + $Packages)
        return
    } catch {
        Write-Host ""
        Write-Warning "安装构建工具失败。请检查代理或 pip 源，然后重试。"
        Write-Host "手动修复示例："
        Write-Host "  $PythonPath -m pip install -U --index-url https://pypi.org/simple setuptools wheel"
        Write-Host ""
        throw
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
    Invoke-Native -FilePath "git" -Arguments $Arguments
}

function Invoke-GitNetwork {
    param(
        [string[]]$Arguments = @()
    )
    try {
        Invoke-Native -FilePath "git" -Arguments $Arguments
    } catch {
        Write-Host ""
        Write-Warning "GitHub 连接失败。国内网络通常需要代理。"
        Write-Host "PowerShell 示例："
        Write-Host '  $env:XBOT_PROXY="http://127.0.0.1:7897"; iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/upgrade.ps1)'
        Write-Host ""
        throw
    }
}

function Update-InstallRepo {
    Write-Host "Upgrading xbot-next in $InstallDir"
    Write-Host "Protected user data: .env, data/, logs/, local database files, untracked uploads and generated skills."
    Invoke-GitNetwork -Arguments @("-C", $InstallDir, "fetch", "--depth", "1", "origin", $Branch)

    $RemoteRef = "origin/$Branch"
    $LocalHead = (& git -C $InstallDir rev-parse HEAD).Trim()
    $RemoteHead = (& git -C $InstallDir rev-parse $RemoteRef).Trim()
    $Status = (& git -C $InstallDir status --porcelain)

    if (($LocalHead -ne $RemoteHead) -or $Status) {
        $BackupBranch = "xbot-local-backup-$(Get-Date -Format 'yyyyMMddHHmmss')"
        Invoke-Git -Arguments @("-C", $InstallDir, "branch", $BackupBranch, "HEAD")
        Write-Warning "安装目录存在本地改动或分叉提交，已备份到分支 $BackupBranch，然后按远端 $RemoteRef 升级。"
        if ($Status) {
            Invoke-Git -Arguments @("-C", $InstallDir, "stash", "push", "-m", "xbot upgrade backup before reset")
        }
        Invoke-Git -Arguments @("-C", $InstallDir, "reset", "--hard")
    }

    Invoke-Git -Arguments @("-C", $InstallDir, "checkout", "-B", $Branch, $RemoteRef)
}

Require-Command git

if (-not (Test-Path (Join-Path $InstallDir ".git"))) {
    throw "xbot is not installed as a git checkout at $InstallDir. Run install.ps1 for first install; upgrade will not overwrite this directory."
}

$Python = Get-PythonCommand
$PythonExe = $Python[0]
$PythonBaseArgs = @($Python | Select-Object -Skip 1)
$VersionArgs = @($PythonBaseArgs) + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
Invoke-Native -FilePath $PythonExe -Arguments $VersionArgs

Update-InstallRepo
Set-Location $InstallDir

if (-not (Test-Path ".env")) {
    Write-Warning ".env not found. Upgrade will not create or overwrite user config; run xbot setup if you need to initialize config."
}

$VenvArgs = @($PythonBaseArgs) + @("-m", "venv", ".venv")
Invoke-Native -FilePath $PythonExe -Arguments $VenvArgs
$VenvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
Invoke-Native -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-U", "pip")
Install-BuildTools -PythonPath $VenvPython
Invoke-Native -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--no-build-isolation", "-e", ".")

try {
    Invoke-Native -FilePath $VenvPython -Arguments @("-m", "playwright", "install", "chromium")
} catch {
    Write-Warning "Playwright chromium install failed: $($_.Exception.Message)"
}

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$CmdPath = Join-Path $BinDir "xbot.cmd"
$CmdContent = @"
@echo off
cd /d "$InstallDir"
"$InstallDir\.venv\Scripts\xbot.exe" %*
"@
Set-Content -LiteralPath $CmdPath -Value $CmdContent -Encoding ASCII

$UpgradeCmdPath = Join-Path $BinDir "xbot-upgrade.cmd"
$UpgradeCmdContent = @"
@echo off
powershell -ExecutionPolicy Bypass -File "$InstallDir\scripts\upgrade.ps1" %*
"@
Set-Content -LiteralPath $UpgradeCmdPath -Value $UpgradeCmdContent -Encoding ASCII

Write-Host ""
Write-Host "xbot upgraded."
Write-Host "Install dir: $InstallDir"
Write-Host "Protected: .env and user data were not overwritten or deleted."
Write-Host "Command: $CmdPath"
Write-Host "Upgrade command: $UpgradeCmdPath"
