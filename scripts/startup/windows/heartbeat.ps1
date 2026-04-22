# AI Agent V2.0 - 心跳写入脚本
# 由Windows任务计划程序每30分钟调用一次

$ErrorActionPreference = "SilentlyContinue"

# 数据目录
$DataDir = "$env:USERPROFILE\.ai-agents"
$HeartbeatFile = "$DataDir\heartbeat.json"
$LogFile = "$DataDir\logs\heartbeat.log"

# 确保目录存在
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

$LogDir = Split-Path -Parent $LogFile
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# 读取系统信息
$MemoryMB = [math]::Round((Get-Process | Measure-Object WorkingSet64 -Sum).Sum / 1MB, 2)
$CPUPercent = [math]::Round((Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1).CounterSamples.CookedValue, 2)
$Uptime = (Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime

# 检查SurrealDB连接
$SurrealDBStatus = "unknown"
try {
    $response = Invoke-WebRequest -Uri "http://localhost:11001/status" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        $SurrealDBStatus = "connected"
    } else {
        $SurrealDBStatus = "error"
    }
} catch {
    $SurrealDBStatus = "disconnected"
}

# 创建心跳数据
$heartbeat = @{
    timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    status = "running"
    namespace = "ai_agents_v2"
    uptime_seconds = [int]$Uptime.TotalSeconds
    uptime_readable = "$([int]$Uptime.TotalHours)小时$($Uptime.Minutes)分钟"
    memory_mb = $MemoryMB
    cpu_percent = $CPUPercent
    surrealdb_status = $SurrealDBStatus
    machine = $env:COMPUTERNAME
    user = $env:USERNAME
}

# 写入心跳文件
$heartbeat | ConvertTo-Json | Out-File -FilePath $HeartbeatFile -Encoding UTF8 -Force

# 写入日志
$logEntry = "[$($heartbeat.timestamp)] HEARTBEAT - Memory: ${MemoryMB}MB, CPU: ${CPUPercent}%, SurrealDB: $SurrealDBStatus"
Add-Content -Path $LogFile -Value $logEntry

# 检查是否需要清理旧日志（保留7天）
$OldLogs = Get-ChildItem -Path $LogDir -Filter "heartbeat-*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) }
$OldLogs | Remove-Item -Force -ErrorAction SilentlyContinue

exit 0
