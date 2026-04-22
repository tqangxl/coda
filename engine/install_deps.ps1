# Coda Engine V7.0 Dependency Installer
# Optimized for Python 3.14 (April 2026)

$ErrorActionPreference = "Stop"
Write-Host "🚀 Starting dependency installation for Python 3.14..." -ForegroundColor Cyan

# 1. 确保 pip 是最新的
Write-Host "📦 Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

# 2. 安装 ModelScope [framework]
# 这会自动拉取 torch, transformers, datasets 等
Write-Host "🤖 Installing ModelScope [framework]..." -ForegroundColor Yellow
pip install --upgrade "modelscope[framework]"

# 3. 安装其他辅助依赖
Write-Host "📚 Installing auxiliary dependencies..." -ForegroundColor Yellow
pip install --upgrade sentence-transformers scikit-learn tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-bash

Write-Host "✅ Dependency installation complete!" -ForegroundColor Green
