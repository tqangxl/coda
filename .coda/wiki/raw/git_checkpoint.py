"""
Coda V4.0 — Git Auto-Checkpoint Layer (Pillar 4)
Git 零泄露安全快照层: 操作前自动 Commit，操作后自动 Audit，保证 100% 可回滚。

设计原则:
  - Pre-Tool: 检测变更 → 自动 commit 临时快照块
  - Post-Tool: 自动 commit 修改结果 → 带 [Success/Fail] 标记
  - 实现全自动运行过程中的"后悔药"机制
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Coda.git")


class GitCheckpoint:
    """Git 自动快照管理器。"""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)
        self._is_git_repo = self._check_git_repo()

    def _check_git_repo(self) -> bool:
        """检测当前目录是否为 Git 仓库。"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.debug(f"Git repo check failed (this may be normal): {e}")
            return False
        except Exception as e:
            logger.warning(f"Git check error: {e}")
            return False

    def get_status(self) -> str:
        """获取当前 Git 状态快照 (Pillar 2: Dynamic Context)。"""
        if not self._is_git_repo:
            return "(not a git repo)"
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return result.stdout.strip() or "(clean)"
        except (subprocess.TimeoutExpired, Exception) as e:
            return f"(git error: {e})"

    def get_status_summary(self) -> str:
        """获取简短的 Git 状态摘要。"""
        if not self._is_git_repo:
            return "No Git"
        try:
            res = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            lines = res.stdout.strip().split("\n")
            if not lines or not lines[0]:
                return "Clean"
            return f"{len(lines)} files changed"
        except:
            return "Unknown"

    def get_current_hash(self) -> str:
        """获取当前 HEAD 的 commit hash。"""
        if not self._is_git_repo:
            return ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning(f"Failed to get git hash: {e}")
            return ""

    def has_changes(self) -> bool:
        """检测工作区是否有未提交的变更。"""
        if not self._is_git_repo:
            return False
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Failed to check git changes: {e}")
            return False

    def pre_tool_snapshot(self, tool_name: str) -> Optional[str]:
        """
        Pre-Tool Hook: 修改前快照。

        如果工作区有未提交的变更，强制进行一次 commit。
        返回 commit hash 或 None。
        """
        if not self._is_git_repo or not self.has_changes():
            return None

        msg = f"🤖 [Pre-Tool: {tool_name}] Auto-checkpoint before modification"
        return self._auto_commit(msg)

    def post_tool_snapshot(self, tool_name: str, success: bool = True) -> Optional[str]:
        """
        Post-Tool Hook: 修改后存档。

        记录工具执行的结果，并附带 [Success/Fail] 标记的提交说明。
        返回 commit hash 或 None。
        """
        if not self._is_git_repo or not self.has_changes():
            return None

        status_tag = "✅ Success" if success else "❌ Fail"
        msg = f"🤖 [{status_tag}] [Post-Tool: {tool_name}] Auto-audit after modification"
        return self._auto_commit(msg)

    def ceremonial_commit(self, summary: str) -> Optional[str]:
        """
        [V5.1] 仪式感提交：在对话结束时执行带有摘要的物理存档。
        
        该提交代表了本轮原子对话的认知终点。
        """
        if not self._is_git_repo:
            return None
            
        # 如果没有变动，也可以选择提交（带 --allow-empty），但通常我们只在有变动时记录
        if not self.has_changes():
            return None

        msg = f"🤖 [Ritual Commit] Summary: {summary}"
        return self._auto_commit(msg)

    def rollback_to(self, commit_hash: str) -> bool:
        """
        紧急回滚到指定的 commit。

        这是"后悔药"机制的核心: 即使大模型产生幻觉导致大面积代码损毁，
        我们也只需一键 git reset 即可回到任何一个工具执行前的瞬间。
        """
        if not self._is_git_repo:
            return False
        try:
            result = subprocess.run(
                ["git", "reset", "--hard", commit_hash],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info(f"Rolled back to {commit_hash}")
                return True
            logger.error(f"Rollback failed: {result.stderr}")
            return False
        except Exception as e:
            logger.error(f"Rollback error: {e}")
            return False

    def _auto_commit(self, message: str) -> Optional[str]:
        """执行 git add -A && git commit -m '...'。"""
        try:
            # Stage all
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.repo_path,
                capture_output=True,
                timeout=15,
            )
            # Commit
            result = subprocess.run(
                ["git", "commit", "-m", message, "--allow-empty"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                new_hash = self.get_current_hash()
                logger.info(f"Auto-committed: {new_hash} — {message}")
                return new_hash
            return None
        except Exception as e:
            logger.warning(f"Auto-commit failed: {e}")
            return None

    @property
    def is_available(self) -> bool:
        return self._is_git_repo
