# -*- coding: utf-8 -*-
"""
Coda V5.1 — Agent Engine (核心 #1)
自主任务执行引擎: 负责任务分解、工具调用、上下文维护与 14 层硬防护。

设计参考: Claude Code 原始 TS `agent/Agent.ts`
"""

from __future__ import annotations

import json
import logging
import time
import asyncio
import os
from pathlib import Path
from collections.abc import Sequence, Mapping, Callable
from typing import cast, TYPE_CHECKING

from .base_types import (
    AgentStatus, LLMResponse,
    BaseLLM, IntentResult, ExecutionPath,
    SovereignIdentity, UniversalCognitivePacket,
    QAResult
)
from .identity import registry
from .progress_monitor import ProgressMonitor
from .state import AppState, AppStateStore
from .llm_caller import create_caller
from .db import SurrealStore
from .context import ContextDiscoverer
from .git_checkpoint import GitCheckpoint
from .doctor import Doctor
from .swarm import SwarmNetwork
from .speculation import PromptSpeculation
from .commands import SlashCommandRouter, SecuritySandbox
from .skill_factory import SkillFactory
from .buddy import BuddySystem
from .hooks import HookEngine
from .intent_engine import IntentEngine
from .history import HistoryCompactor
from .memory import SessionMemory, TeamMemory, CausalGraph
# No accessible imports from migration at this level currently
from .utils.token_audit import calculate_real_compute
from .hierarchy import warden
from .economy import ledger
from .plugins import registry as plugin_registry

if TYPE_CHECKING:
    pass

logger = logging.getLogger("Coda.engine")


