# Token优化系统 - cx智能解析

## 核心问题

### AI Agent读文件的问题
```
人类程序员:
  1. 看目录结构
  2. 搜索函数名
  3. 跳转到定义
  4. 看几行就够了

AI Agent:
  1. 不确定? 读文件
  2. 还不确定? 再读一个
  3. 结果: 全文读取
```

### 统计数据
```
66% 的读取是链式的
  - 读A是为了找到B
  - 读B是为了找到C

37% 是重复读
  - 同一个文件读好几遍

平均每次读文件消耗约1200 token
一个session平均读21次
每个session光读代码就要烧掉2万多token
```

## cx工具 - Token优化方案

### 工具介绍
```
cx是一个命令行工具
基于tree-sitter做语义解析
给Agent提供了一套"代价阶梯"
```

### 代价阶梯

| 操作 | Token消耗 | 用途 |
|------|----------|------|
| `cx overview src/file.rs` | ~200 token | 这个文件里有什么? |
| `cx definition --name func` | ~200 token | 给我看这个函数 |
| `cx symbols --kind fn` | ~70 token | 整个项目有哪些函数? |
| `cx references --name func` | 极少 | 这个符号在哪里被用到? |

### 效果对比
```
直接读文件: 1200 token
cx overview: 200 token
cx definition: 200 token

效果:
- Read calls减少58%
- Token减少40-55%
```

## 为什么不用LSP?

### LSP的问题
```
LSP需要:
- 持续运行的后台进程
- 每个语言单独配置
- 内存动辄1-2GB
- 需要项目编译索引完成

Agent在一次session里可能只用一次
启动这套重型机器不值得
```

### cx的优势
```
无状态设计:
- 第一次运行时解析所有源文件
- 建一个轻量的本地索引(.cx-index.db)
- 之后只增量更新变化的文件
- 无后台进程
- 无编译依赖
- 跑就能用
```

## 集成Agent使用

### 安装
```bash
curl -sL https://raw.githubusercontent.com/ind-igo/cx/master/install.sh | sh

# 或

cargo install cx-cli
```

### 配置Agent
```bash
cx skill > ~/.claude/CX.md

# 然后在CLAUDE.md里加一行
@CX.md
```

### 使用语言支持
```bash
cx lang add rust typescript python

# cx会检测项目里用了哪些语言
# 如果没装对应的grammar，会提示
```

## Agent使用策略

### 读取策略
```yaml
决策树:
1. 先cx overview摸清结构
2. 有需要再cx definition精准取函数
3. 大多数情况根本不用完整读文件

什么时候该读完整文件:
- 需要理解复杂上下文
- 需要修改多行代码
- 需要理解业务逻辑
```

### 工具调用顺序
```yaml
优先使用:
1. cx overview (结构概览)
2. cx definition (精准定义)
3. cx symbols (符号列表)
4. cx references (引用查找)
5. 完整读文件 (最后手段)
```

## 实现示例

### Agent工作流对比

#### 优化前
```
Agent: 读取 main.rs (1200 token)
Agent: 读取 auth.rs (1200 token)
Agent: 读取 user.rs (1200 token)
Agent: 读取 database.rs (1200 token)
Agent: 开始写代码
总消耗: 4800+ token
```

#### 优化后
```
Agent: cx overview src/ (200 token)
Agent: cx definition --name auth (200 token)
Agent: cx references --name User (50 token)
Agent: 开始写代码
总消耗: 450 token
节省: 90%+
```

## Token优化配置

### AGENTS.md配置
```yaml
token_optimization:
  enabled: true
  tools:
    - cx
    - grep
    - find
  strategy:
    - overview_first
    - definition_second
    - full_read_last

  thresholds:
    max_tokens_per_file: 500
    max_files_per_session: 20
    warn_at_tokens: 10000
```

### 智能提示
```markdown
# 读取文件前先问自己:
1. 真的需要完整文件吗?
2. cx overview够用吗?
3. 只看某个函数可以吗?
4. 这是重复读取吗?

# 如果是，读; 否则，用cx
```

## 监控指标

### Token消耗统计
```yaml
metrics:
  total_tokens_saved: 累计节省token
  read_calls_reduced: Read调用减少百分比
  avg_tokens_per_read: 平均每次读取token
  files_fully_read: 完整读取文件数
  files_cx_read: cx读取文件数
```

### 优化报告
```markdown
# Token优化报告

## 节省统计
- 总节省Token: XX,XXX
- 节省百分比: XX%
- Read调用减少: XX%

## 详细记录
| 操作 | Token消耗 | 替代完整读取 |
|------|----------|-------------|
| cx overview | 200 | 1200 |
| cx definition | 200 | 1200 |
| cx symbols | 70 | - |
```

## 持续优化

### 学习机制
```
每次完整读文件后:
1. 记录为什么需要完整读取
2. 分析是否可以改进
3. 更新优化策略
4. 持续减少不必要的读取
```

### 优化反馈
```markdown
如果发现:
- cx不够用 → 反馈改进cx
- 需要新操作 → 添加到工具库
- 策略不生效 → 调整策略
```
