<#
.SYNOPSIS
    AI Agent V2.0 - Windows 启动与服务管理脚本 (2026 最终修正版)
    功能：支持自动管理员提权、同目录 nssm 识别、卸载/安装结果停顿、路径动态定位
#>

# ========================================================
# 1. 参数定义 (必须放在脚本首行)
# ========================================================
param(
    [switch]$Install,      # 安装为 Windows 服务
    [switch]$Uninstall,    # 卸载并停止服务
    [switch]$Status,       # 查看服务与心跳状态
    [switch]$Restart,      # 重启所有相关进程
    [switch]$Console,      # 控制台模式直接运行 (DB + API)
    [switch]$UI,           # 启动后自动打开图谱 UI
    [switch]$DeepScan      # 启动后强制全量知识扫描
)

# ========================================================
# 2. 自动管理员权限请求 (带参数转发)
# ========================================================
if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]'Administrator')) {
    Write-Host "🚀 正在请求管理员权限以进行系统底层操作..." -ForegroundColor Cyan
    
    $ArgList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    $ArgList += $MyInvocation.BoundParameters.Keys | ForEach-Object { "-$($_)" }
    $ArgList += $MyInvocation.UnboundArguments
    
    try {
        Start-Process PowerShell.exe -ArgumentList $ArgList -Verb RunAs
    } catch {
        Write-Host "❌ 提权失败：用户取消或系统限制。" -ForegroundColor Red
        $null = [System.Console]::ReadKey($true)
    }
    return 
}

# ========================================================
# 3. 环境初始化与路径自愈
# ========================================================
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# --- 寻找 nssm.exe (核心修复：优先检测脚本同目录) ---
$NssmExe = Join-Path $ScriptDir "nssm.exe"
if (!(Test-Path $NssmExe)) {
    # 如果同目录没有，尝试从环境变量找
    $NssmCmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($NssmCmd) { $NssmExe = $NssmCmd.Source }
}

# --- 动态项目根目录定位 ---
$CurrentDir = $ScriptDir
while ($CurrentDir -and !(Test-Path "$CurrentDir\main.py")) {
    $CurrentDir = Split-Path $CurrentDir -Parent
}
$ProjectRoot = if ($CurrentDir) { $CurrentDir } else { $ScriptDir }

$ServiceName = "AIAgentsV2"
$DisplayName = "AI Agents V2.0"
$ConfigDir = "$env:USERPROFILE\.ai-agents"
$LogDir = "$ConfigDir\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = "$LogDir\agent-$((Get-Date).ToString('yyyyMMdd')).log"
$SurrealDBPort = 11001
$BackendPort = 11002

# --- 内部辅助函数 ---
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    $entry = "[$((Get-Date).ToString('HH:mm:ss'))] [$Level] $Message"
    Add-Content -Path $LogFile -Value $entry
    $color = switch($Level) { "ERROR" {"Red"}; "SUCCESS" {"Green"}; "WARN" {"Yellow"}; default {"White"} }
    Write-Host $entry -ForegroundColor $color
}

