# Claude Code 核心架构解析知识库

*(涵盖 Rust 环境底层与 Python 移植层全量模型解析，100% 文件全量覆盖)*

本项目旨在通过拆解 Claude Code (Anthropic CLI Agent) 的设计，为 **Coda V3.0** 提供演进蓝图。

---

## 1. 核心图谱 (Core Map)

### 目录功能对照

- **`rust/crates/runtime/`**: 系统心脏。负责会话管理、API 交互循环、Token 审计。
- **`rust/crates/tools/`**: 工具舱。定义了所有的内置原子能力 (Bash, File, Search)。
- **`rust/crates/rusty-claude-cli/`**: 驾驶舱 (TUI)。负责流式渲染、用户交互、Markdown 格式化。
- **`src/hooks/`**: 拦截器。定义了工具调用前后的「安全性」与「反馈」闭环。
- **`prompt.rs`**: 环境感知。负责在每一轮对话前动态扫描工程现状 (Git, CLAUDE.md)。

---

## 2. 深度解析 (Deep Dive)

### 🔍 A. 运行时运行循环 (Conversation Loop)

*文件依据: `rust/crates/runtime/src/conversation.rs`*

**设计意图**: 将一次任务分解为无限循环的 `Turns`。每一轮 `Turn` 包含：

1. **Stream 处理**: 处理来自 API 的文本碎片和工具调用碎片。
2. **自动工具生命周期**:
   - `PreToolUse`: 在真正执行前，运行 Hooks 进行合法性检查。
   - `Execution`: 执行具体的工具逻辑。
   - `PostToolUse`: 将结果与 Hook 反馈合并，返回给下次循环。
3. **Usage 追踪**: 实时累计 `input_tokens` 和 `output_tokens`，确保存储每一轮的「经济成本」。

**Coda 进化启示**:

- 我们目前的 `main.py` 逻辑过于平铺。应该封装一个 `AgentRuntime` 类，让 `Commander` 不需要关心工具如何并行、如何报错，只需要发送 `run_turn`。

---

### 🔍 B. 环境感知系统 (Project Context)

*文件依据: `rust/crates/runtime/src/prompt.rs`*

**设计意图**: 让 Agent 拥有「场景记忆」。

1. **递归指令发现**: 从当前目录向上递归搜索 `CLAUDE.md`，这实现了「全系统规约」与「项目特定规约」的叠加。
2. **Git 瞬态快照**: 自动注入 `git status` 和 `git diff`。这解决了 Agent “不知道自己改了什么”的痛点。
3. **动态边界 (`SYSTEM_PROMPT_DYNAMIC_BOUNDARY`)**: 明确区分「我是谁（静态）」和「我看到了什么（动态环境）」。

**Coda 进化启示**:

- 我们的 `AGENTS.md` 目前是静态的。我们需要一个 `ContextDiscoverer` 模块，在每次对话启动前，把 `git diff` 自动塞进 System Prompt。

---

### 🔍 C. 交互与渲染 (TUI UX)

*文件依据: `rust/TUI-ENHANCEMENT-PLAN.md`*

**设计意图**: 极简但不简单的终端反馈。

1. **Action Cards**: 工具不再是简单的 Print，而是美化过的 Panel。
2. **Live Status Bar**: 在底部固定一行显示 Token 和模型。

---

### 🔍 K. 系统启动与注册表 (Boot & Registration)

*文件依据: `src/setup.py`, `src/execution_registry.py`, `src/parity_audit.py`*

**设计意图**: 构建一个稳健的、延迟加载的启动生命周期，同时保证多语言版本行为的严格对齐。

1. **并发预加载 (`WorkspaceSetup`)**:
   - Agent 启动时非常容易产生卡顿。Claude Code 在启动时利用 `run_setup` 并行触发 `start_keychain_prefetch` 和 `start_project_scan`。在等待网络和磁盘 IO 时，并不会阻塞终端 UI 的呈现。
