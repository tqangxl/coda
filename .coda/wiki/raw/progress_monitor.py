import logging
from pathlib import Path
from typing import Mapping, Sequence, Any
from .base_types import ToolCall, ProgressReport, TerminationSignal

logger = logging.getLogger("Coda.htas")

class ProgressMonitor:
    """
    HTAS 进度监控器 (Pillar 31)。
    由物理侧效应、逻辑成功与信息增量三维度评估任务收敛度。
    """
    
    def __init__(self):
        self._modified_files: set[str] = set()
        self._executed_commands: set[str] = set()
        self._stagnation_count: int = 0
        self._last_side_effect_iter: int = 0
        self._last_total_side_effects: int = 0
        self._last_total_successes: int = 0

    @property
    def modified_files(self) -> set[str]:
        return self._modified_files

    def compute_line_delta(self, path: str, old_content: str, new_content: str) -> dict[str, Any]:
        """
        计算物理层面的行级差异 (Pillar 36)。
        返回包含变更行号范围、操作类型及摘要的字典。
        """
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        
        # 极简 Diff 实现 (真实生产环境建议使用 difflib)
        import difflib
        diff = list(difflib.unified_diff(old_lines, new_lines, n=0))
        
        changed_ranges = []
        # 解析 unified diff 格式: @@ -line,count +line,count @@
        for line in diff:
            if line.startswith("@@"):
                parts = line.split(" ")
                if len(parts) >= 3:
                    new_range = parts[2].replace("+", "")
                    changed_ranges.append(new_range)
        
        return {
            "path": path,
            "ranges": changed_ranges,
            "summary": f"Modified {len(changed_ranges)} segments in {Path(path).name}"
        }

    def audit(self, iteration: int, history: list[dict[str, Any]]) -> ProgressReport:
        """
        审计当前历史轨迹，识别物理变动与进展停滞。
        升级版：集成行级物理审计。
        """
        side_effects = 0
        logical_successes = 0
        info_gain = 0.0
        
        # 扫描历史记录中的工具调用与结果
        for m in history:
            role = str(m.get("role", "")).lower()
            content = str(m.get("content", ""))
            
            if role == "tool":
                tool_name = str(m.get("name", "unknown"))
                
                # 1. 物理侧效应 (Side Effects)
                if tool_name in ("write_file", "replace_file_content", "edit_file", "multi_replace_file_content", "write_to_file"):
                    side_effects += 1
                
                # 2. 逻辑成功 (Logical Successes)
                if tool_name == "run_command" and "EXIT CODE: 0" in content:
                    logical_successes += 1
                
                # 3. 信息增量 (Information Gain)
                if tool_name in ("read_file", "view_file", "grep_search", "list_dir"):
                    if len(content) > 50:
                        info_gain += 0.2
        
        # [HTAS Logic] 检测“新”变动
        has_new_progress = False
        if side_effects > self._last_total_side_effects:
            has_new_progress = True
        if logical_successes > self._last_total_successes:
            has_new_progress = True
            
        if has_new_progress:
            self._stagnation_count = 0
            self._last_side_effect_iter = iteration
        else:
            self._stagnation_count += 1
            
        # 更新状态缓存
        self._last_total_side_effects = side_effects
        self._last_total_successes = logical_successes
            
        report = ProgressReport(
            iteration=iteration,
            physical_side_effects=side_effects,
            logical_successes=logical_successes,
            information_density=info_gain,
            stagnation_count=self._stagnation_count,
        )
        
        if self._stagnation_count >= 3:
            report.is_stuck = True
            report.verdict = TerminationSignal.STALEMATE
            report.reason = f"HTAS Audit: {self._stagnation_count} consecutive steps without new physical progress."
            
        return report