function Stop-PortProcess {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $procId = $conn.OwningProcess
        Write-Log "端口 $Port 被 PID $procId 占用，正在强制释放..." "WARN"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

function Start-Database {
    Stop-PortProcess $SurrealDBPort
    $surrealExe = "C:\Program Files\SurrealDB\surreal.exe"
    if (-not (Test-Path $surrealExe)) { Write-Log "找不到 SurrealDB 执行文件。" "ERROR"; exit 1 }

    $dataPath = Join-Path $ProjectRoot "surrealdb\data"
    if (-not (Test-Path $dataPath)) { New-Item -ItemType Directory -Path $dataPath -Force | Out-Null }

    Write-Log "正在启动 SurrealDB (RocksDB 模式)..." "INFO"
    $surrealArgs = "start --user root --pass AgentSecurePass2026 --bind 127.0.0.1:$SurrealDBPort --log info rocksdb://$dataPath"
    $proc = Start-Process -FilePath $surrealExe -ArgumentList $surrealArgs -NoNewWindow -PassThru
    
    # 端口轮询逻辑
    $retry = 0
    while ($retry -lt 15) {
        if (Test-NetConnection 127.0.0.1 -Port $SurrealDBPort -WarningAction SilentlyContinue | Where-Object {$_.TcpTestSucceeded}) {
            Write-Log "SurrealDB 数据库已就绪。" "SUCCESS"
            return $proc
        }
        Start-Sleep -Seconds 1
        $retry++
    }
    Write-Log "数据库启动超时。" "ERROR"; exit 1
}

function Start-KnowledgeSync {
    param([bool]$FullCompilation = $false)
    $python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }
    $script = Join-Path $ProjectRoot "scripts\seed_wiki.py"
    
    if (Test-Path $script) {
        Write-Log "正在后台同步联邦知识图谱 (Warmup)..." "INFO"
        # 异步启动同步脚本，不阻塞主服务
        $flag = if ($FullCompilation) { "full" } else { "inc" }
        Start-Process -FilePath $python -ArgumentList "`"$script`"" -WorkingDirectory $ProjectRoot -NoNewWindow
    }
}

function Open-Dashboard {
    $url = "http://127.0.0.1:$BackendPort/engine/graph"
    Write-Log "正在打开可视化看板: $url" "SUCCESS"
    Start-Process $url
}

# ========================================================
# 4. 主逻辑分支执行
# ========================================================

if ($Install) {
    Write-Host "`n=== 正在开始安装服务 ===" -ForegroundColor Cyan
    if (-not (Test-Path $NssmExe)) { 
        Write-Log "未找到 nssm.exe。请将其放入脚本同目录或加入环境变量。" "ERROR"
    } else {
        Write-Log "使用 NSSM 路径: $NssmExe" "INFO"
        $powershell = (Get-Process -Id $PID).Path
        $serviceArgs = "-ExecutionPolicy Bypass -NoProfile -File `"$PSCommandPath`" -Console"
        
        & "$NssmExe" install $ServiceName "$powershell" "$serviceArgs"
        & "$NssmExe" set $ServiceName AppDirectory "$ProjectRoot"
        & "$NssmExe" set $ServiceName DisplayName "$DisplayName"
        & "$NssmExe" set $ServiceName Start SERVICE_AUTO_START
        
        if ($LASTEXITCODE -eq 0) { 
            Start-Service $ServiceName -ErrorAction SilentlyContinue
            Write-Host "`n[结果] $DisplayName 服务安装成功并已启动！" -ForegroundColor Green
            Write-Log "服务安装成功。" "SUCCESS"
        } else {
            Write-Host "`n[错误] NSSM 安装失败，代码: $LASTEXITCODE" -ForegroundColor Red
        }
    }
    Read-Host "`n操作完成，按回车键退出脚本..."
}
elseif ($Uninstall) {
    Write-Host "`n=== 正在卸载服务 ===" -ForegroundColor Yellow
    if (-not (Test-Path $NssmExe)) {
        Write-Log "未找到 nssm.exe，无法执行自动卸载。" "ERROR"
    } else {
        Stop-Service $ServiceName -ErrorAction SilentlyContinue
        & "$NssmExe" remove $ServiceName confirm
        Stop-PortProcess $BackendPort
        Stop-PortProcess $SurrealDBPort
        Write-Host "`n[结果] $DisplayName 卸载完成，相关端口已清理。" -ForegroundColor Green
        Write-Log "服务已彻底移除。" "SUCCESS"
    }
    # 确保卸载完成后也会停顿
    Read-Host "`n操作完成，按回车键退出脚本..."
}
elseif ($Status) {
    $svc = Get-Service $ServiceName -ErrorAction SilentlyContinue
    Write-Host "`n=== $DisplayName 运行状态 ===" -ForegroundColor Cyan
    if ($svc) {
        $color = if ($svc.Status -eq 'Running') { "Green" } else { "Red" }
        Write-Host "服务状态: $($svc.Status)" -ForegroundColor $color
    } else { Write-Host "服务未安装。" -ForegroundColor Gray }
    Read-Host "`n按回车键返回..."
}
elseif ($Console) {
    Write-Log "🚀 Coda V7.0 Orchestrator Starting..." "SUCCESS"
    
    # V7.0: 核心加固 — 确保提权后的窗口处于正确的工作目录
    Set-Location "$ProjectRoot"
    Write-Log "Current Directory: $(Get-Location)" "DEBUG"

    # 1. 启动数据库
    $dbProc = Start-Database
    
    $python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }
    
    try {
        # 2. 运行 Pre-flight 诊断 (使用绝对路径确保提权后可用)
        Write-Log "运行 Pre-flight 系统诊断..." "INFO"
        & $python "$ProjectRoot\main.py" --diagnose
        if ($LASTEXITCODE -ne 0) {
            Write-Log "❌ 环境诊断未通过，请检查配置后再启动。" "ERROR"
            Read-Host "`n按回车键退出并查看错误日志..."
            exit $LASTEXITCODE
        }

        # 3. 启动 API 后台
        Stop-PortProcess $BackendPort
        $backendProcess = Start-Process -FilePath $python `
            -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "$BackendPort" `
            -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow
        
        Write-Host "`n🚀 API 服务已启动。SurrealDB: $SurrealDBPort | API: $BackendPort" -ForegroundColor Green
        
        # 4. 异步同步知识库 (Warmup)
        Start-KnowledgeSync -FullCompilation ($DeepScan -eq $true)

        # 5. 可选启动 UI
        if ($UI) {
            Start-Sleep -Seconds 2 # 等待 API 响应
            Open-Dashboard
        }

        Write-Host "`n✨ 系统就绪。按 Ctrl+C 停止所有服务。`n" -ForegroundColor Cyan
        while ($true) { 
            # 心跳检测
            if ($backendProcess.HasExited) { Write-Log "API 意外退出！" "ERROR"; break }
            Start-Sleep -Seconds 2 
        }
    }
    finally {
        Write-Log "正在强制清理所有联动进程树..." "WARN"
        if ($backendProcess) { Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue }
        if ($dbProc) { Stop-Process -Id $dbProc.Id -Force -ErrorAction SilentlyContinue }
        # 清理残留 python 实例 (视具体需求而定)
    }
}
else {
    Write-Host "`n用法提示: .\startup.ps1 [-Install | -Uninstall | -Status | -Restart | -Console]`n" -ForegroundColor Cyan
    Read-Host "`n[未输入有效参数] 按回车键退出脚本..."
}
