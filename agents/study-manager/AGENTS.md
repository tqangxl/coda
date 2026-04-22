# StudyManager Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "study-manager"
  name: "StudyManager"
  type: "study"
  version: "2.0.0"
  namespace: "ai_agents_v2"
  description: "学习管理专家 - 帮助小朋友规划学业、管理作业、养成学习习惯"
```

## 职责

- 学生档案管理（基本信息、年级、科目、目标）
- 学习计划制定（日/周/月/学期/年度计划）
- 作业管理（记录、跟踪、完成确认）
- 错题本维护（收集、分析、复习提醒）
- 考试分析（成绩记录、弱点识别、改进建议）
- 学习习惯养成（专注训练、复习计划、奖励机制）

## cx优化配置

```yaml
cx_config:
  enabled: true

  before_llm_call:
    - command: "symbols"
      reason: "了解当前学习主题和关联知识"
    - command: "overview"
      reason: "获取学生整体学习状态"
    - command: "context"
      reason: "获取近期学习记录和表现"

  optimization:
    daily_planning: 2000
    weekly_review: 3000
    exam_analysis: 4000
```

## 用户画像配置

```yaml
student_profile:
  dimensions:
    - name: "grade_level"
      type: "enum"
      values: ["primary_1", "primary_2", "primary_3", "primary_4", "primary_5", "primary_6", "middle_1", "middle_2", "middle_3", "high_1", "high_2", "high_3"]
    - name: "learning_style"
      type: "enum"
      values: ["visual", "auditory", "reading", "kinesthetic"]
    - name: "subject_strengths"
      type: "array"
    - name: "subject_weaknesses"
      type: "array"
    - name: "attention_span"
      type: "int"  # 分钟
    - name: "work_preference"
      type: "enum"
      values: ["morning", "afternoon", "evening"]
```

## SurrealDB表

```sql
-- StudyManager专用表（使用v2_前缀隔离）
DEFINE TABLE v2_study_plans SCHEMAFULL;
DEFINE FIELD id ON v2_study_plans TYPE string;
DEFINE FIELD student_id ON v2_study_plans TYPE string;
DEFINE FIELD plan_type ON v2_study_plans TYPE string;
DEFINE FIELD title ON v2_study_plans TYPE string;
DEFINE FIELD content ON v2_study_plans TYPE object;
DEFINE FIELD subjects ON v2_study_plans TYPE array;
DEFINE FIELD start_date ON v2_study_plans TYPE datetime;
DEFINE FIELD end_date ON v2_study_plans TYPE datetime;
DEFINE FIELD status ON v2_study_plans TYPE string;
DEFINE FIELD completion_rate ON v2_study_plans TYPE float DEFAULT 0;
DEFINE FIELD created_at ON v2_study_plans TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON v2_study_plans TYPE datetime;

DEFINE TABLE v2_homework_records SCHEMAFULL;
DEFINE FIELD id ON v2_homework_records TYPE string;
DEFINE FIELD student_id ON v2_homework_records TYPE string;
DEFINE FIELD subject ON v2_homework_records TYPE string;
DEFINE FIELD title ON v2_homework_records TYPE string;
DEFINE FIELD description ON v2_homework_records TYPE string;
DEFINE FIELD due_date ON v2_homework_records TYPE datetime;
DEFINE FIELD priority ON v2_homework_records TYPE string;
DEFINE FIELD status ON v2_homework_records TYPE string;
DEFINE FIELD time_estimate ON v2_homework_records TYPE int;
DEFINE FIELD actual_time ON v2_homework_records TYPE option<int>;
DEFINE FIELD notes ON v2_homework_records TYPE option<string>;
DEFINE FIELD created_at ON v2_homework_records TYPE datetime DEFAULT time::now();
DEFINE FIELD completed_at ON v2_homework_records TYPE option<datetime>;

DEFINE TABLE v2_study_sessions SCHEMAFULL;
DEFINE FIELD id ON v2_study_sessions TYPE string;
DEFINE FIELD student_id ON v2_study_sessions TYPE string;
DEFINE FIELD subject ON v2_study_sessions TYPE string;
DEFINE FIELD topic ON v2_study_sessions TYPE string;
DEFINE FIELD activity_type ON v2_study_sessions TYPE string;
DEFINE FIELD start_time ON v2_study_sessions TYPE datetime;
DEFINE FIELD end_time ON v2_study_sessions TYPE datetime;
DEFINE FIELD duration ON v2_study_sessions TYPE int;
DEFINE FIELD focus_score ON v2_study_sessions TYPE option<int>;
DEFINE FIELD understanding_score ON v2_study_sessions TYPE option<int>;
DEFINE FIELD notes ON v2_study_sessions TYPE option<string>;
DEFINE FIELD created_at ON v2_study_sessions TYPE datetime DEFAULT time::now();

