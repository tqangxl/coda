# 外部工具安装指南

本文档提供所有外部工具的安装说明，支持Windows/Linux/macOS自动检测。

## 环境检测

系统会自动检测运行环境：

```bash
# 自动检测脚本
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "Linux detected"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macOS detected"
elif [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "Windows detected"
fi
```

---

## 核心工具清单

| 工具 | 用途 | 优先级 | 必需 |
|-------|------|--------|------|
| cx | Token优化 | P0 | 是 |
| tree-sitter CLI | cx依赖 | P0 | 是 |
| git | 代码管理 | P0 | 是 |
| nodejs | 运行环境 | P1 | 可选 |
| docker | 容器化 | P1 | 可选 |
| neo4j | 知识图谱 | P2 | 可选 |
| terraform | IaC | P2 | 可选 |

---

## P0 - 必需工具

### 1. Git

#### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install git
git --version
```

#### Linux (CentOS/RHEL)
```bash
sudo yum install git
git --version
```

#### Windows
```powershell
# 方法1: Winget
winget install Git.Git

# 方法2: Choco
choco install git -y

# 方法3: 下载安装包
# https://git-scm.com/download/win
```

#### macOS
```bash
# 方法1: Homebrew
brew install git

# 方法2: Xcode
xcode-select --install
```

---

### 2. cx (Token优化工具)

cx是基于tree-sitter的代码解析工具，可减少40-55%的token消耗。

#### Linux/macOS
```bash
# 方法1: 一键安装（推荐）
curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh

# 方法2: Cargo安装
cargo install cx-cli

# 方法3: 预编译二进制
curl -LO https://github.com/ind-igo/cx/releases/latest/download/cx-x86_64-unknown-linux-gnu.tar.gz
tar -xzf cx-x86_64-unknown-linux-gnu.tar.gz
sudo mv cx /usr/local/bin/
```

#### Windows
```powershell
# 方法1: Winget
winget install ind-igo.cx

# 方法2: Choco
choco install cx -y

# 方法3: 预编译二进制
# 下载: https://github.com/ind-igo/cx/releases
# 解压后将cx.exe放入PATH
```

#### 验证安装
```bash
cx --version
```

#### 添加语言支持
```bash
# 添加常用语言
cx lang add rust typescript python go java

# 查看已安装的语言
cx lang list
```

#### 配置Agent使用
```bash
# 生成Agent使用说明
cx skill > ~/.claude/CX.md

# 在CLAUDE.md中添加引用
echo "@CX.md" >> ~/.claude/CLAUDE.md
```

---

### 3. tree-sitter CLI (cx依赖)

#### Linux/macOS
```bash
# 安装Node.js后
npm install -g tree-sitter-cli

# 或使用Cargo
cargo install tree-sitter-cli
```

#### Windows
```powershell
npm install -g tree-sitter-cli
```

---

## P1 - 重要工具

### 4. Node.js

#### Linux (Ubuntu)
```bash
# 使用NodeSource仓库
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version
```

#### Linux (CentOS)
```bash
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo yum install -y nodejs
node --version
```

#### Windows
```powershell
# 方法1: Winget
winget install OpenJS.NodeJS.LTS

# 方法2: Choco
choco install nodejs -y

# 方法3: 下载安装包
# https://nodejs.org/
```

#### macOS
```bash
# Homebrew
brew install node

# 或使用nvm管理多版本
brew install nvm
nvm install 20
nvm use 20
```

---

### 5. Docker

#### Linux (Ubuntu)
```bash
# 安装Docker
sudo apt update
sudo apt install -y docker.io docker-compose

# 启动Docker
sudo systemctl start docker
sudo systemctl enable docker

# 添加当前用户到docker组（无需sudo）
sudo usermod -aG docker $USER
newgrp docker
```

#### Linux (CentOS)
```bash
sudo yum install -y docker docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

#### Windows
```powershell
# 方法1: Winget
winget install Docker.DockerDesktop

# 方法2: Choco
choco install docker-desktop -y

# 启动Docker Desktop后使用
```