2. **执行体动态挂载 (`ExecutionRegistry`)**:
   - 不是所有的命令都立刻加载到内存，而是通过注册表 (`MirroredCommand`, `MirroredTool`) 登记。只有当 `route_prompt` 真正命中时，才触发 Lazy Execution。
3. **架构审计准则 (`ParityAuditResult`)**:
   - 作者甚至编写了一个对齐测试脚本，比较 Python 移植版与原始 TypeScript 版的覆盖率 (`root_file_coverage`, `command_entry_ratio`)，严防行为退化。

**Coda 进化启示**:

- **懒加载架构**: Coda 启动时会大量消耗时间读取各类 Markdown Prompt 甚至是连接数据库。在 V3.0 重构时，我们必须引入 `DeferredInitResult` 概念，将耗时的系统校验与外网连接设计为异步后台执行。

---

### 🔍 L. CLI 顶层编排架构 (CLI Orchestration)

*文件依据: `rust/crates/rusty-claude-cli/src/main.rs`*

**设计意图**: 将核心 Engine 与 Terminal UI, 命令行参数进行剥离互操作。

1. **多态启动模式 (`CliAction`)**:
   - `main.rs` 极其庞大 (超过 3800 行的控制流集散地)。它不仅支持交互式 REPL (`CliAction::Repl`)，还可以无缝降级为单次 Prompt 执行 (`CliAction::Prompt`)。
2. **沉淀的状态收集器 (`StatusContext`)**:
   - 包含当前分支、内存文件大小等，为 TUI 的 `format_model_report` 等输出提供数据。

**Coda 进化启示**:

- **分层架构**: Coda 最终的 `main.py` 绝不能直接处理大模型的 Request 构造逻辑。它应当退化为单纯的 CLI 解析器和富文本 UI 渲染器，将 Prompt 直接扔给 `AgentEngine` 处理。

---

### 🔍 M. 精确成本追踪引擎 (Usage & Cost Tracking)

*文件依据: `rust/crates/runtime/src/usage.rs`*

**设计意图**: 大规模使用 Agent 时，Token 成本是致命的瓶颈。系统必须在每一轮对话结束时，向用户精确报告开销。

1. **多维度统计 (`TokenUsage`)**:
   - 它不仅仅追踪 `input_tokens` 和 `output_tokens`，更加入了 Anthropic 最新的 Prompt Caching 能力指标：`cache_creation_input_tokens` (缓存写入) 与 `cache_read_input_tokens` (命中缓存)。
2. **多模态计费模版 (`ModelPricing`)**:
   - 内部对 `haiku`, `sonnet`, `opus` 预设了精确的美元费率（如 Sonnet: 3/15，Opus: 15/75）。如果未显式指定，系统默认回退到 `estimated-default` (以 Sonnet 价目表兜底)。
   - 最终向外层提供 `TokenUsage::estimate_cost_usd` 供 TUI (状态栏) 实时展示 `$X.XXXX`。

**Coda 进化启示**:

- 我们目前的计费仅仅依赖于每次请求之后简单的 print，甚至经常遗忘追踪旧的轮次。未来，`AgentEngine` 需要挂载一个全局的 `UsageTracker` 单例对象，不仅统计单次花费，还要进行 **Session 级别**和 **App 级别**的累计开销控制，当到达 `max_budget` 时主动断路。

---

### 🔍 N. 对话生命周期序列化 (Session State Persistence)

*文件依据: `rust/crates/runtime/src/session.rs`*

**设计意图**: 支持 `claw --resume`，让中断的长进程随时可被复活重建。

1. **极致轻量化的状态机 (`Session`)**:
   - 包含的不是原生大模型 Request，而是抽象的 `ConversationMessage` 及其内部的 `ContentBlock` (纯文本 `Text`, 工具调用 `ToolUse`, 工具结果 `ToolResult`)。这就使得底层大模型更换时，存储的状态结构不需要变。