DEFINE TABLE v2_exam_records SCHEMAFULL;
DEFINE FIELD id ON v2_exam_records TYPE string;
DEFINE FIELD student_id ON v2_exam_records TYPE string;
DEFINE FIELD subject ON v2_exam_records TYPE string;
DEFINE FIELD exam_type ON v2_exam_records TYPE string;
DEFINE FIELD title ON v2_exam_records TYPE string;
DEFINE FIELD exam_date ON v2_exam_records TYPE datetime;
DEFINE FIELD score ON v2_exam_records TYPE option<float>;
DEFINE FIELD total_score ON v2_exam_records TYPE float;
DEFINE FIELD rank ON v2_exam_records TYPE option<int>;
DEFINE FIELD analysis ON v2_exam_records TYPE option<string>;
DEFINE FIELD weak_points ON v2_exam_records TYPE array;
DEFINE FIELD created_at ON v2_exam_records TYPE datetime DEFAULT time::now();

DEFINE TABLE v2_mistake_book SCHEMAFULL;
DEFINE FIELD id ON v2_mistake_book TYPE string;
DEFINE FIELD student_id ON v2_mistake_book TYPE string;
DEFINE FIELD subject ON v2_mistake_book TYPE string;
DEFINE FIELD question ON v2_mistake_book TYPE string;
DEFINE FIELD correct_answer ON v2_mistake_book TYPE string;
DEFINE FIELD student_answer ON v2_mistake_book TYPE string;
DEFINE FIELD mistake_type ON v2_mistake_book TYPE string;
DEFINE FIELD explanation ON v2_mistake_book TYPE string;
DEFINE FIELD related_knowledge ON v2_mistake_book TYPE array;
DEFINE FIELD mastery_level ON v2_mistake_book TYPE int DEFAULT 0;
DEFINE FIELD review_count ON v2_mistake_book TYPE int DEFAULT 0;
DEFINE FIELD last_review ON v2_mistake_book TYPE datetime;
DEFINE FIELD next_review ON v2_mistake_book TYPE datetime;
DEFINE FIELD created_at ON v2_mistake_book TYPE datetime DEFAULT time::now();

DEFINE TABLE v2_rewards SCHEMAFULL;
DEFINE FIELD id ON v2_rewards TYPE string;
DEFINE FIELD student_id ON v2_rewards TYPE string;
DEFINE FIELD reward_type ON v2_rewards TYPE string;
DEFINE FIELD title ON v2_rewards TYPE string;
DEFINE FIELD description ON v2_rewards TYPE string;
DEFINE FIELD points ON v2_rewards TYPE int;
DEFINE FIELD redeemed_at ON v2_rewards TYPE option<datetime>;
DEFINE FIELD created_at ON v2_rewards TYPE datetime DEFAULT time::now();

-- 索引
DEFINE INDEX idx_v2_plan_student ON v2_study_plans FIELDS student_id, plan_type;
DEFINE INDEX idx_v2_plan_dates ON v2_study_plans FIELDS start_date, end_date;
DEFINE INDEX idx_v2_homework_due ON v2_homework_records FIELDS student_id, due_date, status;
DEFINE INDEX idx_v2_session_student ON v2_study_sessions FIELDS student_id, created_at DESC;
DEFINE INDEX idx_v2_exam_student ON v2_exam_records FIELDS student_id, exam_date DESC;
DEFINE INDEX idx_v2_mistake_student ON v2_mistake_book FIELDS student_id, subject, mastery_level;
```

## Hook触发器

```yaml
hooks:
  after_homework_complete:
    script: "study/on_homework_complete.surql"

  after_exam_recorded:
    script: "study/on_exam_recorded.surql"

  scheduled:
    - name: "daily_review"
      cron: "0 20 * * *"  # 每晚8点
      script: "study/daily_review.surql"
    - name: "mistake_review"
      cron: "0 9 * * 1,3,5"  # 周一三五早9点
      script: "study/mistake_review.surql"
    - name: "weekly_plan"
      cron: "0 18 * * 5"  # 周五晚6点
      script: "study/weekly_plan.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "connect_surrealdb"
  4: "load_student_profiles"
  5: "restore_active_plans"
  6: "register_hooks"
  7: "ready"
```

## 功能模块

### 1. 计划管理

- 日计划生成与跟踪
- 周计划制定与调整
- 月度目标设定与进度跟踪
- 学期计划制定与复盘
- 寒暑假计划安排

### 2. 作业管理

- 作业录入（支持批量）
- 优先级排序
- 完成打卡
- 耗时记录
- 质量评估

### 3. 错题本

- 自动收集（考试/练习）
- 错因分析
- 知识点关联
- 艾宾浩斯复习提醒
- 掌握度跟踪

### 4. 考试分析

- 成绩记录
- 趋势分析
- 薄弱点识别
- 改进建议生成
- 家长报告

### 5. 学习激励

- 积分系统
- 成就徽章
- 连续打卡追踪
- 奖励兑换
- 排行榜

## 与家长交互

- 定期进度报告
- 问题预警通知
- 家长会建议准备
- 家校沟通记录
