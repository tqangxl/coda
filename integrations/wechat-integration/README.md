# 微信集成模块 - WeChat Integration

## 概述

微信集成模块为AI Agent系统提供微信消息推送和接收能力，支持企业微信和个人微信Webhook通知。通过简单的配置即可将系统事件推送到微信，实现随时随地接收通知。

## 功能特性

- 企业微信Webhook推送
- 个人微信（通过第三方服务）
- Markdown格式消息支持
- 模板消息定制
- 消息优先级控制
- 定时汇总报告

## 目录结构

```
wechat-integration/
├── config.yaml          # 配置文件
├── webhook.py           # Webhook推送核心
├── templates/          # 消息模板
│   ├── task.md
│   ├── schedule.md
│   ├── daily_summary.md
│   ├── weekly_report.md
│   ├── alert.md
│   └── study.md
├── surrealdb_schema.surql  # 数据库表定义
└── README.md
```

## SurrealDB表定义

```sql
-- 微信通知配置表
DEFINE TABLE wechat_configs SCHEMAFULL;
DEFINE FIELD id ON wechat_configs TYPE string;
DEFINE FIELD user_id ON wechat_configs TYPE string;
DEFINE FIELD config_type ON wechat_configs TYPE string; -- enterprise/personal
DEFINE FIELD webhook_url ON wechat_configs TYPE string;
DEFINE FIELD enabled ON wechat_configs TYPE bool DEFAULT true;
DEFINE FIELD notify_events ON wechat_configs TYPE array;
DEFINE FIELD quiet_hours_start ON wechat_configs TYPE option<string>; -- "22:00"
DEFINE FIELD quiet_hours_end ON wechat_configs TYPE option<string>; -- "08:00"
DEFINE FIELD created_at ON wechat_configs TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON wechat_configs TYPE datetime;

-- 微信通知记录表
DEFINE TABLE wechat_notifications SCHEMAFULL;
DEFINE FIELD id ON wechat_notifications TYPE string;
DEFINE FIELD user_id ON wechat_notifications TYPE string;
DEFINE FIELD event_type ON wechat_notifications TYPE string;
DEFINE FIELD title ON wechat_notifications TYPE string;
DEFINE FIELD content ON wechat_notifications TYPE string;
DEFINE FIELD priority ON wechat_notifications TYPE string; -- high/normal/low
DEFINE FIELD status ON wechat_notifications TYPE string; -- pending/sent/failed
DEFINE FIELD sent_at ON wechat_notifications TYPE option<datetime>;
DEFINE FIELD error_message ON wechat_notifications TYPE option<string>;
DEFINE FIELD created_at ON wechat_notifications TYPE datetime DEFAULT time::now();

-- 索引
DEFINE INDEX idx_wechat_config_user ON wechat_configs FIELDS user_id;
DEFINE INDEX idx_wechat_notification_user ON wechat_notifications FIELDS user_id, created_at DESC;
DEFINE INDEX idx_wechat_notification_status ON wechat_notifications FIELDS status, created_at;
```

## 配置文件

```yaml
# config.yaml
wechat:
  # 企业微信配置
  enterprise:
    enabled: true
    webhook_url: "${WECHAT_ENTERPRISE_WEBHOOK_URL}"
    corp_id: "${WECHAT_CORP_ID}"
    agent_id: "${WECHAT_AGENT_ID}"

  # 个人微信配置（通过PushPlus或其他服务）
  personal:
    enabled: false
    service: "pushplus"  # pushplus/wxpush/custom
    token: "${WECHAT_PERSONAL_TOKEN}"

# 通知事件配置
notifications:
  # 事件类型：是否启用、优先级、是否汇总
  task_completed:
    enabled: true
    priority: "low"
    digest: true  # 汇总发送
    digest_interval: 30m  # 汇总间隔

  task_failed:
    enabled: true
    priority: "high"
    digest: false  # 立即发送

  daily_summary:
    enabled: true
    priority: "normal"
    time: "21:00"  # 发送时间

  weekly_report:
    enabled: true
    priority: "normal"
    time: "21:00"  # 周日发送

  study_reminder:
    enabled: true
    priority: "normal"
    times: ["08:00", "19:00"]

  schedule_reminder:
    enabled: true
    priority: "normal"
    advance_minutes: 15

  habit_reminder:
    enabled: true
    priority: "low"
    times: ["09:00", "14:00", "18:00"]

# 静默时段
quiet_hours:
  enabled: true
  start: "22:00"
  end: "08:00"
```

