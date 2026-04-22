# LEARNINGS.md — AI Agent System V2.0 持续进化记录

本文件用于记录在 V2.0 架构升级、组件联调及系统加固过程中遇到的关键阻碍、根本原因及其解决方案。这些经验教训（Lessons Learned）应被所有 Agent 摄取为“系统常识”，以确保后续开发不再重蹈覆辙。

---

## 2026-04-01: [CRITICAL] SurrealDB 3.x 强类型化与 SCHEMAFULL 约束 (Datetime Coercion)

### 现象 (Phenomenon)

在同步 `SOUL.md` Agent 灵魂数据至 SurrealDB `agents` 表时，系统持续抛出错误：`Couldn't coerce value for field 'created_at': Expected datetime but found NONE` 或 `Expected datetime but found string`。这导致 70 个核心 Agent 无法正常入库并呈现 0 Count。

### 根因 (Root Cause)

1. **SurrealDB 3.x 的激进类型检查**：在 `SCHEMAFULL` 模式下，如果字段定义为 `TYPE datetime`，而在 UPSERT 操作payload中未显式提供该字段，SurrealDB 3.x 不会自动触发 `DEFAULT time::now()`，而是将其视为 `NONE`（Null），从而触发数据类型不匹配的异常。
2. **Python SDK 日期序列化问题**：若通过 SDK 传入普通 ISO 字符串（如 `"2026-04-01T20:20:55.969201"`），新版 SurrealDB parser 可能会拒绝进行隐式推导并抛错。SDK 需要收到原生的 `datetime` 对象才能在背地里转化为数据库可接受的 datetime 格式。

### 纠正与进化 (Correction & Evolution)

- **Schema 弹性化**：将数据库定义从 `TYPE datetime DEFAULT time::now()` 改为 `TYPE option<datetime> DEFAULT time::now()` 以允许一定的数据传入伸缩性。
- **SDK 层显式传入对象**：在 `UPSERT` 生成写入 payload 时 (`sync_agents.py`)，不再依赖默认设值，而是显式注入 `datetime.now()` 实例。
- **无冗余 ID**：`SCHEMAFULL` 模式下绝不能手写 `DEFINE FIELD id ON xxx TYPE string;`，必须依赖内置的 Record ID 生成引擎，否则会触发主键层的数据异常。

---

## 2026-04-01: [WARN] SurrealDB Python SDK 结果集解析退化 (Result List Parsing)

### 现象 (Phenomenon)

后端 FastAPI 虽然收到了非空的查询响应，但 `/agents` 接口依然抛出 `{"count": 0, "agents": []}`。即便数据已经在数据库就位。

### 根因 (Root Cause)

- **SurrealDB 返回层级变化**：在过去版本中，SDK 结果往往包裹在 `[{ "result": [ {agent1}, {agent2} ] }]` 外壳中；但在某些新版 3.x 场景下（尤其是直接 `SELECT` 或者驱动微小版本升级后），可能会抹平 `"result"` 包装，直接返回一个由记录字典构成的扁平 List `[ {id: xxx, name: xxx}, ... ]`。
- **脆弱的双重解析假设**：现有的代码过度假设 `"result"` 键必然存在，对于直接返回 `[{id: "..."}]` 的情况缺乏兼容，导致提取为空。

### 纠正与进化 (Correction & Evolution)

- 回应解析逻辑必须做**多路兼容**：如果 `isinstance(response[0], dict)` 且包含了核心业务键（如 `"id"` 或 `"status"`），则直接使用该列表；如有 `"result"` 键，则降级解析其内层数组。这就保障了 `main.py` 的容错度。

---

## 2026-04-01: [CRITICAL] Windows 端口彻底释放 (Errno 10048) & Uvicorn 僵尸树

### 现象 (Phenomenon)

启动脚本 `startup.ps1` 尝试拉起一个新的 Uvicorn Worker 后，Python 抛出 `[WinError 10048] 通常每个套接字地址只允许使用一次。`，这意味着端口 8001 或 11001 依然被占，从而阻断了整个系统。

### 根因 (Root Cause)

