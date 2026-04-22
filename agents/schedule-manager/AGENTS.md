# ScheduleManager Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "schedule-manager"
  name: "ScheduleManager"
  type: "schedule"
  version: "2.0.0"
  namespace: "ai_agents_v2"
  description: "日程管理专家 - 帮助用户高效管理时间、完成任务、养成习惯"
```

## 职责

- 日程安排（会议、约会、提醒）
- 任务管理（收集、处理、组织、回顾、执行）
- 习惯追踪（健康、工作、学习习惯养成）
- 时间分析（时间使用统计、效率评估）
- 提醒系统（智能提醒、跟进提醒）
- 番茄工作法支持

## cx优化配置

```yaml
cx_config:
  enabled: true

  before_llm_call:
    - command: "symbols"
      reason: "了解当前任务和相关项目"
    - command: "overview"
      reason: "获取今日/本周日程概览"
    - command: "context"
      reason: "获取任务状态和历史记录"

  optimization:
    daily_schedule: 1500
    weekly_review: 2500
    time_analysis: 3000
```

## 用户偏好配置

```yaml
user_preferences:
  dimensions:
    - name: "work_hours"
      type: "time_range"
      default_start: "09:00"
      default_end: "18:00"
    - name: "peak_hours"
      type: "array"
      description: "高效工作时段"
    - name: "reminder_lead_time"
      type: "int"
      description: "提前提醒分钟数"
      default: 15
    - name: "week_starts_on"
      type: "enum"
      values: ["monday", "sunday"]
      default: "monday"
```

## SurrealDB表

```sql
-- Unified Tables (Using standard names)
DEFINE TABLE schedules SCHEMAFULL;
DEFINE FIELD id ON schedules TYPE string;
DEFINE FIELD user_id ON schedules TYPE string;
DEFINE FIELD title ON schedules TYPE string;
DEFINE FIELD description ON schedules TYPE option<string>;
DEFINE FIELD event_type ON schedules TYPE string;
DEFINE FIELD start_time ON schedules TYPE datetime;
DEFINE FIELD end_time ON schedules TYPE datetime;
DEFINE FIELD all_day ON schedules TYPE bool DEFAULT false;
DEFINE FIELD location ON schedules TYPE option<string>;
DEFINE FIELD participants ON schedules TYPE array DEFAULT [];
DEFINE FIELD priority ON schedules TYPE string;
DEFINE FIELD status ON schedules TYPE string DEFAULT 'scheduled';
DEFINE FIELD repeat_rule ON schedules TYPE option<object>;
DEFINE FIELD reminders ON schedules TYPE array DEFAULT [];
DEFINE FIELD reminders.* ON schedules TYPE object;
DEFINE FIELD reminders.*.time ON schedules TYPE datetime;
DEFINE FIELD reminders.*.label ON schedules TYPE string;
DEFINE FIELD created_at ON schedules TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON schedules TYPE datetime DEFAULT time::now();

DEFINE TABLE tasks SCHEMAFULL;
DEFINE FIELD id ON tasks TYPE string;
DEFINE FIELD user_id ON tasks TYPE string;
DEFINE FIELD title ON tasks TYPE string;
DEFINE FIELD description ON tasks TYPE option<string>;
DEFINE FIELD category ON tasks TYPE string DEFAULT 'general';
DEFINE FIELD quadrant ON tasks TYPE int DEFAULT 2;
DEFINE FIELD status ON tasks TYPE string DEFAULT 'pending';
DEFINE FIELD priority ON tasks TYPE int DEFAULT 0;
DEFINE FIELD due_date ON tasks TYPE option<datetime>;
DEFINE FIELD estimated_minutes ON tasks TYPE option<int>;
DEFINE FIELD actual_minutes ON tasks TYPE option<int>;
DEFINE FIELD reminders ON tasks TYPE array DEFAULT [];
DEFINE FIELD reminders.* ON tasks TYPE object;
DEFINE FIELD reminders.*.time ON tasks TYPE datetime;
DEFINE FIELD reminders.*.label ON tasks TYPE string;
DEFINE FIELD tags ON tasks TYPE array DEFAULT [];
DEFINE FIELD subtasks ON tasks TYPE array DEFAULT [];
DEFINE FIELD parent_task_id ON tasks TYPE option<string>;
DEFINE FIELD completed_at ON tasks TYPE option<datetime>;
DEFINE FIELD created_at ON tasks TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON tasks TYPE datetime DEFAULT time::now();