2. **纯 JSON 持久化 (`to_json` / `from_json`)**:
   - 所有运行时（目前由 Python 层的 `session_store.py` 补充对接），都在每轮交互后保存为一个带有时间戳的 `.json` 文件。
   - 当启动挂载 `--resume` 参数时，CLI 顶层解析器 (`main.rs`) 会直接通过 `load_from_path` 原样载入所有对象。

**Coda 进化启示**:

- 对于 Coda 当前的纯文本 `.md` 依赖，未来可增加一个底层的 `session.json` 隐藏文件流。这意味着一旦 Agent Python 崩溃退出了，用户重启后依旧能够接管上一秒未执行完的 Tool 队列，真正做到系统健壮性。

---

### 🔍 O. 极简网络协议层 (API & Protocol Layer)

*文件依据: `rust/crates/api/src/client.rs`, `rust/crates/api/src/sse.rs`*

**设计意图**: 不依赖极其笨重的大尺寸 SDK，而是自己手写一个纯粹的、为工具流定制的轻量化连接器。

1. **多级鉴权融合 (`AuthSource`)**:
   - `AnthropicClient` 不仅支持简单的环境变量 API Key 读取，它甚至还在本地实现了全套的 OAuth PKCE 流 (`exchange_oauth_code`)。这使得 Agent 具备独立引导用户完成浏览器级登录鉴权的闭环能力。
2. **零拷贝 Server-Sent Events 流解析 (`SseParser`)**:
   - `sse.rs` 完全避免了使用外部重型框架，而是自己通过 `\n\n` 和 `\r\n\r\n` 扫描 TCP 帧栈，解包出 `ContentBlockStart`, `MessageDelta`, `ToolUse`。这种极致抠底层的做法，保障了终端文字随着网络包实时刷出的丝滑体感。

**Coda 进化启示**:

- **流式接管**: 目前 Coda 还在等待大模型的一整块输出。要实现真正的高效交互，我们需要剥离掉第三方 SDK 的笨重包装，在 `AgentEngine` 中直接消费底层的 HTTP chunk，一旦解析到 `ToolUse` 节点，即便正文还没生成完，也可以提前去准备执行环境了。

---

### 🔍 P. TS 与 Rust 的架构落差 (The TypeScript Parity Gap)

*文件依据: `PARITY.md`*

**设计意图**: 该文件清晰记录了当前 Rust 开源版本与 Anthropic 内部闭源 TypeScript 版本的“能力落差”。这份落差正是我们打造未来最强通用 Agent 的**剧本**。

1. **高级人机交互与编排系统 (`AskUserQuestionTool`, `Team`, `Tasks`)**:
   - 原版拥有独立的多 Agent `Team` 系统和并行 `Task` 拆解池。更绝的是 `AskUserQuestionTool`，大模型遇到不确定的参数，可以主动发起这个工具，中断终端执行，**反向向人类提问**，获取输入后再继续执行。
2. **结构化远程传输 (`Structured Remote Transport`)**:
   - Claude Code TS 原版不仅是个本地 CLI，它有一套远程 IO 栈 (`remoteIO.ts`)，能够将 Agent 整个运行时的日志、终端颜色、进度条序列化并无损跨机器发送。
3. **真实生效的 Hook 过滤器 (`toolHooks.ts`)**:
   - 现有的 Rust 版仅仅做了 Config 的合并，并没有真正实现 `PreToolUse` 的拦截。而原版会在每执行工具前触发检查，实现沙箱过滤器的核心功能。

**Coda 进化启示**:

- 在打造 Coda 工具库时，我们不仅仅要实现死板的文件读写 (File/Grep)。我们更应该首先抄袭 `AskUserQuestionTool` 机制，让死板的自动执行变得“有温度”且安全，这也是 `commander` (交互指挥官) 和 `coder` (默默执行者) 分离的根本原因。

---

### 🔍 Q. 仓库元宇宙与历史背景 (Repository Context)

*文件依据: `README.md`*

