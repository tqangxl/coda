# ProfileManager Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "profile-manager"
  name: "ProfileManager"
  type: "profile"
  version: "2.0.0"
  namespace: "ai_agents_v2"
```

## 职责

- 用户画像构建
- 偏好学习
- 个性化服务

## cx优化配置

```yaml
cx_config:
  enabled: false  # ProfileManager主要处理文本和配置
```

## 用户画像配置

```yaml
profile:
  dimensions:
    - name: "skill_level"
      type: "numeric"
      range: [0, 100]
    - name: "work_hours"
      type: "time_range"
    - name: "preferred_style"
      type: "enum"
      values: ["detailed", "concise", "technical"]
    - name: "communication_style"
      type: "enum"
      values: ["formal", "casual", "mixed"]
```

## SurrealDB表

```sql
-- ProfileManager专用表
DEFINE TABLE user_profiles SCHEMAFULL;
DEFINE FIELD id ON user_profiles TYPE string;
DEFINE FIELD user_id ON user_profiles TYPE string;
DEFINE FIELD profile_data ON user_profiles TYPE object;
DEFINE FIELD created_at ON user_profiles TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON user_profiles TYPE datetime;

DEFINE TABLE user_preferences SCHEMAFULL;
DEFINE FIELD id ON user_preferences TYPE string;
DEFINE FIELD user_id ON user_preferences TYPE string;
DEFINE FIELD preference_type ON user_preferences TYPE string;
DEFINE FIELD value ON user_preferences TYPE object;
DEFINE FIELD confidence ON user_preferences TYPE float;
DEFINE FIELD created_at ON user_preferences TYPE datetime DEFAULT time::now();

DEFINE TABLE behavior_events SCHEMAFULL;
DEFINE FIELD id ON behavior_events TYPE string;
DEFINE FIELD user_id ON behavior_events TYPE string;
DEFINE FIELD event_type ON behavior_events TYPE string;
DEFINE FIELD event_data ON behavior_events TYPE object;
DEFINE FIELD timestamp ON behavior_events TYPE datetime DEFAULT time::now();
```

## Hook触发器

```yaml
hooks:
  after_user_feedback:
    script: "update_profile.surql"

  after_task_complete:
    script: "learn_from_task.surql"

  scheduled:
    - name: "profile_sync"
      interval: "30m"
      script: "sync_profiles.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "connect_surrealdb"
  4: "restore_profiles"
  5: "register_hooks"
  6: "ready"
```