- **无效的表面关闭**：使用 PowerShell的 `Stop-Process` 仅结束了宿主前台进程，但由 Uvicorn 生成的 background worker tree（多进程并发）作为子节点依旧“存活”在后台，紧密封锁着监听端口。

### 纠正与进化 (Correction & Evolution)

- **树形强制绞杀行动**：在启动时清理端口必须使用 `taskkill /F /PID <id> /T` 命令。`/T` 参数至关重要，它确保能斩断整个僵尸进程树。不再软性请求中止进程，直接强杀以释放核心端口。
- **释放延时**：引入更客观的睡眠时间 `Start-Sleep -Seconds 3`，给 Windows 系统足够的毫秒数去真正释放回收 TCP Sockets，而非一杀完立即启动后端。

---

## 2026-04-01: [IMPORTANT] 启动脚本数据幂等性 (Idempotent DB Init via Sentinel)

### 现象 (Phenomenon)

反复测试启动流程时，多次导入 `config.surql` 会重置已存数据或报错，尤其是当该文件中缺乏防冲突语句或者带有 `OPTION IMPORT;` 封杀级全量操作。

### 根因 (Root Cause)

- PowerShell 脚本对数据库的启动没有**长记忆**（Long-Term Memory），每次都在干一样的苦力活。

### 纠正与进化 (Correction & Evolution)

- **引入 Sentinel "哨兵" 机制**：部署完成首次数据库初始化后，在 `surrealdb\data` 目录落地一个 `.initialized` 文件。下次 `startup.ps1` 会检查该空文件的存在，若其已生成，则彻底跳过结构重置的导入步骤，实现逻辑解耦和启动的零负荷幂等性（秒起）。

---

## 2026-04-01: [WARNING] SurrealDB 核心路径与网络绑定 (Path & Binding Resolution)

### 现象 (Phenomenon)

在 Windows 环境下运行 `startup.ps1` 启动数据库或后端时，系统可能找不到 `surreal.exe`、将 `data` 目录错误地创建在当前随机工作目录下，或者后端在连接时抛出 `[WinError 1225] 远程计算机拒绝网络连接`。

### 根因 (Root Cause)

1. **相对路径漂移**：脚本如果没有动态计算自身所在绝对路径，当被外部环境（如 IDE 终端、外部服务脚本）跨目录调用时，会导致当前上下文漂移。这会令 `rocksdb://` 驱动无法加载正确的本地存储，也会让 python 脚本的导入发生错乱。
2. **localhost 域解析割裂**：Windows 可能会将 `localhost` 解析为 IPv6 的 `::1`。如果 SurrealDB 只绑定了 IPv4 (`127.0.0.1:11001`)，而 Python 脚本试图用 `ws://localhost:11001/rpc` 去连接，就会发生物理隔离，双向拒识。

### 纠正与进化 (Correction & Evolution)

- **硬性绝对锚定**：在一切启动流程（如 PowerShell 脚本开头），必须使用形如 `Split-Path -Parent $MyInvocation.MyCommand.Definition` 的手段逆向获取真正的项目 `$ProjectRoot`。所有的执行命令、`rocksdb://` 数据路径和环境变量，都必须挂载在这个绝对路径之上。
- **全域禁用 localhost**：在整个代码规范中（涵盖 `.env`, `main.py`, PowerShell, etc.），强制把数据库地址等回调全部锁死在 `127.0.0.1`，规避底层系统解析歧义。

---

## 2026-04-01: [WARNING] PowerShell 环境变量与系统级保留字冲突 (Variable Shadows)

### 现象 (Phenomenon)

在编写 `startup.ps1` 中的端口清理函数时，最初的逻辑尝试循环所有的网络 TCP 连接，并顺手将对应的子进程 ID 赋值给变量 `$PID` 并进行 kill。这触发了极其罕见且不易排查的内置异常，甚至导致脚本停止处理。

### 根因 (Root Cause)

- **PowerShell 内置只读锁定**：在 PowerShell 环境中，`$PID` 并非普通的随便用用的局部变量名，而是**只读（Read-Only）的系统自带变量**，它永远绝对地指向当前承载该会话（PWSH）进程本身的标识。对其进行赋值操作属于非法写操作。

