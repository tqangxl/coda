"""
Coda V4.0 — Self-Healing Doctor (Pillar 24 & 30)
自我诊断与自愈系统: 环境损坏时 Agent 先自愈, 再干活。

设计参考: 原始 TS `screens/Doctor.tsx`
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Coda.doctor")


class DiagnosisResult:
    high_risk: bool

    def __init__(self, component: str, healthy: bool, detail: str = "", fix_available: bool = False, high_risk: bool = False):
        self.component = component
        self.healthy = healthy
        self.detail = detail
        self.fix_available = fix_available
        self.high_risk = high_risk

    def __str__(self) -> str:
        icon = "✅" if self.healthy else ("🔧" if self.fix_available else "❌")
        return f"{icon} {self.component}: {self.detail}"


class Doctor:
    """
    自我诊断与自愈系统。

    当运行环境出问题 (MCP 失联、Git 损坏、依赖缺失) 时,
    Agent 能够自主诊断并尝试修复, 保障无人值守任务的连续性。
    """

    def __init__(self, working_dir: str | Path):
        self.working_dir = Path(working_dir)

    def diagnose(self) -> list[DiagnosisResult]:
        """执行全面的环境诊断。"""
        results: list[DiagnosisResult] = []
        results.append(self._check_git())
        results.append(self._check_python())
        results.append(self._check_disk_space())
        results.append(self._check_network())
        return results

    def heal(self) -> list[str]:
        """
        尝试修复所有可修复的问题。

        返回已执行的修复操作列表。
        """
        actions: list[str] = []
        results = self.diagnose()

        for result in results:
            if not result.healthy and result.fix_available:
                try:
                    fixed = self._fix(result.component)
                    if fixed:
                        actions.append(f"Fixed: {result.component} — {fixed}")
                except Exception as e:
                    actions.append(f"Failed to fix {result.component}: {e}")

        return actions

    def _check_git(self) -> DiagnosisResult:
        """检查 Git 环境。"""
        try:
            result = subprocess.run(
                ["git", "status"],
                cwd=self.working_dir,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return DiagnosisResult("git", True, "Git repository healthy")
            return DiagnosisResult("git", False, result.stderr.strip()[:200], fix_available=True, high_risk=True)
        except FileNotFoundError:
            return DiagnosisResult("git", False, "Git not found in PATH", fix_available=False)
        except Exception as e:
            return DiagnosisResult("git", False, str(e)[:200], fix_available=True, high_risk=True)

    def _check_python(self) -> DiagnosisResult:
        """检查 Python 环境与关键依赖。"""
        missing = []
        for pkg in ["yaml", "aiohttp", "pydantic"]:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)

        if not missing:
            return DiagnosisResult("python", True, "All critical packages available")
        return DiagnosisResult(
            "python", False,
            f"Missing packages: {', '.join(missing)}",
            fix_available=True,
            high_risk=True,
        )

    def _check_disk_space(self) -> DiagnosisResult:
        """检查磁盘空间。"""
        try:
            usage = shutil.disk_usage(self.working_dir)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < 1.0:
                return DiagnosisResult(
                    "disk", False,
                    f"Only {free_gb:.1f}GB free",
                    fix_available=False,
                )
            return DiagnosisResult("disk", True, f"{free_gb:.1f}GB free")
        except Exception as e:
            return DiagnosisResult("disk", False, str(e), fix_available=False)

    def _check_network(self) -> DiagnosisResult:
        """检查网络连接。"""
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "3000", "8.8.8.8"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return DiagnosisResult("network", True, "Internet connectivity OK")
            return DiagnosisResult("network", False, "No internet", fix_available=False)
        except Exception:
            return DiagnosisResult("network", False, "Cannot check network", fix_available=False)

    def _fix(self, component: str) -> str | None:
        """尝试修复指定组件。"""
        if component == "git":
            return self._fix_git()
        elif component == "python":
            return self._fix_python()
        return None

    def _fix_git(self) -> str | None:
        """尝试修复 Git 问题。"""
        # 尝试重置 index
        try:
            subprocess.run(
                ["git", "reset"],
                cwd=self.working_dir,
                capture_output=True, timeout=10,
            )
            return "Executed git reset"
        except Exception as e:
            logger.error(f"Failed to fix Git: {e}")
            return f"Git fix exception: {e}"

    def _fix_python(self) -> str | None:
        """尝试安装缺失的 Python 包。"""
        try:
            result = subprocess.run(
                ["pip", "install", "-r", str(self.working_dir / "requirements.txt")],
                cwd=self.working_dir,
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return "Installed missing dependencies"
            return None
        except Exception as e:
            logger.error(f"Failed to fix Python dependencies: {e}")
            return f"Python fix exception: {e}"
