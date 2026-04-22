# Hook Workflow - 会话结束后自动触发

## 触发条件

- 会话结束事件
- 用户主动结束
- 超时自动结束

## 执行流程

```yaml
workflow:
  name: "after_session_end"
  trigger: "session_ended"
  namespace: "ai_agents_v2"

  steps:
    1:
      name: "consolidate_session"
      description: "汇总会话内容"
      action: "learning.consolidate_session"
      timeout: 30s

    2:
      name: "save_summary"
      description: "保存会话摘要到数据库"
      action: "database.save_session_summary"
      timeout: 10s

    3:
      name: "update_profile"
      description: "更新用户画像"
      action: "profile.update_from_session"
      timeout: 20s

    4:
      name: "notify_summary"
      description: "发送会话摘要通知"
      action: "notification.send_summary"
      timeout: 15s
```

## SurrealDB存储

```sql
-- 会话摘要表
DEFINE TABLE session_summaries SCHEMAFULL;
DEFINE FIELD id ON session_summaries TYPE string;
DEFINE FIELD user_id ON session_summaries TYPE string;
DEFINE FIELD session_id ON session_summaries TYPE string;
DEFINE FIELD start_time ON session_summaries TYPE datetime;
DEFINE FIELD end_time ON session_summaries TYPE datetime;
DEFINE FIELD duration_seconds ON session_summaries TYPE int;
DEFINE FIELD summary ON session_summaries TYPE string;
DEFINE FIELD key_topics ON session_summaries TYPE array;
DEFINE FIELD tasks_completed ON session_summaries TYPE array;
DEFINE FIELD tasks_failed ON session_summaries TYPE array;
DEFINE FIELD agents_used ON session_summaries TYPE array;
DEFINE FIELD token_usage ON session_summaries TYPE object;
DEFINE FIELD user_feedback ON session_summaries TYPE option<string>;
DEFINE FIELD created_at ON session_summaries TYPE datetime DEFAULT time::now();

-- 会话历史表
DEFINE TABLE session_history SCHEMAFULL;
DEFINE FIELD id ON session_history TYPE string;
DEFINE FIELD session_id ON session_history TYPE string;
DEFINE FIELD user_id ON session_history TYPE string;
DEFINE FIELD messages ON session_history TYPE array;
DEFINE FIELD created_at ON session_history TYPE datetime DEFAULT time::now();

-- 索引
DEFINE INDEX idx_session_user ON session_summaries FIELDS user_id, created_at DESC;
DEFINE INDEX idx_session_time ON session_summaries FIELDS created_at DESC;
```

## SurrealQL脚本

```sql
-- 会话摘要保存脚本
DEFINE FUNCTION fn::save_session_summary($session_data: object) {
    LET $summary = {
        id: uuid(),
        user_id: $session_data.user_id,
        session_id: $session_data.session_id,
        start_time: $session_data.start_time,
        end_time: time::now(),
        duration_seconds: $session_data.duration,
        summary: $session_data.summary,
        key_topics: $session_data.topics,
        tasks_completed: $session_data.completed_tasks,
        tasks_failed: $session_data.failed_tasks,
        agents_used: $session_data.agents,
        token_usage: $session_data.token_usage
    };

    CREATE session_summaries CONTENT $summary;
    RETURN $summary;
};

-- 会话历史保存脚本
DEFINE FUNCTION fn::save_session_history($session_id: string, $messages: array) {
    LET $history = {
        id: uuid(),
        session_id: $session_id,
        user_id: (SELECT user_id FROM sessions WHERE id = $session_id)[0].user_id,
        messages: $messages
    };

    CREATE session_history CONTENT $history;
    RETURN $history;
};
```

## 执行示例

```python
async def on_session_end(session_data):
    """会话结束处理"""
    # 1. 汇总会话
    summary = await summarize_session(session_data)

    # 2. 保存摘要
    await db.query("fn::save_session_summary($data)", {
        "data": {
            "user_id": session_data["user_id"],
            "session_id": session_data["session_id"],
            "start_time": session_data["start_time"],
            "duration": session_data["duration"],
            "summary": summary["text"],
            "topics": summary["topics"],
            "completed_tasks": session_data["completed"],
            "failed_tasks": session_data["failed"],
            "agents": session_data["agents"],
            "token_usage": session_data["token_usage"]
        }
    })

    # 3. 发送通知
    if wechat_enabled:
        await send_wechat_notification({
            "type": "session_summary",
            "content": summary["text"]
        })
```