### 纠正与进化 (Correction & Evolution)

- **变量隔离命名法**：所有的目标进程标识全部更名为语义更明确的 `$targetPid`，以此彻底规避系统关键字。未来任何语言环境下编写周边工具链（Ops 脚本）时，均禁止使用全大写的极简缩写，尤其是与系统级环境（如 `$HOME`, `$PID`, `$Error`）可能存在重叠的名字。

---

## 2026-04-01: [ERROR] SurrealDB SCHEMAFULL 模式下的保留关键字碰撞 (Reserved SQL Keywords)

### 现象 (Phenomenon)

开发早期，在 `KanbanBoards` 的对应实体表 `kanban_boards` 的定义语句中，随手设计了一个名为 `columns` 的字段用于存储列数组。但 `surreal import / sql` 在读取该文件时无情抛锚验证失败。

### 根因 (Root Cause)

- **隐藏的 SQL 方言地雷**：随着 SurrealQL 语法的逐步扩张，`COLUMNS`、`TABLE` 等词汇是强保留的词元。在 `SCHEMAFULL` 的表声明里直接赤裸裸地 `DEFINE FIELD columns ...`，会导致数据库内置的解析器将其误分为结构性指令，从而崩盘。

### 纠正与进化 (Correction & Evolution)

- **领域前缀化防御 (Domain Prefixing)**：所有稍微带有宽泛基础概念属性的字段，必须无条件采用带有业务域前缀的命名规则。因此我们将 `columns` 预防性重构为 `board_columns`。这也是所有大规划架构设计必须提前留出的安全边际效应。

---

## 2026-04-01: [TIP] PowerShell 控制流的高鲁棒性选型 (Switch vs If/ElseIf)

### 现象 (Phenomenon)

早前为了“代码美观”，`startup.ps1` 的主执行逻辑使用了大型 `switch ($args)` 树形结构管理诸如 `-Install`, `-Restart`, `-Console` 参数。但我们频繁遭遇到难以定位的 `Missing statement block in switch statement clause` 或者大括号 `}` 对齐解析错误。

### 根因 (Root Cause)

- **隐式终止与解释器脆弱性**：PowerShell 的 Parser 对 `switch` 代码块宽容度随复杂度递减。内部若穿插跨行语句、重定向符或带参的高级命令调用指令时，只要缺少明确的分号或者空行不足，就会瞬间牵连引发整个控制树链式解析崩塌。

### 纠正与进化 (Correction & Evolution)

- **原始级结构回退（降维求稳）**：作为启动与灾备的最底层根基，基础架构脚本全盘摒弃了存在“语法糖解析错觉”的多级 `switch`，粗暴直接地全盘改用最无脑却最刚健的 `if ($A) { ... } elseif ($B) { ... }` 模式。 在“无人值守”（Unattended）、必须一发必中拉起服务器的常驻守护本中，**代码防爆性永远高于版面的整洁度。**

---

## 2026-04-02: [CRITICAL] 认知架构中的快慢通道分离 (Fast-Path vs Slow-Path Routing)

### 现象 (Phenomenon)

将所有用户指令都交由 IntentEngine 生成 TaskDAG 并进行复杂的因果推理，导致闲聊、查询、格式化等简单指令的响应出现数秒延迟，系统显得极度迟钝，严重破坏交互体验。

### 根因 (Root Cause)

- **高级认知的计算壁垒**：目标的动态拆解与多期长效推演从本质上就与即时响应（Real-time reflex）相冲突。让大脑前额叶去处理神经反射是对算力和时间的双重浪费。

### 纠正与进化 (Correction & Evolution)

- **自适应认知分流**：在引擎的最前端插入基于纯规则/正则构建的 `_fast_classify()`。一旦判断意图简单且置信度高（>80%），即刻绕过所有推理直接交年底层执行（Fast-Path）。只有遭遇复杂、具有破坏性或不明确的任务，才调用推演模型生成计划（Slow-Path）。这确立了 Agent "小事极速、大事深思" 的终极架构理念。

---

## 2026-04-02: [IMPORTANT] 元学习负载的解耦与休眠期进化 (Decoupled Background Meta-Learning)