#### macOS
```bash
# Homebrew
brew install --cask docker

# 或下载Docker Desktop
# https://www.docker.com/products/docker-desktop/
```

---

### 6. Python

#### Linux
```bash
# Ubuntu/Debian
sudo apt install -y python3 python3-pip python3-venv

# CentOS/RHEL
sudo yum install -y python3 python3-pip
```

#### Windows
```powershell
# 方法1: Winget
winget install Python.Python.3.11

# 方法2: Choco
choco install python --version=3.11.0 -y

# 方法3: 下载安装包
# https://www.python.org/downloads/
```

#### macOS
```bash
# Homebrew
brew install python@3.11

# 或系统自带
python3 --version
```

---

## P2 - 可选工具

### 7. Neo4j (知识图谱数据库)

#### Linux
```bash
# 使用Docker（推荐）
docker run \
    --name neo4j \
    -p 7474:7474 -p 7687:7687 \
    -d \
    -e NEO4J_AUTH=neo4j/password \
    neo4j:latest

# 或直接安装
wget -O - https://debian.neo4j.org/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.org stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list
sudo apt-get update
sudo apt-get install -y neo4j
```

#### Windows
```powershell
# Docker
docker run --name neo4j -p 7474:7474 -p 7687:7687 -d -e NEO4J_AUTH=neo4j/password neo4j:latest

# 或下载安装包
# https://neo4j.com/download-center/
```

#### macOS
```bash
# Homebrew
brew install neo4j
brew services start neo4j

# 或Docker
docker run --name neo4j -p 7474:7474 -p 7687:7687 -d -e NEO4J_AUTH=neo4j/password neo4j:latest
```

---

### 8. Weaviate (向量数据库)

#### Linux/macOS/Windows
```bash
# Docker一键启动
docker run -d \
  --name weaviate \
  -p 8080:8080 \
  -p 50051:50051 \
  -e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true \
  -e ENABLE_MODULES=text2vec-transformers \
  -e TRANSFORMERS_INFERENCE_API=http://t2v-transformers:8080 \
  semitechnologies/weaviate:latest
```

---

### 9. Terraform (IaC)

#### Linux
```bash
# 官方脚本安装
wget https://apt.releases.hashicorp.com/PACKAGE_HASH
sudo apt-get update && sudo apt-get install terraform

# 或使用tfenv
git clone https://github.com/tfutils/tfenv.git ~/.tfenv
echo 'export PATH="$HOME/.tfenv/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
tfenv install latest
tfenv use latest
```

#### Windows
```powershell
# Winget
winget install HashiCorp.Terraform

# Choco
choco install terraform -y
```

#### macOS
```bash
brew install terraform
```

---

### 10. kubectl (Kubernetes)

#### Linux
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

#### Windows
```powershell
winget install Kubernetes.kubectl
```

#### macOS
```bash
brew install kubectl
```

---

### 11. Helm

#### Linux
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

#### Windows
```powershell
winget install Helm.Helm
```

#### macOS
```bash
brew install helm
```

---

## 自动安装脚本

### 一键安装脚本 (install_all.sh)

```bash
#!/bin/bash

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
    elif [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        echo "windows"
    else
        echo "unknown"
    fi
}

OS=$(detect_os)
echo "Detected OS: $OS"

# 根据操作系统选择安装方法
case $OS in
    "debian")
        echo "Installing for Debian/Ubuntu..."
        sudo apt update
        sudo apt install -y git curl build-essential

        # 安装cx
        curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh

        # 安装Node.js
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs

        # 安装Docker
        sudo apt install -y docker.io docker-compose
        ;;

    "rhel")
        echo "Installing for CentOS/RHEL..."
        sudo yum install -y git curl
        sudo yum install -y docker docker-compose
        sudo systemctl start docker
        sudo systemctl enable docker

        # 安装cx
        curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh

        # 安装Node.js
        curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
        sudo yum install -y nodejs
        ;;

    "macos")
        echo "Installing for macOS..."
        if command -v brew &> /dev/null; then
            brew install git node python@3.11 docker
        else
            echo "Please install Homebrew first: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        fi

        # 安装cx
        curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh
        ;;

    "windows")
        echo "Installing for Windows..."
        echo "Please run PowerShell as Administrator and execute:"
        echo "winget install Git.Git"
        echo "winget install OpenJS.NodeJS.LTS"
        echo "winget install Docker.DockerDesktop"
        echo "winget install ind-igo.cx"
        ;;

    *)
        echo "Unsupported OS. Please install manually."
        exit 1
        ;;
esac

echo "Installation complete!"
echo "Run 'cx --version' to verify cx installation"
echo "Run 'cx lang add rust typescript python' to add language support"
```