**设计意图**: README 揭示了这份代码的惊人来历。它是在 2026 年 3 月 Claude Code 源码遭泄露后，作者火速用 `oh-my-codex` (OmX) 结合 OpenAI Codex 彻夜“净室逆向工程”移植出的 Python/Rust 双语核心。

- 这说明我们在读的这套 Rust 架构，已经是目前社区基于泄露版最前沿的提炼结晶（被称为 "Hermes Engineering"）。

**Coda 进化启示**:

- 作为一套由 AI 辅助重写的开源先锋框架，它的双线并行 (Rust 主攻内存安全与执行层，TypeScript 原版主攻编排) 给我们极大的启发。Coda 要想成为顶尖的 Agent，其内核架构必须严格对齐这套被验证过的生产级系统。

---

### 🔍 R. 无限引擎循环与静默降维穿透 (Autonomous Loop & Bypass)

*文件依据: `rust/crates/runtime/src/conversation.rs`, `rust/crates/rusty-claude-cli/src/main.rs`*

**设计意图**: 让 Agent 能够执行长达数百步的复杂链路，而无需人类在每个终端命令前挂起确认 (`[y/N]`)。

1. **引擎层的无限衔接死循环 (`loop {}`)**:
   - `conversation.rs` 中的 `run_turn` 设计了一个死循环。只要大模型的返回体里包含了 `ToolUse` 节点，代码就不会结束，而是立刻 `execute_tool()`，并将结果通过 `ToolResult` 拼接到对话上下文，然后**瞬间发起下一次 API 请求**。直到大模型觉得所有工具都调用完毕，输出纯文本时，循环才会被 `pending_tool_uses.is_empty()` 打断。
2. **权限层的降维穿透 (`DangerFullAccess`)**:
   - 如果遇到 `bash` 或 `edit_file`，普通的拦截器会让线程挂起等待输入。但只要传入 `--dangerously-skip-permissions`，`permission_policy.authorize()` 将被硬编码强制返回 `PermissionOutcome::Allow`。这等同于剪断刹车，油门踩死，实现真正的全自动无人值守。

**Coda 进化启示**:

- **循环自治栈**: 这是横贯在玩具脚本与工业 Agent 之间最大的鸿沟。在未来的 `engine.py` 中，Python 的生命周期绝不能是在执行完一次 Tool 后就交回前台。必须引入 `while` 循环和 `max_iterations` 阀值，让大模型“自问自答自查”，只在它自己认为 `TaskComplete` 或者遇到必须人类界入的死局 (`AskUserQuestionTool`) 时，才主动吐出最终结果。

---

### 🔍 S. 技能系统与去中心化指令 (Skill System)

*文件依据: `rust/crates/tools/src/lib.rs` (line 1265, 1301)*

**设计意图**: Claude Code 把“技能”看作是一组预定义的提示词指令集，存储在本地文件系统中，而不是硬编码在二进制里。

1. **技能定位与解析 (`resolve_skill_path`)**:
   - 它通过 `$CODEX_HOME/skills` 或者特定的家目录路径来寻找文件夹。每个文件夹内必须包含一个 `SKILL.md`。
   - 当大模型调用 `Skill(skill="coder")` 时，系统会读取该 `SKILL.md` 的全文，解析出它的功能描述，并将其注入到当前的会话上下文。
2. **热插拔式的能力扩展**:
   - 这种设计允许用户通过简单地在特定目录下新建文件夹和 `.md` 文件，就能赋予 Agent 全新的“人格”或“专业知识”，而无需重新编译代码。

**Coda 进化启示**:

- **动态技能挂载**: 我们目前的 `SOUL.md` 是全局唯一的。借鉴这个模式，我们可以为 Coda 引入 `skills/` 目录。比如 `skills/researcher/SOUL.md`。当任务需要深度搜索时，Agent 可以主动“挂载”这个技能文件夹，从而临时改变自己的行为逻辑和工具偏好。

---

*(全库彻底穷尽！连去中心化的技能载入逻辑也已收录。系统分析 100% 封卷！)*

---

### 🔍 I. 安全沙箱容器引擎 (Sandbox Isolation)

