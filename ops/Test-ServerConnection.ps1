[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '.env')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 读取简单的 KEY=VALUE 配置文件并返回键值表。
function Import-ServerConfig {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "服务器配置文件不存在：$Path"
    }

    $config = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            continue
        }

        $parts = $line.Split('=', 2)
        if ($parts.Count -ne 2) {
            throw "配置行格式错误：$rawLine"
        }

        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        $config[$key] = $value
    }

    return $config
}

# 获取必填配置值，缺失时给出明确错误。
function Get-RequiredConfigValue {
    param(
        [Parameter(Mandatory)][hashtable]$Config,
        [Parameter(Mandatory)][string]$Name
    )

    if (-not $Config.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($Config[$Name])) {
        throw "缺少必填配置：$Name"
    }

    return [string]$Config[$Name]
}

# 获取可选配置值，不存在时返回指定默认值。
function Get-OptionalConfigValue {
    param(
        [Parameter(Mandatory)][hashtable]$Config,
        [Parameter(Mandatory)][string]$Name,
        [string]$DefaultValue = ''
    )

    if (-not $Config.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($Config[$Name])) {
        return $DefaultValue
    }

    return [string]$Config[$Name]
}

# 校验远程路径，避免把特殊字符带入远程命令。
function Assert-SafeRemotePath {
    param([Parameter(Mandatory)][string]$Path)

    if (-not $Path.StartsWith('/') -or $Path -match "['`r`n]") {
        throw "REMOTE_PROJECT_PATH 必须是安全的 Linux 绝对路径：$Path"
    }
}

# 构建 SSH 参数，强制批处理模式并限制连接等待时间。
function New-SshArguments {
    param([Parameter(Mandatory)][hashtable]$Config)

    $arguments = @(
        '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=10'
    )

    $strictMode = Get-OptionalConfigValue -Config $Config -Name 'SSH_STRICT_HOST_KEY_CHECKING' -DefaultValue 'yes'
    if ($strictMode -notin @('yes', 'accept-new')) {
        throw 'SSH_STRICT_HOST_KEY_CHECKING 只允许 yes 或 accept-new。'
    }
    $arguments += @('-o', "StrictHostKeyChecking=$strictMode")

    $port = Get-OptionalConfigValue -Config $Config -Name 'SSH_PORT' -DefaultValue '22'
    if ($port -notmatch '^\d{1,5}$' -or [int]$port -lt 1 -or [int]$port -gt 65535) {
        throw "SSH_PORT 无效：$port"
    }
    $arguments += @('-p', $port)

    $identityFile = Get-OptionalConfigValue -Config $Config -Name 'SSH_IDENTITY_FILE'
    if ($identityFile) {
        $resolvedIdentity = (Resolve-Path -LiteralPath $identityFile).Path
        $arguments += @('-i', $resolvedIdentity)
    }

    return $arguments
}

# 通过 SSH 在服务器执行不修改状态的基础巡检。
function Invoke-ReadOnlyServerSurvey {
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string[]]$SshArguments,
        [Parameter(Mandatory)][string]$RemoteProjectPath
    )

    $remoteScript = @'
set -eu
project_dir="$1"

echo "=== 主机信息 ==="
hostname
id -un
date -u '+%Y-%m-%dT%H:%M:%SZ'
uname -a

echo "=== 磁盘与负载 ==="
df -h /
uptime

echo "=== 项目仓库 ==="
if [ -d "$project_dir/.git" ]; then
  git -C "$project_dir" status --short --branch
  git -C "$project_dir" rev-parse HEAD
else
  echo "未找到 Git 仓库：$project_dir"
fi

echo "=== Docker ==="
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker compose version 2>/dev/null || true
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
else
  echo "未安装 Docker"
fi

echo "=== systemd ==="
if command -v systemctl >/dev/null 2>&1; then
  systemctl is-system-running 2>/dev/null || true
else
  echo "未使用 systemd"
fi
# 保留末尾注释，避免 Windows 管道附加的回车影响最后一条 Bash 命令。
'@

    $sshCommand = (Get-Command ssh.exe -ErrorAction Stop).Source
    $remoteCommand = "bash -s -- '$RemoteProjectPath'"

    Write-Host "正在对 $Target 执行只读巡检，远程项目路径：$RemoteProjectPath"
    $remoteScript | & $sshCommand @SshArguments $Target $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "SSH 巡检失败，退出码：$LASTEXITCODE"
    }
}

$serverConfig = Import-ServerConfig -Path $ConfigPath
$sshHostName = Get-RequiredConfigValue -Config $serverConfig -Name 'SSH_HOST'
$sshUserName = Get-RequiredConfigValue -Config $serverConfig -Name 'SSH_USER'
$remotePath = Get-RequiredConfigValue -Config $serverConfig -Name 'REMOTE_PROJECT_PATH'
Assert-SafeRemotePath -Path $remotePath

$sshTarget = "$sshUserName@$sshHostName"
$sshOptions = New-SshArguments -Config $serverConfig
Invoke-ReadOnlyServerSurvey -Target $sshTarget -SshArguments $sshOptions -RemoteProjectPath $remotePath
