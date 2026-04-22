# Infra & Guardrails - 基础设施与安全保障

## 组件定义

Infra & Guardrails是Hermes Engineering的安全防线和运行环境提供者。它确保Agent在安全的沙箱环境中执行操作，提供权限控制、边界检查和失败恢复机制。

## 核心职责

### 1. 沙箱隔离

- **执行环境**: 为Agent提供隔离的执行环境
- **资源限制**: 控制CPU、内存、磁盘使用
- **网络隔离**: 限制网络访问权限
- **文件系统隔离**: 限制文件系统访问范围

### 2. 权限控制

- **角色权限**: 基于角色的访问控制(RBAC)
- **操作授权**: 敏感操作需要明确授权
- **最小权限**: Agent只获得完成工作所需的最小权限
- **权限审计**: 记录和分析权限使用

### 3. 安全护栏

- **输入验证**: 验证所有输入的安全性
- **输出过滤**: 过滤敏感信息泄露
- **恶意检测**: 检测潜在的恶意操作
- **审计日志**: 完整的操作审计追踪

### 4. 失败恢复

- **状态持久化**: Checkpoint机制保存状态
- **优雅降级**: 系统部分失败时保持可用
- **自动恢复**: 从Checkpoint恢复执行
- **数据一致性**: 确保故障后数据一致

## SurrealDB安全模型

```sql
-- 权限角色
DEFINE TABLE roles SCHEMAFULL;
DEFINE FIELD id ON roles TYPE string;
DEFINE FIELD name ON roles TYPE string;
DEFINE FIELD description ON roles TYPE string;
DEFINE FIELD permissions ON roles TYPE array;
DEFINE FIELD constraints ON roles TYPE object;
DEFINE FIELD created_at ON roles TYPE datetime;

-- Agent权限绑定
DEFINE TABLE agent_permissions SCHEMAFULL;
DEFINE FIELD id ON agent_permissions TYPE string;
DEFINE FIELD agent_id ON agent_permissions TYPE string;
DEFINE FIELD role_id ON agent_permissions TYPE string;
DEFINE FIELD scope ON agent_permissions TYPE object; -- workspace, files, tools
DEFINE FIELD granted_by ON agent_permissions TYPE string;
DEFINE FIELD expires_at ON agent_permissions TYPE option<datetime>;
DEFINE FIELD created_at ON agent_permissions TYPE datetime;

-- Checkpoint记录
DEFINE TABLE checkpoints SCHEMAFULL;
DEFINE FIELD id ON checkpoints TYPE string;
DEFINE FIELD agent_id ON checkpoints TYPE string;
DEFINE FIELD task_id ON checkpoints TYPE string;
DEFINE FIELD state ON checkpoints TYPE object;
DEFINE FIELD memory_snapshot ON checkpoints TYPE object;
DEFINE FIELD created_at ON checkpoints TYPE datetime;
DEFINE FIELD size_bytes ON checkpoints TYPE int;

-- 审计日志
DEFINE TABLE audit_logs SCHEMAFULL;
DEFINE FIELD id ON audit_logs TYPE string;
DEFINE FIELD timestamp ON audit_logs TYPE datetime;
DEFINE FIELD agent_id ON audit_logs TYPE string;
DEFINE FIELD action ON audit_logs TYPE string;
DEFINE FIELD resource ON audit_logs TYPE string;
DEFINE FIELD details ON audit_logs TYPE object;
DEFINE FIELD result ON audit_logs TYPE string; -- success, denied, error
DEFINE FIELD ip_address ON audit_logs TYPE option<string>;

-- 沙箱配置
DEFINE TABLE sandbox_configs SCHEMAFULL;
DEFINE FIELD id ON sandbox_configs TYPE string;
DEFINE FIELD agent_type ON sandbox_configs TYPE string;
DEFINE FIELD cpu_limit ON sandbox_configs TYPE int; -- millicores
DEFINE FIELD memory_limit ON sandbox_configs TYPE int; -- MB
DEFINE FIELD disk_limit ON sandbox_configs TYPE int; -- MB
DEFINE FIELD network_policy ON sandbox_configs TYPE string; -- allow, deny, isolated
DEFINE FIELD allowed_paths ON sandbox_configs TYPE array;
DEFINE FIELD denied_paths ON sandbox_configs TYPE array;
DEFINE FIELD timeout_seconds ON sandbox_configs TYPE int;

-- 索引
DEFINE INDEX idx_checkpoint_agent ON checkpoints FIELDS agent_id, created_at DESC;
DEFINE INDEX idx_audit_agent ON audit_logs FIELDS agent_id, timestamp DESC;
DEFINE INDEX idx_audit_action ON audit_logs FIELDS action, timestamp;
```