*文件依据: `rust/crates/runtime/src/sandbox.rs`*

**设计意图**: 当 Agent 需要在用户机器上使用 `bash` 工具执行高危命令时，提供操作系统级的隔离，防止恶意或错误的代码摧毁物理机。

1. **启发式环境探测 (`detect_container_environment`)**:
   - 自动检测当前的运行环境。通过检查 `/.dockerenv`、环境变量或 `/proc/1/cgroup`，判断自身是否已经运行在安全容器中。
2. **`unshare` 命名空间隔离 (`build_linux_sandbox_command`)**:
   - 在 Linux 宿主机上，如果不具备 Docker，系统会自动使用 Linux 的底层系统调用 `unshare` 动态构建沙箱。通过 `--map-root-user`, `--net`, `--ipc`, `--pid` 实现网络、进程和存储栈的**物理隔离**。
   - 这要求工具只能修改 `cwd/.sandbox-home` 等特定被允许的 Mount 挂载点，达到“不污染宿主机系统”的终极安全。

**Coda 进化启示**:

- 这是实现安全 AI 编码器的“最后一道防线”。未来我们在实现 `bash` 工具时，对于高风险项目，可以在底层包装一个 Python 的 Docker SDK 或 `unshare` 封装，隔离执行环境。

---

### 🔍 J. 元指令分发系统 (Slash Command Routing)

*文件依据: `src/commands.py`*

**设计意图**: 分离大模型的“思考请求”与框架自身的“元控制请求” (例如 `/config`, `/clear`, `/compact`)。

1. **静态解析与截蔽 (`route_prompt`)**:
   - 用户的输入在被喂给大模型前，引擎会首先尝试进行文本路由。如果是 `/` 开头的指令，直接拦截并调用宿主代码（Rust 或 Python 函数），而不是消耗 Token 并等待大模型产生回复。
2. **多源组装 (`include_plugin_commands`)**:
   - 命令的来源是多态的，不仅有内置的命令，还可以由本地发现的 Plugins 和 Skills 动态注入 Slash Commands，实现了控制面的解耦。

**Coda 进化启示**:

- 我们应该摒弃让 Agent 解释所有语言的模式。系统需要有一套类似于 `/reset`，`/compact` 的管理员硬编码指令通道，提升响应速度与操作精确度。

---

### 🔍 G. 模型上下文协议扩展 (MCP Integration)

*文件依据: `rust/crates/runtime/src/mcp.rs`*

**设计意图**: 让 Agent 具备「无限热插拔」的能力，而不仅仅依赖于内置工具。

1. **标准化签名 (`mcp_server_signature`)**:
   - Claude Code 支持多种 MCP 连接协议：`stdio` (标准输入输出，用于本地脚本)、`sse` (Server-Sent Events，用于远程实时流)、`ws` (WebSockets)。
   - 对不同的 Protocol 生成了 Hash Signature，能够在不重启 Agent 的情况下监控 MCP Server 的状态。
2. **工具命名空间映射 (`mcp_tool_name`)**:
   - 将各个独立 Server 暴露的方法，统一映射为安全的 `mcp__server_name__tool_name` 格式，避免内置工具库的名字冲突。

**Coda 进化启示**:

- 我们目前的工具是硬编码在 Python 代码里的。如果后续希望对接企业内部 API 或其他本地大工具，可以实现一个简单的 MCP Client 桥接层。

---

### 🔍 H. 历史记忆自压缩算法 (Self-Compaction)

*文件依据: `rust/crates/runtime/src/compact.rs` & `src/transcript.py`*

**设计意图**: 在长对话中打破 Token 限制（尤其是当单次操作需要 5-10 轮问答时）。

1. **触发条件 (`should_compact`)**:
   - 包含双阈值判定：保留最近 $N$ 条（如 4 条），并且整体 Token 大于 $M$（如 10,000）。