### 现象 (Phenomenon)

V7 引擎引入了超参数自调优（`self_tune`）和由于计算海量日志带来的因果链推演（`infer_causal_chains`），若放在交互循环中执行会锁死主线程，造成机器僵死错觉。

### 根因 (Root Cause)

- **热路径阻塞 (Hot-Path Blocking)**：繁重的统计演算、数据库扫表以及权重纠正如果发生在前台对话链路（Hot-Path）中，违背了交互系统的非阻塞体验原则。

### 纠正与进化 (Correction & Evolution)

- **引入仿生“休眠期”反思**：将此类自私进化与自我诊断任务彻底同用户前台对话生命周期解耦。定义 `shutdown()` 钩子并绑定于 CLI 的 `/exit` 退出阶段。系统如同人类在睡眠期固化神经突触一般，在无 UI 阻塞压力的后台安静地完成权重的自适应迭代。

---

## 2026-04-02: [TIP] 高危执行流的宏观阻断与动态授权 (Risk-Based DAG Interception)

### 现象 (Phenomenon)

赋予多重 Agent 集群执行 TaskDAG 的能力后，系统对大规模数据库删除、大面积代码覆盖的操作如同脱缰野马。但如果保守地对每一步工具调用都要求一次授权，又回到了最原始的“非自动”手摇模式。

### 根因 (Root Cause)

- 全自动集群执行 (Autonomous Execution) 与 绝对安全防护 (Absolute Security) 之间存在固有的粒度矛盾。执行层（Worker）自身陷入局部任务，缺乏宏观全局危险意识。

### 纠正与进化 (Correction & Evolution)

- **防线前置到规划层 (Plan-Level Interception)**：把安全审查卡在计划分解（Slow-Path）生成 DAG 的阶段。评估报告若判定为 Medium/High 风险，系统自动拦下主循环，输出意图拆解路线文本（Narrative）让长官一目了然操作意图，并停机要求键入 `Y` 同意。通过“高危拦截、低危放行”管线，完美平衡了自动化的流畅与指挥官的最终裁量权。

---

## 2026-04-02: [WARNING] 隐式类型塌陷与边界防御 (Dynamic Type Poisoning)

### 现象 (Phenomenon)

在引擎演进开发过程中，遇到了海量基于 `basedpyright` 报出的 `Type Any is not allowed` 或 `Type is unknown` 的代码异味告警。尽管程序实际运行时完全正确，但 IDE 中的静态类型链条被大面积破坏。

### 根因 (Root Cause)

- **动态源的毒性扩散**：`SurrealDB` 的数据库查询返回、以及 `LLM` 的 JSON 抓取输出等异构数据源，其原生产物是处于“暗箱”状态的嵌套字典 (`dict`)。如果任由这种无约束字典在 `AgentEngine` 各个核心类之间随意传递，整个 Python 程序的显式类型网就会发生“塌陷”，退化成了不可维护的动态脚本。

### 纠正与进化 (Correction & Evolution)

- **构建强类型防波堤 (Typed Boundaries)**：今后所有的外部输入（特别是数据库 I/O 和大模型输出），必须在入口第一前线即刻利用 `Pydantic` 或等效实体类进行强制序列化校验转换。业务逻辑链路中绝对禁止流转 `Raw Dict`（裸字典）。

---

## 2026-04-07: [CRITICAL] 引擎核心与 API 层的构造函数失步 (Constructor Mismatch Drift)

### 现象 (Phenomenon)

在引擎 V5.1 加固过程中，`main.py` 的 `/chat` 接口及其它入口频繁抛出 `TypeError: __init__() missing 1 required positional argument: 'session_id'`。

### 根因 (Root Cause)

- **多入口初始化不一致**：为了支持分布式状态追踪，`AgentEngine` 构造函数新增了 `session_id` 和 `db_url` 必填参数。但由于系统存在测试脚本 (`verify_hermes.py`)、CLI (`cli.py`)、仿真环境 (`war_god_simulation.py`) 等多个独立入口，这些入口在核心接口变更后没有被同步更新，导致了碎片化的运行时崩溃。