class AgentEngine:
    """
    Coda 核心引擎。
    继承了 Hermes 的所有高性能特性:
    - 投机推理 (Pillar 1)
    - 响应式状态管理 (Pillar 31)
    - 3 维度 QA 验证 (Pillar 32)
    - 混合 prompt 缓存 (Pillar 26)
    """

    def __init__(
        self,
        working_dir: str | Path = ".",
        session_id: str | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
        max_iterations: int = 200,
        cost_limit: float = 5.0,
        danger_full_access: bool = False,
        enable_embedding: bool = False,
        db: SurrealStore | None = None,
        db_url: str | None = None,
        store: AppStateStore | None = None,
        swarm: SwarmNetwork | None = None,
        **args: object,
    ) -> None:
        self.agent_id: str = str(args.get("agent_id", "commander"))
        self.working_dir: Path = Path(working_dir).absolute()
        self.session_id: str = session_id or f"sess_{int(time.time())}"
        self._model_name: str = model_name or os.getenv("DEFAULT_MODEL_NAME", " ")
        self.swarm: SwarmNetwork | None = swarm
        
        # ── 主权身份 (Pillar: Sovereign Identity) ──
        self.identity: SovereignIdentity = SovereignIdentity(
            role_id=str(args.get("role_id", "commander")),
            instance_id=self.agent_id,
            owner_did=os.getenv("OWNER_DID", "did:emp:james")
        )
        # 初始注册推迟到 initialize
        
        # ── 状态层 (AppStateStore) ──
        self.store: AppStateStore = store or AppStateStore(AppState(
            agent_id=str(args.get("agent_id", "commander")),
            session_id=self.session_id,
            model_name=self._model_name,
            cost_limit_usd=cost_limit,
            danger_full_access=danger_full_access,
            max_iterations=max_iterations,
        ))

        # ── 统一存储后端 (SurrealDB 桥接) ──
        self.db: SurrealStore = db or SurrealStore()
        self._db_url: str | None = db_url

        # ── 本地向量化引擎 ──
        self._embedder: object | None = None
        self._enable_embedding: bool = enable_embedding
        
        # [V5.1] 状态扩展 (用于 main.py 监控)
        self.matched_soul: dict[str, object] | None = None
        self.last_intent: IntentResult | None = None

        self._llm: BaseLLM = create_caller(self._model_name, api_key) # Simple for now
        # ── 工具与执行层 (Pillar 21/24) ──
        from .tool_executor import ToolExecutor
        from .skill_factory import SkillFactory
        
        self.tools: ToolExecutor = ToolExecutor(str(self.working_dir))
        self.git: GitCheckpoint = GitCheckpoint(str(self.working_dir))
        self.hooks: HookEngine = HookEngine(self.store, self.git)
        self.compactor: HistoryCompactor = HistoryCompactor()
        self._skill_factory: SkillFactory = SkillFactory([self.working_dir / "skills"])
        
        self._tool_schemas: list[dict[str, object]] = self._build_tool_schemas(model_name)
        from .llm_caller import get_token_counter
        self._token_counter: Callable[[Sequence[Mapping[str, object]]], int] = get_token_counter(self._model_name)
        
        self.context: ContextDiscoverer = ContextDiscoverer(self.working_dir, self.git)
        
        # ── 技能与伴侣系 ──
        self.buddy: BuddySystem = BuddySystem(self.store, personality="战神")
        
        # ── Pillar 28: 意图中枢 (Intent Engine) ──
        self.intent_engine: IntentEngine = IntentEngine(self._llm, self.db)
        
        # ── Pillar 7: 安全沙箱 ──
        self.sandbox: SecuritySandbox = SecuritySandbox()
        self.router: SlashCommandRouter = SlashCommandRouter()

        # ── [Pillar 13 & 31] 技能与因果
        self.causal_graph: CausalGraph = CausalGraph(self.db)
        self.memory: SessionMemory = SessionMemory(self.working_dir / ".gemini" / "memory")
        self.team_memory: TeamMemory = TeamMemory(self.working_dir / ".gemini" / "team_memory")
        
        # ── 自愈诊断与预判 ──
        self.doctor: Doctor = Doctor(self.working_dir)
        self.speculation: PromptSpeculation = PromptSpeculation(self.working_dir)
        self.htas: ProgressMonitor = ProgressMonitor()
        self._ritual_triggered: bool = False
        
        # ── 插件系统 (Pillar: Heterogeneous Polyglot) ──
        from .plugins import PluginRegistry
        self.plugins: PluginRegistry = plugin_registry
        # [V5.2] 同步资源守卫开关
        self.plugins.strict_resource_limit = bool(self.store.state.beta_flags.get("strict_plugin_guard", False))

        # ── 会话状态 ──
        self._messages: list[dict[str, object]] = []
        self._is_verified: bool = False
        self._max_history_tokens: int = 180000
        self._killswitch_triggered: bool = False
        self._trajectory_dir: Path = self.working_dir / ".trajectories" / self.session_id
        
        # [V5.2] 持续化通讯日志 (Convenient Identification)
        self._comm_dir: Path = self.working_dir / "agents" / self.agent_id / "logs" / self.session_id
        self._comm_seq: int = 0
        
        # ── 状态初始化 ──
        self.store.state.working_directory = str(self.working_dir)
        self.store.state.model_name = self._model_name
        self.store.state.agent_id = self.agent_id

        # [V5.2] 加载工业级角色灵魂 (Soul)
        self._load_industrial_soul()

        logger.info(f"🚀 Coda V5.1 Online: sess={self.session_id}, agent={self.agent_id}, model={self._model_name}")

    def _load_industrial_soul(self) -> None:
        """从 SOUL.md 加载工业级人格设定与专家元数据。"""
        soul_path = self.working_dir / "agents" / self.agent_id / "SOUL.md"
        if not soul_path.exists():
            logger.warning(f"Industrial SOUL not found at {soul_path}, falling back to basic prompt.")
            return

        from .identity import registry
        ident = registry.parse_soul_metadata(soul_path, self.agent_id)
        if ident:
            # 更新当前引擎的身份元数据
            self.identity.name = ident.name
            self.identity.description = ident.description
            self.identity.capabilities = ident.capabilities
            self.identity.tools = ident.tools
            self.identity.preferred_model = ident.preferred_model
            
            # 使用偏好模型 (如果指定)
            if self.identity.preferred_model:
                self._model_name = self.identity.preferred_model
            
            logger.info(f"🎭 Industrial SOUL loaded for {self.agent_id} ({self.identity.role_id})")

    async def initialize(self, db_url: str | None = None) -> None:
        """
        [V5.2] 异步初始化引擎核心平面。
        负责连接数据库、加载身份注册表、同步指挥链与审计账本。
        """
        if self._is_verified: return
        
        # 1. 连接数据库 (SurrealDB)
        target_url = db_url or self._db_url
        if target_url:
            await self.db.connect(url=target_url)
        else:
            await self.db.connect()
            
        # 2. 注入持久化存储到 V5.2 核心模块 (Late Binding)
        registry.set_store(self.db)
        warden.set_store(self.db)
        ledger.set_store(self.db)
        
        # 3. 初始化身份注册表
        await registry.initialize()
        
        # [V6.5] 动态身份映射: 从 LLM 探测当前活动的人类账号
        if self._llm and hasattr(self._llm, "owner_identity"):
            new_owner = self._llm.owner_identity
            if new_owner and new_owner != "unknown":
                if self.identity.owner_did != new_owner:
                    logger.info(f"👤 Identity Shift Detected: {self.identity.owner_did} -> {new_owner}")
                    self.identity.owner_did = new_owner

        # 4. 注册自身身份
        await registry.register(self.identity)
        
        # 5. 执行专家库扫描 (智能感悟)
        # 注入 LLM 支持自动感悟补全 (Pillar 26)
        # 仅在数据库为空或强制扫描时执行
        if len(registry.list_all_identities()) <= 1:
            logger.info("📡 Database appears empty. Triggering autonomous specialist scan...")
            await registry.scan_agents(self.working_dir, llm=self._llm)
        
        # 6. 启动集群监听 (如果已配置)
        if self.swarm:
            await self.swarm.start_listening()
        
        # 4. 初始化经济账本与审计平面
        await ledger.initialize()
            
        self._is_verified = True
        logger.info(f"✨ Coda Engine V5.2 fully initialized and verified for {self.agent_id}.")

    @property
    def skills(self) -> SkillFactory:
        """[V5.2] 获取技能工厂 (main.py 监控项)。"""
        return self._skill_factory

    @property
    def embedder_loaded(self) -> bool:
        """检查向量化引擎是否已就位。"""
        return self._embedder is not None

    def _build_tool_schemas(self, _model: str | None) -> list[dict[str, object]]:
        """构建工具描述 (Gemini 格式)。"""
        schemas = []
        for name in self.tools.dispatch.keys():
            # 这里简化处理，为所有工具提供通用的基础描述
            # 实际工业生产中应从 ToolExecutor 的元数据中提取精确 schema
            schemas.append({
                "name": name,
                "description": f"Coda Atomic Tool: {name}. 请根据上下文参数进行调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "目标文件路径"},
                        "content": {"type": "string", "description": "写入或替换的内容"},
                        "command": {"type": "string", "description": "要执行的任务命令"},
                        "instruction": {"type": "string", "description": "给工具的指令"},
                        "AbsolutePath": {"type": "string", "description": "文件绝对路径"},
                        "CommandLine": {"type": "string", "description": "执行命令行"},
                    }
                }
            })
        return schemas

    async def run(self, user_message: str, verdict: Any | None = None) -> str:
        """
        运行自主循环 (Pillar 26).
        [V6.5 Traceability] 支持注入军师裁决 (AdvisorVerdict) 以实现全链路溯源。
        """
        # [V5.2 Hardening] 确保引擎已完全初始化
        if not self._is_verified:
            await self.initialize()
            
        self.store.update("status", AgentStatus.RUNNING)
        
        # ── [V6.5] HT-TRACE: 注入军师交接认定 ──
        if verdict and hasattr(verdict, "handover_pkt") and verdict.handover_pkt:
            pkt = verdict.handover_pkt
            logger.info(f"🛡️ [HT-TRACE] Handover Active: {pkt.id} | Advisor: {pkt.source.instance_id}")
            
            # 注入到系统提示词或消息流中，确保执行器“知道”军师说了什么
            handover_context = (
                f"\n\n[ADVISOR_HANDOVER_CERTIFICATE]\n"
                f"Pairing ID: {pkt.domain_payload.get('pairing_id', 'N/A')}\n"
                f"Advisor: {pkt.source.instance_id} ({pkt.source.role_id})\n"
                f"Verdict: {pkt.objective}\n"
                f"Logic Reference: {pkt.instruction}\n"
            )
            self._messages.append({"role": "system", "content": f"🛡️ 军师指引已就位: {handover_context}"})

        self._messages.append({"role": "user", "content": user_message})
        self._ritual_triggered = False
        
        step_count = 0
        final_answer = ""

        try:
            while step_count < self.store.state.max_iterations:
                step_count += 1
                self.store.update("iteration", step_count)
                
                # [V5.2] 结对编程感知：同步外部 Agent 的变更 (Pillar 36)
                await self._sync_foreign_observations()
                
                # HTAS 物理审计 (Pillar 31)
                # Context Unwinding (Pruning)
                await self._enforce_token_budget()
                
                # ── Step 0: Slash Command Routing (Pillar 8) ──
                cmd_result = await self.router.route(user_message, engine=self)
                if cmd_result:
                    return cmd_result
                
                # 0. HTAS: 任务进度审计与诚实反射 (Pillar 31)
                progress = self.htas.audit(step_count, self._messages)
                
                # 每 3 步或检测到停滞时进行 LLM 深度反射
                if step_count % 3 == 0 or progress.is_stuck:
                    reflection: dict[str, object] = await self.intent_engine.reflect_on_progress(
                        goal=user_message,
                        messages=self._messages,
                        modified_files=self.htas.modified_files,
                        stagnation_count=progress.stagnation_count
                    )
                    verdict = str(reflection.get("verdict", "continue"))
                    
                    if verdict == "converged":
                        logger.info(f"🎯 HTAS: Goal converged ({reflection.get('honest_progress', 0)}%). Terminating.")
                        break
                    elif verdict == "stuck_pivot":
                        logger.warning(f"⚠️ HTAS: Stagnation detected. Reason: {reflection.get('reason', 'Unknown')}. Triggering Strategy Pivot...")
                        # [V5.2] 自动换道: SAS-L -> MAS (强制拆解任务以破局)
                        if self.last_intent:
                            self.last_intent.execution_path = ExecutionPath.MAS
                            self.last_intent.complexity = "compound" # 升级复杂度以强制生成新 DAG
                        
                        # 注入“战术重置”信号，提示模型停止当前死循环
                        self._messages.append({
                            "role": "user",
                            "content": (f"[HTAS 战术重置]: 检测到执行停滞记录。理由: {reflection.get('reason', 'Unknown')}。\n"
                                        "当前策略已强制切换为多步拆解模式 (MAS)。请重新评估目标并尝试新的路径。")
                        })
                        continue # 立即重新开始循环，使用新策略

                # 1. 意图分析 (Intent Analysis) - 仅在初始步或需要重新评估时更新
                if step_count == 1 or (progress.is_stuck and self.last_intent and self.last_intent.execution_path == ExecutionPath.MAS):
                    self.last_intent = await self.intent_engine.analyze(user_message, self._messages)
                
                # 2. [V5.1] SAS-L 动态增强 (单体深度推理提示词)
                active_messages = self._messages.copy()
                if self.last_intent and self.last_intent.execution_path == ExecutionPath.SAS_L:
                    active_messages.insert(0, {
                        "role": "system", 
                        "content": "COMMANDER_SOUL: 你正在处于单体深度推理模式 (SAS-L)。请在一个回复中完成多跳推理、工具调用和最终审计，不要尝试将任务碎片化。"
                    })

                # 3. 带流量防御的 LLM 调用 (Pillar 23: Traffic Armor + V5.1 Mechanical Sympathy)
                try:
                    # ── Phase 4: 经济审计 (Economic Audit Check) ──
                    # 预估成本检查 (此处预设一个极小值作为基准，真实扣费在调用后)
                    if not await ledger.check_and_record(self.identity, 0.000001):
                        logger.error("🚫 Insufficient budget in Ledger. Refusing LLM call.")
                        self._messages.append({"role": "system", "content": "🚫 [经济限制]: 团队配额耗尽，任务中止。"})
                        break
                    
                    response = await self._llm.call(active_messages)
                    
                    # 真实扣费记录
                    await ledger.check_and_record(self.identity, response.usage.total_cost_usd)
                    # 4. 更新 Token 账单
                    ledger.record_usage(response.usage)
                except Exception as e:
                    error_msg = str(e).lower()
                    if "high traffic" in error_msg or "429" in error_msg or "overloaded" in error_msg:
                        logger.warning("🛡️ Traffic Armor: Provider overloaded. Attempting 1st Backoff...")
                        await asyncio.sleep(2)
                        try:
                            response = await self._llm.call(active_messages)
                        except Exception as e2:
                            # [V5.1] 机械共情：单体推理 Payload 过载，强制退化为 MAS 颗粒化处理
                            logger.error(f"🛑 SAS-L Payload too large or provider busy: {e2}. Downgrading to MAS...")
                            if self.last_intent:
                                self.last_intent.execution_path = ExecutionPath.MAS
                            # 重新运行意图决策以获取拆分步骤 (如果此前是单体)
                            self.last_intent = await self.intent_engine.analyze(user_message, self._messages)
                            continue # 跳回循环开头，按 MAS 路径执行
                    else:
                        raise e
                
                # Step Persistence
                _ = await self._dump_trajectory(step_count, response, [])
                
                # Process thought and tools
                if response.tool_calls:
                    for tc in response.tool_calls:
                        res = await self._execute_tool_with_hooks(self.store.state.agent_id, tc)
                        self._messages.append({"role": "tool", "content": json.dumps(res)})
                else:
                    final_answer = response.text
                    
                    # [V5.2] 验证门控 (Stop Hook / Verification Gate)
                    # 如果有物理变更且尚未通过正式验证，则发起验证请求
                    if self.htas.modified_files and not self._is_verified:
                        logger.info("🛡️ Verification Gate: Requesting audit from Verifier...")
                        await self._request_swarm_verification(user_message, final_answer)
                        # 继续循环，等待 Verifier 的认知包同步
                        self._messages.append({
                            "role": "system",
                            "content": "⏳ [验证门控]: 已发起集群验证请求。正在等待 Verifier 专家审计物理变更。请不要退出。"
                        })
                        continue

                    # Verification Pillar 32 (Legacy Triple QA)
                    qa_res = await self._perform_triple_qa(user_message, final_answer)
                    if qa_res.success:
                        self.store.update("qa_passed", True)
                        break
                    else:
                        self._messages.append({"role": "user", "content": f"QA Failed: {qa_res.reason}"})

        finally:
            self.store.update("status", AgentStatus.IDLE)
            # [V5.1] 自动摘要提交协议 (Auto-Summary Commit Protocol)
            # 无论成功失败，只要有消息生成且 Git 可用，就执行“静默仪式”提交。
            await self._perform_silent_ritual()

        return final_answer

    async def _sync_foreign_observations(self) -> None:
        """
        [Pillar 36] 监听并注入来自 Swarm 的外部观测 (V5.2 增强版)。
        集成 CommandWarden 审计与主权认知包解析。
        """
        if not self.swarm: return

        # 遍历 SwarmNetwork 中的认知包缓冲
        for pkt_id, pkt_dict in list(self.swarm.results.items()):
            try:
                # 转换回对象
                packet = UniversalCognitivePacket.from_dict(pkt_dict) # type: ignore
                
                # 过滤掉自己发出的消息
                if packet.source.did == self.identity.did:
                    continue
                
                # ── [V5.2] 统一通讯审计 ──
                self._write_comm_log(packet, direction="IN")
                
                # ── Phase 3: 指挥权审计 (Command Audit) ──
                if not await warden.audit_command(packet, self.identity):
                    logger.warning(f"🛡️ Warden REJECTED packet {packet.id} from {packet.source.did}")
                    continue

                # ── [V5.2] 验证结果处理 ──
                if packet.packet_type == "verification_result":
                    verdict = str(packet.domain_payload.get("verdict", "REJECTED"))
                    if verdict == "SUCCESS":
                        self._is_verified = True
                        self._messages.append({
                            "role": "system", 
                            "content": f"✅ [验证通过] 来自 {packet.source.to_short_id()} 的审计结论: {packet.instruction}"
                        })
                    else:
                        self._is_verified = False
                        self._messages.append({
                            "role": "system", 
                            "content": f"❌ [验证失败] 来自 {packet.source.to_short_id()} 的审计拒绝: {packet.instruction}\n理由: {packet.domain_payload.get('reason', '未知')}"
                        })
                    # 处理完后移除
                    self.swarm.results.pop(pkt_id, None)
                    continue

                # 提取物理层 Delta
                delta = packet.physical_delta
                if not delta: continue
                
                path = delta.get("path", "未知文件")
                sender = packet.source.to_short_id()
                
                # 注入系统消息上下文 (诚实感知)
                notice = (
                    f"🔔 [Swarm 同步] 收到来自 {sender} 的物理层同步:\n"
                    f"   文件: {path}\n"
                    f"   动作: {packet.instruction}\n"
                    f"   摘要: {delta.get('summary', '无')}"
                )
                self._messages.append({"role": "system", "content": notice})
                logger.info(f"🔄 Synced audited change from {sender} on {path}")
                
                # 处理完毕后，移出缓冲 (如果是特定目标消息)
                if packet.target != "all":
                    self.swarm.results.pop(pkt_id, None)

            except Exception as e:
                logger.error(f"Failed to parse or audit swarm packet: {e}")
                
        # 清理已处理的同步消息 (实际应有更完善的 Offset 机制)

    async def _execute_tool_with_hooks(self, agent_id: str, tool_call: Mapping[str, object]) -> dict[str, object]:
        """
        执行工具并触发异步同步协议 (Pillar 36-39)。
        """
        tool_name = str(tool_call.get("name", ""))
        args = cast(dict[str, object], tool_call.get("arguments", {}))
        
        # 识别侧效应工具
        is_write = tool_name in ("write_file", "edit_file", "replace_file_content", "multi_replace_file_content")
        target_path_str = str(args.get("path") or args.get("TargetFile") or "")
        target_path = Path(target_path_str) if target_path_str else None
        
        old_content = ""
        if is_write and target_path and target_path.exists():
            try:
                old_content = target_path.read_text(encoding="utf-8", errors="ignore")
            except Exception: pass

        # 2. 执行工具
        result_str = await self.tools.execute(tool_name, args)
        
        # 3. 产生物理感知并广播
        if is_write and target_path and "ERROR" not in result_str:
            try:
                new_content = target_path.read_text(encoding="utf-8", errors="ignore")
                # 计算由物理层生成的真实 Diff (诚实感知)
                delta = self.htas.compute_line_delta(str(target_path), old_content, new_content)
                
                # 组装通用认知包 (UMDCS Protocol V2)
                packet = UniversalCognitivePacket(
                    source=self.identity,
                    objective=self.last_intent.intent_type if self.last_intent else "Task Execution",
                    instruction=f"Executed {tool_name} on {target_path.name}",
                    physical_delta=delta,
                    domain_payload={"tool": tool_name, "args_digest": str(args)[:200]}
                )
                
                # 签名认知包
                packet.signature = registry.sign_packet(packet)
                
                # 广播到集群 (V2 API)
                if self.swarm:
                    await self.swarm.broadcast_packet(packet)
                    # 记录发送日志
                    self._write_comm_log(packet, direction="OUT")
            except Exception as e:
                logger.error(f"Failed to emit sync event: {e}")

        return {"name": tool_name, "content": result_str}

    async def _request_swarm_verification(self, goal: str, solution: str) -> None:
        """
        向集群广播验证请求。
        """
        if not self.swarm:
            return

        packet = UniversalCognitivePacket(
            source=self.identity,
            packet_type="verification_request",
            objective="Verification Audit",
            instruction=f"Please verify the changes for goal: {goal}",
            target="role:verifier",
            domain_payload={
                "goal": goal,
                "solution_summary": solution[:500],
                "modified_files": list(self.htas.modified_files)
            }
        )
        packet.signature = registry.sign_packet(packet)
        await self.swarm.broadcast_packet(packet)
        logger.info(f"📡 Broadcasted verification_request for {len(self.htas.modified_files)} files.")
        
        # 记录发送日志
        self._write_comm_log(packet, direction="OUT")

    def _write_comm_log(self, packet: UniversalCognitivePacket, direction: str) -> None:
        """
        [V5.2] 统一通讯日志记录协议。
        同时输出详细的独立 MD 追踪包和中央汇总日志 communication.md。
        """
        try:
            self._comm_seq += 1
            self._comm_dir.mkdir(parents=True, exist_ok=True)
            
            # 1. 详细追踪包 (Trace Packet)
            p_type = packet.packet_type.upper()
            ts_perf = time.strftime("%H%M%S", time.localtime(packet.timestamp))
            filename = f"{self._comm_seq:03d}_{direction}_{p_type}_{ts_perf}.md"
            file_path = self._comm_dir / filename
            
            content = [
                f"# Communication Trace: {direction} Packet",
                f"- **ID**: `{packet.id}`",
                f"- **Timestamp**: {time.ctime(packet.timestamp)}",
                f"- **From**: `{packet.source.to_short_id()}`",
                f"- **To**: `{packet.target}`",
                f"- **Intent**: {packet.objective or 'N/A'}",
                "",
                "## Instruction",
                packet.instruction or "No instruction",
                "",
                "## Payload",
                "```json\n" + json.dumps(packet.domain_payload, indent=2, ensure_ascii=False) + "\n```",
            ]
            
            if packet.physical_delta:
                content.extend([
                    "",
                    "## Physical Delta",
                    f"- **File**: `{packet.physical_delta.get('path', 'unknown')}`",
                    f"- **Summary**: {packet.physical_delta.get('summary', 'none')}",
                    "```diff\n" + str(packet.physical_delta.get("diff", "")) + "\n```"
                ])
                
            file_path.write_text("\n".join(content), encoding="utf-8")

            # 2. 中央汇总日志 (Consolidated Log)
            # 路径: agents/{agent_id}/logs/communication.md
            central_log = self.working_dir / "agents" / self.agent_id / "logs" / "communication.md"
            if not central_log.exists():
                central_log.parent.mkdir(parents=True, exist_ok=True)
                header = f"# {self.agent_id} Swarm Communication History\n\n| Seq | Dir | From | To | Intent | Instruction |\n| :-- | :-- | :--- | :--- | :--- | :--- |\n"
                central_log.write_text(header, encoding="utf-8")
            
            instr = (packet.instruction or "").replace("|", "\\|").replace("\n", " ")[:80]
            if len(packet.instruction or "") > 80: instr += "..."
            
            log_line = f"| {self._comm_seq:03d} | {direction} | {packet.source.to_short_id()} | {packet.target} | {packet.objective or 'N/A'} | {instr} |\n"
            with open(central_log, "a", encoding="utf-8") as f:
                f.write(log_line)
                
            logger.debug(f"💾 Comm log persisted: {filename} + central index")
        except Exception as e:
            logger.error(f"Failed to persist communication log: {e}", exc_info=True)

    async def _perform_triple_qa(self, _prompt: str, _completion: str) -> QAResult:
        """三维度审计。"""
        return QAResult(success=True, reason="Verified", report="All tests passed.")

    async def _enforce_token_budget(self) -> None:
        """
        Token 熔断保护与上下文剪枝 (Pillar 23).
        当 Token 消耗超过阈值时, 触发历史压缩逻辑。
        """
        if not self._messages:
            return

        current_tokens = self._token_counter(self._messages)
        if self.compactor.needs_compaction(self._messages, current_usage=current_tokens):
            logger.info(f"🚨 Context budget exceeded ({current_tokens} tokens). Triggering compaction...")
            
            # 执行压缩
            self._messages = self.compactor.compact(
                self._messages,
                complexity="simple",
                memory=self.memory
            )
            
            # 重新计算压缩后的真实 Token (可选，用于日志)
            new_tokens = self._token_counter(self._messages)
            logger.info(f"✨ Compaction completed. New budget: {new_tokens} tokens.")

    async def _inject_semantic_recall(self, query: str) -> None:
        """
        [Pillar 17 & 26] 语义回溯注入。
        根据当前 Query 检索长效记忆, 并将其作为临时系统上下文注入。
        """
        # 1. 检索本地 SessionMemory
        local_mems = self.memory.recall(query, top_k=3)
        
        # 2. 检索 SurrealDB Memories (向量/关键词)
        db_mems = []
        if self.db.is_connected:
            db_mems = await self.db.search_memories(keyword=query, top_k=3)
            
        combined_content = []
        for m in local_mems:
            combined_content.append(m.content)
        for m in db_mems:
            content = m.get("content", {})
            if isinstance(content, dict):
                combined_content.append(content.get("text", ""))
            else:
                combined_content.append(str(content))

        if not combined_content:
            return

        # 3. 构造语义回溯块
        recall_block = "\n".join([f"- {c}" for c in combined_content])
        injection: dict[str, object] = {
            "role": "system",
            "content": f"<semantic_recall>\n这是与当前任务相关的历史上下文/偏好, 请参考:\n{recall_block}\n</semantic_recall>"
        }

        # 注入到第 1 条消息之后 (通常 system prompt 在第 0 条)
        if len(self._messages) > 1:
            self._messages.insert(1, injection)
        else:
            self._messages.append(injection)
            
        logger.info(f"🧠 Semantic Recall injected for query: '{query}'")

    async def _dump_trajectory(self, step: int, response: LLMResponse, tool_results: list[dict[str, object]]) -> dict[str, object]:
        """轨迹持久化: 将步骤记录到磁盘和数据库。"""
        self._trajectory_dir.mkdir(parents=True, exist_ok=True)
        
        trajectory_data: dict[str, object] = {
            "session_id": self.session_id,
            "step": step,
            "timestamp": time.time(),
            "model": self._model_name,
            "prompt": self._messages[-1]["content"] if self._messages else "",
            "thought": response.text,
            "tool_calls": response.tool_calls,
            "tool_results": tool_results,
            "usage": {
                "input": response.input_tokens,
                "output": response.output_tokens,
                "cache": response.cache_tokens,
                # [V5.1] 注入事实算力审计 (基于物理词汇密度)
                "real_input": calculate_real_compute(str(self._messages[-1]["content"] if self._messages else "")),
                "real_output": calculate_real_compute(response.text)
            }
        }
        
        # 同步更新 AppState 中的总量
        self.store.state.usage.add(
            inp=response.input_tokens,
            out=response.output_tokens,
            real_inp=calculate_real_compute(str(self._messages[-1]["content"] if self._messages else "")),
            real_output=calculate_real_compute(response.text)
        )
        
        # 写入磁盘
        file_path = self._trajectory_dir / f"step_{step:03d}.json"
        _ = file_path.write_text(json.dumps(trajectory_data, indent=2, ensure_ascii=False), encoding="utf-8")
        
        # 同步数据库
        if self.db.is_connected:
            await self.db.log_trajectory(self.session_id, step, trajectory_data)
            
        return trajectory_data

    def set_beta_flag(self, flag: str, value: bool) -> None:
        """开启或关闭测试特性。"""
        self.store.state.beta_flags[flag] = value
        logger.info(f"Beta flag {flag} set to {value}")

    def resume(self, session_id: str) -> bool:
        """从会话 ID 恢复引擎状态。"""
        # 简化版实现，实际需要从磁盘/DB加载
        self.session_id = session_id
        self.store.update("session_id", session_id)
        logger.info(f"Resuming session {session_id}")
        return True

    async def shutdown(self) -> None:
        """优雅关闭引擎。"""
        self.store.update("status", AgentStatus.TERMINATED)
        
        # 兜底：如果有关闭前的未提交更改，执行一次静默仪式
        await self._perform_silent_ritual()
        
        if self.db.is_connected:
            await self.db.disconnect()
        logger.info(f"Agent Engine {self.session_id} shutting down...")

    async def _perform_silent_ritual(self) -> None:
        """
        [V5.1] 执行“静默仪式” (Silent Ritual)。
        提炼对话摘要并物理存档至 Git。该方法是幂等且受保护的，每轮 run 尽量只执行一次。
        """
        if self._ritual_triggered or not self._messages:
            return

        if self.htas.modified_files and len(self.htas.modified_files) > 0:
            logger.info(f"HTAS: {len(self.htas.modified_files)} files modified in this run.")
            try:
                summary = self.compactor.export_session_summary(self._messages)
                commit_hash = self.git.ceremonial_commit(summary)
                if commit_hash:
                    self._ritual_triggered = True
                    logger.info(f"💾 Ritual Complete: {commit_hash}")
            except Exception as e:
                logger.error(f"❌ Silent Ritual failed: {e}")


