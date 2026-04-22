"""
Coda Base Types — Core Shared Types (Pillar 0)
基础类型定义: 旨在打破循环依赖，提供全引擎通用的 Enum 与 Dataclasses。
"""

from __future__ import annotations

from collections.abc import Sequence, Mapping
from enum import Enum
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import TypedDict, Protocol, runtime_checkable, cast
import time
import re
import json
import uuid


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_EXECUTING = "tool_executing"
    WAITING_USER = "waiting_user"
    SELF_HEALING = "self_healing"
    QA_VERIFYING = "qa_verifying"
    RUNNING = "running"
    ERROR = "error"
    TERMINATED = "terminated"


class LoopPhase(str, Enum):
    INIT = "init"
    PROMPT_BUILD = "prompt_build"
    LLM_CALL = "llm_call"
    TOOL_DISPATCH = "tool_dispatch"
    POST_TOOL = "post_tool"
    COMPACTION = "compaction"
    REFLECTION = "reflection"
    DONE = "done"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    # Aliases for compatibility
    IN_PROGRESS = "running"
    DONE = "completed"


class ExecutionPath(str, Enum):
    """[V5.1] 认知执行路径 (DPI 理论)。"""
    SAS_L = "sas_l"     # Single-Agent Long-Thinking (Priority)
    MAS = "mas"         # Multi-Agent Swarm (Fallback for high noise)


class TerminationSignal(str, Enum):
    """[V5.1] HTAS 终结信号。"""
    CONTINUE = "continue"           # 继续执行
    CONVERGED = "converged"         # 目标已达成，强制结束
    STALEMATE = "stalemate"         # 思维陷于僵局，建议跳过或求助
    PIVOT = "pivot"                 # 策略失效，需切换 MAS/SAS 路径


