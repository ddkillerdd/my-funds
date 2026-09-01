[CmdletBinding()]
param(
    [switch]$RunPythonTests,
    [switch]$BuildFrontend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$failures = [System.Collections.Generic.List[string]]::new()

# 记录一条检查失败信息，统一在脚本末尾汇总。
function Add-CheckFailure {
    param([Parameter(Mandatory)][string]$Message)

    $failures.Add($Message)
    Write-Host "[失败] $Message" -ForegroundColor Red
}

# 执行 Python AST 解析，检查语法但不生成 pyc 文件。
function Test-PythonSyntax {
    param([Parameter(Mandatory)][string]$PythonPath)

    $pythonFiles = Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Filter '*.py' |
        Where-Object {
            $_.FullName -notmatch '\\(?:\.git|\.venv|venv|__pycache__|\.runtime|\.tools|node_modules|dist)\\'
        }

    $parseCode = 'import ast,sys; p=sys.argv[-1]; ast.parse(open(p,encoding="utf-8").read(),filename=p)'
    foreach ($file in $pythonFiles) {
        & $PythonPath -c $parseCode -- $file.FullName 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Add-CheckFailure "Python 语法错误：$($file.FullName)"
        }
    }
    Write-Host "[通过] Python 语法检查：$($pythonFiles.Count) 个文件" -ForegroundColor Green
}

# 检查前端 JSON 配置和锁文件是否可以正常解析。
function Test-FrontendMetadata {
    $frontendRoot = Join-Path $repoRoot 'fund-advisor\frontend'
    foreach ($name in @('package.json', 'package-lock.json')) {
        $path = Join-Path $frontendRoot $name
        try {
            Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable | Out-Null
        } catch {
            Add-CheckFailure "前端 JSON 配置无法解析：$path"
        }
    }
    if ($failures.Count -eq 0) {
        Write-Host '[通过] 前端 package.json/package-lock.json' -ForegroundColor Green
    }
}

# 检查常见密钥文件和私钥头，避免把秘密带入公开仓库。
function Test-SensitiveFiles {
    $privateKeyHits = rg --hidden -n -g '!.git/**' -g '!*.lock' '-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}' $repoRoot 2>$null
    if ($LASTEXITCODE -eq 0 -and $privateKeyHits) {
        Add-CheckFailure '发现疑似私钥或访问令牌，请人工检查后再提交。'
    } else {
        Write-Host '[通过] 未发现常见私钥或令牌特征' -ForegroundColor Green
    }
}

# 检查 Git 差异格式和关键模板文件。
function Test-RepositoryState {
    git -C $repoRoot diff --check
    if ($LASTEXITCODE -ne 0) {
        Add-CheckFailure 'Git 差异存在空白或格式错误。'
    } else {
        Write-Host '[通过] Git diff --check' -ForegroundColor Green
    }

    $alembicExample = Join-Path $repoRoot 'fund-advisor\alembic.ini.example'
    if (-not (Test-Path -LiteralPath $alembicExample)) {
        Add-CheckFailure "缺少 Alembic 配置模板：$alembicExample"
    } else {
        Write-Host '[通过] Alembic 配置模板存在' -ForegroundColor Green
    }
}

# 运行分析引擎与后端服务单元测试，测试数据仅来自仓库夹具和假会话。
function Invoke-PythonTests {
    param([Parameter(Mandatory)][string]$PythonPath)

    & $PythonPath -m pytest (Join-Path $repoRoot 'fund-analyzer\tests') -q
    if ($LASTEXITCODE -ne 0) {
        Add-CheckFailure 'fund-analyzer Python 单元测试失败或 pytest 未安装。'
    } else {
        Write-Host '[通过] fund-analyzer Python 单元测试' -ForegroundColor Green
    }

    & $PythonPath -m pytest (Join-Path $repoRoot 'fund-advisor\backend\tests') -q
    if ($LASTEXITCODE -ne 0) {
        Add-CheckFailure 'fund-advisor 后端服务单元测试失败或 pytest 未安装。'
    } else {
        Write-Host '[通过] fund-advisor 后端服务单元测试' -ForegroundColor Green
    }
}

# 构建前端静态产物，验证 Vue 代码和生产构建配置。
function Invoke-FrontendBuild {
    $frontendRoot = Join-Path $repoRoot 'fund-advisor\frontend'
    if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules'))) {
        Add-CheckFailure "前端依赖未安装，无法构建：$frontendRoot。请先在该目录执行 npm ci。"
        return
    }

    Push-Location $frontendRoot
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) {
            Add-CheckFailure '前端生产构建失败。'
        } else {
            Write-Host '[通过] 前端生产构建' -ForegroundColor Green
        }
    } finally {
        Pop-Location
    }
}

$advisorPythonPath = Join-Path $repoRoot 'fund-advisor\.venv\Scripts\python.exe'
$analyzerPythonPath = Join-Path $repoRoot 'fund-analyzer\.venv\Scripts\python.exe'
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$pythonPath = if (Test-Path -LiteralPath $advisorPythonPath) {
    $advisorPythonPath
} elseif (Test-Path -LiteralPath $analyzerPythonPath) {
    $analyzerPythonPath
} elseif ($pythonCommand) {
    $pythonCommand.Source
} else {
    $null
}

if (-not $pythonPath) {
    Add-CheckFailure '未找到 python.exe。'
} else {
    Test-PythonSyntax -PythonPath $pythonPath
}

Test-FrontendMetadata
Test-SensitiveFiles
Test-RepositoryState

if ($RunPythonTests -and $pythonPath) {
    Invoke-PythonTests -PythonPath $pythonPath
}
if ($BuildFrontend) {
    Invoke-FrontendBuild
}

if ($failures.Count -gt 0) {
    Write-Host "本地检查未通过，共 $($failures.Count) 项。" -ForegroundColor Red
    exit 1
}

Write-Host '本地开发检查全部通过。' -ForegroundColor Green