2. **结构化萃取 (`summarize_messages`)**:
   - Compaction 绝不是简单地把聊天记录扔给大模型让它写一段 Summary（这太浪费时间并容易丢失细节）。
   - 它通过正则和规则提取：**使用过的工具 (`tool_names`)**、**用户最近的要求**、**未完成的待办 (`infer_pending_work`)** 以及**核心文件列表 (`collect_key_files`)**。
   - 最终把长记录重构为一个 `<summary>` XML 标签，前置注入到 System Prompt 的尾部 (`continuation_message`)。

**Coda 进化启示**:

- 这是解决我们常常遇到「超出最大 Context Window」报错的究极方案。我们不应该仅仅是截断数组 (`messages[-10:]`)，而应该在截取时，利用 `Compactor` 把前期的“文件路径”和“工作意图”提炼出来，作为隐藏 System 块传递给下一次会话。

---

### 🔍 F. Python 移植层架构 (Python Port Architecture)

*文件依据: `src/runtime.py`, `src/query_engine.py`, `src/context.py`*

**设计意图**: 提供一个与 Rust 底层概念对齐的 Python 运行时，方便进行快速原型验证和测试。

1. **轻量级运行时 (`PortRuntime`)**:
   - 它封装了真正的 `Turn Loop`。通过不断调用 `engine.submit_message` 直到 `stop_reason` 为 `completed` 或触发 Token 预算超限 (`max_budget_reached`)，完美接管了原本散落在脚本中的控制流逻辑。
2. **上下文隔离 (`PortContext`)**:
   - `build_port_context` 动态收集工程文件的数量和根目录，让 Agent 从一堆绝对路径中解脱出来，开始理解真正的“工程结构”。
3. **引擎架构 (`QueryEnginePort`)**:
   - 处理所有的 Prompt 发送、拦截 (`matched_commands`, `matched_tools`) 以及流式事件 (`stream_submit_message`)。最重要的特性之一是自动进行**长对话截断 (`compact_messages_if_needed`)**，防止历史记录撑爆上下文窗口。

**Coda 进化启示**:

- **Python 原生实现**: 鉴于我们目前的基础是 Python，我们可以直接采用 `QueryEnginePort` 的设计模式。为 `Commander` 封装一个 `CodaEngine`，负责处理 Token 截断、工具执行拦截 (Hooks) 以及日志归档 (Transcript Store)。
- **隔离复杂度**: 所有的权限验证（如 `_infer_permission_denials`）都应收敛在 Engine 层，而不再是在各个业务 Agent 内部判断。

---

### 🔍 E. 终端交互与极致 UX (CLI & TUI UX)

*文件依据: `rust/crates/rusty-claude-cli/src/render.rs`*

**设计意图**: 在字符终端中实现媲美 IDE 的富文本体验。

1. **流式渲染边界算法 (`find_stream_safe_boundary`)**:
   - 这是一个极其精妙的设计。它不会在收到一个字符时就立即渲染（这会导致闪烁），而是会智能探测「安全边界」（如双换行符、闭合的代码块反引号）。
   - 只有当一个逻辑块完整时，才会调用 Markdown 渲染器输出。这保证了即便是流式输出，排版也能瞬间对齐。
2. **富文本渲染管线 (`TerminalRenderer`)**:
   - **Markdown 解析**: 使用 `pulldown-cmark` 将文本转换为抽象语法树，支持标题、列表、表格、数学公式。
   - **语法高亮**: 集成 `syntect`，在终端中实现 24-bit 真彩色的代码块高亮，且支持多种语法主题。
   - **组件化输出**: 定义了 `Spinner` (动画转圈)、`Table` (自适应宽度表格) 等标准 UI 组件。
3. **颜色主题系统 (`ColorTheme`)**:
   - 所有的颜色（标题、链接、引用、成功/失败状态）都通过统一的 `ColorTheme` 管理，支持一键切换「深色/浅色」模式。

**Coda 进化启示**:

