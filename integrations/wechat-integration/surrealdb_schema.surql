-- WeChat Integration SurrealDB Schema
-- 微信集成模块数据库表定义

-- =============================================
-- 微信通知配置表
-- =============================================
DEFINE TABLE wechat_configs SCHEMAFULL;
DEFINE FIELD id ON wechat_configs TYPE string;
DEFINE FIELD user_id ON wechat_configs TYPE string;
DEFINE FIELD config_type ON wechat_configs TYPE string; -- enterprise/personal
DEFINE FIELD webhook_url ON wechat_configs TYPE string;
DEFINE FIELD enabled ON wechat_configs TYPE bool DEFAULT true;
DEFINE FIELD notify_events ON wechat_configs TYPE array;
DEFINE FIELD priority_filter ON wechat_configs TYPE array; -- high/normal/low
DEFINE FIELD quiet_hours_enabled ON wechat_configs TYPE bool DEFAULT false;
DEFINE FIELD quiet_hours_start ON wechat_configs TYPE option<string>;
DEFINE FIELD quiet_hours_end ON wechat_configs TYPE option<string>;
DEFINE FIELD created_at ON wechat_configs TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON wechat_configs TYPE datetime;

-- =============================================
-- 微信通知记录表
-- =============================================
DEFINE TABLE wechat_notifications SCHEMAFULL;
DEFINE FIELD id ON wechat_notifications TYPE string;
DEFINE FIELD user_id ON wechat_notifications TYPE string;
DEFINE FIELD event_type ON wechat_notifications TYPE string;
DEFINE FIELD template_name ON wechat_notifications TYPE string;
DEFINE FIELD title ON wechat_notifications TYPE string;
DEFINE FIELD content ON wechat_notifications TYPE string;
DEFINE FIELD rendered_content ON wechat_notifications TYPE string;
DEFINE FIELD priority ON wechat_notifications TYPE string; -- high/normal/low
DEFINE FIELD status ON wechat_notifications TYPE string; -- pending/sending/sent/failed
DEFINE FIELD sent_at ON wechat_notifications TYPE option<datetime>;
DEFINE FIELD error_code ON wechat_notifications TYPE option<int>;
DEFINE FIELD error_message ON wechat_notifications TYPE option<string>;
DEFINE FIELD retry_count ON wechat_notifications TYPE int DEFAULT 0;
DEFINE FIELD created_at ON wechat_notifications TYPE datetime DEFAULT time::now();

-- =============================================
-- 通知模板表
-- =============================================
DEFINE TABLE wechat_templates SCHEMAFULL;
DEFINE FIELD id ON wechat_templates TYPE string;
DEFINE FIELD name ON wechat_templates TYPE string;
DEFINE FIELD event_type ON wechat_templates TYPE string;
DEFINE FIELD template_content ON wechat_templates TYPE string;
DEFINE FIELD variables ON wechat_templates TYPE array;
DEFINE FIELD is_markdown ON wechat_templates TYPE bool DEFAULT true;
DEFINE FIELD priority ON wechat_templates TYPE string DEFAULT 'normal';
DEFINE FIELD created_at ON wechat_templates TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON wechat_templates TYPE datetime;

-- =============================================
-- 消息汇总队列表
-- =============================================
DEFINE TABLE wechat_digest_queue SCHEMAFULL;
DEFINE FIELD id ON wechat_digest_queue TYPE string;
DEFINE FIELD user_id ON wechat_digest_queue TYPE string;
DEFINE FIELD event_type ON wechat_digest_queue TYPE string;
DEFINE FIELD messages ON wechat_digest_queue TYPE array;
DEFINE FIELD last_update ON wechat_digest_queue TYPE datetime DEFAULT time::now();
DEFINE FIELD created_at ON wechat_digest_queue TYPE datetime DEFAULT time::now();

-- =============================================
-- 索引定义
-- =============================================
DEFINE INDEX idx_wechat_config_user ON wechat_configs FIELDS user_id;
DEFINE INDEX idx_wechat_config_type ON wechat_configs FIELDS user_id, config_type;
DEFINE INDEX idx_wechat_notification_user ON wechat_notifications FIELDS user_id, created_at DESC;
DEFINE INDEX idx_wechat_notification_status ON wechat_notifications FIELDS status, created_at;
DEFINE INDEX idx_wechat_notification_event ON wechat_notifications FIELDS user_id, event_type;
DEFINE INDEX idx_wechat_template_name ON wechat_templates FIELDS name UNIQUE;
DEFINE INDEX idx_wechat_template_event ON wechat_templates FIELDS event_type;
DEFINE INDEX idx_wechat_digest_user ON wechat_digest_queue FIELDS user_id, event_type;