## 权限模型

### 角色定义

```yaml
roles:
  commander:
    permissions:
      - tasks:create
      - tasks:assign
      - agents:coordinate
      - workflows:execute
    constraints:
      max_concurrent_tasks: 10

  generator:
    permissions:
      - code:read
      - code:generate
      - files:create
      - tools:use
    constraints:
      max_file_size: 1MB

  verifier:
    permissions:
      - code:read
      - code:execute
      - files:read
      - security:scan
    constraints:
      no_network_access: true

  coder:
    permissions:
      - files:read
      - files:write
      - files:execute
      - code:format
      - git:commit
    constraints:
      allowed_paths: [workspace/*, tmp/*]
      denied_paths: [~/.ssh, /etc, /root]
```

### 权限检查流程

```
操作请求 → 权限验证 → 约束检查 → 资源限制 → 执行/拒绝
    ↓
拒绝 → 记录审计 → 返回错误
```

## 沙箱配置

### 开发沙箱

```yaml
sandbox:
  name: "development"
  cpu: 2000  # 2 cores
  memory: 4096  # 4GB
  disk: 10240  # 10GB
  network: "allow"
  timeout: 600  # 10 minutes
  allowed_tools:
    - bash
    - read_file
    - write_file
    - edit_file
    - glob
```

### 安全沙箱

```yaml
sandbox:
  name: "security_test"
  cpu: 1000  # 1 core
  memory: 2048  # 2GB
  disk: 5120  # 5GB
  network: "deny"
  timeout: 300  # 5 minutes
  allowed_tools:
    - read_file
    - security_scan
  read_only: true
```

## Checkpoint机制

### 状态保存

```python
class CheckpointManager:
    def save_checkpoint(self, agent_id, task_id, state):
        """保存Checkpoint"""
        checkpoint = {
            "id": f"ckpt_{uuid()}",
            "agent_id": agent_id,
            "task_id": task_id,
            "state": state,
            "memory_snapshot": self.capture_memory(agent_id),
            "created_at": datetime.now().isoformat(),
            "size_bytes": len(json.dumps(state))
        }

        # 存储到SurrealDB
        db.create("checkpoints", checkpoint)

        # 保留最近N个Checkpoint
        self.prune_old_checkpoints(agent_id, keep=5)
        return checkpoint["id"]

    def restore_checkpoint(self, checkpoint_id):
        """恢复Checkpoint"""
        checkpoint = db.get("checkpoints", checkpoint_id)
        agent = get_agent(checkpoint["agent_id"])
        agent.restore_state(checkpoint["state"])
        agent.load_memory(checkpoint["memory_snapshot"])
        return agent
```

### 恢复策略

```python
def handle_failure(agent_id, error):
    """处理Agent失败"""
    # 1. 获取最近的Checkpoint
    checkpoint = db.query(
        "SELECT * FROM checkpoints WHERE agent_id = $id ORDER BY created_at DESC LIMIT 1",
        {"id": agent_id}
    )

    if checkpoint:
        # 2. 恢复状态
        restore_checkpoint(checkpoint["id"])
        # 3. 重试任务
        retry_task(checkpoint["task_id"])
    else:
        # 4. 无法恢复，通知人工介入
        notify_human(agent_id, error)
```

## 安全护栏规则

### 文件访问控制

```yaml
guardrails:
  file_access:
    allowed_paths:
      - "/workspace/**"
      - "/tmp/**"
    denied_paths:
      - "/home/**/.ssh/**"
      - "/etc/**"
      - "/root/**"
    max_file_size: 10485760  # 10MB
    blocked_extensions:
      - ".exe"
      - ".dll"
      - ".so"
```

### 命令执行控制

```yaml
guardrails:
  command_execution:
    allowed_commands:
      - "git"
      - "npm"
      - "python"
      - "node"
    denied_patterns:
      - "rm -rf /"
      - "curl.*|sh"
      - "wget.*|sh"
    max_execution_time: 300  # 5 minutes
```

### 网络访问控制

```yaml
guardrails:
  network:
    allowed_domains:
      - "api.github.com"
      - "registry.npmjs.org"
    allowed_ports:
      - 80
      - 443
    blocked_ips:
      - "10.0.0.0/8"
      - "192.168.0.0/16"
```

## 审计日志示例

```json
{
  "id": "audit_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "agent_id": "coder_001",
  "action": "file_write",
  "resource": "/workspace/project/main.py",
  "details": {
    "size": 1024,
    "operation": "create"
  },
  "result": "success",
  "permissions_checked": true
}
```

## 监控指标

- 权限拒绝次数
- Checkpoint恢复次数
- 沙箱资源使用率
- 平均执行时间
- 安全事件数量
