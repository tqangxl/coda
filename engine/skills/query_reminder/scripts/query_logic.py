"""
Query Reminder — 查询提醒脚本
从 SurrealDB 聚合查询今日日程、待办任务、系统任务。

用法:
  python query_logic.py              # 直接执行
  from scripts.query_logic import ... # Engine 内部导入

关键陷阱 (来自 LEARNINGS.md):
  - 用 AsyncSurreal, 不用 Surreal
  - 数据库名 agent_system, 不是 agent_system_v2
  - 永远 127.0.0.1, 不用 localhost
  - SDK 结果解析要做多路兼容
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger("Coda.skills.query_reminder")


class ReminderReport:
    """查询提醒结果的结构化容器。"""

    def __init__(self) -> None:
        self.timestamp: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.schedules: list[dict[str, Any]] = []
        self.active_tasks: list[dict[str, Any]] = []
        self.system_tasks: list[dict[str, Any]] = []
        self.recently_expired: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.db_online: bool = False

    @property
    def total_items(self) -> int:
        return len(self.schedules) + len(self.active_tasks) + len(self.system_tasks)

    def to_markdown(self) -> str:
        """输出结构化 Markdown 报告。"""
        lines: list[str] = []
        lines.append(f"### 🔍 今日提醒 ({self.timestamp})")
        lines.append("")

        if not self.db_online:
            lines.append("> ⚠️ SurrealDB 离线, 无法查询提醒。请运行 `startup.ps1 -Console`")
            return "\n".join(lines)

        lines.append("| 类型 | 状态 | 内容 | 优先级 |")
        lines.append("|:---|:---|:---|:---|")

        if self.schedules:
            for s in self.schedules:
                time_str = str(s.get("start_time", ""))
                if len(time_str) > 16:
                    time_str = time_str[11:16]
                
                content = s.get("title", "?")
                # 检查多阶段提醒
                reminders = s.get("reminders", [])
                next_stage = _get_next_stage(reminders)
                if next_stage:
                    content += f" <br>↳ **下一阶段**: {next_stage}"

                lines.append(f"| 📅 日程 | `{time_str}` | {content} | {s.get('priority', '-')} |")
        else:
            lines.append("| 📅 日程 | - | (暂无今日日程) | - |")

        if self.active_tasks:
            for t in self.active_tasks:
                status = str(t.get("status", "?"))[:4].upper()
                quad = str(t.get("quadrant", "2"))
                
                content = t.get("title", "?")
                # 检查多阶段提醒
                reminders = t.get("reminders", [])
                next_stage = _get_next_stage(reminders)
                if next_stage:
                    content += f" <br>↳ **下一阶段**: {next_stage}"

                lines.append(f"| ✅ 待办 | `{status}` | {content} | {quad} |")
        else:
            lines.append("| ✅ 待办 | - | (暂无待办任务) | - |")

        if self.system_tasks:
            for st in self.system_tasks:
                content = st.get("title", "?")
                
                # 检查多阶段提醒
                reminders = st.get("reminders", [])
                next_stage = _get_next_stage(reminders)
                if next_stage:
                    content += f" <br>↳ **下一阶段**: {next_stage}"

                lines.append(f"| ⚙️ 系统 | `{st.get('status', '?')}` | {content} | P{st.get('priority', 0)} |")
        else:
            lines.append("| ⚙️ 系统 | - | (暂无系统任务) | - |")

        # 最近过期 (2天内)
        if self.recently_expired:
            lines.append("")
            lines.append("#### 🕰️ 最近 2 天内过期")
            lines.append("| 类型 | 内容 | 过期点 |")
            lines.append("|:---|:---|:---|")
            for ex in self.recently_expired:
                # 兼容 tasks (due_date) 和 schedules (end_time)
                exp_time = ex.get("due_date") or ex.get("end_time")
                time_str = str(exp_time)[:16].replace("T", " ") if exp_time else "-"
                icon = "📅" if "end_time" in ex else "✅"
                lines.append(f"| {icon} 过期 | {ex.get('title', '?')} | `{time_str}` |")

        if self.errors:
            lines.append("")
            lines.append("**查询异常:**")
            for err in self.errors:
                lines.append(f"- ⚠️ {err}")

        return "\n".join(lines)


def _get_next_stage(reminders: list[dict[str, Any]]) -> str | None:
    """从提醒列表中寻找下一个即将到来的阶段。"""
    if not isinstance(reminders, list) or not reminders:
        return None
    
    now = datetime.now().astimezone() if datetime.now().tzinfo else datetime.now()
    future_reminders = []
    
    for r in reminders:
        r_time_val = r.get("time")
        if not r_time_val:
            continue
            
        try:
            r_time = None
            if isinstance(r_time_val, str):
                if 'T' in r_time_val:
                    # ISO 格式
                    r_time = datetime.fromisoformat(r_time_val.replace('Z', '+00:00'))
                else:
                    # 格式如 '2026-04-03 21:00'
                    r_time = datetime.strptime(r_time_val[:16], "%Y-%m-%d %H:%M")
            elif isinstance(r_time_val, datetime):
                r_time = r_time_val
            
            if r_time:
                # 统一转为 offset-naive 进行比较，或者统一为 aware
                now_compare = now
                if r_time.tzinfo and not now.tzinfo:
                    r_compare = r_time.replace(tzinfo=None)
                elif not r_time.tzinfo and now.tzinfo:
                    r_compare = r_time
                    now_compare = now.replace(tzinfo=None)
                else:
                    r_compare = r_time
                
                if r_compare > now_compare:
                    future_reminders.append((r_time, r.get("label", "提醒")))
        except Exception as e:
            logger.debug(f"Failed to parse reminder time {r_time_val}: {e}")
            continue
    
    if not future_reminders:
        return None
        
    future_reminders.sort(key=lambda x: x[0])
    next_r = future_reminders[0]
    return f"`{next_r[0].strftime('%m-%d %H:%M')}` - **{next_r[1]}**"


def _extract_result(response: Any) -> list[dict[str, Any]]:
    """
    从 SurrealDB 响应中提取结果列表 (兼容不同版本 SDK)。

    多路兼容:
    - Wrapped: [{"status": "OK", "result": [{...}]}]
    - Flat: [{"id": "xxx", ...}]
    - Nested: [[{...}]]
    """
    if isinstance(response, list) and len(response) > 0:
        first = response[0]
        if isinstance(first, dict) and "result" in first:
            result = first["result"]
            return result if isinstance(result, list) else []
        elif isinstance(first, dict) and "id" in first:
            return response  # type: ignore[return-value]
        elif isinstance(first, list):
            return first
    elif isinstance(response, dict) and "result" in response:
        result = response["result"]
        return result if isinstance(result, list) else []
    return []


async def query_reminders(
    url: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> ReminderReport:
    """
    主查询函数: 连接 SurrealDB, 聚合查询三张表。

    返回 ReminderReport 对象, 即使 DB 不可达也不抛异常。
    """
    report = ReminderReport()

    url = url or os.getenv("SURREALDB_URL", "ws://127.0.0.1:11001/rpc")
    user = user or os.getenv("SURREALDB_USER", "root")
    password = password or os.getenv("SURREALDB_PASS", "AgentSecurePass2026")

    try:
        from surrealdb import AsyncSurreal
    except ImportError:
        report.errors.append("surrealdb 包未安装")
        return report

    db = AsyncSurreal(url)
    try:
        await db.connect(url)
        await db.signin({"user": user, "pass": password})
        await db.use("ai_agents_v2", "agent_system")
        report.db_online = True
    except Exception as e:
        report.errors.append(f"DB 连接失败: {e}")
        return report

    try:
        # 1. 今日日程 (统一后的表名)
        try:
            # 自动置为已完成或过期 (可选，取决于业务逻辑，此处先标记过期)
            await db.query(
                "UPDATE schedules SET status = 'expired' "
                "WHERE status = 'scheduled' "
                "AND end_time < time::now()"
            )
            
            result = await db.query(
                "SELECT * FROM schedules "
                "WHERE start_time >= time::floor(time::now(), 1d) "
                "AND start_time < time::floor(time::now() + 1d, 1d) "
                "AND status != 'expired' "
                "ORDER BY start_time ASC"
            )
            report.schedules = _extract_result(result)
        except Exception as e:
            if "does not exist" not in str(e):
                report.errors.append(f"日程查询: {e}")


        # 3. 核心任务查询 (自动过期 + 多阶段提醒 + 过滤)
        try:
            # 先自动将过期任务标记为 expired (包含待办和进行中任务)
            await db.query(
                "UPDATE tasks SET status = 'expired' "
                "WHERE status IN ['pending', 'todo', 'in_progress'] "
                "AND due_date IS NOT NONE "
                "AND due_date < time::now()"
            )
            # 再查询真正活跃的任务 (包括之前 v2_tasks 的 todo，现在都在 status='pending' 且 quadrant 为 1-4)
            result = await db.query(
                "SELECT * FROM tasks "
                "WHERE status NOT IN ['completed', 'failed', 'expired'] "
                "ORDER BY quadrant ASC, priority DESC, created_at DESC"
            )
            
            # 我们将 tasks 划分为“待办”和“系统通知”来保持 UI 兼容
            all_tasks = _extract_result(result)
            report.active_tasks = [t for t in all_tasks if (t.get("quadrant") or 2) <= 4 and t.get("category") != "system"]
            report.system_tasks = [t for t in all_tasks if t not in report.active_tasks or t.get("category") == "system"]

            # 4. 最近过期查询 (2天内)
            try:
                # 任务
                ex_tasks_res = await db.query(
                    "SELECT * FROM tasks WHERE status = 'expired' AND due_date >= time::now() - 2d ORDER BY due_date DESC"
                )
                # 日程
                ex_sched_res = await db.query(
                    "SELECT * FROM schedules WHERE status = 'expired' AND end_time >= time::now() - 2d ORDER BY end_time DESC"
                )
                report.recently_expired = _extract_result(ex_tasks_res) + _extract_result(ex_sched_res)
            except Exception as e:
                report.errors.append(f"最近过期查询失败: {e}")
        except Exception as e:
            if "does not exist" not in str(e):
                report.errors.append(f"核心任务查询: {e}")

    finally:
        await db.close()

    return report


async def main() -> None:
    """独立运行入口。"""
    report = await query_reminders()
    print(report.to_markdown())


if __name__ == "__main__":
    asyncio.run(main())
