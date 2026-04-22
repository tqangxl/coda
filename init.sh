#!/bin/bash

# =============================================================================
# AI Agent系统 V2.0 - 自动初始化脚本
# 支持: Linux / macOS / Windows (WSL/PowerShell)
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if [ -f /etc/debian_version ]; then
            echo "debian"
        elif [ -f /etc/redhat-release ]; then
            echo "rhel"
        else
            echo "linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    elif [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]]; then
        echo "windows-gitbash"
    else
        echo "unknown"
    fi
}

# 检测包管理器
detect_package_manager() {
    local os=$1
    case $os in
        "debian")
            if command -v apt-get &> /dev/null; then
                echo "apt"
            fi
            ;;
        "rhel")
            if command -v dnf &> /dev/null; then
                echo "dnf"
            elif command -v yum &> /dev/null; then
                echo "yum"
            fi
            ;;
        "macos")
            if command -v brew &> /dev/null; then
                echo "brew"
            fi
            ;;
    esac
}

# 安装核心依赖
install_core_dependencies() {
    local os=$1
    local pm=$2

    log_info "Installing core dependencies for $os..."

    case $os in
        "debian")
            sudo apt-get update
            sudo apt-get install -y curl wget git build-essential
            ;;
        "rhel")
            sudo yum install -y curl wget git make gcc
            ;;
        "macos")
            if ! command -v brew &> /dev/null; then
                log_warning "Homebrew not found. Installing..."
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            fi
            brew install curl wget git
            ;;
        "windows-gitbash")
            log_warning "Windows Git Bash detected. Please ensure Git is installed."
            ;;
    esac

    log_success "Core dependencies installed"
}

# 安装cx (Token优化工具)
install_cx() {
    log_info "Installing cx (Token Optimizer)..."

    if command -v cx &> /dev/null; then
        log_success "cx already installed: $(cx --version)"
        return 0
    fi

    # 尝试不同安装方法
    if command -v curl &> /dev/null; then
        log_info "Trying curl installation..."
        if curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh 2>/dev/null; then
            log_success "cx installed via curl"
            return 0
        fi
    fi

    if command -v cargo &> /dev/null; then
        log_info "Trying cargo installation..."
        if cargo install cx-cli 2>/dev/null; then
            log_success "cx installed via cargo"
            return 0
        fi
    fi

    # 下载预编译二进制
    log_info "Trying binary download..."
    local os=$(uname -s | tr '[:upper:]' '[:lower:]')
    local arch=$(uname -m)
    local cx_url="https://github.com/ind-igo/cx/releases/latest/download/cx-${os}-${arch}.tar.gz"

    if curl -LO "$cx_url" 2>/dev/null; then
        tar -xzf "cx-${os}-${arch}.tar.gz"
        sudo mv cx /usr/local/bin/
        rm -f "cx-${os}-${arch}.tar.gz"
        log_success "cx installed via binary download"
        return 0
    fi

    log_warning "cx installation failed. You can install manually later."
    return 1
}

# 安装Node.js
install_nodejs() {
    log_info "Checking Node.js..."

    if command -v node &> /dev/null; then
        log_success "Node.js already installed: $(node --version)"
        return 0
    fi

    local os=$(detect_os)

    case $os in
        "debian")
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt-get install -y nodejs
            ;;
        "rhel")
            curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
            sudo yum install -y nodejs
            ;;
        "macos")
            brew install node
            ;;
    esac

    if command -v node &> /dev/null; then
        log_success "Node.js installed: $(node --version)"
    else
        log_warning "Node.js installation failed"
    fi
}

# 安装Python
install_python() {
    log_info "Checking Python..."

    if command -v python3 &> /dev/null; then
        log_success "Python already installed: $(python3 --version)"
        return 0
    fi

    local os=$(detect_os)

    case $os in
        "debian")
            sudo apt-get install -y python3 python3-pip python3-venv
            ;;
        "rhel")
            sudo yum install -y python3 python3-pip
            ;;
        "macos")
            brew install python@3.11
            ;;
    esac

    if command -v python3 &> /dev/null; then
        log_success "Python installed: $(python3 --version)"
    else
        log_warning "Python installation failed"
    fi
}

# 配置cx语言支持
setup_cx_languages() {
    log_info "Setting up cx language support..."

    if ! command -v cx &> /dev/null; then
        log_warning "cx not installed, skipping language setup"
        return 1
    fi

    # 添加常用语言
    local languages="rust typescript python"
    for lang in $languages; do
        if cx lang add $lang 2>/dev/null; then
            log_success "Added $lang support"
        else
            log_warning "Failed to add $lang support"
        fi
    done

    log_success "cx language setup complete"
}