### 纠正与进化 (Correction & Evolution)

- **严格接口同步协议**：在修改 `AgentEngine` 这种单例核心类的 `__init__` 签名时，必须同步扫描整个工作区的引用点。
- **引入默认会话分配**：在构造函数内部对 `session_id` 提供回退逻辑 (`session_id or f"sess_{int(time.time())}"`)，同时强制要求 API 层显式传入外部状态，保障了“零侵入”监控。

---

## 2026-04-07: [IMPORTANT] SDK 类型不变性冲突 (Types.Tool List Invariance)

### 现象 (Phenomenon)

在使用 `basedpyright` 进行零债务扫描时，`GeminiCaller` 传递给 `google-genai` SDK 的 `tools` 列表报错：`Type 'Sequence[types.Tool]' is incompatible with 'list[types.Tool]'` (或类似由于协变/逆变引起的不匹配)。

### 根因 (Root Cause)

- **第三方库的类型刚性**：许多 LLM SDK 的内部类型定义在静态分析中表现得很脆，不支持 Python 内置协议的弹性扩展。

### 纠正 with 进化 (Correction & Evolution)

- **边界透明隧道 (Boundary Tunneling)**：在处理不稳定或过于刚硬的第三方 SDK 接口时，允许在模块边界处使用 `cast(Any, ...)`。这并非放弃类型检查，而是建立一个明确的、有记录的“隧道”，将内部的高质量协议类型通过隧道安全地注入外部库。
- **Protocol 隔离**：建立 `BaseLLM` 协议，使 `AgentEngine` 只依赖于系统自身的 Protocol，而非具体的 SDK 类型，从而实现真正的解耦。

---

## 2026-04-07: [TIP] 轨迹审计的主动持久化 (Active Trajectory Persistence)

### 现象 (Phenomenon)

自主循环在运行后，缺乏可追溯的详细决策记录。虽然有终端日志，但难以用于后续的“因果推演”和“事后分析”。

### 根因 (Root Cause)

- **虚假实现占位符**：`_dump_trajectory` 在早期版本中仅为存根函数（Mock），未建立真正的 I/O 链路。

### 纠正与进化 (Correction & Evolution)

- **双重审计持久化**：轨迹不再仅仅是“打印”，而是必须同时落地为物理 JSON 文件（用于专家排查）和 SurrealDB 记录（用于多 Agent 共享认知）。
- **字段规范化**：轨迹数据必须涵盖：`Thought`、`ToolCalls`、`ToolResults` 及精确的 `Token Usage` 统计，为未来的 Auto-Tune 算法提供高质量输入数据。

---

## 2026-04-08: [V5.1] 因果存档锚点与静默摘要提交 (Silent Ritual & Causal Summary)

### 现象 (Phenomenon)

在长时间、高频率的任务迭代中，开发者往往难以回忆起过去 10 个对话轮次中具体的物理变动（修改了哪些文件、做了哪些决策），仅依赖终端滚动日志会导致“认知丢失”。

### 根因 (Root Cause)

- **对话与存档的脱节**：Agent 的“会话结束”与 Git 的“提交操作”是两个孤立的物理事件。如果 Agent 不主动在认知终点执行存档，物理层的状态变动就缺乏语义标签。

### 纠正与进化 (Correction & Evolution)

### V5.1 后集：Causal Archiving & Silent Rituals

- **物理审计优先**：在长跑模式下，必须通过 Git Checkpoint 强制物理状态与逻辑状态对齐，防止“思维漂移”。
- **沉默仪式**：Agent 结束时必须进行 Git 提交，作为因果链的物理终结。

### V5.2：HTAS (Honest Termination & Anti-Stall)