-- =============================================
-- 内置消息模板
-- =============================================
CREATE wechat_templates CONTENT [
    {
        id: uuid(),
        name: "task_completed",
        event_type: "task_completed",
        template_content: "## ✅ 任务完成\n\n**任务**: {task_name}\n**Agent**: {agent_id}\n**耗时**: {duration}\n\n{output_summary}\n\n---\n_来自 AI Agent 系统_",
        variables: ["task_name", "agent_id", "duration", "output_summary"],
        is_markdown: true,
        priority: "low"
    },
    {
        id: uuid(),
        name: "task_failed",
        event_type: "task_failed",
        template_content: "## ❌ 任务失败\n\n**任务**: {task_name}\n**Agent**: {agent_id}\n**错误**: {error_message}\n\n**建议**: {recommendations}\n\n---\n_来自 AI Agent 系统_",
        variables: ["task_name", "agent_id", "error_message", "recommendations"],
        is_markdown: true,
        priority: "high"
    },
    {
        id: uuid(),
        name: "daily_summary",
        event_type: "daily_summary",
        template_content: "## 📊 每日汇总 - {date}\n\n### 📈 今日数据\n- ✅ 完成: {completed}\n- ❌ 失败: {failed}\n- 📊 成功率: {success_rate}%\n\n### ⏱️ 统计\n- 💼 运行时长: {runtime}\n- 🎯 最高效时段: {peak_hour}\n\n### 🔥 热门任务\n{top_tasks}\n\n---\n_来自 AI Agent 系统_",
        variables: ["date", "completed", "failed", "success_rate", "runtime", "peak_hour", "top_tasks"],
        is_markdown: true,
        priority: "normal"
    },
    {
        id: uuid(),
        name: "weekly_report",
        event_type: "weekly_report",
        template_content: "## 📈 每周报告\n\n**周期**: {week_start} ~ {week_end}\n\n### 📊 周度概览\n- 📝 总任务数: {total_tasks}\n- ✅ 完成率: {completion_rate}%\n- 📈 效率提升: {efficiency_change}%\n\n### 🎯 重点成就\n{achievements}\n\n### ⚠️ 待改进项\n{improvements}\n\n### 📅 下周计划\n{next_week_plan}\n\n---\n_来自 AI Agent 系统_",
        variables: ["week_start", "week_end", "total_tasks", "completion_rate", "efficiency_change", "achievements", "improvements", "next_week_plan"],
        is_markdown: true,
        priority: "normal"
    },
    {
        id: uuid(),
        name: "study_reminder",
        event_type: "study_reminder",
        template_content: "## 📚 学习提醒\n\n**学生**: {student_name}\n**科目**: {subject}\n**类型**: {task_type}\n\n### 📋 今日任务\n{tasks}\n\n### ⏰ 截止时间\n{due_time}\n\n### 🎯 今日目标\n- 完成 {homework_count} 项作业\n- 复习 {review_count} 个知识点\n\n---\n_来自 StudyManager_",
        variables: ["student_name", "subject", "task_type", "tasks", "due_time", "homework_count", "review_count"],
        is_markdown: true,
        priority: "normal"
    },
    {
        id: uuid(),
        name: "schedule_reminder",
        event_type: "schedule_reminder",
        template_content: "## 📅 日程提醒\n\n**事件**: {title}\n**时间**: {start_time}\n**时长**: {duration}\n\n**地点**: {location}\n\n{description}\n\n---\n_来自 ScheduleManager_",
        variables: ["title", "start_time", "duration", "location", "description"],
        is_markdown: true,
        priority: "normal"
    },
    {
        id: uuid(),
        name: "habit_reminder",
        event_type: "habit_reminder",
        template_content: "## 🎯 习惯提醒\n\n**习惯**: {habit_name}\n\n当前连续: {current_streak} 天\n最长记录: {longest_streak} 天\n\n💪 坚持就是胜利！\n\n---\n_来自 ScheduleManager_",
        variables: ["habit_name", "current_streak", "longest_streak"],
        is_markdown: true,
        priority: "low"
    },
    {
        id: uuid(),
        name: "system_alert",
        event_type: "system_alert",
        template_content: "## 🚨 系统告警\n\n**级别**: {severity}\n**类型**: {alert_type}\n**时间**: {timestamp}\n\n### ⚠️ 详情\n{alert_content}\n\n### 🔧 建议\n{recommendations}\n\n---\n_来自 AI Agent 系统_",
        variables: ["severity", "alert_type", "timestamp", "alert_content", "recommendations"],
        is_markdown: true,
        priority: "high"
    }
];

