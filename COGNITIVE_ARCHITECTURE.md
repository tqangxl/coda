# Coda Engine V7.1 进阶认知架构 (Cognitive Architecture)

本文档记录了 Coda Engine V7.1 在联邦知识图谱（Federated Knowledge Graph）之上实装的**高级认知、隐式推演与动态生命周期管理**机制。这标志着系统从传统的被动检索式 RAG 系统，正式跨越为具备“记忆新陈代谢”与“自主神经反射”的自治认知架构。

---

## 核心组件与物理实现

### 1. Memory Horizon (记忆地平线与生命周期衰减)
抛弃了所有数据永久存储的脂肪化堆积，V7.1 引入了四级强制记忆生命周期：

*   **`LONG_TERM` (长效真理)**：永不过期。高置信度的架构决策、经过验证的业务逻辑。检索打分（Hybrid Score）中自带 `+0.5` 提权。
*   **`SUMMARY` (结晶聚合)**：默认 7 天 TTL (Time-to-Live)。用于对话摘要、会话结晶。如果不被提升或再次引用，将自动清理。
*   **`SHORT_TERM` (短期快照)**：默认 1 天 TTL。当前上下文的调试记录。
*   **`WORKING` (工作缓存)**：1 小时后立即挥发。不进入向量化，仅占极小内存。

**物理实现**：
- `akp_types.py`: `MemoryHorizon` 枚举控制 `compile_depth` 与 `max_body_chars`。
- `surreal_atlas.py`: 根据 TTL 自动计算 Unix Timestamp 并注入 `expires_at` 字段。
- `db.py`: `federated_search_nodes` 检索时底层通过 `(expires_at IS NONE OR expires_at > time::unix())` 强制屏蔽过期节点。
- `main.py`: `maintenance_daemon` 守护进程每 5 分钟向 SurrealDB 发送 `DELETE` 指令，彻底物理回收（Garbage Collection）超期数据。

### 2. LLM 隐式依赖抽取 (Implicit Relation Extraction)
当 Markdown 文件未通过 Frontmatter 显式提供引用关系时，系统不再满足于孤立节点。

**物理实现**：
在 `compiler.py` 的增量编译流水线中，若策略允许 (`depth_policy="full"`) 且节点缺乏显式关联，编译器将挂起大模型 (LLM)，通过 `CognitiveEngine.extract_implicit_relations` 接口阅读全文并隐式推断出其 `depends_on` 和 `extends` 边。提取到的深层连接直接写回 SurrealDB，使得图谱变得极其稠密且逻辑严谨。

### 3. DreamCycle (认知盲区发现与突触自动合成)
Coda Engine 能够在夜间（系统闲置时）“做梦”，寻找并建立未知的关联。它是实现知识涌现（Emergence）的核心引擎。

**物理实现**：
- 守护进程 `maintenance_daemon` 记录轮询，每约 50 分钟自主唤醒一次。
- 系统进入 `dreamcycle.py`，从数据库随机锚定一个 `LONG_TERM` 核心节点 A。
- 使用向量相似度检索（`vector::similarity::cosine`）找到一个与 A 语义极度相似（如 `>0.75`）、但在图拓扑层面**毫无边连接**（通过 `->?.out` 和 `<-?.in` 排除）的节点 B。
- **合成**：系统判断 A 和 B 之间存在“未命名的设计模式”或“认知盲区”，将其同时发给大模型进行融合推演，生成全新的 `SUMMARY` 节点 C（带有桥接总结），并连线 `C -> extends -> A`, `C -> extends -> B`。

### 4. 架构脆弱性与爆炸半径预测 (Fragility & Impact Radius)
系统不再仅仅是被动记录依赖，而是能主动预测技术债风险。

**物理实现**：
- 通过开放的 `/predict-fragility/{project}/{node}` REST API。
- 引擎向图数据库执行图穿透查询 `SELECT <-depends_on<-wiki_nodes`，瞬间计算出某个节点的直接和间接依赖下游总数（**爆炸半径**）。
- 结合节点本身的 `confidence`（置信度）和 `memory_horizon`，预测其脆弱性。
- 例如：若 10+ 个组件依赖于一个 `confidence < 0.6` 且只具备 `SHORT_TERM` 生命周期的节点，系统会明确抛出 `HIGH_IMPACT_SHORT_LIVED` 的红色预警，指导工程师优先重构。

---

## 结论

V7.1 版本的所有认知扩展并非处于假设或“占位符”阶段，而是：
1. **100% 物理落盘**，直接驱动底层 SurrealDB。
2. **零阻碍自动推进**，所有的提纯、降级、连线、休眠演算均由守护引擎在无人值守的情况下自动闭环。
3. **真实 LLM 调度**，所有连线推断与概念桥接全部基于真实的 Token 运算，彻底实现了智能体系统的“自主神经反射”。