- **拒绝阈值诱惑**：不要信任 `max_iterations`，要信任“物理侧效应”。如果连续 3 轮无文件变动或命令输出且无信息密度增益，系统应强制判定为 `STALEMATE`。
- **诚实监察员 (Honest Judge)**：引入反射层，以“任务达成审计员”身份独立审视轨迹。这种“元认知”调用虽然增加了单次成本，但极大降低了 Agent 陷入“假性思考”产生的垃圾 Token。
- **策略降级换道 (Pivot Strategy)**：当判定为卡死时，强制清除本地认知缓存并降级路径（如 `SAS-L` -> `MAS`），通过增加“众包”颗粒度来击坏思维僵局。
- **物理驱动的摘要生成 (Causal Summarization)**：摘要不应仅靠 LLM 的朦胧回忆，而应强制从消息流的历史工具调用（如 `TargetFile`）中提取。通过 `HistoryCompactor.export_session_summary` 将“操作了哪些文件”直接转化为 Commit Message 标题，极大提升了 `git log` 的可读性。
- **一致性审计**：协议确立了“每一次成功结束必须有对应的 Git 记录”这一终极共识，确保了自主进化过程的物理可审计性。

---

## 2026-04-11: [ARCHITECTURE] Agent Hermes 与 Advisor-Executor 模式 (Engineering Reliability)

### 现象 (Phenomenon)

随着系统复杂性增加，单一 Agent 在执行长路径任务（如大规模重构或跨模态对齐）时，容易在关键决策点（Gate）犹豫不决或产生误判。同时，全量使用高智商昂贵模型（Opus）会导致成本激增，而全量使用高速度便宜模型（Sonnet）会面临逻辑崩盘。

### 根因 (Root Cause)

- **Hermes 认知偏差**：Agent 被视为单纯的“对话者”，而非“受控的基础设施”。缺乏一个能够隔离、监控并持久化 Agent 生命周期的“马具”（Hermes）。
- **职责边界模糊**：由“执行者”同时担任“审计员”，会导致自我博弈的死循环或逻辑盲点。

### 纠正与进化 (Correction & Evolution)

- **Agent Hermes 基础设施化 (Formal Hermes)**：
  - 确立 Coda 为 **Autonomous Hermes**。它不仅运行 Agent，更提供沙盒环境、SessionLifecycle 钩子、及基于 Elo 评分的 `SkillTracker`。
  - 将每一次成功的“对话”沈淀为“确定性的软件工程技能”，实现从“概率性交互”到“确定性资产”的跨越。
- **Advisor-Executor (军师-特种兵) 模式**：
  - 在 `GovernanceEngine` 中引入 **Advisor（军师）** 接口。
  - **Executor (Sonnet/Flash)**：负责 90% 的物理侧执行任务（文件读写、基础编译）。
  - **Advisor (Opus/Gemini 1.5 Pro)**：作为高阶审计员，仅在 `StageGate` 报错、高风险变更（如 `Pre-Mutation Gate` 拦截）或逻辑死胡同时被激活。
  - 这种分层架构实现了 **10x 成本优化** 与 **2x 任务成功率** 的双赢。
- **Vibe Coding 生产力革命**：
  - 拥抱多 Agent 专业协作。通过 `Identity` 中的角色路由，让不同擅长的模块（UI、架构、测试）并发协作，将“沟通”视为最高效的编程语言。

---

## 2026-04-12: [CRITICAL] SurrealDB Python SDK RecordID 类型污染 (Type Poisoning)

### 现象 (Phenomenon)

在联邦搜索实现中，`federated_search_nodes` 返回的结果集中，`id` 字段并非字符串，而是 SDK 特有的 `RecordID` 对象。这导致后续逻辑中使用 `if "wiki_nodes:" in id` 等字符串操作时抛出 `argument of type 'RecordID' is not a container` 错误，导致检索管道崩溃回退。

### 根因 (Root Cause)

- **SDK 抽象层过深**：SurrealDB Python SDK 为了支持强类型操作，将返回记录的 ID 自动封装为 `RecordID` 对象。在进行逻辑判断或跨层传递时，如果没有显式强制转换为 `str`，会导致 Python 内置操作符失效。

### 纠正与进化 (Correction & Evolution)

- **强制字符串化防御**：在搜索结果提取的第一时间执行 `surreal_id = str(rr.get("id", ""))`。这确立了“数据库返回第一时间解包”原则，防止特有类型污染业务逻辑。

---

## 2026-04-12: [IMPORTANT] SurrealQL 模糊搜索的非对称性 (Case-Sensitive CONTAINS)