## Webhook推送核心

```python
# webhook.py
import httpx
import yaml
from datetime import datetime
from typing import Optional, List
import markdown

class WeChatWebhook:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)['wechat']
        self.session = httpx.AsyncClient(timeout=30.0)

    async def send_message(
        self,
        content: str,
        webhook_url: Optional[str] = None,
        msg_type: str = "markdown"
    ) -> dict:
        """发送微信消息"""
        webhook = webhook_url or self.config['enterprise']['webhook_url']

        if msg_type == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
        else:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }

        try:
            response = await self.session.post(webhook, json=payload)
            result = response.json()

            if result.get('errcode') == 0:
                return {"status": "success", "message": "消息发送成功"}
            else:
                return {"status": "failed", "error": result.get('errmsg')}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def send_task_notification(
        self,
        task_id: str,
        task_name: str,
        status: str,
        duration: Optional[str] = None,
        error: Optional[str] = None
    ):
        """发送任务通知"""
        if status == "completed":
            content = f"""## ✅ 任务完成

**任务**: {task_name}
**耗时**: {duration or 'N/A'}

---
_来自 AI Agent 系统_"""
        else:
            content = f"""## ❌ 任务失败

**任务**: {task_name}
**错误**: {error or '未知错误'}

---
_来自 AI Agent 系统_"""

        return await self.send_message(content)

    async def send_daily_summary(
        self,
        date: str,
        tasks_completed: int,
        tasks_failed: int,
        focus_hours: float,
        top_tasks: List[str]
    ):
        """发送每日汇总"""
        success_rate = tasks_completed / (tasks_completed + tasks_failed) * 100 if (tasks_completed + tasks_failed) > 0 else 0

        content = f"""## 📊 每日汇总 - {date}

### 📈 今日数据
- ✅ 完成任务: {tasks_completed}
- ❌ 失败任务: {tasks_failed}
- 📊 成功率: {success_rate:.1f}%
- ⏱️ 专注时长: {focus_hours}小时

### 🎯 重点任务
"""
        for task in top_tasks:
            content += f"- {task}\n"

        content += """
---
_来自 AI Agent 系统_"""

        return await self.send_message(content)

    async def send_study_reminder(
        self,
        student_name: str,
        subject: str,
        task_type: str,
        due_time: Optional[str] = None
    ):
        """发送学习提醒"""
        emoji = {"homework": "📝", "review": "🔄", "preview": "📖"}.get(task_type, "📚")

        content = f"""## 📚 学习提醒

**学生**: {student_name}
**科目**: {subject}
**类型**: {emoji} {task_type}

"""
        if due_time:
            content += f"**截止时间**: {due_time}\n"

        content += """
---
_来自 StudyManager_"""

        return await self.send_message(content)

    async def send_schedule_reminder(
        self,
        title: str,
        start_time: str,
        location: Optional[str] = None,
        notes: Optional[str] = None
    ):
        """发送日程提醒"""
        content = f"""## 📅 日程提醒

**事件**: {title}
**时间**: {start_time}
"""
        if location:
            content += f"**地点**: {location}\n"
        if notes:
            content += f"**备注**: {notes}\n"

        content += """
---
_来自 ScheduleManager_"""

        return await self.send_message(content)

    async def close(self):
        await self.session.aclose()
```

## 消息模板

### 任务完成模板

```markdown
## ✅ 任务完成

**任务名称**: {task_name}
**执行Agent**: {agent_id}
**开始时间**: {start_time}
**完成时间**: {end_time}
**总耗时**: {duration}

**输出摘要**:
{output_summary}

---
_来自 AI Agent 系统_
```

### 任务失败模板

```markdown
## ❌ 任务执行失败

**任务名称**: {task_name}
**执行Agent**: {agent_id}
**失败时间**: {failed_time}
**错误类型**: {error_type}

**错误信息**:
```
{error_message}
```

**建议操作**:
{recommendations}

---
_来自 AI Agent 系统_
```

### 每日汇总模板

```markdown
## 📊 每日汇总

**日期**: {date}
**Agent**: AI Agent 系统

### 📈 任务统计
| 类型 | 数量 | 成功率 |
|------|------|--------|
| 完成任务 | {completed} | {rate}% |
| 失败任务 | {failed} | - |
| 总计 | {total} | - |

### ⏱️ 时间统计
- 💼 运行时长: {runtime}
- 📝 平均任务时长: {avg_duration}
- 🎯 最高效时段: {peak_hour}

### 🔥 热门任务
{top_tasks}

### 💡 系统状态
- 🧠 内存使用: {memory}
- 📦 缓存命中率: {cache_hit_rate}%

---
_来自 AI Agent 系统_
```

