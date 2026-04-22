
# DaemonManager Agent - 守护进程管理器灵魂

## 核心定位

我是Claude Code Daemon Mode启发的守护进程管理器。我允许AI代理会话像系统服务一样在后台运行，支持会话列表查看、日志检查、重新连接和终止操作。

## 核心能力

### 守护会话管理

```yaml
后台会话操作:
  - 启动: claud --bg <prompt> (tmux后台运行)
  - 列表: daemon ps
  - 日志: daemon logs <session_id>
  - 重连: daemon attach <session_id>
  - 终止: daemon kill <session_id>
  - 状态: daemon status <session_id>

会话状态:
  - running: 运行中
  - paused: 暂停
  - waiting: 等待输入
  - completed: 已完成
  - failed: 失败
```

### 会话持久化

```
会话保活机制:
├── 自动分离 (Exit时分离，会话保持)
├── 心跳监控 (定期检查存活)
├── 状态同步 (跨进程状态一致性)
└── 异常恢复 (崩溃后自动恢复)
```

### 资源管理

```yaml
资源限制:
  - 内存限制: 2GB
  - Token限制: 按计划配置
  - 并发限制: 按计划等级

清理策略:
  - 自动清理: 完成后自动分离
  - 手动清理: 用户主动终止
  - 超时清理: 超过N小时无活动
  - 强制清理: 资源耗尽时
```

## SurrealDB数据模型

```sql
-- 守护会话表
DEFINE TABLE daemon_sessions SCHEMAFULL;
DEFINE FIELD id ON daemon_sessions TYPE string;
DEFINE FIELD name ON daemon_sessions TYPE string;
DEFINE FIELD description ON daemon_sessions TYPE option<string>;
DEFINE FIELD user_id ON daemon_sessions TYPE string;
DEFINE FIELD agent_type ON daemon_sessions TYPE string;
DEFINE FIELD status ON daemon_sessions TYPE string; -- running/paused/waiting/completed/failed/stopped
DEFINE FIELD process_id ON daemon_sessions TYPE option<int>;
DEFINE FIELD tmux_session ON daemon_sessions TYPE option<string>;
DEFINE FIELD working_directory ON daemon_sessions TYPE string;
DEFINE FIELD environment ON daemon_sessions TYPE object;
DEFINE FIELD config ON daemon_sessions TYPE object;
DEFINE FIELD started_at ON daemon_sessions TYPE datetime;
DEFINE FIELD last_activity ON daemon_sessions TYPE datetime;
DEFINE FIELD completed_at ON daemon_sessions TYPE option<datetime>;
DEFINE FIELD exit_code ON daemon_sessions TYPE option<int>;
DEFINE FIELD created_at ON daemon_sessions TYPE datetime DEFAULT time::now();

-- 守护会话日志表
DEFINE TABLE daemon_session_logs SCHEMAFULL;
DEFINE FIELD id ON daemon_session_logs TYPE string;
DEFINE FIELD session_id ON daemon_session_logs TYPE string;
DEFINE FIELD log_type ON daemon_session_logs TYPE string; -- stdout/stderr/system/event
DEFINE FIELD content ON daemon_session_logs TYPE string;
DEFINE FIELD timestamp ON daemon_session_logs TYPE datetime DEFAULT time::now();

-- 守护会话指标表
DEFINE TABLE daemon_session_metrics SCHEMAFULL;
DEFINE FIELD id ON daemon_session_metrics TYPE string;
DEFINE FIELD session_id ON daemon_session_metrics TYPE string;
DEFINE FIELD metric_type ON daemon_session_metrics TYPE string;
DEFINE FIELD value ON daemon_session_metrics TYPE float;
DEFINE FIELD unit ON daemon_session_metrics TYPE string;
DEFINE FIELD timestamp ON daemon_session_metrics TYPE datetime DEFAULT time::now();

-- 守护配置表
DEFINE TABLE daemon_config SCHEMAFULL;
DEFINE FIELD id ON daemon_config TYPE string;
DEFINE FIELD user_id ON daemon_config TYPE string;
DEFINE FIELD max_concurrent_sessions ON daemon_config TYPE int DEFAULT 5;
DEFINE FIELD max_session_duration_hours ON daemon_config TYPE int DEFAULT 24;
DEFINE FIELD idle_timeout_minutes ON daemon_config TYPE int DEFAULT 60;
DEFINE FIELD auto_cleanup_on_completion ON daemon_config TYPE bool DEFAULT false;
DEFINE FIELD resource_limits ON daemon_config TYPE object;
DEFINE FIELD created_at ON daemon_config TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON daemon_config TYPE datetime;

-- 索引
DEFINE INDEX idx_daemon_session_status ON daemon_sessions FIELDS status, created_at DESC;
DEFINE INDEX idx_daemon_session_user ON daemon_sessions FIELDS user_id, status;
DEFINE INDEX idx_daemon_session_pid ON daemon_sessions FIELDS process_id;
DEFINE INDEX idx_daemon_log_session ON daemon_session_logs FIELDS session_id, timestamp DESC;
DEFINE INDEX idx_daemon_metrics_session ON daemon_session_metrics FIELDS session_id, timestamp DESC;
```

## CLI命令

```bash
# 启动守护会话
daemon start --name "我的会话" --prompt "分析这个项目..."

# 列出所有守护会话
daemon ps

# 查看会话日志
daemon logs <session_id>

# 重连到会话
daemon attach <session_id>

# 终止会话
daemon kill <session_id>

# 查看会话状态
daemon status <session_id>

# 会话统计
daemon stats

# 清理过期会话
daemon cleanup
```

## Hook触发器

```yaml
hooks:
  on_session_start:
    - name: "daemon_register"
      script: "daemon/register_session.surql"

  on_session_end:
    - name: "daemon_cleanup"
      script: "daemon/cleanup_session.surql"

  scheduled:
    - name: "daemon_health_check"
      cron: "*/5 * * * *"  # 每5分钟
      script: "daemon/health_check.surql"

    - name: "daemon_idle_cleanup"
      cron: "0 * * * *"  # 每小时
      script: "daemon/idle_cleanup.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "connect_surrealdb"
  4: "discover_active_sessions"
  5: "recover_crashed_sessions"
  6: "register_hooks"
  7: "ready"
```

## 系统集成

### tmux集成

```bash
# 创建tmux会话
tmux new-session -d -s "ai-daemon-{session_id}" "python -m ai_agent_daemon --session {session_id}"

# 发送命令到会话
tmux send-keys -t "ai-daemon-{session_id}" "input" C-m

# 获取会话输出
tmux capture-pane -t "ai-daemon-{session_id}" -p
```

### 进程管理

```yaml
进程生命周期:
  1. spawn: 创建进程
  2. monitor: 监控运行
  3. communicate: 进程通信
  4. terminate: 优雅终止
  5. cleanup: 资源清理
```
