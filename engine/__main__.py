"""
Coda V4.0 — Module Entry Point

Usage:
  python -m engine "帮我分析这个项目"
  python -m engine --interactive
  python -m engine --model claude-sonnet-4 "重构 main.py"
"""
from engine.cli import entry
entry()