### 每周报告模板

```markdown
## 📈 每周报告

**周期**: {week_start} ~ {week_end}

### 📊 周度概览
- 📝 总任务数: {total_tasks}
- ✅ 完成率: {completion_rate}%
- 📈 效率提升: {efficiency_improvement}%

### 🎯 重点成就
{achievements}

### ⚠️ 待改进项
{improvements}

### 📅 下周计划
{next_week_plan}

---
_来自 AI Agent 系统_
```

### 学习提醒模板

```markdown
## 📚 学习提醒

**学生**: {student_name}
**年级**: {grade}

### 📋 今日任务

#### 校内作业
{schoolwork}

#### 复习任务
{review_tasks}

#### 预习任务
{preview_tasks}

### ⏰ 重要截止
{deadlines}

### 🎯 今日目标
- 完成 {homework_count} 项作业
- 复习 {review_count} 个知识点
- 预习 {preview_count} 个新知识

---
_来自 StudyManager_
```

### 日程提醒模板

```markdown
## 📅 日程提醒

**时间**: {start_time}
**时长**: {duration}

### 📝 日程详情
**标题**: {title}
**类型**: {event_type}
**地点**: {location}

### 📋 日程描述
{description}

### 👥 参与者
{participants}

### 💡 建议
{notes}

---
_来自 ScheduleManager_
```

### 紧急告警模板

```markdown
## 🚨 紧急告警

**级别**: {severity}
**时间**: {timestamp}

### ⚠️ 告警详情
**告警类型**: {alert_type}
**告警内容**: {alert_content}

### 📊 影响范围
{impact}

### 🔧 建议措施
{recommendations}

### 📞 联系方式
{contact}

---
_来自 AI Agent 系统_
```

## Hook集成

```yaml
# hooks/wechat_hook.yaml
hook:
  name: "wechat_notification"
  namespace: "ai_agents_v2"

  triggers:
    - event: "task_completed"
      conditions:
        - field: "notify_enabled"
          operator: "eq"
          value: true
      actions:
        - type: "wechat"
          template: "task_completed"
          priority: "low"
          digest: true

    - event: "task_failed"
      conditions: []
      actions:
        - type: "wechat"
          template: "task_failed"
          priority: "high"
          digest: false

    - event: "daily_summary"
      conditions:
        - field: "time"
          operator: "eq"
          value: "21:00"
      actions:
        - type: "wechat"
          template: "daily_summary"
          priority: "normal"
          digest: false

    - event: "study_reminder"
      conditions: []
      actions:
        - type: "wechat"
          template: "study_reminder"
          priority: "normal"
          digest: false

    - event: "schedule_reminder"
      conditions: []
      actions:
        - type: "wechat"
          template: "schedule_reminder"
          priority: "normal"
          digest: false
```

## 使用示例

```python
# 使用示例
from webhook import WeChatWebhook

async def main():
    webhook = WeChatWebhook()

    # 发送任务完成通知
    await webhook.send_task_notification(
        task_id="task_001",
        task_name="生成报告",
        status="completed",
        duration="5分钟"
    )

    # 发送每日汇总
    await webhook.send_daily_summary(
        date="2024-01-15",
        tasks_completed=12,
        tasks_failed=1,
        focus_hours=4.5,
        top_tasks=["报告生成", "数据分析", "邮件处理"]
    )

    # 发送学习提醒
    await webhook.send_study_reminder(
        student_name="小明",
        subject="数学",
        task_type="homework",
        due_time="18:00"
    )

    await webhook.close()

# 或者使用Hook自动触发
# 在 workflow 配置中启用 wechat 通知
```

## 环境变量

```bash
# 企业微信
WECHAT_ENTERPRISE_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
WECHAT_CORP_ID=wwxxxx
WECHAT_AGENT_ID=1000001

# 个人微信 (PushPlus)
WECHAT_PERSONAL_TOKEN=your_pushplus_token
```

## 获取企业微信Webhook

1. 登录企业微信管理后台
2. 进入「应用管理」
3. 创建自建应用（或者使用「群机器人」）
4. 获取应用的 Webhook 地址
5. 将地址配置到环境变量或配置文件中

## 获取PushPlus Token（个人微信）

1. 访问 [PushPlus官网](http://pushplus.plus)
2. 登录后获取Token
3. 绑定微信后即可接收通知
