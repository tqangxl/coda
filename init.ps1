# =============================================================================
# AI Agent系统 V2.0 - Windows自动初始化脚本
# 需要以管理员权限运行PowerShell
# =============================================================================

$ErrorActionPreference = "Stop"

# 颜色定义
function Write-Info { Write-Host "[INFO] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[SUCCESS] $args" -ForegroundColor Green }
function Write-Warning { Write-Host "[WARNING] $args" -ForegroundColor Yellow }
function Write-Error { Write-Host "[ERROR] $args" -ForegroundColor Red }

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "   AI Agent系统 V2.0 - Windows初始化" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# 检查管理员权限
function Test-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Warning "建议以管理员权限运行以安装系统级工具"
    $continue = Read-Host "继续? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit 0
    }
}

# 检测winget
function Test-Winget {
    try {
        $result = winget --version 2>$null
        return $true
    }
    catch {
        return $false
    }
}

# 安装工具函数
function Install-Tool {
    param (
        [string]$ToolName,
        [string]$WingetId,
        [string]$ChocoId = $null
    )

    Write-Info "Checking $ToolName..."

    # 检查是否已安装
    $installed = $false

    # winget
    if (Test-Winget) {
        try {
            winget list --id $WingetId --exact 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Success "$ToolName already installed"
                return $true
            }
        }
        catch {}
    }

    # choco
    if ($ChocoId) {
        try {
            choco list --local-only $ChocoId 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Success "$ToolName already installed (via Chocolatey)"
                return $true
            }
        }
        catch {}
    }

    # 尝试安装
    Write-Info "Installing $ToolName..."

    if (Test-Winget) {
        try {
            winget install --id $WingetId --accept-source-agreements --accept-package-agreements --silent
            Write-Success "$ToolName installed via winget"
            return $true
        }
        catch {
            Write-Warning "winget安装失败"
        }
    }

    if ($ChocoId) {
        try {
            choco install $ChocoId -y --force
            Write-Success "$ToolName installed via Chocolatey"
            return $true
        }
        catch {
            Write-Warning "Chocolatey安装失败"
        }
    }

    Write-Error "$ToolName 安装失败"
    return $false
}