@dataclass
class TokenUsage:
    """精确成本与用量追踪 (Pillar 9)"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_cost_usd: float = 0.0
    
    # [V5.1] 事实算力审计 (基于物理词汇密度)
    real_input_tokens: int = 0
    real_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, inp: int = 0, out: int = 0, cache_create: int = 0, cache_read: int = 0, 
            real_inp: int = 0, real_output: int = 0) -> None:
        self.input_tokens += inp
        self.output_tokens += out
        self.cache_creation_tokens += cache_create
        self.cache_read_tokens += cache_read
        self.real_input_tokens += real_inp
        self.real_output_tokens += real_output
        # 粗略估算成本 (Gemini flash pricing approx)
        self.total_cost_usd += (inp * 0.1 + out * 0.3) / 1_000_000


@dataclass
class ToolCall:
    """单次工具调用的记录"""
    tool_name: str
    arguments: dict[str, object] = field(default_factory=dict)
    result: str | None = None
    success: bool = True
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class QAResult:
    """Triple-Perspective QA 验证结果封装 (Pillar 21+)。"""
    success: bool
    reason: str
    report: str


@dataclass
class AdvisorVerdict:
    """[V6.5 Traceability] 军师(Advisor)的裁决报告与交接认定。"""
    verdict: TerminationSignal
    confidence: float
    reason: str
    handover_pkt: UniversalCognitivePacket | None = None
    pairing_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """统一的 LLM 响应封装 (V5.0 Enriched Version)"""
    text: str = ""
    tool_calls: Sequence[Mapping[str, object]] = field(default_factory=list)
    raw: object = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    model: str = ""
    finish_reason: str = ""
    cache_read_tokens: int = 0
    
    # 兼容性属性
    @property
    def usage(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens
        )
    
    # [Hermes Pattern] 结构化思维映射: 存储从响应中提取出的推理片段
    thought: str = ""
    analysis: str = ""
    plan: str = ""
    
    raw_speculation: LLMResponse | None = None

    def parse_reasoning(self) -> None:
        """从响应文本中提取结构化推理标记 (Pillar 28)。"""
        # 提取 <analysis>
        analysis_match = re.search(r"<analysis>(.*?)</analysis>", self.text, re.DOTALL | re.IGNORECASE)
        if analysis_match:
            self.analysis = analysis_match.group(1).strip()
            
        # 提取 <plan>
        plan_match = re.search(r"<plan>(.*?)</plan>", self.text, re.DOTALL | re.IGNORECASE)
        if plan_match:
            self.plan = plan_match.group(1).strip()
            
        # 提取 <thought> (兼容 V7 Cognition)
        thought_match = re.search(r"<thought>(.*?)</thought>", self.text, re.DOTALL | re.IGNORECASE)
        if thought_match:
            self.thought = thought_match.group(1).strip()

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def cost_usd(self) -> float:
        """估算本次调用的总成本 (USD)"""
        return (self.input_tokens * 3.0 + self.output_tokens * 15.0) / 1_000_000

    @property
    def usage_dict(self) -> dict[str, int | float]:
        """[Hermes] 返回与 TokenUsage 兼容的字典格式。"""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_tokens,
            "total_cost_usd": self.cost_usd
        }


@dataclass
class ProgressReport:
    """[V5.1] HTAS 进度审计报告 (Pillar 31)。"""
    iteration: int
    physical_side_effects: int = 0  # 文件修改次数
    logical_successes: int = 0      # 命令成功次数
    information_density: float = 0.0 # 新发现的信息权重
    stagnation_count: int = 0       # 停滞步数
    is_converged: bool = False
    is_stuck: bool = False
    verdict: TerminationSignal = TerminationSignal.CONTINUE
    reason: str = ""


@runtime_checkable
class BaseLLM(Protocol):
    """大模型调用器接口协议 (Pillar 1)。"""
    @property
    def model_name(self) -> str: ...

    @property
    def owner_identity(self) -> str:
        """[V5.2] 获取当前调用器的认证者身份 (Email/DID)。"""
        return "unknown"

    async def call(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse: ...


@dataclass
class SubTask:
    """拆分后的子任务 (Pillar 12)。"""
    task_id: str
    description: str
    assigned_to: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: object = None
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    retry_count: int = 0
    max_retries: int = 3


class DomainConfig(TypedDict):
    keywords: list[str]
    agents: list[str]
    base_confidence: float


@dataclass
class IntentResult:
    """LLM 结构化意图分析结果 (Pillar 28+)"""
    intent_type: str = "general"
    confidence: float = 0.5
    domain: str = "general"
    complexity: str = "simple"
    suggested_agents: list[str] = field(default_factory=list)
    decomposed_steps: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    proactive_hints: list[str] = field(default_factory=list)
    risk_level: str = "low"
    reasoning: str = ""
    thought: str = ""
    raw_llm_output: str = ""
    domain_scores: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    
    # [V5.1] 执行路径与噪声
    execution_path: ExecutionPath = ExecutionPath.SAS_L
    noise_score: float = 0.0


@dataclass
class TaskNode:
    """DAG 中的一个任务节点。"""
    task_id: str
    description: str
    assigned_agent: str = ""
    depends_on: list[str] = field(default_factory=list)
    result: object = None
    metadata: dict[str, object] = field(default_factory=dict)
    priority: int = 50
    status: str = "pending"


class TaskDAG:
    """有向无环图 — 表示带依赖关系的任务拆解。"""

    def __init__(self) -> None:
        self.nodes: dict[str, TaskNode] = {}

    def add_node(self, node: TaskNode) -> None:
        self.nodes[node.task_id] = node

    def topological_sort(self) -> list[list[str]]:
        """
        Kahn 算法拓扑排序 → 返回按层分组的执行计划。
        同一层内的任务可并行执行。
        """
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep in in_degree:
                    in_degree[node.task_id] = in_degree.get(node.task_id, 0) + 1

        # 初始入度为 0 的节点
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        layers: list[list[str]] = []

        while queue:
            layers.append(sorted(queue))  # 同一层可并行
            next_queue: list[str] = []
            for nid in queue:
                for child_id, child in self.nodes.items():
                    if nid in child.depends_on:
                        in_degree[child_id] -= 1
                        if in_degree[child_id] == 0:
                            next_queue.append(child_id)
            queue = next_queue

        return layers

    @property
    def execution_order(self) -> list[list[str]]:
        return self.topological_sort()

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": {k: {"desc": v.description, "agent": v.assigned_agent, "deps": v.depends_on}
                      for k, v in self.nodes.items()},
            "execution_layers": self.execution_order,
        }


class PhaseTransition(TypedDict, total=False):
    """PHASE_TRANSITIONS 中的单个转换规则定义。"""
    phase: str
    reason: str
    agents: list[str]
    risk: str
    domain: str
    source: str  # Rule source (e.g., 'agent_id', 'llm_discovery')
    metadata: dict[str, object]


class AppStateProtocol(Protocol):
    """中央大脑状态机协议。"""
    agent_id: str
    session_id: str
    model_name: str
    status: AgentStatus
    loop_phase: LoopPhase
    iteration: int
    max_iterations: int
    current_intent: str
    task_status: TaskStatus
    usage: TokenUsage
    cost_limit_usd: float
    tool_history: list[ToolCall]
    git_auto_commit: bool
    danger_full_access: bool
    cyber_risk_enabled: bool
    query_guard_enabled: bool
    beta_flags: dict[str, bool]
    messages: list[dict[str, object]]
    consecutive_errors: int


class AppStateStoreProtocol(Protocol):
    """状态存储存储协议。"""
    @property
    def state(self) -> AppStateProtocol: ...
    def migrate(self, old_model: str, new_model: str) -> dict[str, object]: ...
    def update(self, key: str, value: object, silent: bool = False) -> object: ...
    def notify(self, key: str) -> None: ...
    def save_to_file(self, path: Path) -> bool: ...
    def load_from_file(self, path: Path) -> bool: ...


@runtime_checkable
class AgentEngineProtocol(Protocol):
    """用于打破循环依赖的 AgentEngine 接口协议 (Pillar 0)。"""
    session_id: str
    working_dir: Path
    store: AppStateStoreProtocol
    
    @property
    def buddy(self) -> object: ...
    @property
    def skills(self) -> object: ...
    @property
    def memory(self) -> object: ...
    @property
    def doctor(self) -> object: ...
    @property
    def compactor(self) -> object: ...
    @property
    def swarm(self) -> object: ...
    @property
    def git(self) -> object: ...
    @property
    def db(self) -> object: ...
    @property
    def intent_engine(self) -> object: ...
    @property
    def last_intent(self) -> IntentResult | None: ...
    @property
    def agent_id(self) -> str: ...
    @property
    def _messages(self) -> list[dict[str, object]]: ...

    async def run(self, user_message: str, *, resume: bool = False) -> str: ...
    async def initialize(self, db_url: str | None = None) -> None: ...
    async def resume(self, session_id: str) -> bool: ...
    async def shutdown(self) -> None: ...
    def set_beta_flag(self, flag: str, value: bool) -> None: ...


@runtime_checkable
class IntentEngineProtocol(Protocol):
    """用于打破循环依赖的 IntentEngine 接口协议。"""
    PHASE_TRANSITIONS: dict[str, list[PhaseTransition]]

    async def analyze(
        self,
        message: str,
        context: list[dict[str, object]] | None = None,
        agent_roster: list[dict[str, object]] | None = None,
    ) -> IntentResult: ...
    
    def build_dag(self, intent: IntentResult) -> TaskDAG: ...


@dataclass
class SovereignIdentity:
    """
    主权身份模型 (Pillar: Sovereign Identity).
    实现 DID -> Role -> Instance -> Owner 的多维映射。
    """
    did: str = field(default_factory=lambda: str(uuid.uuid4())) # 全局唯一身份
    role_id: str = "general"               # 逻辑岗位 (如 'coder', 'auditor')
    instance_id: str = "default"           # 具体实例名 (如 'coder_01')
    owner_did: str = "unknown"             # 背后的人类员工 DID
    team_id: str = "default_team"          # 所属团队
    trust_score: float = 1.0               # 信任评分
    
    # [V5.2 Enriched Metadata] Claude Specialist Spec Alignment
    name: str = ""                         # 人类可读名称
    description: str = ""                  # 能力描述
    capabilities: list[str] = field(default_factory=list) # 核心能力列表
    tools: list[str] = field(default_factory=list)         # 常用工具列表
    preferred_model: str = ""              # 偏好模型
    is_active: bool = True                  # [V5.2] 激活状态 (Active/Inactive)
    priority: int = 10                      # [V5.2] 优先级 (1-10, 1最高)
    auto_start: bool = True                 # [V5.2] 自动启动

    def to_short_id(self) -> str:
        return f"{self.role_id}@{self.instance_id}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SovereignIdentity:
        """从字典创建身份实例。"""
        # 移除 SurrealDB 自动生成的 id 等字段
        fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        
        # 处理可能的 list/dict 转换
        caps = fields.get("capabilities", [])
        if isinstance(caps, str): caps = [caps]
        
        tls = fields.get("tools", [])
        if isinstance(tls, str): tls = [tls]

        return cls(
            did=str(fields.get("did", str(uuid.uuid4()))),
            role_id=str(fields.get("role_id", "general")),
            instance_id=str(fields.get("instance_id", "default")),
            owner_did=str(fields.get("owner_did", "unknown")),
            team_id=str(fields.get("team_id", "default_team")),
            trust_score=float(cast(float, fields.get("trust_score", 1.0))),
            name=str(fields.get("name", "")),
            description=str(fields.get("description", "")),
            capabilities=cast(list[str], caps),
            tools=cast(list[str], tls),
            preferred_model=str(fields.get("preferred_model", "")),
            is_active=bool(fields.get("is_active", True)),
            priority=int(cast(int, fields.get("priority", 10))),
            auto_start=bool(fields.get("auto_start", True))
        )

@runtime_checkable
class Plugin(Protocol):
    """插件基础接口协议 (Pillar: Modular Extensions)"""
    name: str
    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def on_packet(self, packet: UniversalCognitivePacket) -> UniversalCognitivePacket | None: ...

class SwarmRole(str, Enum):
    COORDINATOR = "coordinator"   # 主控引擎
    WORKER = "worker"             # 工作节点


@dataclass
class SwarmPeer:
    """一个集群中的对等节点 (Pillar 29)。"""
    peer_id: str
    role: SwarmRole
    identity: SovereignIdentity = field(default_factory=SovereignIdentity) # 主权身份
    address: str = ""           # host:port
    public_key: str = ""
    connected: bool = False
    last_heartbeat: float = field(default_factory=time.time)
    capabilities: list[str] = field(default_factory=list)


@dataclass
class SwarmMessage:
    """集群间的通信消息 (Pillar 29)。遵循 JSON-RPC 2.0 风格以保证通用性。"""
    sender_id: str
    receiver_id: str
    msg_type: str               # task, result, heartbeat, sync_event
    payload: dict[str, object] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    signature: str = ""         # HMAC 签名
    
    # JSON-RPC 2.0 兼容字段
    jsonrpc: str = "2.0"
    method: str | None = None
    params: dict[str, object] | None = None

    def to_json(self) -> str:
        """序列化为 JSON 字符串。"""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "SwarmMessage":
        """从 JSON 字符串反序列化。"""
        d = cast(dict[str, object], json.loads(data))
        return cls(
            sender_id=str(d.get("sender_id", "")),
            receiver_id=str(d.get("receiver_id", "")),
            msg_type=str(d.get("msg_type", "")),
            payload=cast(dict[str, object], d.get("payload", {})),
            timestamp=float(str(d.get("timestamp", 0.0))),
            signature=str(d.get("signature", "")),
            method=cast(str | None, d.get("method")),
            params=cast(dict[str, object] | None, d.get("params")),
        )


@dataclass
class UniversalCognitivePacket:
    """
    通用层级认知同步协议 (V2 - Enterprise Grade).
    支持主权身份验证、重要性评分与防溢出认知保护。
    """
    # [Identity] 主权身份
    source: SovereignIdentity

    # [Core] 诚实感知的核心契约
    objective: str             # 战略目标
    instruction: str           # 具体的原子指令内容
    
    # [Fields with defaults]
    id: str = field(default_factory=lambda: f"pkt_{int(time.time()*1000)}_{str(uuid.uuid4())[:8]}")
    physical_delta: dict[str, object] = field(default_factory=dict) # 真实的级联变更报告
    
    # [Extension] 领域自适应对象
    domain_payload: dict[str, object] = field(default_factory=dict) 
    
    # [Metadata] 元数据与安全
    packet_type: str = "observation" # observation, verification_request, verification_result, task_dispatch
    target: str = "all"        # 路由目标：可以是 'all', 'role:xxx', 或具体的 'did'
    importance: int = 5        # 重要性评分 (1-10)
    aura: float = 1.0          # 认知能量/系数 (用于 Aegis 防火墙判定)
    signature: str | None = None # 签名验证
    namespace: str = "general"
    resource_refs: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> UniversalCognitivePacket:
        """从字典还原包内容，支持嵌套的身份还原。"""
        src_dict = d.get("source", {})
        if isinstance(src_dict, dict):
            source = SovereignIdentity.from_dict(src_dict)
        else:
            source = cast(SovereignIdentity, src_dict)
        
        return cls(
            source=source,
            id=str(d.get("id", "")),
            objective=str(d.get("objective", "")),
            instruction=str(d.get("instruction", "")),
            physical_delta=cast(dict[str, object], d.get("physical_delta", {})),
            domain_payload=cast(dict[str, object], d.get("domain_payload", {})),
            packet_type=str(d.get("packet_type", "observation")),
            target=str(d.get("target", "all")),
            importance=int(str(d.get("importance", 5))),
            aura=float(str(d.get("aura", 1.0))),
            signature=cast(str | None, d.get("signature")),
            namespace=str(d.get("namespace", "general")),
            resource_refs=cast(list[str], d.get("resource_refs", [])),
            timestamp=float(str(d.get("timestamp", time.time()))),
        )


@runtime_checkable
class KnowledgeSource(Protocol):
    """
    认知知识源接口 (Pillar: Knowledge Integration).
    允许 Agent 通过插件挂载外部 Wiki, 文档库或数据库。
    """
    name: str
    async def query(self, query: str, top_k: int = 5) -> list[dict[str, object]]: ...
    async def get_context(self, resource_id: str) -> str | None: ...


@runtime_checkable
class SwarmNetworkProtocol(Protocol):
    """集群网络接口协议，用于打破 CoordinatorEngine 与 SwarmNetwork 的循环依赖。"""
    agent_id: str
    role: SwarmRole
    
    def get_active_workers(self) -> list[SwarmPeer]: ...
    async def dispatch_task(self, objective: str, instruction: str, target: str = "any:worker") -> str: ...
    async def collect_result(self, task_id: str, timeout: float = 300) -> dict[str, object] | None: ...
    async def broadcast_packet(self, packet: UniversalCognitivePacket) -> None: ...
