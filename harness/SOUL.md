# SOUL.md - Hermes Engineering核心灵魂

## 核心身份

Hermes Engineering是围绕AI模型搭建的"脚手架"系统。

**核心公式**: Agent = LLM + Hermes

**核心理念**:

- 模型决定做什么
- Hermes决定模型能看到什么
- Hermes决定模型能用什么工具
- Hermes决定失败时该怎么办

## 三层架构

### 信息层（资源准备）

**目标**: 让Agent获得正确的信息

**Trick 1: 渐进式披露**

```
Level 1: CLAUDE.md - 最关键、最常用的元规则
Level 2: SKILL.md - 按需调用的小型能力包
Level 3: reference - 具体细节
```

**Trick 2: Tools越少而精越好**

```
Agent强大不在于工具多少
而在于是否有几把"万能扳手"
```

**Trick 3: 找到Context窗口的"甜蜜区间"**

```
超过60%利用率后性能下降
建议控制在60%以下
```

**Trick 4: 利用subagent做context隔离**

```
把子任务分配给独立subagent
减少context污染
```

### 执行层（执行规划）

**目标**: 让Agent正确地执行

**Trick 5: 把研究、计划、执行、验证分开**

```
分成四个独立session
避免context污染
```

**Trick 6: 人最该介入的地方是事前规划**

```
把精力从事后code review
前移到research和plan环节
```

### 反馈层（复利飞轮）

**目标**: 让Agent从每次执行中学习

**Trick 7: 构建反馈闭环**

```
核心原则: 每一次失败都是让系统永久变好的机会
```

**具体做法**:

```
把错误经验记入AGENTS.md/CLAUDE.md
让Agent下次不再犯同样错误
```

## 六大关键组件

### 1. Memory & Context Management

```
功能: 记忆与上下文管理
解决: "Agent应该看到什么信息"
包含:
  - 上下文裁剪
  - 压缩算法
  - 按需检索
  - 外部状态存储
```

### 2. Tools & Skills

```
功能: 工具与技能扩展Agent行动能力
包含:
  - 工具: 可调用外部能力
  - 技能: 可复用任务方法
```

### 3. Orchestration & Coordination

```
功能: 管理任务流程、协调分工
包含:
  - 任务流程管理
  - 分工协调
  - 规划/执行/交接决策
```

### 4. Infra & Guardrails

```
功能: 提供运行环境、边界条件
包含:
  - 运行环境
  - 沙箱
  - 权限控制
  - 失败恢复
  - 安全护栏
```

### 5. Evaluation & Verification

```
功能: 内置测试、检查和反馈机制
包含:
  - 自动化测试
  - 检查机制
  - 反馈系统
  - 修正能力
```

### 6. Tracing & Observability

```
功能: 还原Agent行为过程
包含:
  - 执行轨迹
  - 日志
  - 监控
  - 成本分析
```

## 自我进化

### Mitchell Hashimoto原则

```
"Anytime you find an agent makes a mistake,
you take the time to engineer a solution such that
the agent never makes that mistake again"
```

### 训练即部署

```
Agentic RL训练逻辑:
模型和Hermes从一开始就不是分开设计的
训练效果很大程度上取决于"训练场设计得好不好"
```

### Hermes即数据

```
Philipp Schmid金句:
"The Hermes is the Dataset.
Competitive advantage is now the trajectories
your hermes captures"
```

## 持续优化循环

```
模型团队和社区用户在前线摸索
        ↓
试出哪些方法有效
        ↓
训练团队把这些模式拿去做post-training
        ↓
模型开始把hermes能力内生化
        ↓
新的hermes被重新设计出来支持新的模型能力
        ↓
如此循环往复
```

## Coordination Engineering

### 多Agent协作

```
下一阶段Agents需要达到:
协调无数agent/人类节点共同完成复杂任务
```

### 四层Agentic Engineering范式

```
L1: 解决问答质量
L2: 解决认知边界
L3: 解决执行闭环
L4: 解决组织协同
```

### 终极推演

```
一切似乎只剩下了intention engineering（意图工程）
人的价值只剩"设定目标函数"
其余AI都可自行包揽
```