# 检查工具
function Test-Tool {
    param ([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

# 1. 安装Git
Write-Info "Step 1/7: Git"
Install-Tool -ToolName "Git" -WingetId "Git.Git" -ChocoId "git"

# 2. 安装Node.js
Write-Info "Step 2/7: Node.js"
Install-Tool -ToolName "Node.js" -WingetId "OpenJS.NodeJS.LTS" -ChocoId "nodejs"

# 3. 安装Python
Write-Info "Step 3/7: Python"
Install-Tool -ToolName "Python" -WingetId "Python.Python.3.13" -ChocoId "python"

# 4. 安装Docker Desktop
Write-Info "Step 4/7: Docker Desktop"
$dockerChoice = Read-Host "安装Docker Desktop? (需要WLS2) (y/N)"
if ($dockerChoice -eq "y" -or $dockerChoice -eq "Y") {
    Install-Tool -ToolName "Docker Desktop" -WingetId "Docker.DockerDesktop" -ChocoId "docker-desktop"
}

# 5. 安装cx (Token优化工具)
Write-Info "Step 5/7: cx (Token Optimizer)"
if (Test-Tool "cx") {
    Write-Success "cx already installed"
}
else {
    try {
        $installDir = "D:\env\cx"
        Write-Info "Installing cx from source to $installDir..."
        
        # Ensure directory exists
        if (-not (Test-Path $installDir)) {
            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
        }

        # 获取安装脚本并执行 (使用 -InstallDir 参数)
        $scriptUrl = "https://raw.githubusercontent.com/ind-igo/cx/master/install.ps1"
        $script = Invoke-RestMethod $scriptUrl
        
        # 补丁：使脚本支持传参并覆盖硬编码路径
        if ($script -notmatch "param\(") {
            $script = "param(`$InstallDir) " + $script.Replace('`$InstallDir = "`$env:LOCALAPPDATA\cx\bin"', "")
        }

        # 运行安装
        Write-Info "Executing installation script..."
        $executionPolicy = Get-ExecutionPolicy
        Set-ExecutionPolicy RemoteSigned -Scope Process -Force
        & ([scriptblock]::Create($script)) -InstallDir $installDir
        Set-ExecutionPolicy $executionPolicy -Scope Process -Force

        if (Test-Tool "cx") {
            Write-Success "cx installed successfully to $installDir"
        }
        else {
            # 尝试通过完整路径验证
            if (Test-Path (Join-Path $installDir "cx.exe")) {
                Write-Success "cx installed to $installDir (manual path verified)"
            }
            else {
                throw "cx installation could not be verified"
            }
        }
    }
    catch {
        Write-Warning "cx安装失败: $($_.Exception.Message)"
        Write-Info "请手动安装: https://github.com/ind-igo/cx"
    }
}

# 6. 安装其他工具
Write-Info "Step 6/7: Additional Tools"
$moreChoice = Read-Host "安装额外工具(Terraform, kubectl等)? (y/N)"
if ($moreChoice -eq "y" -or $moreChoice -eq "Y") {
    Install-Tool -ToolName "Terraform" -WingetId "HashiCorp.Terraform" -ChocoId "terraform"
    Install-Tool -ToolName "kubectl" -WingetId "Kubernetes.kubectl" -ChocoId "kubectl"
}

# 7. 配置cx
Write-Info "Step 7/7: Configure cx"
if (Test-Tool "cx") {
    try {
        # 添加语言支持
        $languages = @("typescript", "python", "rust")
        foreach ($lang in $languages) {
            Write-Info "Adding $lang support..."
            cx lang add $lang 2>$null
        }

        # 生成Agent使用说明
        $cxMdPath = "$env:USERPROFILE\.claude\CX.md"
        if (-not (Test-Path (Split-Path $cxMdPath))) {
            New-Item -Path (Split-Path $cxMdPath) -ItemType Directory -Force | Out-Null
        }
        cx skill 2>$null | Out-File -FilePath $cxMdPath -Encoding UTF8
        Write-Success "cx configured"

        # 更新CLAUDE.md
        $claudeMdPath = "$env:USERPROFILE\.claude\CLAUDE.md"
        if (Test-Path $claudeMdPath) {
            if (-not (Select-String -Path $claudeMdPath -Pattern "@CX.md" -Quiet)) {
                Add-Content -Path $claudeMdPath -Value "`n@CX.md"
                Write-Success "Updated CLAUDE.md"
            }
        }
    }
    catch {
        Write-Warning "cx配置失败，但工具已安装"
    }
}

# 创建工作目录
Write-Info "Creating workspace..."
$workspaceDir = "$env:USERPROFILE\ai-agents-workspace"
if (-not (Test-Path $workspaceDir)) {
    New-Item -Path $workspaceDir -ItemType Directory -Force | Out-Null
}

# 复制模板文件
$templateDir = Join-Path $PSScriptRoot "templates"
if (Test-Path $templateDir) {
    Copy-Item -Path "$templateDir\*" -Destination $workspaceDir -Force
    Write-Success "Template files copied to $workspaceDir"
}

# 创建MEMORY.md
$memoryPath = Join-Path $workspaceDir "MEMORY.md"
if (-not (Test-Path $memoryPath)) {
    @"
# MEMORY.md - 长期记忆

## 版本
- v1.0
- 创建日期: $(Get-Date -Format "yyyy-MM-dd")

## 核心原则
- [添加你的核心工作原则]

## 项目背景
- [添加项目背景]

## 重要决策
| 日期 | 决策 | 原因 | 结果 |
|------|------|------|------|
"@ | Out-File -FilePath $memoryPath -Encoding UTF8
    Write-Success "MEMORY.md created"
}

# 创建PROFILE.md
$profilePath = Join-Path $workspaceDir "PROFILE.md"
if (-not (Test-Path $profilePath)) {
    @"
# PROFILE.md - 用户画像

## 版本
- v1.0
- 创建日期: $(Get-Date -Format "yyyy-MM-dd")

## 基础信息
- 技术背景: [你的技术背景]
- 偏好: [你的偏好]

## 沟通风格
- 详细程度: [简洁/详细]
- 术语使用: [专业/通俗]
- 格式: [Markdown/纯文本]
"@ | Out-File -FilePath $profilePath -Encoding UTF8
    Write-Success "PROFILE.md created"
}

# 验证安装
Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "   验证安装" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

$allGood = $true

if (Test-Tool "git") {
    Write-Success "Git: $(git --version | Select-Object -First 1)"
}
else {
    Write-Error "Git: 未找到"
    $allGood = $false
}

if (Test-Tool "node") {
    Write-Success "Node.js: $(node --version)"
}
else {
    Write-Warning "Node.js: 未找到 (可选)"
}

if (Test-Tool "python") {
    Write-Success "Python: $(python --version 2>$null)"
}
elseif (Test-Tool "python3") {
    Write-Success "Python: $(python3 --version)"
}
else {
    Write-Warning "Python: 未找到 (可选)"
}

if (Test-Tool "cx") {
    Write-Success "cx: $(cx --version)"
}
else {
    Write-Warning "cx: 未找到 (可选)"
}

if (Test-Tool "docker") {
    Write-Success "Docker: $(docker --version 2>$null)"
}
else {
    Write-Warning "Docker: 未找到 (可选)"
}

# 完成
Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "   初始化完成!" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "下一步:" -ForegroundColor Yellow
Write-Host "  1. 编辑 $workspaceDir\MEMORY.md - 添加你的项目背景"
Write-Host "  2. 编辑 $workspaceDir\PROFILE.md - 添加你的偏好"
Write-Host "  3. 查看 TOOLS.md - 查看完整工具安装指南"
Write-Host "  4. 重启终端以使环境变量生效"
Write-Host ""

# 打开工作目录
$openChoice = Read-Host "打开工作目录? (y/N)"
if ($openChoice -eq "y" -or $openChoice -eq "Y") {
    Start-Process explorer $workspaceDir
}