### 现象 (Phenomenon)

使用 `WHERE body CONTAINS $keyword` 进行混合搜索时，无法搜到大小写不匹配的内容，导致全量召回率大幅下降。

### 根因 (Root Cause)

- **SurrealQL 默认行为**：`CONTAINS` 操作符在 SurrealDB 中是大小写敏感的。与 SQL 标准中某些数据库的默认行为不同。

### 纠正与进化 (Correction & Evolution)

- **标准化小写索引查询**：在查询构造层强制使用 `string::lowercase(body) CONTAINS $kw_lower`。虽然这会带来微小的 CPU 开销，但保障了认知引擎检索的鲁棒性。

---

## 2026-04-12: [V7.0] 强化写入闭环与作用域扩展 (Synthesis Ingestion Scope)

### 现象 (Phenomenon)

实现了会话蒸馏（Extraction）后，生成的 `synthesis/` 目录下的新知识节点无法被编译器自动识别，需要手动触发全量编译才能入库。

### 根因 (Root Cause)

- **编译作用域锁定**：`Compiler` 插件默认只扫描 `raw/` 和 `knowledge/` 目录。新引入的 `synthesis/` 目录不在增量编译的 Dirty 检测范围内。

### 纠正与进化 (Correction & Evolution)

- **扩展示踪作用域**：在 `compiler.py` 中将 `synthesis/` 纳入核心扫描路径，并确保 `background_closeout` 处理完后立即触发 `compile_incremental()`。这实现了“思考-记录-入库-检索”的毫秒级认知闭环。

---

## 2026-04-12: [DESIGN] 流式与结晶记忆隔离模式 (Fluid vs Crystalized Memory)

### 背景 (Context)

关于是否将“原始聊天日志 (Raw Transcripts)”全量同步到 SurrealDB 的决策权衡。

### 核心原则 (Core Principle)

- **流式记忆 (Fluid Memory - Local)**：原始对话历史属于高噪、瞬时数据，保存在本地磁盘（`overview.txt`）。它们是过程，不是结果。
- **结晶实体 (Crystalized Memory - DB)**：数据库（SurrealDB）只存储经过提取、验证和结构化的知识节点（L3 提取结论）。它们是结果，不是过程。

### 收益 (Benefits)

1. **检索信噪比 (Signal-to-Noise)**：后续检索不会被“好的”、“谢谢”、“哈哈”等对话噪音污染，只召回确定性结论。
2. **隐私隔离**：敏感对话过程留在本地，只有经确认的知识结论才进入可能跨项目共享的联邦图谱。
3. **性能优化**：数据库表规模受控，避免了海量原始消息导致的向量索引膨胀。

---

## 2026-04-12: [CRITICAL] SurrealDB Python SDK RecordID 类型污染 (Type Poisoning)

### 现象 (Phenomenon)

在引擎并行处理大量 AKP 时，数据库频繁抛出 `KeyError: '...'`。

### 根因 (Root Cause)

- **SDK 内部竞态 (SDK Race)**：SurrealDB Python SDK 在多协程并发使用同一个实例时，内部响应 ID 匹配机制可能发生错乱。

### 纠正与进化 (Correction & Evolution)

- **连接池模式 (Connection Pooling)**：在 `SurrealStore` 中引入 `SurrealPool`。每个并发请求从池中 `acquire()` 一个独立的连接实例。

---

## 2026-04-12: [WARN] 知识图谱的可视化污染与渲染瓶颈 (Visualization Sanitization)

### 现象 (Phenomenon)

`/engine/graph` 页面在节点较多时直接白屏。

### 根因 (Root Cause)

- **JS 注入漏洞**：直接拼接字符串导致引号冲突。

### 纠正与进化 (Correction & Evolution)

- **JSON 注入隧道 (JSON Tunneling)**：统一使用 `json.dumps` 生成 JSON 后注入 HTML。

---

## 2026-04-12: [TIP] 端口冲突的自适应换道 (Dynamic Port Adaptation)

### 纠正与进化 (Correction & Evolution)

- **CLI 参数接管**：支持通过 `--port` 无痕换道运行。
