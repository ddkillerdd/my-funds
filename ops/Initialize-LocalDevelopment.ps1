[CmdletBinding()]
param(
    [switch]$SkipFrontendInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$advisorRoot = Join-Path $repoRoot 'fund-advisor'
$frontendRoot = Join-Path $advisorRoot 'frontend'
$toolRoot = Join-Path $repoRoot '.tools\uv-venv'
$uvPath = Join-Path $toolRoot 'Scripts\uv.exe'
$runtimeRoot = Join-Path $repoRoot '.runtime'
$pythonInstallRoot = Join-Path $runtimeRoot 'python'
$uvCacheRoot = Join-Path $runtimeRoot 'uv-cache'
$advisorPythonPath = Join-Path $advisorRoot '.venv\Scripts\python.exe'
$lockFile = Join-Path $advisorRoot 'requirements-lock-py312-windows.txt'
$pythonVersion = '3.12.13'
$uvVersion = '0.12.7'

# 执行外部命令，并在失败时立即给出中文错误。
function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$FailureMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

# 在项目隔离目录中安装 uv，不修改系统级 Python 配置。
function Install-LocalUv {
    if (Test-Path -LiteralPath $uvPath) {
        return
    }

    $bootstrapPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $bootstrapPython) {
        throw '未找到用于引导 uv 的 python.exe。请先安装任意受支持的本机 Python。'
    }

    Write-Host "正在创建 uv 工具环境：$toolRoot" -ForegroundColor Cyan
    Invoke-CheckedCommand -FilePath $bootstrapPython.Source `
        -Arguments @('-m', 'venv', $toolRoot) `
        -FailureMessage '创建 uv 工具环境失败。'

    $toolPython = Join-Path $toolRoot 'Scripts\python.exe'
    Invoke-CheckedCommand -FilePath $toolPython `
        -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', "uv==$uvVersion") `
        -FailureMessage '安装固定版本 uv 失败。'
}

# 创建与生产服务一致的 Python 3.12.13 虚拟环境。
function Initialize-BackendEnvironment {
    $env:UV_PYTHON_INSTALL_DIR = $pythonInstallRoot
    $env:UV_CACHE_DIR = $uvCacheRoot

    Invoke-CheckedCommand -FilePath $uvPath `
        -Arguments @('python', 'install', $pythonVersion) `
        -FailureMessage "下载 Python $pythonVersion 失败。"

    $currentVersion = $null
    if (Test-Path -LiteralPath $advisorPythonPath) {
        $currentVersion = (& $advisorPythonPath -c 'import platform; print(platform.python_version())' 2>$null)
    }

    if ($currentVersion -ne $pythonVersion) {
        Write-Host "正在重建后端虚拟环境：$advisorRoot\.venv" -ForegroundColor Cyan
        Invoke-CheckedCommand -FilePath $uvPath `
            -Arguments @('venv', '--clear', '--python', $pythonVersion, (Join-Path $advisorRoot '.venv')) `
            -FailureMessage '创建后端虚拟环境失败。'
    }

    Invoke-CheckedCommand -FilePath $uvPath `
        -Arguments @('pip', 'sync', '--python', $advisorPythonPath, $lockFile) `
        -FailureMessage '同步后端锁定依赖失败。'
}

# 仅在文件不存在时创建本地配置，避免覆盖用户已有配置。
function Initialize-LocalConfig {
    $envPath = Join-Path $advisorRoot '.env'
    $alembicPath = Join-Path $advisorRoot 'alembic.ini'

    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $advisorRoot 'local.env.example') -Destination $envPath
        Write-Host "已创建本地合成环境配置：$envPath" -ForegroundColor Green
    } else {
        Write-Host "保留已有配置，不覆盖：$envPath" -ForegroundColor Yellow
    }

    if (-not (Test-Path -LiteralPath $alembicPath)) {
        Copy-Item -LiteralPath (Join-Path $advisorRoot 'alembic.ini.example') -Destination $alembicPath
        Write-Host "已创建本地 Alembic 配置：$alembicPath" -ForegroundColor Green
    } else {
        Write-Host "保留已有配置，不覆盖：$alembicPath" -ForegroundColor Yellow
    }
}

# 按 package-lock.json 安装前端依赖，不自动执行高风险强制升级。
function Initialize-FrontendEnvironment {
    if ($SkipFrontendInstall) {
        Write-Host '已按参数跳过前端依赖安装。' -ForegroundColor Yellow
        return
    }

    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw '未找到 npm.cmd，请先安装 Node.js 24。'
    }

    Push-Location $frontendRoot
    try {
        Invoke-CheckedCommand -FilePath 'npm.cmd' `
            -Arguments @('ci') `
            -FailureMessage '按锁文件安装前端依赖失败。'
    } finally {
        Pop-Location
    }
}

Install-LocalUv
Initialize-BackendEnvironment
Initialize-LocalConfig
Initialize-FrontendEnvironment

Write-Host '本地开发依赖初始化完成。' -ForegroundColor Green
Write-Host "后端 Python：$advisorPythonPath" -ForegroundColor Green
Write-Host "下一步检查：& '$repoRoot\ops\Invoke-LocalChecks.ps1' -RunPythonTests -BuildFrontend" -ForegroundColor Cyan