### Windows PowerShell脚本 (install_all.ps1)

```powershell
# Windows一键安装脚本
# 需要以管理员权限运行

Write-Host "Starting installation..." -ForegroundColor Green

# 安装winget（Windows 10 1803+自带）
# 检查是否需要安装

# 安装核心工具
Write-Host "Installing Git..." -ForegroundColor Cyan
winget install Git.Git --accept-source-agreements --accept-package-agreements

Write-Host "Installing Node.js..." -ForegroundColor Cyan
winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements

Write-Host "Installing Python..." -ForegroundColor Cyan
winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements

Write-Host "Installing Docker Desktop..." -ForegroundColor Cyan
winget install Docker.DockerDesktop --accept-source-agreements --accept-package-agreements

Write-Host "Installing cx..." -ForegroundColor Cyan
winget install ind-igo.cx --accept-source-agreements --accept-package-agreements

# 安装其他工具（可选）
Write-Host "Installing additional tools..." -ForegroundColor Cyan
winget install HashiCorp.Terraform --accept-source-agreements --accept-package-agreements
winget install Kubernetes.kubectl --accept-source-agreements --accept-package-agreements

Write-Host "Installation complete!" -ForegroundColor Green
Write-Host "Please restart your terminal and run: cx lang add rust typescript python" -ForegroundColor Yellow
```

---

## 验证安装

### 验证所有工具
```bash
#!/bin/bash

echo "Verifying installations..."

# Git
if command -v git &> /dev/null; then
    echo "✓ Git: $(git --version)"
else
    echo "✗ Git not found"
fi

# cx
if command -v cx &> /dev/null; then
    echo "✓ cx: $(cx --version)"
else
    echo "✗ cx not found"
fi

# Node.js
if command -v node &> /dev/null; then
    echo "✓ Node.js: $(node --version)"
else
    echo "✗ Node.js not found"
fi

# Python
if command -v python3 &> /dev/null; then
    echo "✓ Python: $(python3 --version)"
else
    echo "✗ Python not found"
fi

# Docker
if command -v docker &> /dev/null; then
    echo "✓ Docker: $(docker --version)"
else
    echo "✗ Docker not found"
fi

# Terraform
if command -v terraform &> /dev/null; then
    echo "✓ Terraform: $(terraform --version | head -n1)"
else
    echo "✗ Terraform not found"
fi
```

---

## 故障排除

### cx安装失败
```bash
# 检查依赖
which node
node --version

# 重新安装
curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh -s -- --debug

# 或手动编译
git clone https://github.com/ind-igo/cx.git
cd cx
cargo build --release
sudo mv target/release/cx /usr/local/bin/
```

### Docker权限问题 (Linux)
```bash
# 添加用户到docker组
sudo usermod -aG docker $USER

# 重新登录或
newgrp docker

# 验证
docker ps
```

### cx语言支持问题
```bash
# 查看可用语言
cx lang list-available

# 安装特定语言
cx lang add typescript

# 手动安装grammar
cx grammars install typescript
```

---

## 更新工具

### 更新cx
```bash
# 重新运行安装脚本
curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh

# 或使用cargo
cargo install cx-cli
```

### 更新所有工具 (Linux/macOS)
```bash
# Homebrew (macOS)
brew update && brew upgrade

# apt (Debian/Ubuntu)
sudo apt update && sudo apt upgrade

# yum (CentOS/RHEL)
sudo yum update
```

### 更新所有工具 (Windows)
```powershell
winget upgrade --all
```