-- =============================================
-- 初始化用户通知配置
-- =============================================
DEFINE FUNCTION fn::init_user_wechat_config($user_id: string, $webhook_url: string, $config_type: string) {
    LET $config = {
        id: uuid(),
        user_id: $user_id,
        config_type: $config_type,
        webhook_url: $webhook_url,
        enabled: true,
        notify_events: ["task_completed", "task_failed", "daily_summary", "weekly_report"],
        priority_filter: ["high", "normal", "low"],
        quiet_hours_enabled: true,
        quiet_hours_start: "22:00",
        quiet_hours_end: "08:00"
    };

    CREATE wechat_configs CONTENT $config;
    RETURN $config;
};

-- =============================================
-- 检查是否在静默时段
-- =============================================
DEFINE FUNCTION fn::is_quiet_hours($user_id: string) {
    LET $config = (SELECT * FROM wechat_configs WHERE user_id = $user_id LIMIT 1)[0];

    IF !$config OR !$config.quiet_hours_enabled {
        RETURN false;
    }

    LET $now = time::now();
    LET $current_hour = string::slice(string::format("{}", $now), 11, 16); -- "HH:MM" format

    LET $start = $config.quiet_hours_start;
    LET $end = $config.quiet_hours_end;

    -- 跨天情况（如22:00-08:00）
    IF $start > $end {
        RETURN $current_hour >= $start OR $current_hour < $end;
    }

    RETURN $current_hour >= $start AND $current_hour < $end;
};

-- =============================================
-- 发送微信通知（带静默时段检查）
-- =============================================
DEFINE FUNCTION fn::send_wechat_notification($notification: object) {
    -- 检查静默时段（紧急通知除外）
    IF $notification.priority != 'high' AND fn::is_quiet_hours($notification.user_id) {
        RETURN {
            status: 'skipped',
            reason: 'quiet_hours'
        };
    }

    -- 创建通知记录
    LET $record = {
        id: uuid(),
        user_id: $notification.user_id,
        event_type: $notification.event_type,
        template_name: $notification.template_name,
        title: $notification.title,
        content: $notification.content,
        rendered_content: $notification.rendered_content,
        priority: $notification.priority,
        status: 'pending',
        created_at: time::now()
    };

    CREATE wechat_notifications CONTENT $record;

    RETURN {
        status: 'queued',
        notification_id: $record.id
    };
};

-- =============================================
-- 添加到汇总队列
-- =============================================
DEFINE FUNCTION fn::add_to_digest_queue($user_id: string, $event_type: string, $message: object) {
    LET $existing = (SELECT * FROM wechat_digest_queue
        WHERE user_id = $user_id AND event_type = $event_type
        AND last_update > time::now() - 30m
        LIMIT 1)[0];

    IF $existing {
        LET $updated_messages = array::combine($existing.messages, [$message]);
        UPDATE wechat_digest_queue SET {
            messages: $updated_messages,
            last_update: time::now()
        } WHERE id = $existing.id;
        RETURN { status: 'updated', queue_id: $existing.id };
    } ELSE {
        LET $queue = {
            id: uuid(),
            user_id: $user_id,
            event_type: $event_type,
            messages: [$message],
            last_update: time::now(),
            created_at: time::now()
        };
        CREATE wechat_digest_queue CONTENT $queue;
        RETURN { status: 'created', queue_id: $queue.id };
    }
};

-- =============================================
-- 获取并清空汇总队列
-- =============================================
DEFINE FUNCTION fn::flush_digest_queue($user_id: string, $event_type: string) {
    LET $queue = (SELECT * FROM wechat_digest_queue
        WHERE user_id = $user_id AND event_type = $event_type
        LIMIT 1)[0];

    IF $queue {
        DELETE FROM wechat_digest_queue WHERE id = $queue.id;
        RETURN {
            status: 'flushed',
            messages: $queue.messages
        };
    }

    RETURN {
        status: 'empty',
        messages: []
    };
};