# 配置Agent使用cx
setup_agent_cx() {
    log_info "Configuring Agent to use cx..."

    # 生成cx使用说明
    if command -v cx &> /dev/null; then
        mkdir -p ~/.claude 2>/dev/null || true
        cx skill > ~/.claude/CX.md 2>/dev/null || true

        # 添加到CLAUDE.md
        if [ -f ~/.claude/CLAUDE.md ]; then
            if ! grep -q "@CX.md" ~/.claude/CLAUDE.md; then
                echo -e "\n@CX.md" >> ~/.claude/CLAUDE.md
                log_success "Added @CX.md to CLAUDE.md"
            fi
        fi
    fi
}

# 创建工作目录结构
setup_workspace() {
    log_info "Setting up workspace structure..."

    local workspace_dir="${1:-$HOME/ai-agents-workspace}"

    mkdir -p "$workspace_dir"
    cd "$workspace_dir"

    # 创建子目录
    mkdir -p memory
    mkdir -p knowledge-base
    mkdir -p outputs
    mkdir -p logs
    mkdir -p temp

    log_success "Workspace created at: $workspace_dir"
    echo "$workspace_dir" > .workspace_root

    # 复制模板文件
    if [ -d "../ai-agents-v2/templates" ]; then
        cp ../ai-agents-v2/templates/*.md . 2>/dev/null || true
        log_success "Template files copied"
    fi

    # 创建初始记忆文件
    if [ ! -f MEMORY.md ]; then
        cat > MEMORY.md << 'EOF'
# MEMORY.md - 长期记忆

## 版本
- v1.0
- 创建日期: $(date +%Y-%m-%d)

## 核心原则
- [添加你的核心工作原则]

## 项目背景
- [添加项目背景]

## 重要决策
| 日期 | 决策 | 原因 | 结果 |
|------|------|------|------|
EOF
        log_success "MEMORY.md created"
    fi

    if [ ! -f PROFILE.md ]; then
        cat > PROFILE.md << 'EOF'
# PROFILE.md - 用户画像

## 版本
- v1.0
- 创建日期: $(date +%Y-%m-%d)

## 基础信息
- 技术背景: [你的技术背景]
- 偏好: [你的偏好]

## 沟通风格
- 详细程度: [简洁/详细]
- 术语使用: [专业/通俗]
- 格式: [Markdown/纯文本]
EOF
        log_success "PROFILE.md created"
    fi

    cd ..
}

# 验证安装
verify_installation() {
    log_info "Verifying installation..."

    local all_passed=true

    # 核心工具
    if command -v git &> /dev/null; then
        log_success "Git: $(git --version | head -c50)"
    else
        log_error "Git: NOT FOUND"
        all_passed=false
    fi

    if command -v cx &> /dev/null; then
        log_success "cx: $(cx --version)"
    else
        log_warning "cx: NOT FOUND (optional)"
    fi

    if command -v node &> /dev/null; then
        log_success "Node.js: $(node --version)"
    else
        log_warning "Node.js: NOT FOUND (optional)"
    fi

    if command -v python3 &> /dev/null; then
        log_success "Python: $(python3 --version)"
    else
        log_warning "Python: NOT FOUND (optional)"
    fi

    if command -v docker &> /dev/null; then
        log_success "Docker: $(docker --version)"
    else
        log_warning "Docker: NOT FOUND (optional)"
    fi

    if [ "$all_passed" = true ]; then
        log_success "All core tools installed!"
        return 0
    else
        log_warning "Some tools are missing. Run 'bash TOOLS.md' for installation instructions."
        return 1
    fi
}

# 显示使用指南
show_usage() {
    echo ""
    echo "========================================"
    echo "   AI Agent系统 V2.0 初始化完成!"
    echo "========================================"
    echo ""
    echo "下一步:"
    echo "  1. 编辑 MEMORY.md - 添加你的项目背景"
    echo "  2. 编辑 PROFILE.md - 添加你的偏好"
    echo "  3. 编辑 agents/SOUL.md - 配置Agent灵魂"
    echo "  4. 查看 TOOLS.md - 查看完整工具安装指南"
    echo ""
    echo "快速开始:"
    echo "  - 查看 README.md 了解系统架构"
    echo "  - 查看 README.md 了解核心Agent角色"
    echo "  - 使用 cx lang add <language> 添加语言支持"
    echo ""
}

# 主函数
main() {
    echo ""
    echo "========================================"
    echo "   AI Agent系统 V2.0 - 自动初始化"
    echo "========================================"
    echo ""

    local os=$(detect_os)
    local pm=$(detect_package_manager "$os")

    log_info "Detected OS: $os"
    log_info "Package Manager: ${pm:-none}"

    # 安装核心依赖
    install_core_dependencies "$os" "$pm"

    # 安装必需工具
    install_cx
    install_nodejs
    install_python

    # 配置
    setup_cx_languages
    setup_agent_cx
    setup_workspace "$@"

    # 验证
    echo ""
    verify_installation

    # 显示使用指南
    show_usage
}

# 运行
main "$@"