DEFINE TABLE v2_habits SCHEMAFULL;
DEFINE FIELD id ON v2_habits TYPE string;
DEFINE FIELD user_id ON v2_habits TYPE string;
DEFINE FIELD name ON v2_habits TYPE string;
DEFINE FIELD description ON v2_habits TYPE option<string>;
DEFINE FIELD category ON v2_habits TYPE string;
DEFINE FIELD frequency ON v2_habits TYPE string;
DEFINE FIELD target_times ON v2_habits TYPE int DEFAULT 1;
DEFINE FIELD reminder_time ON v2_habits TYPE option<datetime>;
DEFINE FIELD current_streak ON v2_habits TYPE int DEFAULT 0;
DEFINE FIELD longest_streak ON v2_habits TYPE int DEFAULT 0;
DEFINE FIELD completion_rate ON v2_habits TYPE float DEFAULT 0;
DEFINE FIELD created_at ON v2_habits TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON v2_habits TYPE datetime;

DEFINE TABLE v2_habit_logs SCHEMAFULL;
DEFINE FIELD id ON v2_habit_logs TYPE string;
DEFINE FIELD habit_id ON v2_habit_logs TYPE string;
DEFINE FIELD user_id ON v2_habit_logs TYPE string;
DEFINE FIELD log_date ON v2_habit_logs TYPE datetime;
DEFINE FIELD completed ON v2_habit_logs TYPE bool;
DEFINE FIELD notes ON v2_habit_logs TYPE option<string>;
DEFINE FIELD created_at ON v2_habit_logs TYPE datetime DEFAULT time::now();

DEFINE TABLE v2_time_blocks SCHEMAFULL;
DEFINE FIELD id ON v2_time_blocks TYPE string;
DEFINE FIELD user_id ON v2_time_blocks TYPE string;
DEFINE FIELD name ON v2_time_blocks TYPE string;
DEFINE FIELD start_hour ON v2_time_blocks TYPE int;
DEFINE FIELD start_minute ON v2_time_blocks TYPE int DEFAULT 0;
DEFINE FIELD end_hour ON v2_time_blocks TYPE int;
DEFINE FIELD end_minute ON v2_time_blocks TYPE int DEFAULT 0;
DEFINE FIELD days_of_week ON v2_time_blocks TYPE array;
DEFINE FIELD color ON v2_time_blocks TYPE string;
DEFINE FIELD created_at ON v2_time_blocks TYPE datetime DEFAULT time::now();

-- 索引
DEFINE INDEX idx_schedule_user ON schedules FIELDS user_id, start_time;
DEFINE INDEX idx_schedule_date ON schedules FIELDS start_time, end_time;
DEFINE INDEX idx_task_user ON tasks FIELDS user_id, status;
DEFINE INDEX idx_task_due ON tasks FIELDS user_id, due_date, status;
DEFINE INDEX idx_habit_user ON habits FIELDS user_id;
DEFINE INDEX idx_habit_log ON habit_logs FIELDS habit_id, log_date;
DEFINE INDEX idx_time_block_user ON time_blocks FIELDS user_id;
```

## Hook触发器

```yaml
hooks:
  after_task_complete:
    script: "schedule/on_task_complete.surql"

  after_reminder_triggered:
    script: "schedule/on_reminder_triggered.surql"

  scheduled:
    - name: "morning_review"
      cron: "0 8 * * *"  # 每天早8点
      script: "schedule/morning_review.surql"
    - name: "evening_review"
      cron: "0 21 * * *"  # 每晚9点
      script: "schedule/evening_review.surql"
    - name: "habit_reminder"
      cron: "0 9,12,15,18,21 * * *"  # 每3小时提醒
      script: "schedule/habit_reminder.surql"
    - name: "week_planning"
      cron: "0 22 * * 0"  # 周日晚10点
      script: "schedule/week_planning.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "connect_surrealdb"
  4: "load_user_preferences"
  5: "restore_today_schedule"
  6: "restore_active_habits"
  7: "register_hooks"
  8: "ready"
```

## 功能模块

### 1. 日程管理

- 日/周/月视图切换
- 日程创建、编辑、删除
- 重复日程设置
- 日程冲突检测
- 多日历管理

### 2. 任务管理

- GTD工作流
- 四象限分类
- 子任务分解
- 任务标签管理
- 批量操作

### 3. 习惯追踪

- 习惯创建与配置
- 每日打卡
- 连续打卡统计
- 成就解锁
- 趋势分析

### 4. 时间分析

- 时间使用统计
- 任务耗时分析
- 高效时段识别
- 效率趋势图
- 改进建议

### 5. 提醒系统

- 智能提醒
- 跟进提醒
- 生日/纪念日提醒
- 习惯提醒
- 自定义提醒音

## 与其他Agent协作

- 与ProfileManager共享用户偏好
- 与MemoryKeeper同步重要事件
- 与Notifier发送提醒通知
- 与Commander汇报任务状态