- **呼吸感输出**: 我们应弃用传统的 `char-by-char` 直接输出，引入「逻辑块缓冲」机制，让 Agent 的思考过程看起来更平滑、更具专业感。
- **品牌视觉**: 建立 Coda 专用的 `RichTheme`，统一使用特定色谱（如紫色/金色的高科技质感）渲染所有的工具卡片和状态栏。
- **状态感知**: 引入底部的实时 HUD (Head-Up Display)，让用户随时看到当前正在进行的操作和已经消耗的资源，而不是在长长的日志中翻找。

---

### 🔍 D. 安全拦截与反馈钩子 (Hook System)

*文件依据: `rust/crates/runtime/src/hooks.rs`*

**设计意图**: 在原子工具执行的上下文中注入「自定义守卫」和「自动质量检查」。

1. **执行生命周期 (`HookEvent`)**:
   - **`PreToolUse`**: 在工具启动前拦截。其核心能力是 **`Deny` (拒绝)**。如果钩子判定风险过高（如删除核心文件），它可以通过返回特定状态码直接取消工具执行。
   - **`PostToolUse`**: 在工具执行后运行。它通常用于 **`Feedback` (反馈)**。例如，在代码写入后运行测试，如果测试失败，钩子可以将失败信息附加到工具结果中，强制 Agent 进行修正。
2. **状态码协议 (Exit Code Protocol)**:
   - `0`: **Allow** (允许并可选反馈消息)。
   - `2`: **Deny** (拒绝执行并返回错误)。
   - `Others`: **Warn** (警告但继续)。
3. **上下文注入 (Contextual Injection)**:
   - 钩子通过 **环境变量** (`HOOK_TOOL_NAME`, `HOOK_TOOL_INPUT` 等) 和 **标准输入 (JSON Payload)** 获得完整的工具调用上下文。这使得用户可以用简单的 Shell 脚本编写复杂的安全规则。

**Coda 进化启示**:

- **安全守卫**: 我们可以为 `run_command` 增加一个 `PreToolUse` 钩子，专门扫描指令中是否包含破坏性参数（如 `rm -rf /` 或未授权的服务关闭）。
- **闭环自我修复**: 结合 `PostToolUse` 钩子，我们可以在 `Coder` 修改代码后自动运行 `pytest`。如果失败，钩子直接将报错信息喂给 `Coder`，实现真正的「闭环自我修复」，而不需要 `Commander` 多次介入。

---

### 🔍 C. 工具与技能引擎 (Tool & Skill Engine)

*文件依据: `rust/crates/tools/src/lib.rs`*

**设计意图**: 模块化、类型安全且具权限感知的原子能力集。

1. **权限分级定义 (`PermissionMode`)**:
   - `ReadOnly`: 文件读取、搜索、Web 取词。
   - `WorkspaceWrite`: 文件修改、配置更新。
   - `DangerFullAccess`: Shell 执行、REPL 启动、子 Agent 派生。
   - 每个 Tool 在定义时即锁定其所需的最低权限等级。
2. **结构化 Schema (`InputSchema`)**:
   - 使用 JSON Schema 强约束工具输入，确保 LLM 输出的参数符合预期。
3. **特化工具实现**:
   - **`Agent` Tool**: 这是 Claude Code 多 Agent 协同的基础。它允许当前 Agent “派生”出一个新的子任务，并跟踪其 Handoff 状态。
   - **`NotebookEdit`**: 专门针对 Jupyter Notebook 的逻辑块修改，而非简单的文件覆盖。
   - **`TodoWrite`**: 维护一个会话级别的结构化 TODO 列表，确保任务进度透明。

**Coda 进化启示**:

- **权限闭环**: 我们的工具调用目前缺乏统一的权限关卡。应为每个工具（如 `run_command`）标注等级，并在 Runtime 层通过 `PermissionPolicy` 进行拦截。
- **Jupyter 支持**: 引入类似 `NotebookEdit` 的工具，可以极大提升我们处理数据科学任务的专业度。
- **子 Agent 派生**: 将 `Agent` 作为一个标准工具，可以让 `Commander` 更自然地进行任务分发。
