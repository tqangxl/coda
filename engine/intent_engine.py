"""
Coda V4.0 — Intent Engine (Pillar 28+ 进化版)
智能意图中枢: LLM 驱动的意图分类、任务拆解(DAG)、多 Agent 语义路由、主动建议。

替代原有的纯正则 PromptSpeculation 和换行符拆分 CoordinatorEngine._split_task。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import cast, TYPE_CHECKING, TypedDict, Any
from collections.abc import Sequence

from .base_types import (
    AgentStatus, LoopPhase, TaskStatus, TokenUsage, ToolCall, IntentResult,
    TaskNode, PhaseTransition, TaskDAG, DomainConfig, LLMResponse, ExecutionPath,
    BaseLLM
)

if TYPE_CHECKING:
    from .db import SurrealStore

from .identity import registry

logger = logging.getLogger("Coda.intent")


# ════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════

# IntentResult and TaskNode are now imported from .base_types


# TaskDAG moved to base_types.py


# ════════════════════════════════════════════
#  意图分析 Prompt 模板
# ════════════════════════════════════════════

INTENT_ANALYSIS_PROMPT = """你是一个任务分析引擎。分析用户的请求并输出严格的 JSON（不要添加任何 markdown 标记）。

已注册的 Agent 角色:
{agent_roster}

用户消息:
"{user_message}"

最近上下文（最后 3 条对话）:
{recent_context}

请输出以下 JSON 结构:
{{
  "intent_type": "具体意图类型 (如: code_fix, audit_loan, schedule_task, data_analysis, deploy, general)",
  "confidence": 0.0到1.0的浮点数,
  "domain": "所属领域 (banking, engineering, scheduling, devops, general)",
  "complexity": "simple 或 compound 或 multi_phase",
  "steps": ["步骤1描述", "步骤2描述"],
  "dependencies": {{"步骤2描述": ["步骤1描述"]}},
  "suggested_agents": ["最匹配的agent_id"],
  "risk_level": "low 或 medium 或 high",
  "proactive_hints": ["你可能还需要...", "建议同时检查..."]
}}

规则:
- 如果任务涉及贷款、审计、财务、信贷、风控，domain 应为 "banking"，suggested_agents 应包含 "banking-expert"
- 如果任务涉及代码、修复、部署、测试，domain 应为 "engineering"
- 如果任务涉及日程、提醒、待办，domain 应为 "scheduling"
- 对于复合任务，steps 应拆解为有依赖关系的子步骤
- proactive_hints 应基于上下文给出 1-3 条主动建议"""


# ════════════════════════════════════════════
#  快速意图分类（零 LLM 调用版）
# ════════════════════════════════════════════

# DomainConfig moved to base_types.py

# 领域关键词映射（覆盖全部 10 个 Agent）
DOMAIN_KEYWORDS: dict[str, DomainConfig] = {
    "banking": {
        "keywords": [
            "贷款", "审批", "审计", "信贷", "风控", "抵押", "担保", "授信",
            "财务报表", "现金流", "拨备", "不良", "五级分类", "巴塞尔",
            "loan", "audit", "credit", "risk", "collateral", "financial",
            "三查", "贷前", "贷中", "贷后", "资本充足率", "行业分析",
            "融资", "利率", "还款", "逾期", "催收", "尽调", "尽职调查",
            "资产负债", "利润表", "现金流量表", "银行", "金融",
        ],
        "agents": ["banking-expert"],
        "base_confidence": 0.85,
    },
    "scheduling": {
        "keywords": [
            "提醒", "日程", "待办", "安排", "会议", "计划", "习惯",
            "schedule", "reminder", "todo", "meeting", "plan",
            "deadline", "打卡", "番茄钟", "周计划", "日历",
            "闹钟", "预约", "排期", "倒计时", "定时",
        ],
        "agents": ["schedule-manager"],
        "base_confidence": 0.80,
    },
    "engineering": {
        "keywords": [
            "代码", "修复", "bug", "fix", "deploy", "部署", "测试", "test",
            "编译", "构建", "build", "重构", "refactor", "优化", "性能",
            "api", "接口", "数据库", "migration", "迁移", "调试", "debug",
            "commit", "git", "分支", "合并", "merge", "pipeline",
        ],
        "agents": ["coder", "verifier"],
        "base_confidence": 0.75,
    },
    "learning": {
        "keywords": [
            "学习", "教程", "课程", "笔记", "复习", "考试", "刷题",
            "study", "learn", "course", "review", "quiz", "练习",
            "知识点", "大纲", "教材", "论文", "文献", "摘要",
            "总结", "归纳", "思维导图", "闪卡", "flashcard",
        ],
        "agents": ["study-manager"],
        "base_confidence": 0.80,
    },
    "memory": {
        "keywords": [
            "记住", "记忆", "存储", "回忆", "经验", "知识图谱",
            "remember", "memory", "knowledge", "insight", "store",
            "向量", "embedding", "检索", "索引", "归档",
        ],
        "agents": ["memory-keeper"],
        "base_confidence": 0.75,
    },
    "generation": {
        "keywords": [
            "生成", "创建", "写作", "设计", "草稿", "模板",
            "generate", "create", "write", "design", "draft", "template",
            "文案", "报告", "邮件", "文档", "方案", "策划",
        ],
        "agents": ["generator"],
        "base_confidence": 0.70,
    },
    "verification": {
        "keywords": [
            "验证", "检查", "对比", "校验", "审查", "合规",
            "verify", "check", "validate", "compare", "inspect",
            "质检", "回归", "断言", "assert", "一致性",
        ],
        "agents": ["verifier"],
        "base_confidence": 0.75,
    },
    "profile": {
        "keywords": [
            "用户画像", "偏好", "个性化", "配置", "设置", "风格",
            "profile", "preference", "personalize", "config", "settings",
            "习惯分析", "行为模式", "推荐",
        ],
        "agents": ["profile-manager"],
        "base_confidence": 0.70,
    },
}



class IntentEngine:
    """
    智能意图中枢 — Coda V5.0 认知推理架构。

    工作模式:
      1. Fast Path (零 LLM): 关键词匹配 → 快速路由（<1ms）
      2. Deep Path (LLM): 结构化分析 → 复杂意图拆解（~500 tokens）
      3. Hybrid: Fast Path 先行，置信度不足时降级到 Deep Path

    V5 超高阶能力:
      - 上下文感知推演 (SurrealDB 记忆注入)
      - LLM 动态转换发现 (未知意图 → LLM 推理新推演链)
      - 转换自动固化 (发现 → 验证 → 持久化)
      - 强化反馈环路 (成功/失败反馈 → 权重自动调整)
      - Agent 本地规则注入 (每个 Agent 注入自己的领域转换)
      - DAG 编译执行 (推演链 → TaskDAG → 并行执行)
    """

    # [Hermes Pattern] 意图引擎核心 (V5.0)
    
    _llm: BaseLLM | None
    _db: SurrealStore | None

    def __init__(
        self,
        llm_caller: BaseLLM | None = None,
        db: SurrealStore | None = None,
    ):
        self._llm = llm_caller
        self._db = db  # SurrealStore 实例
        self._history: list[IntentResult] = []   # 意图历史（用于模式学习）
        self._completed_phases: set[str] = set()  # 完成追踪
        self._active_roadmap: list[IntentResult] = []  # 当前活跃路线图
        # V5 新增
        self._outcome_log: list[dict[str, object]] = []  # 强化反馈日志
        self._learner_weights: dict[str, float] = {}  # 推演置信度权重
        self._agent_local_transitions: dict[str, list[PhaseTransition]] = {}  # Agent 本地规则
        self._solidified_transitions: dict[str, list[PhaseTransition]] = {}  # LLM 发现的已固化规则

    async def tune(self, feedback_data: dict[str, object]) -> None:
        """[Intent Pillar 42] 强化反馈环路: 根据执行结果动态调整意图置信度权重。"""
        intent = str(feedback_data.get("intent") or "")
        success = bool(feedback_data.get("success", True))
        
        if not intent:
            return
            
        current_weight = self._learner_weights.get(intent, 1.0)
        if success:
            new_weight = min(2.0, current_weight * 1.05)
        else:
            new_weight = max(0.5, current_weight * 0.8)
            
        self._learner_weights[intent] = new_weight
        logger.info(f"🧠 IntentEngine tuned: {intent} weight {current_weight:.2f} → {new_weight:.2f}")

        # 持久化到数据库 (Pillar 26)
        if self._db and self._db.is_connected:
            await self._db.save_intent_weights(self._learner_weights)

    async def load_weights(self) -> None:
        """[Intent Pillar 42] 从 DB/JSON 加载认知权重。"""
        if self._db:
            weights = await self._db.load_intent_weights()
            if weights:
                self.set_weights(weights)

    def get_weights(self) -> dict[str, float]:
        """[Pillar 42] 获取当前认知权重字典。"""
        return self._learner_weights.copy()

    def set_weights(self, weights: dict[str, float]) -> None:
        """[Pillar 42] 加载认知权重字典。"""
        self._learner_weights.update(weights)
        logger.debug(f"🧠 IntentEngine weights loaded: {len(weights)} entries.")

    # ════════════════════════════════════════════
    #  主入口
    # ════════════════════════════════════════════

    async def analyze(
        self,
        message: str,
        context: list[dict[str, object]] | None = None,
        agent_roster: list[dict[str, object]] | None = None,
    ) -> IntentResult:
        """
        分析意图并决定执行路径 (SAS vs MAS)。
        """
        # 1. 评估关联上下文噪声 (Pillar 28.1)
        noise_level = self._detect_context_noise(message, context)
        
        # 2. Fast Path (关键词极速路由)
        fast_res = self._fast_classify(message)
        fast_res.noise_score = noise_level
        
        # [SAS-L 极速优化] 如果是简单意图且噪声极低，直接返回单体路径
        if fast_res.confidence > 0.85 and noise_level < 0.2 and fast_res.complexity == "simple":
            fast_res.execution_path = ExecutionPath.SAS_L
            self._history.append(fast_res)
            return fast_res

        # 3. Deep Path (LLM 深度意图分析)
        if self._llm:
            try:
                deep_res = await self._deep_analyze(message, context, agent_roster)
                merged = self._merge_results(fast_res, deep_res)
                merged.noise_score = noise_level
                
                # [DPI 决策核心] SAS-L 优先
                if noise_level > 0.5:
                    merged.execution_path = ExecutionPath.MAS
                else:
                    merged.execution_path = ExecutionPath.SAS_L
                    if merged.complexity != "simple":
                        merged.complexity = "sas_l_monolithic"
                
                self._history.append(merged)
                return merged
            except Exception as e:
                logger.warning(f"IntentEngine Deep Path failed: {e}")

        # Fallback to SAS-L
        fast_res.execution_path = ExecutionPath.SAS_L
        self._history.append(fast_res)
        return fast_res
    def _detect_context_noise(self, message: str, context: list[dict[str, object]] | None) -> float:
        """
        [新增强化] 基于词汇密度和语义偏移评估上下文噪声阈值。
        如果包含大量无关信息、幻觉标记或冲突指令，噪声值升高。
        """
        if not context:
            return 0.0
            
        noise_score = 0.0
        
        # 1. 语义偏移检测: 检查最近消息与当前请求的相关度
        total_tokens = sum(len(str(m.get("content", ""))) for m in context[-5:])
        if total_tokens > 2000: # 上下文过长，潜在噪声增加
            noise_score += 0.2
            
        # 2. 幻觉与非法标记扫描 (如 Mock, Fake, placeholder 等被禁止的标记)
        prohibited_markers = ["mock", "stub", "placeholder", "fake", "TODO", "FIXME"]
        context_str = " ".join(str(m.get("content", "")) for m in context[-3:]).lower()
        for marker in prohibited_markers:
            if marker.lower() in context_str:
                noise_score += 0.15
                
        # 3. 角色切换频率 (频繁切换角色暗示任务碎片化/噪声高)
        roles = [m.get("role") for m in context[-5:]]
        switches = sum(1 for i in range(len(roles)-1) if roles[i] != roles[i+1])
        if switches > 3:
            noise_score += 0.2
            
        return min(1.0, noise_score)

    # ════════════════════════════════════════════
    #  Fast Path: 零 LLM 关键词分类
    # ════════════════════════════════════════════

    def _fast_classify(self, message: str) -> IntentResult:
        """基于关键词的快速意图分类（<1ms, 零 Token 消耗）。"""
        msg_lower = message.lower()
        best_domain = "general"
        best_score = 0
        best_config: DomainConfig | None = None

        for domain, config in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in config["keywords"] if kw in msg_lower)
            if score > best_score:
                best_score = score
                best_domain = domain
                best_config = config

        # 置信度 = base_confidence × min(命中词数/3, 1.0)
        confidence = 0.3  # 默认低置信度
        agents: list[str] = []
        
        # [V5.2] 动态专家发现: 使用 IdentityRegistry 匹配最佳专家
        matched_specialists = registry.search_specialists(message)
        if matched_specialists:
            agents = [s.role_id for s in matched_specialists[:2]]
            # 基础置信度提升，因为有匹配的专家元数据
            confidence = 0.7
        elif best_score > 0 and best_config:
            confidence = best_config["base_confidence"] * min(best_score / 3.0, 1.0)
            agents = best_config.get("agents", [])

        # 复杂度推断
        complexity = self._infer_complexity(message)

        # 意图类型推断
        intent_type = self._infer_intent_type(message, best_domain)

        # 主动建议（基于领域）
        hints = self._generate_fast_hints(message, best_domain)

        return IntentResult(
            intent_type=intent_type,
            confidence=round(confidence, 2),
            domain=best_domain,
            complexity=complexity,
            suggested_agents=agents,
            decomposed_steps=[],
            dependencies={},
            proactive_hints=hints,
            risk_level="low",
        )

    def _infer_complexity(self, message: str) -> str:
        """推断任务复杂度。"""
        # 多动词/多分句 → compound
        clauses = re.split(r"[，,。；;、然后并且接着再]", message)
        clauses = [c.strip() for c in clauses if len(c.strip()) > 2]

        action_patterns = [
            r"(分析|审计|检查|修复|部署|测试|创建|更新|删除|列出|查询|优化|重构)",
            r"(analyze|audit|check|fix|deploy|test|create|update|delete|list|query|optimize)",
        ]
        action_count = 0
        for pat in action_patterns:
            action_count += len(re.findall(pat, message, re.IGNORECASE))

        if action_count >= 3 or len(clauses) >= 3:
            return "multi_phase"
        elif action_count >= 2 or len(clauses) >= 2:
            return "compound"
        return "simple"

    def _infer_intent_type(self, message: str, domain: str) -> str:
        """基于消息内容和领域推断具体意图类型。"""
        msg_lower = message.lower()

        type_patterns: dict[str, list[str]] = {
            "audit_loan": ["审计", "贷款审批", "信贷审查", "loan audit"],
            "risk_assessment": ["风险评估", "风控", "risk assessment", "压力测试"],
            "financial_analysis": ["财务分析", "报表", "现金流", "financial"],
            "industry_analysis": ["行业分析", "行业风险", "industry"],
            "code_fix": ["修复", "bug", "fix", "error", "报错"],
            "code_review": ["审查", "review", "代码检查"],
            "deployment": ["部署", "deploy", "上线", "发布"],
            "testing": ["测试", "test", "验证"],
            "schedule_create": ["安排", "创建日程", "提醒", "schedule"],
            "task_query": ["待办", "任务列表", "今日任务", "task list"],
        }

        for itype, patterns in type_patterns.items():
            if any(p in msg_lower for p in patterns):
                return itype

        return f"{domain}_general"

    def _generate_fast_hints(self, message: str, domain: str) -> list[str]:
        """基于领域生成快速主动建议。"""
        hints: list[str] = []
        msg_lower = message.lower()

        if domain == "banking":
            if "贷款" in msg_lower or "loan" in msg_lower:
                hints.append("建议同步检查借款人的行业风险敞口")
            if "审计" in msg_lower or "audit" in msg_lower:
                hints.append("建议交叉验证财务报表与税审报告的一致性")
            if "财务" in msg_lower or "financial" in msg_lower:
                hints.append("建议对经营性现金流进行压力测试")
        elif domain == "engineering":
            if "修复" in msg_lower or "fix" in msg_lower:
                hints.append("修复后建议运行相关测试用例")
            if "部署" in msg_lower or "deploy" in msg_lower:
                hints.append("部署前建议检查环境变量和配置文件")
        elif domain == "scheduling":
            if "提醒" in msg_lower or "reminder" in msg_lower:
                hints.append("建议为重要提醒设置提前预警时间")

        # 通用建议：基于历史模式
        if len(self._history) >= 3:
            recent_domains = [h.domain for h in self._history[-5:]]
            if recent_domains.count(domain) >= 3:
                hints.append(f"检测到你近期频繁处理 {domain} 类任务，是否需要批量处理？")

        return hints[:3]

    # ════════════════════════════════════════════
    #  Deep Path: LLM 结构化分析
    # ════════════════════════════════════════════

    async def _deep_analyze(
        self,
        message: str,
        context: list[dict[str, object]] | None = None,
        agent_roster: list[dict[str, object]] | None = None,
    ) -> IntentResult:
        """调用 LLM 进行深度意图分析。"""
        # 构建 Agent 名单 (从 IdentityRegistry 动态获取，且仅包含已激活专家)
        agent_roster = agent_roster or [id.to_dict() for id in registry._identities.values() if id.is_active]
        roster_text = "无"
        if agent_roster:
            roster_lines = []
            for a in agent_roster:
                name = str(a.get("name", "?"))
                aid = str(a.get("role_id", a.get("id", "?")))
                desc = str(a.get("description", ""))
                caps = ", ".join(cast(list[str], a.get("capabilities", [])))
                roster_lines.append(f"  - {aid} ({name}):\n    描述: {desc}\n    能力: {caps}")
            roster_text = "\n".join(roster_lines)

        # 构建上下文
        ctx_text = "无"
        if context:
            ctx_lines = []
            for m in context[-3:]:
                role = str(m.get("role", "?"))
                content = str(m.get("content", ""))[:200]
                ctx_lines.append(f"  [{role}] {content}")
            ctx_text = "\n".join(ctx_lines)

        prompt = INTENT_ANALYSIS_PROMPT.format(
            agent_roster=roster_text,
            user_message=message,
            recent_context=ctx_text,
        )

        # 调用 LLM
        if not self._llm:
            logger.warning("Deep Path skipped: LLM not configured.")
            # 如果深度分析跳过，返回一个基础 General 意图，确保流程继续
            return IntentResult(intent_type="general", confidence=0.5)

        # 调用 LLM
        if not self._llm:
            logger.warning("Deep Path skipped: LLM not configured.")
            # 如果深度分析跳过，返回一个基础 General 意图，确保流程继续
            return IntentResult(intent_type="general", confidence=0.5)

        llm_resp: LLMResponse = await self._llm.call(
            [{"role": "user", "content": prompt}],
            tools=None,
        )

        # 解析 JSON
        return self._parse_llm_response(llm_resp.text)

    def _parse_llm_response(self, text: str) -> IntentResult:
        """从 LLM 输出中解析 IntentResult。"""
        # 尝试提取 JSON
        json_match = re.search(r"\{[\s\S]*\}", text)
        if not json_match:
            logger.warning("IntentEngine: No JSON found in LLM response")
            return IntentResult(raw_llm_output=text)

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.warning("IntentEngine: Invalid JSON in LLM response")
            return IntentResult(raw_llm_output=text)

        data = cast(dict[str, object], data)
        return IntentResult(
            intent_type=str(data.get("intent_type", "general")),
            confidence=float(cast(float, data.get("confidence", 0.5))),
            domain=str(data.get("domain", "general")),
            complexity=str(data.get("complexity", "simple")),
            suggested_agents=cast(list[str], data.get("suggested_agents", [])),
            decomposed_steps=cast(list[str], data.get("steps", [])),
            dependencies=cast(dict[str, list[str]], data.get("dependencies", {})),
            proactive_hints=cast(list[str], data.get("proactive_hints", [])),
            risk_level=str(data.get("risk_level", "low")),
            raw_llm_output=text,
        )

    # ════════════════════════════════════════════
    #  结果合并
    # ════════════════════════════════════════════

    def _merge_results(self, fast: IntentResult, deep: IntentResult) -> IntentResult:
        """合并 Fast Path 和 Deep Path 的结果（Deep 优先）。"""
        # Agent 列表合并去重
        agents = list(dict.fromkeys(deep.suggested_agents + fast.suggested_agents))

        # Hints 合并去重
        hints = list(dict.fromkeys(deep.proactive_hints + fast.proactive_hints))[:5]

        return IntentResult(
            intent_type=deep.intent_type or fast.intent_type,
            confidence=max(deep.confidence, fast.confidence),
            domain=deep.domain if deep.domain != "general" else fast.domain,
            complexity=deep.complexity if deep.complexity != "simple" else fast.complexity,
            suggested_agents=agents,
            decomposed_steps=deep.decomposed_steps or fast.decomposed_steps,
            dependencies=deep.dependencies or fast.dependencies,
            proactive_hints=hints,
            risk_level=deep.risk_level if deep.risk_level != "low" else fast.risk_level,
            raw_llm_output=deep.raw_llm_output,
        )

    # ════════════════════════════════════════════
    #  任务拆解: IntentResult → TaskDAG
    # ════════════════════════════════════════════

    def build_dag(self, intent: IntentResult) -> TaskDAG:
        """将 IntentResult 转化为 TaskDAG。支持单体长思考节点的特殊处理。"""
        dag = TaskDAG()

        # [V5.1] SAS_L 优化: 如果选择单体路径，生成“单节点”DAG
        if intent.execution_path == ExecutionPath.SAS_L:
            dag.add_node(TaskNode(
                task_id="sas_l_reasoning_node",
                description=f"Long-Thinking Reasoning for: {intent.intent_type}",
                assigned_agent=intent.suggested_agents[0] if intent.suggested_agents else "commander",
                metadata={"mode": "sas_l", "budget_mult": 1.5}
            ))
            return dag

        if not intent.decomposed_steps:
            # 单步任务
            dag.add_node(TaskNode(
                task_id="step_0",
                description=intent.intent_type,
                assigned_agent=intent.suggested_agents[0] if intent.suggested_agents else "",
            ))
            return dag

        # 为每个步骤创建节点
        step_to_id: dict[str, str] = {}
        for i, step in enumerate(intent.decomposed_steps):
            tid = f"step_{i}"
            step_to_id[step] = tid

            # 从 dependencies 中查找依赖
            deps: list[str] = []
            for dep_step in intent.dependencies.get(step, []):
                if dep_step in step_to_id:
                    deps.append(step_to_id[dep_step])

            # 轮询分配 Agent
            agent = ""
            if intent.suggested_agents:
                agent = intent.suggested_agents[i % len(intent.suggested_agents)]

            dag.add_node(TaskNode(
                task_id=tid,
                description=step,
                assigned_agent=agent,
                depends_on=deps,
                priority=100 - i * 10,
            ))

        return dag

    # ════════════════════════════════════════════
    #  HTAS: 诚实终止与抗卡死审计 (Pillar 31)
    # ════════════════════════════════════════════

    async def reflect_on_progress(
        self,
        goal: str,
        messages: list[dict[str, Any]],
        modified_files: set[str],
        stagnation_count: int = 0
    ) -> dict[str, Any]:
        """
        [HTAS] 执行“诚实监察员”反射。
        评估物理变动、历史轨迹并输出客观终结结论。
        """
        if not self._llm:
            return {"verdict": "continue", "reason": "LLM not available for reflection"}

        # 1. 加载提示词模板
        prompt_path = Path("d:/ai/workspace/engine/prompt-templates/termination_judge.prompt")
        if not prompt_path.exists():
            # 回退到内建极简模板
            template = "目标: {user_goal}\n变动文件: {modified_files}\n停滞步数: {stagnation_count}\n请基于轨迹判断是否达成。输出 JSON: {{'verdict': ...}}"
        else:
            template = prompt_path.read_text(encoding="utf-8")

        # 2. 提炼轨迹摘要 (最近 5 轮)
        recent_history = messages[-10:]
        trajectory_text = "\n".join([f"[{m.get('role')}]: {str(m.get('content'))[:200]}..." for m in recent_history])
        
        last_tool_res = ""
        for m in reversed(messages):
            if m.get("role") == "tool":
                last_tool_res = str(m.get("content"))[:300]
                break

        # 3. 填充模板
        prompt = template.format(
            user_goal=goal,
            trajectory_summary=trajectory_text,
            modified_files=", ".join(modified_files) if modified_files else "无",
            last_tool_result=last_tool_res or "无",
            stagnation_count=stagnation_count
        )

        # 4. 调用 LLM
        try:
            resp = await self._llm.call([{"role": "user", "content": prompt}])
            
            # 5. 解析 JSON 结论
            json_match = re.search(r"\{[\s\S]*\}", resp.text)
            if json_match:
                result = json.loads(json_match.group())
                logger.info(f"🧐 HTAS Reflection Verdict: {result.get('verdict')} (Progress: {result.get('honest_progress')}%)")
                return result
        except Exception as e:
            logger.error(f"HTAS Reflection failed: {e}")
            
        return {"verdict": "continue", "reason": "Reflection encountered error"}

    # ════════════════════════════════════════════
    #  递归多阶段前瞻推演 V2 (Cross-Domain Recursive Projection)
    # ════════════════════════════════════════════

    # 全领域阶段转换图: intent_type → 后续可能的阶段链
    # 每条边可以跨领域 (domain bridge)
    PHASE_TRANSITIONS: dict[str, list[PhaseTransition]] = {

        # ═══════════════════════════════════════
        # Banking 领域推演链
        # ═══════════════════════════════════════
        "audit_loan": [
            {"phase": "financial_analysis", "reason": "审计发现后需深入分析财务数据",
             "agents": ["banking-expert"], "risk": "medium", "domain": "banking"},
            {"phase": "risk_assessment", "reason": "财务分析完成后需量化风险敞口",
             "agents": ["banking-expert"], "risk": "high", "domain": "banking"},
            {"phase": "industry_analysis", "reason": "需评估借款人所在行业整体风险",
             "agents": ["banking-expert"], "risk": "medium", "domain": "banking"},
            # 🔀 跨域: 审计 → 工程 (发现系统风控漏洞)
            {"phase": "code_fix", "reason": "🔀 审计发现风控系统缺陷需技术修复",
             "agents": ["coder"], "risk": "high", "domain": "engineering"},
        ],
        "financial_analysis": [
            {"phase": "risk_assessment", "reason": "发现财务异常后需评估风险",
             "agents": ["banking-expert"], "risk": "medium", "domain": "banking"},
            {"phase": "industry_analysis", "reason": "需结合行业背景验证财务合理性",
             "agents": ["banking-expert"], "risk": "low", "domain": "banking"},
            # 🔀 跨域: 财务分析 → 生成 (自动出报告)
            {"phase": "report_generation", "reason": "🔀 财务分析完成后自动生成审计报告",
             "agents": ["generator"], "risk": "low", "domain": "generation"},
        ],
        "risk_assessment": [
            {"phase": "stress_testing", "reason": "风险量化后需执行极端场景压力测试",
             "agents": ["banking-expert"], "risk": "high", "domain": "banking"},
            {"phase": "approval_decision", "reason": "风险评估完成后出具最终审批意见",
             "agents": ["banking-expert"], "risk": "high", "domain": "banking"},
            # 🔀 跨域: 风险 → 日程 (设置风险复核提醒)
            {"phase": "schedule_create", "reason": "🔀 高风险敞口需设置定期复核提醒",
             "agents": ["schedule-manager"], "risk": "medium", "domain": "scheduling"},
        ],
        "industry_analysis": [
            {"phase": "risk_assessment", "reason": "行业分析揭示潜在风险需量化",
             "agents": ["banking-expert"], "risk": "medium", "domain": "banking"},
            {"phase": "concentration_alert", "reason": "需检查行业集中度是否触发预警",
             "agents": ["banking-expert"], "risk": "medium", "domain": "banking"},
            # 🔀 跨域: 行业分析 → 记忆 (固化行业知识)
            {"phase": "knowledge_store", "reason": "🔀 行业分析结论应存入知识图谱供复用",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],
        "stress_testing": [
            {"phase": "approval_decision", "reason": "压力测试通过后出具审批意见",
             "agents": ["banking-expert"], "risk": "high", "domain": "banking"},
        ],
        "approval_decision": [
            {"phase": "post_loan_monitoring", "reason": "审批通过后需建立贷后监控计划",
             "agents": ["banking-expert", "schedule-manager"], "risk": "medium", "domain": "banking"},
            # 🔀 跨域: 审批 → 记忆 (归档审批经验)
            {"phase": "experience_archive", "reason": "🔀 审批案例应归档为团队经验",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],
        "post_loan_monitoring": [
            {"phase": "schedule_create", "reason": "设置贷后检查定期提醒",
             "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
        ],

        # ═══════════════════════════════════════
        # Engineering 领域推演链
        # ═══════════════════════════════════════
        "code_fix": [
            {"phase": "testing", "reason": "修复后必须验证功能正确性",
             "agents": ["verifier"], "risk": "medium", "domain": "engineering"},
            {"phase": "code_review", "reason": "测试通过后需代码审查",
             "agents": ["verifier"], "risk": "low", "domain": "engineering"},
            {"phase": "deployment", "reason": "审查通过后可部署生产",
             "agents": ["coder"], "risk": "medium", "domain": "engineering"},
        ],
        "testing": [
            {"phase": "code_review", "reason": "测试全部通过后进行代码审查",
             "agents": ["verifier"], "risk": "low", "domain": "engineering"},
            {"phase": "deployment", "reason": "验证完成后可部署",
             "agents": ["coder"], "risk": "medium", "domain": "engineering"},
            # 🔀 跨域: 测试 → 生成 (自动生成测试报告)
            {"phase": "report_generation", "reason": "🔀 测试完成后自动生成测试报告",
             "agents": ["generator"], "risk": "low", "domain": "generation"},
        ],
        "deployment": [
            {"phase": "monitoring", "reason": "部署后需监控服务健康状态",
             "agents": ["schedule-manager"], "risk": "medium", "domain": "scheduling"},
            {"phase": "rollback_plan", "reason": "需准备回滚方案以应对异常",
             "agents": ["coder"], "risk": "high", "domain": "engineering"},
            # 🔀 跨域: 部署 → 记忆 (记录部署经验)
            {"phase": "experience_archive", "reason": "🔀 部署过程应记录为运维经验",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],
        "code_review": [
            {"phase": "code_fix", "reason": "审查发现问题需修复",
             "agents": ["coder"], "risk": "low", "domain": "engineering"},
            {"phase": "deployment", "reason": "审查通过后部署",
             "agents": ["coder"], "risk": "medium", "domain": "engineering"},
        ],
        "monitoring": [
            {"phase": "alert_triage", "reason": "监控触发告警后需分级处理",
             "agents": ["coder", "verifier"], "risk": "high", "domain": "engineering"},
            # 🔀 跨域: 监控 → 日程 (设置监控巡检)
            {"phase": "schedule_create", "reason": "🔀 需设置定期监控巡检计划",
             "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
        ],
        "alert_triage": [
            {"phase": "code_fix", "reason": "告警分析后需紧急修复",
             "agents": ["coder"], "risk": "high", "domain": "engineering"},
        ],

        # ═══════════════════════════════════════
        # Learning 领域推演链
        # ═══════════════════════════════════════
        "study_plan": [
            {"phase": "content_review", "reason": "制定学习计划后开始内容复习",
             "agents": ["study-manager"], "risk": "low", "domain": "learning"},
            # 🔀 跨域: 学习 → 日程 (设置学习提醒)
            {"phase": "schedule_create", "reason": "🔀 需设置复习提醒和学习计划日程",
             "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
        ],
        "content_review": [
            {"phase": "knowledge_test", "reason": "复习完成后需自测验证掌握程度",
             "agents": ["study-manager"], "risk": "low", "domain": "learning"},
            # 🔀 跨域: 复习 → 记忆 (固化知识点)
            {"phase": "knowledge_store", "reason": "🔀 复习内容应存入长效记忆",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],
        "knowledge_test": [
            {"phase": "weak_point_analysis", "reason": "测试后分析薄弱环节",
             "agents": ["study-manager"], "risk": "low", "domain": "learning"},
            # 🔀 跨域: 测试 → 生成 (生成错题集)
            {"phase": "report_generation", "reason": "🔀 自动生成错题分析报告",
             "agents": ["generator"], "risk": "low", "domain": "generation"},
        ],
        "weak_point_analysis": [
            {"phase": "study_plan", "reason": "基于薄弱点调整学习计划",
             "agents": ["study-manager"], "risk": "low", "domain": "learning"},
        ],

        # ═══════════════════════════════════════
        # Memory 领域推演链
        # ═══════════════════════════════════════
        "knowledge_store": [
            {"phase": "knowledge_index", "reason": "存储后需建立向量索引方便检索",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
            # 🔀 跨域: 存储 → 验证 (验证知识一致性)
            {"phase": "consistency_check", "reason": "🔀 新知识需检查与已有知识的一致性",
             "agents": ["verifier"], "risk": "low", "domain": "verification"},
        ],
        "knowledge_index": [
            {"phase": "knowledge_link", "reason": "索引建立后需关联相关知识节点",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],
        "knowledge_link": [
            # 🔀 跨域: 关联 → 画像 (更新用户知识画像)
            {"phase": "profile_update", "reason": "🔀 知识图谱更新后应刷新用户画像",
             "agents": ["profile-manager"], "risk": "low", "domain": "profile"},
        ],
        "experience_archive": [
            {"phase": "knowledge_store", "reason": "经验归档后存入知识库",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],

        # ═══════════════════════════════════════
        # Generation 领域推演链
        # ═══════════════════════════════════════
        "report_generation": [
            {"phase": "content_review_gen", "reason": "生成后需审校内容准确性",
             "agents": ["verifier"], "risk": "medium", "domain": "verification"},
            # 🔀 跨域: 生成 → 记忆 (归档生成物)
            {"phase": "knowledge_store", "reason": "🔀 生成的报告应归档到知识库",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],
        "draft_creation": [
            {"phase": "content_review_gen", "reason": "草稿完成后需审校",
             "agents": ["verifier"], "risk": "low", "domain": "verification"},
        ],
        "template_design": [
            {"phase": "draft_creation", "reason": "模板设计完成后生成草稿",
             "agents": ["generator"], "risk": "low", "domain": "generation"},
        ],

        # ═══════════════════════════════════════
        # Verification 领域推演链
        # ═══════════════════════════════════════
        "consistency_check": [
            {"phase": "conflict_resolution", "reason": "发现不一致后需解决冲突",
             "agents": ["verifier"], "risk": "medium", "domain": "verification"},
        ],
        "content_review_gen": [
            {"phase": "draft_creation", "reason": "审校发现问题需重新生成",
             "agents": ["generator"], "risk": "low", "domain": "generation"},
            # 🔀 跨域: 审校通过 → 记忆 (归档终稿)
            {"phase": "knowledge_store", "reason": "🔀 审校通过后归档为正式文档",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],
        "conflict_resolution": [
            {"phase": "knowledge_store", "reason": "冲突解决后更新知识库",
             "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
        ],

        # ═══════════════════════════════════════
        # Scheduling 领域推演链
        # ═══════════════════════════════════════
        "schedule_create": [
            {"phase": "reminder_setup", "reason": "日程创建后需设置提醒",
             "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
            {"phase": "conflict_check_sched", "reason": "需检查是否与现有日程冲突",
             "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
        ],
        "task_query": [
            {"phase": "priority_sort", "reason": "查询结果需按紧急重要度排序",
             "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
            {"phase": "overdue_alert", "reason": "需检查是否有逾期未完成的任务",
             "agents": ["schedule-manager"], "risk": "medium", "domain": "scheduling"},
        ],
        "overdue_alert": [
            # 🔀 跨域: 逾期 → 画像 (分析拖延模式)
            {"phase": "profile_update", "reason": "🔀 逾期频繁时需分析用户行为模式",
             "agents": ["profile-manager"], "risk": "low", "domain": "profile"},
        ],

        # ═══════════════════════════════════════
        # Profile 领域推演链
        # ═══════════════════════════════════════
        "profile_update": [
            {"phase": "preference_analysis", "reason": "画像更新后需分析偏好变化",
             "agents": ["profile-manager"], "risk": "low", "domain": "profile"},
        ],
        "preference_analysis": [
            # 🔀 跨域: 偏好 → 学习 (个性化学习路径)
            {"phase": "study_plan", "reason": "🔀 基于偏好分析推荐个性化学习路径",
             "agents": ["study-manager"], "risk": "low", "domain": "learning"},
            # 🔀 跨域: 偏好 → 日程 (优化日程安排)
            {"phase": "schedule_create", "reason": "🔀 基于行为模式优化日程安排",
             "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
        ],
    }

    def project_forward(
        self,
        current_intent: IntentResult,
        depth: int = 3,
        visited: set[str] | None = None,
        include_branches: bool = False,
    ) -> list[IntentResult]:
        """
        递归多阶段前瞻推演 V2 — 支持跨领域桥接 + 并行分支。

        从当前意图出发，沿着 PHASE_TRANSITIONS 图递归推演后续阶段。
        V2 新增：
          - 跨领域桥接：banking → engineering, learning → memory, 等
          - 并行分支：include_branches=True 时，展示备选路径
          - 域切换标记：跨域阶段会在 proactive_hints 中用 🔀 标记

        Args:
            current_intent: 当前已分析的意图
            depth: 最大推演深度（防止无限递归）
            visited: 已访问的阶段（防止环路）
            include_branches: 是否包含并行备选路径

        Returns:
            按执行顺序排列的 IntentResult 列表（不含当前阶段）
        """
        if depth <= 0:
            return []

        if visited is None:
            visited = set()

        if current_intent.intent_type in visited:
            return []
        visited.add(current_intent.intent_type)

        next_phases = self.PHASE_TRANSITIONS.get(current_intent.intent_type, [])

        # —— 无静态转换规则时，尝试 LLM 动态推演 ——
        if not next_phases:
            return self._dynamic_project(current_intent, depth)

        projections: list[IntentResult] = []

        # 主路径：第一个未访问的后续阶段
        primary: PhaseTransition | None = None
        for candidate in next_phases:
            cname = str(candidate.get("phase", ""))
            if cname and cname not in visited:
                primary = candidate
                break
        if primary is None:
            return []

        phase_name = str(primary.get("phase", ""))
        phase_domain = str(primary.get("domain", current_intent.domain))
        is_cross_domain = phase_domain != current_intent.domain
        reason = str(primary.get("reason", ""))

        projected = IntentResult(
            intent_type=phase_name,
            confidence=current_intent.confidence * 0.85,
            domain=phase_domain,
            complexity="simple",
            suggested_agents=list(primary.get("agents", [])),
            decomposed_steps=[],
            dependencies={},
            proactive_hints=[reason],
            risk_level=str(primary.get("risk", "low")),
        )
        projections.append(projected)

        # 并行分支：记录备选路径（不递归深入，仅标记）
        if include_branches:
            for alt in next_phases[1:]:
                alt_name = str(alt.get("phase", ""))
                if alt_name and alt_name not in visited and alt_name != phase_name:
                    alt_domain = str(alt.get("domain", current_intent.domain))
                    branch = IntentResult(
                        intent_type=f"[branch] {alt_name}",
                        confidence=current_intent.confidence * 0.6,  # 分支置信度更低
                        domain=alt_domain,
                        complexity="simple",
                        suggested_agents=list(alt.get("agents", [])),
                        proactive_hints=[f"备选: {alt.get('reason', '')}"],
                        risk_level=str(alt.get("risk", "low")),
                    )
                    projections.append(branch)

        # 递归推演下一阶段
        deeper = self.project_forward(projected, depth - 1, visited.copy(), include_branches)
        projections.extend(deeper)

        return projections

    def _dynamic_project(self, intent: IntentResult, depth: int) -> list[IntentResult]:
        """
        动态推演兜底 — 当 PHASE_TRANSITIONS 中无匹配规则时。

        使用通用的领域推演模式（不需要 LLM 调用），
        基于意图的 domain 属性推断下一步。
        """
        generic_transitions: dict[str, list[PhaseTransition]] = {
            "banking": [
                {"phase": "report_generation", "reason": "完成分析后需生成报告",
                 "agents": ["generator"], "risk": "low", "domain": "generation"},
            ],
            "engineering": [
                {"phase": "experience_archive", "reason": "工程任务完成后归档经验",
                 "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
            ],
            "learning": [
                {"phase": "knowledge_store", "reason": "学习完成后固化知识",
                 "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
            ],
            "generation": [
                {"phase": "content_review_gen", "reason": "内容生成后需审校",
                 "agents": ["verifier"], "risk": "low", "domain": "verification"},
            ],
            "verification": [
                {"phase": "experience_archive", "reason": "验证完成后记录结论",
                 "agents": ["memory-keeper"], "risk": "low", "domain": "memory"},
            ],
            "scheduling": [
                {"phase": "profile_update", "reason": "日程执行后更新行为画像",
                 "agents": ["profile-manager"], "risk": "low", "domain": "profile"},
            ],
            "memory": [
                {"phase": "profile_update", "reason": "知识更新后刷新画像",
                 "agents": ["profile-manager"], "risk": "low", "domain": "profile"},
            ],
            "profile": [
                {"phase": "schedule_create", "reason": "画像更新后优化日程",
                 "agents": ["schedule-manager"], "risk": "low", "domain": "scheduling"},
            ],
        }

        fallback = generic_transitions.get(intent.domain, [])
        if not fallback or depth <= 0:
            return []

        fb = fallback[0]
        return [IntentResult(
            intent_type=str(fb.get("phase", "")),
            confidence=intent.confidence * 0.7,  # 动态推演置信度更低
            domain=str(fb.get("domain", "general")),
            complexity="simple",
            suggested_agents=list(fb.get("agents", [])),
            proactive_hints=[f"⚡ 动态推演: {fb.get('reason', '')}"],
            risk_level=str(fb.get("risk", "low")),
        )]

    def build_full_roadmap(
        self,
        intent: IntentResult,
        depth: int = 5,
        include_branches: bool = False,
    ) -> dict[str, object]:
        """
        构建完整的多阶段执行路线图 V2。

        将当前意图 + 前瞻推演结果组合为一个结构化的路线图，
        可直接注入到 System Prompt 中指导 LLM 的多步推理。

        V2 新增：
          - 跨域桥接标记 (🔀)
          - 并行分支 ([branch])
          - 紧急度评分 (urgency)
          - 域切换统计

        Returns:
            完整路线图字典
        """
        projections = self.project_forward(intent, depth=depth, include_branches=include_branches)

        phases: list[dict[str, object]] = []
        risk_chain: list[str] = [intent.risk_level]
        domain_switches: int = 0
        prev_domain: str = intent.domain
        urgent_phases: list[str] = []

        for proj in projections:
            is_branch = proj.intent_type.startswith("[branch]")
            is_cross_domain = proj.domain != prev_domain and not is_branch
            urgency = self._score_urgency(proj)

            phase_info: dict[str, object] = {
                "phase": proj.intent_type,
                "reason": proj.proactive_hints[0] if proj.proactive_hints else "",
                "agents": proj.suggested_agents,
                "risk": proj.risk_level,
                "confidence": round(proj.confidence, 2),
                "domain": proj.domain,
                "urgency": urgency,
            }

            if is_cross_domain:
                phase_info["cross_domain"] = True
                phase_info["from_domain"] = prev_domain
                domain_switches += 1

            if is_branch:
                phase_info["is_branch"] = True

            phases.append(phase_info)
            risk_chain.append(proj.risk_level)

            if not is_branch:
                prev_domain = proj.domain

            if urgency >= 0.7:
                urgent_phases.append(proj.intent_type)

        return {
            "current": {
                "phase": intent.intent_type,
                "domain": intent.domain,
                "agents": intent.suggested_agents,
                "risk": intent.risk_level,
            },
            "projected_phases": phases,
            "total_phases": 1 + len([p for p in phases if not str(p.get("phase", "")).startswith("[branch]")]),
            "risk_escalation": " → ".join(risk_chain),
            "domain_switches": domain_switches,
            "urgent_phases": urgent_phases,
        }

    # ════════════════════════════════════════════
    #  紧急度评分 (Urgency Scoring)
    # ════════════════════════════════════════════

    # 高紧急度关键词
    _URGENCY_KEYWORDS: list[str] = [
        "紧急", "立即", "马上", "urgent", "asap", "critical",
        "告警", "alert", "故障", "down", "P0", "P1",
        "逾期", "overdue", "rollback", "回滚",
    ]

    def _score_urgency(self, intent: IntentResult) -> float:
        """
        评估某个推演阶段的紧急度 (0.0 ~ 1.0)。

        综合考虑:
          - 风险等级 (high → 0.6 base)
          - 关键词匹配 (紧急/告警/故障 → +0.3)
          - 置信度 (高置信高风险 → 更紧急)
        """
        score = 0.0

        # 风险基线
        risk_scores = {"high": 0.6, "medium": 0.3, "low": 0.1}
        score += risk_scores.get(intent.risk_level, 0.1)

        # 关键词提升
        all_text = " ".join(intent.proactive_hints + [intent.intent_type])
        for kw in self._URGENCY_KEYWORDS:
            if kw in all_text:
                score += 0.15
                break  # 只加一次

        # 置信度加权
        if intent.confidence > 0.7 and intent.risk_level == "high":
            score += 0.15

        return min(score, 1.0)

    # ════════════════════════════════════════════
    #  完成追踪 (Phase Completion Tracking)
    # ════════════════════════════════════════════

    def __init_completion_tracker(self) -> None:
        """初始化完成追踪器（在 __init__ 中调用）。"""
        if not hasattr(self, "_completed_phases"):
            self._completed_phases = set()
            self._active_roadmap = []

    def mark_phase_complete(self, phase_name: str) -> dict[str, object]:
        """
        标记某个推演阶段为已完成，返回下一步建议。

        Returns:
            {
                "completed": "phase_name",
                "remaining": [...],
                "next_phase": {...} or None,
                "progress": "2/5 (40%)"
            }
        """
        self.__init_completion_tracker()
        self._completed_phases.add(phase_name)

        remaining = [
            p for p in self._active_roadmap
            if p.intent_type not in self._completed_phases
            and not p.intent_type.startswith("[branch]")
        ]

        next_phase = remaining[0] if remaining else None
        total = len([p for p in self._active_roadmap if not p.intent_type.startswith("[branch]")])
        done = total - len(remaining)

        result: dict[str, object] = {
            "completed": phase_name,
            "remaining": [p.intent_type for p in remaining],
            "progress": f"{done}/{total} ({done*100//max(total,1)}%)",
        }

        if next_phase:
            result["next_phase"] = {
                "phase": next_phase.intent_type,
                "domain": next_phase.domain,
                "agents": next_phase.suggested_agents,
                "reason": next_phase.proactive_hints[0] if next_phase.proactive_hints else "",
                "urgency": self._score_urgency(next_phase),
            }

        return result

    def start_roadmap_tracking(self, intent: IntentResult, depth: int = 5) -> dict[str, object]:
        """
        启动路线图追踪 — 结合 build_full_roadmap + 完成追踪。

        生成完整路线图并激活追踪器，后续可通过
        mark_phase_complete() 逐步推进。
        """
        self.__init_completion_tracker()
        self._completed_phases.clear()
        self._active_roadmap = self.project_forward(intent, depth=depth)

        roadmap = self.build_full_roadmap(intent, depth=depth, include_branches=True)
        roadmap["tracking_active"] = True
        roadmap["completed"] = []
        return roadmap

    # ════════════════════════════════════════════
    #  历史自适应学习 (Adaptive History Learning)
    # ════════════════════════════════════════════

    def learn_from_history(self) -> dict[str, object]:
        """
        从 _history 中学习实际发生的转换模式。

        分析历史中连续的意图类型对，统计实际发生的转换频率，
        用于动态调整推演链的置信度。

        Returns:
            {
                "observed_transitions": {"audit_loan → financial_analysis": 3, ...},
                "domain_flow": ["banking", "banking", "engineering", ...],
                "cross_domain_count": 2,
                "pattern_confidence": {...}
            }
        """
        if len(self._history) < 2:
            return {"observed_transitions": {}, "domain_flow": [], "cross_domain_count": 0}

        transitions: dict[str, int] = {}
        domain_flow: list[str] = []
        cross_domain = 0

        for i in range(len(self._history) - 1):
            curr = self._history[i]
            nxt = self._history[i + 1]
            key = f"{curr.intent_type} → {nxt.intent_type}"
            transitions[key] = transitions.get(key, 0) + 1
            domain_flow.append(curr.domain)

            if curr.domain != nxt.domain:
                cross_domain += 1

        if self._history:
            domain_flow.append(self._history[-1].domain)

        # 基于历史频率调整转换置信度
        pattern_confidence: dict[str, float] = {}
        total = sum(transitions.values())
        for key, count in transitions.items():
            pattern_confidence[key] = round(count / max(total, 1), 2)

        return {
            "observed_transitions": transitions,
            "domain_flow": domain_flow,
            "cross_domain_count": cross_domain,
            "pattern_confidence": pattern_confidence,
        }

    # ════════════════════════════════════════════
    #  状态报告
    # ════════════════════════════════════════════

    @property
    def stats(self) -> dict[str, object]:
        domain_counts: dict[str, int] = {}
        for h in self._history:
            domain_counts[h.domain] = domain_counts.get(h.domain, 0) + 1

        transition_stats = self.learn_from_history()

        return {
            "total_analyses": len(self._history),
            "domain_distribution": domain_counts,
            "last_intent": self._history[-1].intent_type if self._history else None,
            "last_confidence": self._history[-1].confidence if self._history else None,
            "transition_count": len(self.PHASE_TRANSITIONS),
            "cross_domain_bridges": sum(
                1 for phases in self.PHASE_TRANSITIONS.values()
                for p in phases
                if "🔀" in str(p.get("reason", ""))
            ),
            "history_patterns": transition_stats.get("observed_transitions", {}),
        }

    # ════════════════════════════════════════════════════════════════
    #  V3: 条件分支推演 (Conditional Branching)
    # ════════════════════════════════════════════════════════════════

    # 条件规则表: intent_type → 条件函数 → 优先选择哪条边
    # 当条件满足时，重排 PHASE_TRANSITIONS 中对应的候选列表
    CONDITION_RULES: dict[str, list[dict[str, object]]] = {
        "risk_assessment": [
            # 如果当前推演链中已经有过 stress_testing，跳过它
            {"condition": "already_visited:stress_testing",
             "prefer": "approval_decision",
             "reason": "压力测试已执行，直接进入审批"},
        ],
        "code_review": [
            # 如果推演链中风险等级为 high，优先修复而非部署
            {"condition": "risk_level:high",
             "prefer": "code_fix",
             "reason": "高风险场景下审查发现问题应优先修复"},
        ],
        "financial_analysis": [
            # 如果历史中已经有行业分析，跳过它
            {"condition": "already_visited:industry_analysis",
             "prefer": "risk_assessment",
             "reason": "行业分析已完成，直接进入风险评估"},
        ],
    }

    def _evaluate_conditions(
        self,
        intent_type: str,
        candidates: list[PhaseTransition],
        visited: set[str],
        risk_level: str,
    ) -> list[PhaseTransition]:
        """
        条件推演引擎 — 基于运行时上下文重排候选转换。

        检查 CONDITION_RULES 中的条件规则，若匹配则将首选阶段
        提前到候选列表最前面，实现 if/else 式的推演分支。
        """
        rules = self.CONDITION_RULES.get(intent_type, [])
        if not rules:
            return candidates

        for rule in rules:
            cond = str(rule.get("condition", ""))
            prefer = str(rule.get("prefer", ""))

            matched = False

            if cond.startswith("already_visited:"):
                check_phase = cond.split(":", 1)[1]
                matched = check_phase in visited

            elif cond.startswith("risk_level:"):
                check_risk = cond.split(":", 1)[1]
                matched = risk_level == check_risk

            elif cond.startswith("history_count_gt:"):
                # history_count_gt:3 → 历史分析次数 > 3 时触发
                threshold = int(cond.split(":", 1)[1])
                matched = len(self._history) > threshold

            if matched and prefer:
                # 将首选阶段提到最前
                reordered = []
                rest = []
                for c in candidates:
                    if str(c.get("phase", "")) == prefer:
                        reordered.insert(0, c)
                    else:
                        rest.append(c)
                return reordered + rest

        return candidates

    # ════════════════════════════════════════════════════════════════
    #  V3: 推演链可视化编译 (Mermaid Roadmap Compiler)
    # ════════════════════════════════════════════════════════════════

    def compile_mermaid(self, intent: IntentResult, depth: int = 5) -> str:
        """
        将推演链编译为 Mermaid 状态图，可直接渲染为可视化图。

        输出格式:
        ```mermaid
        stateDiagram-v2
            [*] --> audit_loan
            audit_loan --> financial_analysis : 审计发现后需分析
            financial_analysis --> risk_assessment : 发现异常需评估
            ...
        ```
        """
        projections = self.project_forward(intent, depth=depth, include_branches=True)

        lines: list[str] = ["stateDiagram-v2"]

        # 起始节点
        safe_start = intent.intent_type.replace(" ", "_")
        lines.append(f"    [*] --> {safe_start}")

        # 为每个阶段添加样式标注
        domain_colors: dict[str, str] = {
            "banking": "🏦",
            "engineering": "⚙️",
            "scheduling": "📅",
            "learning": "📚",
            "memory": "🧠",
            "generation": "✏️",
            "verification": "✅",
            "profile": "👤",
        }

        prev_phase = safe_start
        prev_domain = intent.domain
        branches_from: dict[str, list[str]] = {}

        for proj in projections:
            is_branch = proj.intent_type.startswith("[branch]")

            if is_branch:
                # 分支节点：记录但不推进
                branch_name = proj.intent_type.replace("[branch] ", "").replace(" ", "_")
                if prev_phase not in branches_from:
                    branches_from[prev_phase] = []
                branches_from[prev_phase].append(branch_name)
                reason = proj.proactive_hints[0][:20] if proj.proactive_hints else "备选"
                emoji = domain_colors.get(proj.domain, "")
                lines.append(f"    {prev_phase} --> {branch_name} : {emoji} {reason}")
                # 添加 note
                lines.append(f"    note right of {branch_name} : [备选路径]")
            else:
                safe_name = proj.intent_type.replace(" ", "_")
                reason = proj.proactive_hints[0][:25] if proj.proactive_hints else ""
                emoji = domain_colors.get(proj.domain, "")

                # 跨域标记
                cross = "🔀 " if proj.domain != prev_domain else ""

                lines.append(f"    {prev_phase} --> {safe_name} : {cross}{emoji} {reason}")

                # 高风险标注
                if proj.risk_level == "high":
                    lines.append(f"    note right of {safe_name} : ⚠️ HIGH RISK")

                prev_phase = safe_name
                prev_domain = proj.domain

        # 终止节点
        lines.append(f"    {prev_phase} --> [*]")

        return "\n".join(lines)

    # ════════════════════════════════════════════════════════════════
    #  V3: 推演链权重自适应 (Weight Adaptation)
    # ════════════════════════════════════════════════════════════════

    def adapt_weights(self) -> dict[str, list[str]]:
        """
        基于历史学习结果，自适应调整 PHASE_TRANSITIONS 中的边排序。

        原理：统计历史中实际发生的 A→B 转换频率，
        频率高的边排到对应 intent_type 候选列表的前面，
        使得未来推演时优先走"常走的路"。

        Returns:
            {
                "adapted": ["risk_assessment: stress_testing↑", ...],
                "unchanged": ["code_fix: no history data"]
            }
        """
        history_data = self.learn_from_history()
        observed_raw = history_data.get("observed_transitions", {})
        observed: dict[str, int] = cast(dict[str, int], observed_raw)

        if not observed:
            return {"adapted": [], "unchanged": list(self.PHASE_TRANSITIONS.keys())}

        adapted: list[str] = []
        unchanged: list[str] = []

        for intent_type, candidates in self.PHASE_TRANSITIONS.items():
            # 收集该 intent_type 的所有历史转换频率
            freq: dict[str, int] = {}
            for key, count in observed.items():
                if key.startswith(f"{intent_type} → "):
                    target = key.split(" → ", 1)[1]
                    freq[target] = count

            if not freq:
                unchanged.append(intent_type)
                continue

            # 按频率重排候选列表
            original_order = [str(c.get("phase", "")) for c in candidates]

            def sort_key(candidate: PhaseTransition) -> int:
                phase = str(candidate.get("phase", ""))
                return -freq.get(phase, 0)  # 频率高的排前面

            sorted_candidates: list[PhaseTransition] = sorted(candidates, key=sort_key)

            new_order = [str(c.get("phase", "")) for c in sorted_candidates]
            if new_order != original_order:
                self.PHASE_TRANSITIONS[intent_type] = sorted_candidates
                adapted.append(f"{intent_type}: {'→'.join(new_order)}")
            else:
                unchanged.append(intent_type)

        return {"adapted": adapted, "unchanged": unchanged}

    # ════════════════════════════════════════════════════════════════
    #  V3: 多路径并行评分 (Multi-Path Scoring)
    # ════════════════════════════════════════════════════════════════

    def score_all_paths(
        self,
        intent: IntentResult,
        max_depth: int = 5,
        max_paths: int = 8,
    ) -> list[dict[str, object]]:
        """
        探索所有可能的推演路径并评分，推荐最优路径。

        对每条完整路径计算综合评分：
          - total_risk_score: 风险累积分 (high=3, medium=2, low=1)
          - domain_diversity: 涉及多少个不同领域 (越多越复杂)
          - cross_domain_count: 跨域次数
          - avg_confidence: 平均置信度
          - path_score: 综合评分 (越高越推荐)

        Returns:
            按 path_score 降序排列的路径列表
        """
        all_paths: list[list[IntentResult]] = []
        self._explore_paths(intent, max_depth, set(), [], all_paths, max_paths)

        scored: list[dict[str, object]] = []
        risk_map = {"high": 3, "medium": 2, "low": 1}

        for path in all_paths:
            if not path:
                continue

            total_risk = sum(risk_map.get(p.risk_level, 1) for p in path)
            domains = set(p.domain for p in path)
            cross_domain = sum(
                1 for i in range(len(path) - 1)
                if path[i].domain != path[i + 1].domain
            )
            avg_conf = sum(p.confidence for p in path) / len(path)

            # 综合评分公式:
            # 高置信度 → +分
            # 低风险 → +分
            # 适度跨域 → +分（但太多跨域反而罚分）
            path_score = (
                avg_conf * 40                           # 置信度权重
                + (1 - total_risk / (len(path) * 3)) * 30  # 风险倒数权重
                + min(cross_domain, 3) * 10             # 跨域奖励（最多3次）
                - max(0, cross_domain - 3) * 5          # 过多跨域惩罚
            )

            scored.append({
                "path": [p.intent_type for p in path],
                "domains": sorted(domains),
                "total_risk_score": total_risk,
                "cross_domain_count": cross_domain,
                "avg_confidence": round(avg_conf, 3),
                "path_score": round(path_score, 1),
                "length": len(path),
                "risk_trajectory": " → ".join(p.risk_level for p in path),
                "domain_trajectory": " → ".join(p.domain for p in path),
            })

        # 按综合评分降序排列
        scored.sort(key=lambda x: float(str(x.get("path_score", 0))), reverse=True)
        return scored

    def _explore_paths(
        self,
        current: IntentResult,
        depth: int,
        visited: set[str],
        current_path: list[IntentResult],
        all_paths: list[list[IntentResult]],
        max_paths: int,
    ) -> None:
        """DFS 探索所有可能的路径（带剪枝）。"""
        if len(all_paths) >= max_paths:
            return
        if depth <= 0 or current.intent_type in visited:
            if current_path:
                all_paths.append(list(current_path))
            return

        visited_copy = visited | {current.intent_type}
        next_phases = self.PHASE_TRANSITIONS.get(current.intent_type, [])

        if not next_phases:
            if current_path:
                all_paths.append(list(current_path))
            return

        for candidate in next_phases:
            if len(all_paths) >= max_paths:
                return

            phase_name = str(candidate.get("phase", ""))
            if phase_name in visited_copy:
                continue

            projected = IntentResult(
                intent_type=phase_name,
                confidence=current.confidence * 0.85,
                domain=str(candidate.get("domain", current.domain)),
                complexity="simple",
                suggested_agents=list(candidate.get("agents", [])),
                proactive_hints=[str(candidate.get("reason", ""))],
                risk_level=str(candidate.get("risk", "low")),
            )

            current_path.append(projected)
            self._explore_paths(projected, depth - 1, visited_copy, current_path, all_paths, max_paths)
            current_path.pop()

    # ════════════════════════════════════════════════════════════════
    #  V3: 条件感知的推演入口 (升级 project_forward)
    # ════════════════════════════════════════════════════════════════

    def project_forward_v3(
        self,
        current_intent: IntentResult,
        depth: int = 5,
        visited: set[str] | None = None,
        include_branches: bool = False,
    ) -> list[IntentResult]:
        """
        V3 增强版递归推演 — 在 V2 基础上增加条件分支评估。

        与 project_forward 的区别：
          - 调用 _evaluate_conditions() 动态重排候选列表
          - 支持 CONDITION_RULES 中的 if/else 逻辑
          - 可根据 visited 集合和 risk_level 做运行时决策
        """
        if depth <= 0:
            return []

        if visited is None:
            visited = set()

        if current_intent.intent_type in visited:
            return []
        visited.add(current_intent.intent_type)

        next_phases = self.PHASE_TRANSITIONS.get(current_intent.intent_type, [])

        if not next_phases:
            return self._dynamic_project(current_intent, depth)

        # V3: 条件评估 — 动态重排候选
        next_phases_reordered = self._evaluate_conditions(
            current_intent.intent_type,
            next_phases,
            visited,
            current_intent.risk_level,
        )

        projections: list[IntentResult] = []

        primary = None
        for candidate in next_phases_reordered:
            cname = str(candidate.get("phase", ""))
            if cname not in visited:
                primary = candidate
                break
        if primary is None:
            return []

        phase_name = str(primary.get("phase", ""))
        phase_domain = str(primary.get("domain", current_intent.domain))

        projected = IntentResult(
            intent_type=phase_name,
            confidence=current_intent.confidence * 0.85,
            domain=phase_domain,
            complexity="simple",
            suggested_agents=list(primary.get("agents", [])),
            proactive_hints=[str(primary.get("reason", ""))],
            risk_level=str(primary.get("risk", "low")),
        )
        projections.append(projected)

        if include_branches:
            for alt in next_phases_reordered[1:]:
                alt_name = str(alt.get("phase", ""))
                if alt_name not in visited and alt_name != phase_name:
                    alt_domain = str(alt.get("domain", current_intent.domain))
                    branch = IntentResult(
                        intent_type=f"[branch] {alt_name}",
                        confidence=current_intent.confidence * 0.6,
                        domain=alt_domain,
                        complexity="simple",
                        suggested_agents=list(alt.get("agents", [])),
                        proactive_hints=[f"备选: {alt.get('reason', '')}"],
                        risk_level=str(alt.get("risk", "low")),
                    )
                    projections.append(branch)

        deeper = self.project_forward_v3(projected, depth - 1, visited.copy(), include_branches)
        projections.extend(deeper)

        return projections

    # ════════════════════════════════════════════════════════════════
    #  V4: 时间感知推演 (Temporal-Aware Projection)
    # ════════════════════════════════════════════════════════════════

    # 每个阶段类型的预估耗时（分钟）
    PHASE_DURATION: dict[str, int] = {
        # Banking
        "audit_loan": 120, "financial_analysis": 90, "risk_assessment": 60,
        "stress_testing": 45, "approval_decision": 30, "post_loan_monitoring": 15,
        "industry_analysis": 60, "concentration_alert": 20,
        # Engineering
        "code_fix": 60, "testing": 30, "code_review": 45,
        "deployment": 20, "monitoring": 10, "rollback_plan": 15,
        "alert_triage": 15,
        # Learning
        "study_plan": 30, "content_review": 60, "knowledge_test": 20,
        "weak_point_analysis": 25,
        # Memory
        "knowledge_store": 5, "knowledge_index": 3, "knowledge_link": 5,
        "experience_archive": 5,
        # Generation
        "report_generation": 30, "draft_creation": 20, "template_design": 15,
        # Verification
        "consistency_check": 15, "content_review_gen": 20, "conflict_resolution": 30,
        # Scheduling
        "schedule_create": 5, "reminder_setup": 3, "conflict_check_sched": 5,
        "task_query": 2, "priority_sort": 3, "overdue_alert": 5,
        # Profile
        "profile_update": 5, "preference_analysis": 15,
    }

    # 可并行执行的阶段对（同时执行不冲突）
    PARALLELIZABLE: list[tuple[str, str]] = [
        ("financial_analysis", "industry_analysis"),
        ("testing", "code_review"),
        ("knowledge_store", "schedule_create"),
        ("report_generation", "knowledge_store"),
        ("reminder_setup", "conflict_check_sched"),
        ("experience_archive", "profile_update"),
        ("stress_testing", "industry_analysis"),
        ("knowledge_index", "profile_update"),
    ]

    def build_temporal_roadmap(self, intent: IntentResult, depth: int = 5) -> dict[str, object]:
        """
        时间感知路线图 — 在 V2 路线图基础上增加：
          - 每阶段预估耗时
          - 总预估耗时 (串行) vs 优化耗时 (并行)
          - 关键路径标识
          - 可并行的阶段对
        """
        roadmap = self.build_full_roadmap(intent, depth=depth, include_branches=False)
        phases_raw = roadmap.get("projected_phases", [])
        phases = phases_raw if isinstance(phases_raw, list) else []

        total_serial = self.PHASE_DURATION.get(intent.intent_type, 30)
        parallel_savings = 0
        parallel_pairs: list[tuple[str, str]] = []
        timeline: list[dict[str, object]] = []
        cumulative = 0

        phase_names = [str(p.get("phase", "")) for p in phases if isinstance(p, dict)]  # type: ignore[union-attr]

        for i, p in enumerate(phases):
            if not isinstance(p, dict):
                continue
            name = str(p.get("phase", ""))
            dur = self.PHASE_DURATION.get(name, 15)
            total_serial += dur

            entry: dict[str, object] = {
                "phase": name,
                "duration_min": dur,
                "starts_at": cumulative,
                "ends_at": cumulative + dur,
            }

            # 检查是否可与前一阶段并行
            if i > 0:
                prev_name = phase_names[i - 1] if i - 1 < len(phase_names) else ""
                for pair in self.PARALLELIZABLE:
                    if (name in pair and prev_name in pair) or (prev_name in pair and name in pair):
                        entry["parallel_with"] = prev_name
                        parallel_savings += min(dur, self.PHASE_DURATION.get(prev_name, 15))
                        parallel_pairs.append((prev_name, name))
                        break

            timeline.append(entry)
            if "parallel_with" not in entry:
                cumulative += dur

        optimized = total_serial - parallel_savings
        savings_pct = round(parallel_savings / max(total_serial, 1) * 100) if total_serial > 0 else 0

        roadmap["temporal"] = {
            "serial_duration_min": total_serial,
            "optimized_duration_min": optimized,
            "parallel_savings_min": parallel_savings,
            "savings_percent": f"{savings_pct}%",
            "parallel_pairs": parallel_pairs,
            "timeline": timeline,
            "critical_path": [t["phase"] for t in timeline if "parallel_with" not in t],
        }

        return roadmap

    # ════════════════════════════════════════════════════════════════
    #  V4: 反向目标拆解 (Backward Goal Decomposition)
    # ════════════════════════════════════════════════════════════════

    def decompose_from_goal(
        self,
        goal_phase: str,
        max_depth: int = 6,
    ) -> dict[str, object]:
        """
        反向拆解 — 给定目标阶段，逆向推导到达该目标的最短路径。

        构建反向图 (B→A if A→B in PHASE_TRANSITIONS)，
        然后从 goal 出发 BFS 找到所有可能的起点路径。

        Example:
            goal = "approval_decision"
            → 最短路径: audit_loan → financial_analysis → risk_assessment → approval_decision
        """
        # 构建反向图
        reverse_graph: dict[str, list[dict[str, str | list[str]]]] = {}
        for source, targets in self.PHASE_TRANSITIONS.items():
            for target in targets:
                target_phase = str(target.get("phase", ""))
                if target_phase not in reverse_graph:
                    reverse_graph[target_phase] = []
                reverse_graph[target_phase].append({
                    "phase": source,
                    "reason": f"← 反向: {target.get('reason', '')}",
                    "agents": target.get("agents", []),
                    "risk": target.get("risk", "low"),
                    "domain": target.get("domain", "general"),
                })

        # BFS 从 goal 反向搜索
        from collections import deque
        queue: deque[list[str]] = deque([[goal_phase]])
        visited: set[str] = {goal_phase}
        all_paths: list[list[str]] = []

        while queue and len(all_paths) < 5:
            path = queue.popleft()
            if len(path) > max_depth:
                continue

            current = path[-1]
            predecessors = reverse_graph.get(current, [])

            if not predecessors:
                # 到达源头（无前驱 = 可能的起点）
                all_paths.append(list(reversed(path)))
                continue

            for pred in predecessors:
                pred_phase = str(pred.get("phase", ""))
                if pred_phase not in visited:
                    visited.add(pred_phase)
                    queue.append(path + [pred_phase])

        # 按路径长度排序（最短优先）
        all_paths.sort(key=len)

        # 构建详细的最短路径
        best_path = all_paths[0] if all_paths else [goal_phase]
        detailed_steps: list[dict[str, str]] = []
        for i, phase in enumerate(best_path):
            dur = self.PHASE_DURATION.get(phase, 15)
            detailed_steps.append({
                "step": str(i + 1),
                "phase": phase,
                "duration_min": str(dur),
            })

        total_time = sum(self.PHASE_DURATION.get(p, 15) for p in best_path)

        return {
            "goal": goal_phase,
            "shortest_path": best_path,
            "shortest_length": len(best_path),
            "total_duration_min": total_time,
            "detailed_steps": detailed_steps,
            "alternative_paths": all_paths[1:4],  # 最多3条备选
            "all_possible_starts": list(set(p[0] for p in all_paths)) if all_paths else [],
        }

    # ════════════════════════════════════════════════════════════════
    #  V4: 对抗风险分析 (Adversarial Risk Analysis)
    # ════════════════════════════════════════════════════════════════

    # 阶段失败场景库
    FAILURE_SCENARIOS: dict[str, dict[str, str]] = {
        "financial_analysis": {
            "failure": "财务数据造假/粉饰报表",
            "impact": "审计结论失真 → 错误审批 → 坏账风险",
            "mitigation": "交叉验证税审报告、银行流水、上下游对账",
        },
        "risk_assessment": {
            "failure": "风险模型参数偏差/极端场景遗漏",
            "impact": "低估实际风险 → 资本计提不足",
            "mitigation": "引入多模型交叉验证，增加尾部风险场景",
        },
        "stress_testing": {
            "failure": "压力场景设定不充分/数据时滞",
            "impact": "未能发现极端情况下的偿付危机",
            "mitigation": "参考历史极端事件，增加黑天鹅场景",
        },
        "approval_decision": {
            "failure": "审批流程被绕过/越权审批",
            "impact": "合规风险 → 监管处罚",
            "mitigation": "强制双人复核 + 审批权限自动校验",
        },
        "code_fix": {
            "failure": "修复引入新 Bug / 回归问题",
            "impact": "生产环境出错 → 服务中断",
            "mitigation": "强制 CI 全量回归测试 + 灰度发布",
        },
        "deployment": {
            "failure": "部署配置错误 / 环境不一致",
            "impact": "服务不可用 → 用户影响",
            "mitigation": "Infrastructure as Code + 自动回滚机制",
        },
        "testing": {
            "failure": "测试覆盖不足 / 用例遗漏",
            "impact": "未发现的缺陷流入生产",
            "mitigation": "代码覆盖率 ≥80% + 边界值测试 + 模糊测试",
        },
        "knowledge_store": {
            "failure": "知识冲突 / 过期信息覆盖有效信息",
            "impact": "知识库污染 → 后续决策失真",
            "mitigation": "版本化存储 + 一致性校验 + 人工审核关键知识",
        },
    }

    def analyze_risks(self, intent: IntentResult, depth: int = 5) -> dict[str, object]:
        """
        对抗风险分析 — 对推演链中每个阶段进行"魔鬼辩护"。

        为每个阶段回答三个问题：
          1. 这一步可能怎么失败？
          2. 失败的影响是什么？
          3. 如何缓解？

        同时计算整条推演链的"风险热力图"。
        """
        projections = self.project_forward(intent, depth=depth)

        risk_entries: list[dict[str, object]] = []
        total_risk_score = 0
        high_risk_phases: list[str] = []
        risk_map_vals = {"high": 3, "medium": 2, "low": 1}

        for proj in projections:
            if proj.intent_type.startswith("[branch]"):
                continue

            scenario = self.FAILURE_SCENARIOS.get(proj.intent_type, {})
            risk_val = risk_map_vals.get(proj.risk_level, 1)
            total_risk_score += risk_val

            entry: dict[str, object] = {
                "phase": proj.intent_type,
                "domain": proj.domain,
                "risk_level": proj.risk_level,
                "risk_score": risk_val,
            }

            if scenario:
                entry["failure_scenario"] = scenario.get("failure", "未定义")
                entry["impact"] = scenario.get("impact", "未评估")
                entry["mitigation"] = scenario.get("mitigation", "无")
                if proj.risk_level == "high":
                    high_risk_phases.append(proj.intent_type)
            else:
                entry["failure_scenario"] = "⚠️ 无预定义失败场景（建议补充）"
                entry["impact"] = "未评估"
                entry["mitigation"] = "建议人工评估"

            risk_entries.append(entry)

        # 风险热力图
        max_possible = len(risk_entries) * 3
        risk_ratio = total_risk_score / max(max_possible, 1)

        if risk_ratio > 0.7:
            overall = "🔴 HIGH — 需高级审批 + 全程监控"
        elif risk_ratio > 0.4:
            overall = "🟡 MEDIUM — 标准流程 + 关键节点复核"
        else:
            overall = "🟢 LOW — 常规流程即可"

        return {
            "overall_assessment": overall,
            "risk_score": total_risk_score,
            "max_score": max_possible,
            "risk_ratio": round(risk_ratio, 2),
            "high_risk_phases": high_risk_phases,
            "phase_analysis": risk_entries,
            "recommendation": (
                f"共 {len(risk_entries)} 个阶段，"
                f"{len(high_risk_phases)} 个高风险节点。"
                + (f" 重点关注: {', '.join(high_risk_phases)}" if high_risk_phases else " 无高风险瓶颈。")
            ),
        }

    # ════════════════════════════════════════════════════════════════
    #  V4: 并行机会检测 (Parallelism Opportunity Detection)
    # ════════════════════════════════════════════════════════════════

    def detect_parallelism(self, intent: IntentResult, depth: int = 5) -> dict[str, object]:
        """
        分析推演链中哪些阶段可以并行执行。

        检测逻辑：
          1. 查找 PARALLELIZABLE 表中的已注册并行对
          2. 分析依赖关系 — 如果 A 不是 B 的输入，则可并行
          3. 计算并行执行的时间节省

        Returns:
            {
                "parallel_groups": [("A", "B"), ...],
                "serial_time": 120,
                "parallel_time": 85,
                "savings": "29%",
                "execution_plan": [
                    {"parallel": ["A", "B"], "duration": 30},
                    {"serial": "C", "duration": 20},
                    ...
                ]
            }
        """
        projections = self.project_forward(intent, depth=depth)
        phases = [p for p in projections if not p.intent_type.startswith("[branch]")]

        if not phases:
            return {"parallel_groups": [], "serial_time": 0, "parallel_time": 0, "savings": "0%"}

        # 检测可并行对
        parallel_groups: list[tuple[str, str]] = []
        phase_names = [p.intent_type for p in phases]

        for i in range(len(phase_names)):
            for j in range(i + 1, min(i + 3, len(phase_names))):  # 只检查相邻3个
                a, b = phase_names[i], phase_names[j]
                for pair in self.PARALLELIZABLE:
                    if (a in pair and b in pair):
                        parallel_groups.append((a, b))

        # 构建执行计划
        execution_plan: list[dict[str, object]] = []
        parallelized: set[str] = set()

        for pair in parallel_groups:
            parallelized.update(pair)

        serial_time = 0
        parallel_time = 0

        i = 0
        while i < len(phases):
            phase = phases[i]
            dur = self.PHASE_DURATION.get(phase.intent_type, 15)

            # 检查是否和下一个阶段可并行
            found_parallel = False
            if i + 1 < len(phases):
                next_phase = phases[i + 1]
                for pair in parallel_groups:
                    if phase.intent_type in pair and next_phase.intent_type in pair:
                        next_dur = self.PHASE_DURATION.get(next_phase.intent_type, 15)
                        max_dur = max(dur, next_dur)
                        execution_plan.append({
                            "type": "parallel",
                            "phases": [phase.intent_type, next_phase.intent_type],
                            "duration": max_dur,
                            "saved": dur + next_dur - max_dur,
                        })
                        serial_time += dur + next_dur
                        parallel_time += max_dur
                        i += 2
                        found_parallel = True
                        break

            if not found_parallel:
                execution_plan.append({
                    "type": "serial",
                    "phase": phase.intent_type,
                    "duration": dur,
                })
                serial_time += dur
                parallel_time += dur
                i += 1

        savings_pct = round((serial_time - parallel_time) / max(serial_time, 1) * 100)

        return {
            "parallel_groups": parallel_groups,
            "serial_time_min": serial_time,
            "parallel_time_min": parallel_time,
            "savings": f"{savings_pct}%",
            "execution_plan": execution_plan,
            "total_phases": len(phases),
        }

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║  V5: 超高阶能力 — 从推演到自主进化                            ║
    # ╚═══════════════════════════════════════════════════════════════╝

    # ════════════════════════════════════════════════════════════════
    #  V5.1: 上下文感知推演 (Context-Aware Projection)
    # ════════════════════════════════════════════════════════════════

    async def project_with_context(
        self,
        intent: IntentResult,
        depth: int = 5,
    ) -> dict[str, object]:
        """
        上下文感知推演 — 查询 SurrealDB 记忆库注入推演链。

        流程:
          1. 从 memories 表搜索与当前意图相关的历史记忆
          2. 从 _history 提取最近的意图模式
          3. 基于记忆上下文调整推演链的置信度和路径选择
          4. 构建增强版路线图

        这使得推演链不再是"通用"的，而是"个性化"的 —
        基于用户的历史行为和积累的知识来定制推演。
        """
        # ── 1. 查询 SurrealDB 记忆 ──
        memories: list[dict[str, object]] = []
        if self._db and hasattr(self._db, "search_memories"):
            try:
                memories = await self._db.search_memories(
                    keyword=intent.intent_type,
                    top_k=5,
                )
            except Exception as e:
                logger.warning(f"V5 context query failed: {e}")

        # ── 2. 提取历史模式 ──
        recent_domains = [h.domain for h in self._history[-10:]]
        domain_freq: dict[str, int] = {}
        for d in recent_domains:
            domain_freq[d] = domain_freq.get(d, 0) + 1

        # ── 3. 上下文增强推演 ──
        projections = self.project_forward_v3(intent, depth=depth, include_branches=True)

        # 基于历史频率调整置信度
        enhanced: list[IntentResult] = []
        for proj in projections:
            boost = 1.0
            # 如果该域是用户常用域，置信度 +10%
            if proj.domain in domain_freq and domain_freq[proj.domain] >= 2:
                boost += 0.1
            # 如果记忆中有相关内容，置信度 +15%
            for mem in memories:
                _content_obj = mem.get("content", "")
                if isinstance(_content_obj, dict):
                    content = str(_content_obj.get("text", ""))
                else:
                    content = str(_content_obj)
                
                if proj.intent_type in content or intent.intent_type in content:
                    boost += 0.15
                    # 注入记忆提示
                    hint = f"💾 记忆关联: {content[:60]}"
                    if hint not in proj.proactive_hints:
                        proj.proactive_hints.append(hint)
                    break

            proj.confidence = min(proj.confidence * boost, 1.0)
            enhanced.append(proj)

        # ── 4. 构建增强路线图 ──
        roadmap = self.build_full_roadmap(intent, depth=depth, include_branches=True)
        roadmap["context_enhanced"] = True
        roadmap["memory_hits"] = len(memories)
        roadmap["domain_frequency"] = domain_freq
        roadmap["enhanced_projections"] = [
            {
                "phase": p.intent_type,
                "confidence": round(p.confidence, 3),
                "domain": p.domain,
                "hints": p.proactive_hints,
            }
            for p in enhanced[:depth]
        ]

        return roadmap

    # ════════════════════════════════════════════════════════════════
    #  V5.2: LLM 动态转换发现 (LLM-Powered Transition Discovery)
    # ════════════════════════════════════════════════════════════════

    _DISCOVERY_PROMPT = """你是一个工作流推演专家。
给定一个当前意图类型和领域，推理出接下来最可能的 3-5 个阶段。

当前意图: {intent_type}
领域: {domain}
置信度: {confidence}
上下文提示: {hints}
已有转换规则中的领域: banking, engineering, scheduling, learning, memory, generation, verification, profile

请输出 JSON 数组（不要输出其他内容），每个元素格式:
[
  {{"phase": "阶段名_英文", "reason": "为什么是下一步", "risk": "low/medium/high", "domain": "所属领域", "agents": ["相关agent"]}},
  ...
]"""

    async def discover_transitions(self, intent: IntentResult) -> list[dict[str, str | list[str]]]:
        """
        LLM 动态发现 — 当 PHASE_TRANSITIONS 中无法找到后续转换时，
        调用 LLM 推理出合理的推演链。

        与 _dynamic_project() 的区别:
          - _dynamic_project: 静态兜底，用预定义的域通用模式
          - discover_transitions: 真正调用 LLM，基于上下文动态生成

        Returns:
            新发现的转换列表 (可直接注入 PHASE_TRANSITIONS)
        """
        if not self._llm:
            logger.info("V5 discovery: No LLM available, falling back to static")
            return []

        prompt = self._DISCOVERY_PROMPT.format(
            intent_type=intent.intent_type,
            domain=intent.domain,
            confidence=intent.confidence,
            hints=" | ".join(intent.proactive_hints[:3]),
        )

        try:
            from .base_types import LLMResponse
            resp: LLMResponse = await self._llm.call(
                [{"role": "user", "content": prompt}],
                tools=None,
            )

            # 解析 JSON 数组
            json_match = re.search(r"\[[\s\S]*\]", resp.text)
            if not json_match:
                logger.warning("V5 discovery: No JSON array in LLM response")
                return []

            discovered: list[dict[str, str | list[str]]] = json.loads(json_match.group())
            logger.info(f"V5 discovery: LLM found {len(discovered)} transitions for {intent.intent_type}")
            return discovered

        except Exception as e:
            logger.warning(f"V5 discovery failed: {e}")
            return []

    # ════════════════════════════════════════════════════════════════
    #  V5.3: 转换自动固化 (Auto-Solidification)
    # ════════════════════════════════════════════════════════════════

    async def solidify_transitions(
        self,
        intent_type: str,
        transitions: list[dict[str, str | list[str]]],
        persist_to_db: bool = True,
    ) -> dict[str, object]:
        """
        将 LLM 发现的转换固化到 PHASE_TRANSITIONS 中。

        流程:
          1. 验证转换格式合法性
          2. 去重（不覆盖已有的规则）
          3. 注入到 PHASE_TRANSITIONS（运行时生效）
          4. 持久化到 SurrealDB（重启后生效）
          5. 记录到 _solidified_transitions（审计追踪）

        Returns:
            {
                "solidified": 3,
                "skipped": 1,
                "persisted": True,
                "intent_type": "..."
            }
        """
        solidified = 0
        persisted = False
        skipped = 0

        existing = self.PHASE_TRANSITIONS.get(intent_type, [])
        existing_phases = {str(t.get("phase", "")) for t in existing}

        valid_transitions: list[dict[str, str | list[str]]] = []

        for t in transitions:
            phase = str(t.get("phase", ""))
            if not phase or phase in existing_phases:
                skipped += 1
                continue

            # 格式验证
            validated: dict[str, str | list[str]] = {
                "phase": phase,
                "reason": str(t.get("reason", "LLM 推演发现")),
                "risk": str(t.get("risk", "low")),
                "domain": str(t.get("domain", "general")),
                "agents": list(t.get("agents", [])),
            }
            valid_transitions.append(validated)
            solidified += 1

        if valid_transitions:
            # 注入运行时
            if intent_type not in self.PHASE_TRANSITIONS:
                self.PHASE_TRANSITIONS[intent_type] = []
            self.PHASE_TRANSITIONS[intent_type].extend(cast(list[PhaseTransition], valid_transitions))

            # 记录到审计日志
            self._solidified_transitions[intent_type] = cast(list[PhaseTransition], valid_transitions)

            # 持久化到 SurrealDB
            persisted = False
            if persist_to_db and self._db and self._db.is_connected:
                try:
                    await self._db.execute_query(
                        """CREATE intent_transitions SET
                            intent_type = $intent_type,
                            transitions = $transitions,
                            source = 'llm_discovery',
                            created_at = time::now()""",
                        {
                            "intent_type": intent_type,
                            "transitions": valid_transitions,
                        },
                    )
                    persisted = True
                    logger.info(f"V5 solidify: {solidified} transitions persisted for {intent_type}")
                except Exception as e:
                    logger.warning(f"V5 solidify persist failed: {e}")

        return {
            "intent_type": intent_type,
            "solidified": solidified,
            "skipped": skipped,
            "persisted": persisted if valid_transitions else False,
            "new_rules": [str(t.get("phase", "")) for t in valid_transitions],
        }

    async def load_solidified_from_db(self) -> int:
        """从 SurrealDB 加载已固化的转换规则（启动时调用）。"""
        if not self._db or not self._db.is_connected:
            return 0

        try:
            rows = await self._db.execute_query(
                "SELECT intent_type, transitions FROM intent_transitions"
            )
            loaded = 0
            for row in rows:
                it = str(row.get("intent_type", ""))
                transitions = row.get("transitions", [])
                if it and isinstance(transitions, list):
                    existing = self.PHASE_TRANSITIONS.get(it, [])
                    existing_phases = {str(t.get("phase", "")) for t in existing}
                    for t in transitions:
                        if str(t.get("phase", "")) not in existing_phases:
                            if it not in self.PHASE_TRANSITIONS:
                                self.PHASE_TRANSITIONS[it] = []
                            self.PHASE_TRANSITIONS[it].append(t)
                            loaded += 1
            logger.info(f"V5 solidify: Loaded {loaded} transitions from DB")
            return loaded
        except Exception as e:
            logger.warning(f"V5 solidify load failed: {e}")
            return 0

    # ════════════════════════════════════════════════════════════════
    #  V5.4: 强化反馈环路 (Reinforcement Feedback Loop)
    # ════════════════════════════════════════════════════════════════

    def record_outcome(
        self,
        phase_name: str,
        success: bool,
        duration_min: int = 0,
        notes: str = "",
    ) -> None:
        """
        记录某个推演阶段的实际执行结果。

        这是强化学习的数据来源 — 积累足够的 outcome 后，
        调用 reinforce_weights() 自动调整转换权重。
        """
        self._outcome_log.append({
            "phase": phase_name,
            "success": success,
            "duration_min": duration_min,
            "notes": notes,
            "timestamp": time.time(),
        })

    def reinforce_weights(self, min_samples: int = 3) -> dict[str, object]:
        """
        强化反馈调整 — 基于 outcome_log 的成功/失败率调整转换优先级。

        原理:
          - 统计每个 phase 的成功率
          - 成功率 > 70% 的 phase → 在其父转换中提升优先级
          - 成功率 < 30% 的 phase → 降低优先级 + 标记风险
          - 需要至少 min_samples 条记录才触发调整

        Returns:
            {
                "promoted": ["phase_a", ...],
                "demoted": ["phase_b", ...],
                "unchanged": [...],
                "sample_count": 10
            }
        """
        if len(self._outcome_log) < min_samples:
            return {
                "promoted": [],
                "demoted": [],
                "unchanged": [],
                "sample_count": len(self._outcome_log),
                "status": f"需要至少 {min_samples} 条记录，当前 {len(self._outcome_log)} 条",
            }

        # 统计每个 phase 的成功率
        phase_stats: dict[str, dict[str, int]] = {}
        for outcome in self._outcome_log:
            phase = str(outcome.get("phase", ""))
            if phase not in phase_stats:
                phase_stats[phase] = {"success": 0, "failure": 0}
            if outcome.get("success"):
                phase_stats[phase]["success"] += 1
            else:
                phase_stats[phase]["failure"] += 1

        promoted: list[str] = []
        demoted: list[str] = []
        unchanged: list[str] = []

        for phase, stats in phase_stats.items():
            total = stats["success"] + stats["failure"]
            if total < 2:
                unchanged.append(phase)
                continue

            success_rate = stats["success"] / total

            if success_rate >= 0.7:
                # 提升: 在所有包含该 phase 的转换列表中，将其移到前面
                self._promote_phase(phase)
                promoted.append(phase)
            elif success_rate <= 0.3:
                # 降级: 移到后面 + 提升风险等级
                self._demote_phase(phase)
                demoted.append(phase)
            else:
                unchanged.append(phase)

        return {
            "promoted": promoted,
            "demoted": demoted,
            "unchanged": unchanged,
            "sample_count": len(self._outcome_log),
            "phase_success_rates": {
                phase: round(s["success"] / max(s["success"] + s["failure"], 1), 2)
                for phase, s in phase_stats.items()
            },
        }

    def _promote_phase(self, phase_name: str) -> None:
        """将某个 phase 在所有转换列表中提升到第一位。"""
        for intent_type, candidates in self.PHASE_TRANSITIONS.items():
            for i, c in enumerate(candidates):
                if str(c.get("phase", "")) == phase_name and i > 0:
                    candidates.insert(0, candidates.pop(i))
                    break

    def _demote_phase(self, phase_name: str) -> None:
        """将某个 phase 在所有转换列表中降到最后，并标记为高风险。"""
        for intent_type, candidates in self.PHASE_TRANSITIONS.items():
            for i, c in enumerate(candidates):
                if str(c.get("phase", "")) == phase_name and i < len(candidates) - 1:
                    item = candidates.pop(i)
                    item["risk"] = "high"
                    item["reason"] = str(item.get("reason", "")) + " ⚠️ 强化降级"
                    candidates.append(item)
                    break

    # ════════════════════════════════════════════════════════════════
    #  V5.5: Agent 本地规则注入 (Agent Local Transition Injection)
    # ════════════════════════════════════════════════════════════════

    def register_agent_transitions(
        self,
        agent_id: str,
        transitions: dict[str, list[dict[str, str | list[str]]]],
    ) -> dict[str, str | int]:
        """
        Agent 注入自己的领域专属转换规则。

        每个 Agent 可以定义自己领域内的 phase 转换链。
        这些规则在运行时合并到中央 PHASE_TRANSITIONS 中，
        但带有 agent 来源标记，可以独立管理。

        Example:
            ie.register_agent_transitions("banking-expert", {
                "collateral_valuation": [
                    {"phase": "lien_verification", "reason": "估值后需验证抵押权", ...},
                ],
            })
        """
        merged = 0
        for intent_type, rules in transitions.items():
            # 存储到 agent 本地规则库
            key = f"{agent_id}:{intent_type}"
            self._agent_local_transitions[key] = cast(list[PhaseTransition], rules)

            # 合并到中央图
            existing = self.PHASE_TRANSITIONS.get(intent_type, [])
            existing_phases = {str(t.get("phase", "")) for t in existing}

            for rule in rules:
                phase = str(rule.get("phase", ""))
                if phase and phase not in existing_phases:
                    # 标记来源
                    rule_with_source = dict(rule)
                    rule_with_source["source"] = agent_id
                    if intent_type not in self.PHASE_TRANSITIONS:
                        self.PHASE_TRANSITIONS[intent_type] = []
                    self.PHASE_TRANSITIONS[intent_type].append(cast(PhaseTransition, cast(object, rule_with_source)))  # type: ignore[arg-type]
                    merged += 1

        return {
            "agent": agent_id,
            "rules_registered": sum(len(r) for r in transitions.values()),
            "rules_merged": merged,
        }

    def unregister_agent_transitions(self, agent_id: str) -> int:
        """移除某个 Agent 注入的所有本地规则。"""
        removed = 0
        keys_to_remove = [k for k in self._agent_local_transitions if k.startswith(f"{agent_id}:")]

        for key in keys_to_remove:
            del self._agent_local_transitions[key]

        # 从中央图移除
        for intent_type, candidates in self.PHASE_TRANSITIONS.items():
            original_len = len(candidates)
            self.PHASE_TRANSITIONS[intent_type] = [
                c for c in candidates if c.get("source") != agent_id
            ]
            removed += original_len - len(self.PHASE_TRANSITIONS[intent_type])

        return removed

    def get_merged_transitions(self, intent_type: str) -> list[dict[str, str | list[str]]]:
        """获取合并后的转换列表（中央 + 所有 Agent 本地规则 + 已固化规则）。"""
        central = self.PHASE_TRANSITIONS.get(intent_type, [])
        solidified = self._solidified_transitions.get(intent_type, [])

        # 去重合并
        seen: set[str] = set()
        merged: list[dict[str, str | list[str]]] = []
        for t in central + solidified:
            phase = str(t.get("phase", ""))
            if phase not in seen:
                seen.add(phase)
                merged.append(cast(dict[str, str | list[str]], cast(object, t)))

        return merged

    # ════════════════════════════════════════════════════════════════
    #  V5.6: DAG 编译执行 (Roadmap → TaskDAG Compilation)
    # ════════════════════════════════════════════════════════════════

    def compile_to_dag(self, intent: IntentResult, depth: int = 5) -> TaskDAG:
        """
        将推演链编译为可执行的 TaskDAG。

        流程:
          1. 生成推演链 (project_forward)
          2. 检测并行机会 (PARALLELIZABLE)
          3. 构建 TaskDAG 节点 + 依赖关系
          4. 并行阶段设为无依赖（可同时执行）

        Returns:
            TaskDAG 实例，可直接交给 CoordinatorEngine 执行
        """
        projections = self.project_forward(intent, depth=depth)
        phases = [p for p in projections if not p.intent_type.startswith("[branch]")]

        dag = TaskDAG()

        # 起始节点
        start_node = TaskNode(
            task_id="phase_0_start",
            description=f"[起点] {intent.intent_type}",
            assigned_agent=intent.suggested_agents[0] if intent.suggested_agents else "",
            priority=100,
        )
        dag.add_node(start_node)

        prev_id = "phase_0_start"

        for i, phase in enumerate(phases):
            task_id = f"phase_{i+1}_{phase.intent_type}"
            dur = self.PHASE_DURATION.get(phase.intent_type, 15)

            # 检查是否可以和前一阶段并行
            is_parallel = False
            if i > 0:
                prev_phase = phases[i - 1].intent_type
                for pair in self.PARALLELIZABLE:
                    if phase.intent_type in pair and prev_phase in pair:
                        is_parallel = True
                        break

            # 并行阶段的依赖指向更早的节点（跳过前一个）
            if is_parallel and i >= 2:
                dep_id = f"phase_{i-1}_{phases[i-2].intent_type}"
                deps = [dep_id]
            elif is_parallel:
                deps = ["phase_0_start"]
            else:
                deps = [prev_id]

            node = TaskNode(
                task_id=task_id,
                description=f"{phase.intent_type} ({phase.domain})",
                assigned_agent=phase.suggested_agents[0] if phase.suggested_agents else "",
                depends_on=deps,
                priority=100 - i * 10,
                metadata={
                    "domain": phase.domain,
                    "risk": phase.risk_level,
                    "duration_min": dur,
                    "parallel": is_parallel,
                    "hints": phase.proactive_hints,
                },
            )
            dag.add_node(node)

            if not is_parallel:
                prev_id = task_id

        return dag

    # ════════════════════════════════════════════════════════════════
    #  V5 综合入口: 全能推演 (Ultimate Projection)
    # ════════════════════════════════════════════════════════════════

    async def ultimate_project(
        self,
        intent: IntentResult,
        depth: int = 5,
    ) -> dict[str, object]:
        """
        V5 终极推演 — 一次调用，综合所有能力。

        集成:
          1. 上下文感知推演 (SurrealDB 记忆)
          2. 条件分支评估 (V3)
          3. 时间感知 (V4)
          4. 对抗风险分析 (V4)
          5. 并行机会检测 (V4)
          6. 多路径评分 (V3)
          7. Mermaid 可视化 (V3)
          8. DAG 编译 (V5)

        Returns:
            一个包含所有分析维度的超级路线图
        """
        # 基础推演 + 时间感知
        temporal = self.build_temporal_roadmap(intent, depth=depth)

        # 对抗风险分析
        risks = self.analyze_risks(intent, depth=depth)

        # 并行机会
        parallelism = self.detect_parallelism(intent, depth=depth)

        # 多路径评分
        paths = self.score_all_paths(intent, max_depth=depth, max_paths=5)

        # Mermaid 可视化
        mermaid = self.compile_mermaid(intent, depth=depth)

        # DAG 编译
        dag = self.compile_to_dag(intent, depth=depth)

        # 上下文感知（如果有 DB）
        context_data: dict[str, object] = {}
        if self._db:
            try:
                context_data = await self.project_with_context(intent, depth=depth)
            except Exception as e:
                logger.warning(f"Intent projection with context failed: {e}")

        # 强化反馈统计
        reinforcement = self.reinforce_weights(min_samples=3)

        return {
            "intent": {
                "type": intent.intent_type,
                "domain": intent.domain,
                "confidence": intent.confidence,
                "risk": intent.risk_level,
            },
            "temporal_roadmap": temporal,
            "risk_analysis": risks,
            "parallelism": parallelism,
            "best_paths": paths[:3],
            "mermaid_diagram": mermaid,
            "dag_nodes": len(dag.nodes),
            "dag_ready": True,
            "context_enhanced": bool(context_data),
            "reinforcement": reinforcement,
            "engine_version": "V5.0",
            "capabilities": [
                "cross_domain_projection",
                "conditional_branching",
                "mermaid_visualization",
                "weight_adaptation",
                "multi_path_scoring",
                "temporal_awareness",
                "backward_decomposition",
                "adversarial_risk",
                "parallel_detection",
                "context_aware_projection",
                "llm_discovery",
                "auto_solidification",
                "reinforcement_feedback",
                "agent_local_rules",
                "dag_compilation",
                "counterfactual_simulation",
                "intent_clustering",
                "narrative_explanation",
                "predictive_precompute",
                "self_diagnostic",
            ],
        }

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║  V6: 元认知层 — 引擎理解自身 + 预测用户                       ║
    # ╚═══════════════════════════════════════════════════════════════╝

    # ════════════════════════════════════════════════════════════════
    #  V6.1: 反事实模拟 (Counterfactual Simulation)
    # ════════════════════════════════════════════════════════════════

    def simulate_counterfactual(
        self,
        intent: IntentResult,
        actual_path: list[str],
        depth: int = 5,
    ) -> dict[str, object]:
        """
        反事实模拟 — "如果当初选了另一条路会怎样？"

        给定实际执行的路径，探索所有未被选择的备选路径，
        并对比每条路径的风险、耗时和成功概率。

        用途:
          - 事后复盘: 审批完毕后，对比是否有更优路径
          - 学习优化: 发现被忽略的更优解，调整未来决策

        Example:
            actual = ["audit_loan", "financial_analysis", "approval_decision"]
            ie.simulate_counterfactual(intent, actual)
            → 发现: 如果走 risk_assessment 路径，风险更低但耗时多30min
        """
        # 获取最优的前 N 条路径
        all_paths = self.score_all_paths(intent, max_depth=depth, max_paths=8)

        # 提取每条路径的阶段名列表
        def path_phases(path_data: dict[str, object]) -> list[str]:
            p = path_data.get("path", [])
            if isinstance(p, list):
                return [str(x) for x in p]
            return []

        actual_set = set(actual_path)

        # 分析备选路径
        alternatives: list[dict[str, object]] = []
        actual_risk = sum(
            self.FAILURE_SCENARIOS.get(p, {}).get("risk", "low") == "high"  # type: ignore[arg-type]
            for p in actual_path
        )
        actual_time = sum(self.PHASE_DURATION.get(p, 15) for p in actual_path)

        for path_data in all_paths:
            phases = path_phases(path_data)
            alt_set = set(phases)

            # 只比较与实际路径不同的路径
            divergence = alt_set - actual_set
            if not divergence and alt_set == actual_set:
                continue

            alt_time = sum(self.PHASE_DURATION.get(p, 15) for p in phases)
            alt_risk_count = sum(1 for p in phases if p in self.FAILURE_SCENARIOS)

            # 计算 outcome 加权分数（基于历史记录）
            alt_success_score = 0.0
            for p in phases:
                stats = [o for o in self._outcome_log if o.get("phase") == p]
                if stats:
                    successes = sum(1 for o in stats if o.get("success"))
                    alt_success_score += successes / len(stats)
                else:
                    alt_success_score += 0.5  # 无数据默认 50%

            avg_success = alt_success_score / max(len(phases), 1)

            time_diff = alt_time - actual_time
            verdict = "⚡ 更快" if time_diff < -10 else ("🐢 更慢" if time_diff > 10 else "≈ 相当")

            alternatives.append({
                "path": phases,
                "divergent_phases": list(divergence),
                "time_min": alt_time,
                "time_diff": time_diff,
                "time_verdict": verdict,
                "risk_phases": alt_risk_count,
                "avg_success_rate": round(avg_success, 2),
                "score": path_data.get("score", 0),
            })

        # 排序: 高成功率 → 短耗时 → 低风险
        alternatives.sort(
            key=lambda x: (
                -float(str(x.get("avg_success_rate", 0))),
                int(str(x.get("time_min", 999))),
                int(str(x.get("risk_phases", 999))),
            )
        )

        best_alt = alternatives[0] if alternatives else None
        
        best_alt_path = best_alt.get("path", []) if best_alt else []
        best_alt_path = best_alt_path if isinstance(best_alt_path, list) else []
        
        recommendation = "无更优备选" if not best_alt else (
            f"发现更优路径: {' → '.join(str(p) for p in best_alt_path)} "
            f"(成功率={best_alt['avg_success_rate']}, "
            f"耗时{best_alt['time_verdict']} {best_alt['time_diff']:+d}min)"
        )

        return {
            "actual_path": actual_path,
            "actual_time_min": actual_time,
            "alternatives_count": len(alternatives),
            "alternatives": alternatives[:5],
            "recommendation": recommendation,
            "should_update_weights": best_alt is not None and float(str(best_alt.get("avg_success_rate", 0))) > 0.7,
        }

    # ════════════════════════════════════════════════════════════════
    #  V6.2: 意图聚类 (Intent Clustering)
    # ════════════════════════════════════════════════════════════════

    def cluster_intents(self) -> dict[str, object]:
        """
        意图聚类 — 从历史中自动发现高层意图模式。

        分析 _history 中的意图序列，找出：
          1. 频繁出现的意图组合（共现模式）
          2. 领域偏好分布
          3. 时间段模式（如果有时间戳）
          4. 建议的"宏意图"（聚合多个原子意图为工作流）

        Returns:
            {
                "total_intents": 42,
                "domain_distribution": {"banking": 60%, ...},
                "frequent_pairs": [("audit_loan", "financial_analysis"), ...],
                "suggested_macros": [...],
            }
        """
        if len(self._history) < 3:
            return {
                "total_intents": len(self._history),
                "status": "历史数据不足 (<3)，暂无法聚类",
            }

        # 领域分布
        domain_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for h in self._history:
            domain_counts[h.domain] = domain_counts.get(h.domain, 0) + 1
            type_counts[h.intent_type] = type_counts.get(h.intent_type, 0) + 1

        total = len(self._history)
        domain_dist = {
            d: f"{round(c / total * 100)}%"
            for d, c in sorted(domain_counts.items(), key=lambda x: -x[1])
        }

        # 共现分析（连续意图对）
        pair_counts: dict[tuple[str, str], int] = {}
        for i in range(len(self._history) - 1):
            pair = (self._history[i].intent_type, self._history[i + 1].intent_type)
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

        frequent_pairs = sorted(pair_counts.items(), key=lambda x: -x[1])[:10]

        # 序列窗口分析（3连续意图）
        triple_counts: dict[tuple[str, str, str], int] = {}
        for i in range(len(self._history) - 2):
            triple = (
                self._history[i].intent_type,
                self._history[i + 1].intent_type,
                self._history[i + 2].intent_type,
            )
            triple_counts[triple] = triple_counts.get(triple, 0) + 1

        frequent_triples = sorted(triple_counts.items(), key=lambda x: -x[1])[:5]

        # 建议宏意图
        suggested_macros: list[dict[str, object]] = []
        for pair, count in frequent_pairs[:3]:
            if count >= 2:
                suggested_macros.append({
                    "name": f"macro_{pair[0]}_{pair[1]}",
                    "sequence": list(pair),
                    "frequency": count,
                    "suggestion": f"将 {pair[0]} → {pair[1]} 固化为一键工作流",
                })

        for triple, count in frequent_triples[:2]:
            if count >= 2:
                suggested_macros.append({
                    "name": f"macro_{'_'.join(triple)}",
                    "sequence": list(triple),
                    "frequency": count,
                    "suggestion": f"将 {' → '.join(triple)} 固化为复合工作流",
                })

        return {
            "total_intents": total,
            "domain_distribution": domain_dist,
            "top_intent_types": dict(sorted(type_counts.items(), key=lambda x: -x[1])[:10]),
            "frequent_pairs": [(list(p), c) for p, c in frequent_pairs],
            "frequent_triples": [(list(t), c) for t, c in frequent_triples],
            "suggested_macros": suggested_macros,
        }

    # ════════════════════════════════════════════════════════════════
    #  V6.3: 叙事解释生成 (Narrative Explanation)
    # ════════════════════════════════════════════════════════════════

    def explain_projection(self, intent: IntentResult, depth: int = 5) -> str:
        """
        叙事解释 — 为推演链生成人类可读的推理说明。

        不是简单列出阶段，而是像分析师一样解释：
          - 为什么选择这条路径
          - 每步之间的因果关系
          - 风险在哪里
          - 预期的时间投入

        Returns:
            多段落中文叙事
        """
        projections = self.project_forward(intent, depth=depth)
        risks = self.analyze_risks(intent, depth=depth)
        temporal = self.build_temporal_roadmap(intent, depth=depth)
        temp_data = temporal.get("temporal", {})

        lines: list[str] = []

        # 开头
        lines.append(f"## 推演分析报告: {intent.intent_type}")
        if intent.reasoning:
            lines.append("")
            lines.append(f"> [!NOTE]\n> **核心思考**: {intent.reasoning}")
        lines.append("")
        lines.append(
            f"基于当前意图 **{intent.intent_type}** (域={intent.domain}, "
            f"置信度={intent.confidence:.0%}, 风险={intent.risk_level})，"
            f"引擎推演出以下 {len(projections)} 步工作流："
        )
        lines.append("")

        # 每步解释
        for i, proj in enumerate(projections):
            if proj.intent_type.startswith("[branch]"):
                clean_name = proj.intent_type.replace("[branch] ", "")
                lines.append(f"  **备选 {i+1}**: {clean_name} — {proj.proactive_hints[0] if proj.proactive_hints else '备选路径'}")
                continue

            dur = self.PHASE_DURATION.get(proj.intent_type, 15)
            scenario = self.FAILURE_SCENARIOS.get(proj.intent_type, {})
            risk_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(proj.risk_level, "⚪")

            lines.append(f"### Step {i+1}: {proj.intent_type} {risk_icon}")

            # 因果关系
            transition = None
            source = intent.intent_type if i == 0 else projections[i-1].intent_type
            for t in self.PHASE_TRANSITIONS.get(source, []): 
                if str(t.get("phase", "")) == proj.intent_type:
                    transition = t
                    break

            if transition:
                lines.append(f"- **原因**: {transition.get('reason', '推演逻辑')}")
            lines.append(f"- **领域**: {proj.domain} | **预估耗时**: {dur} 分钟")

            if scenario:
                lines.append(f"- **⚠️ 风险**: {scenario.get('failure', '未知')}")
                lines.append(f"- **缓解**: {scenario.get('mitigation', '无')}")

            if proj.proactive_hints:
                lines.append(f"- **建议**: {proj.proactive_hints[0]}")

            lines.append("")

        # 总结
        serial = temp_data.get("serial_duration_min", 0) if isinstance(temp_data, dict) else 0
        optimized = temp_data.get("optimized_duration_min", 0) if isinstance(temp_data, dict) else 0
        overall = str(risks.get("overall_assessment", "未评估"))

        lines.append("---")
        lines.append("### 总结")
        lines.append(f"- **总预估耗时**: {serial} 分钟 (优化后 {optimized} 分钟)")
        lines.append(f"- **整体风险**: {overall}")
        lines.append(f"- **建议**: {risks.get('recommendation', '无')}")

        return "\n".join(lines)

    # ════════════════════════════════════════════════════════════════
    #  V6.4: 预测性预计算 (Predictive Pre-computation)
    # ════════════════════════════════════════════════════════════════

    def predict_next_intent(self, top_k: int = 3) -> list[dict[str, object]]:
        """
        预测用户的下一个意图 — 基于历史行为模式。

        使用 N-gram 模型分析 _history 中的意图序列，
        预测最可能的下一个意图类型。

        算法:
          1. Bigram: P(next | current) = count(current→next) / count(current)
          2. Trigram: P(next | prev, current) 作为修正
          3. 时间衰减: 近期行为权重更高
          4. 领域惯性: 用户倾向于停留在同一领域

        Returns:
            [
                {"intent_type": "...", "probability": 0.7, "reason": "..."},
                ...
            ]
        """
        if len(self._history) < 2:
            return [{"intent_type": "unknown", "probability": 0.0, "reason": "历史不足"}]

        current = self._history[-1]
        current_type = current.intent_type

        # Bigram 统计
        bigram_next: dict[str, int] = {}
        bigram_total = 0
        for i in range(len(self._history) - 1):
            if self._history[i].intent_type == current_type:
                next_type = self._history[i + 1].intent_type
                bigram_next[next_type] = bigram_next.get(next_type, 0) + 1
                bigram_total += 1

        # Trigram 修正（如果有足够历史）
        trigram_next: dict[str, int] = {}
        trigram_total = 0
        if len(self._history) >= 3:
            prev = self._history[-2]
            for i in range(len(self._history) - 2):
                if (self._history[i].intent_type == prev.intent_type and
                        self._history[i + 1].intent_type == current_type):
                    next_type = self._history[i + 2].intent_type
                    trigram_next[next_type] = trigram_next.get(next_type, 0) + 1
                    trigram_total += 1

        # 基于转换规则的先验
        transition_prior: dict[str, float] = {}
        for t in self.PHASE_TRANSITIONS.get(current_type, []):
            phase = str(t.get("phase", ""))
            transition_prior[phase] = 0.3  # 先验基础分

        # 合并计算概率
        candidates: dict[str, float] = {}
        all_types = set(list(bigram_next.keys()) + list(trigram_next.keys()) + list(transition_prior.keys()))

        for intent_type in all_types:
            prob = 0.0

            # Bigram 概率 (权重 0.4)
            if bigram_total > 0 and intent_type in bigram_next:
                prob += 0.4 * (bigram_next[intent_type] / bigram_total)

            # Trigram 概率 (权重 0.3)
            if trigram_total > 0 and intent_type in trigram_next:
                prob += 0.3 * (trigram_next[intent_type] / trigram_total)

            # 转换先验 (权重 0.2)
            if intent_type in transition_prior:
                prob += 0.2 * transition_prior[intent_type]

            # 领域惯性 (权重 0.1)
            if intent_type in [h.intent_type for h in self._history[-3:] if h.domain == current.domain]:
                prob += 0.1

            candidates[intent_type] = prob

        # 排序取 top_k
        sorted_candidates = sorted(candidates.items(), key=lambda x: -x[1])[:top_k]

        predictions: list[dict[str, object]] = []
        for intent_type, prob in sorted_candidates:
            reason_parts: list[str] = []
            if intent_type in bigram_next:
                reason_parts.append(f"历史序列 {bigram_next[intent_type]}/{bigram_total}")
            if intent_type in trigram_next:
                reason_parts.append(f"三元组 {trigram_next[intent_type]}/{trigram_total}")
            if intent_type in transition_prior:
                reason_parts.append("转换规则匹配")

            predictions.append({
                "intent_type": intent_type,
                "probability": round(prob, 3),
                "reason": " + ".join(reason_parts) if reason_parts else "先验推断",
            })

        return predictions

    # ════════════════════════════════════════════════════════════════
    #  V6.5: 自诊断 (Self-Diagnostic)
    # ════════════════════════════════════════════════════════════════

    def self_diagnose(self) -> dict[str, object]:
        """
        引擎自诊断 — 评估 IntentEngine 自身的健康状态。

        检查维度:
          1. 覆盖率: PHASE_TRANSITIONS 中有多少意图类型
          2. 历史深度: _history 的样本量是否充足
          3. 反馈质量: outcome_log 的成功/失败比
          4. 进化状态: 已固化的规则数量
          5. Agent 生态: 注册的 Agent 本地规则数量
          6. 推演健康度: 是否有孤立节点（无后续转换）
          7. 能力覆盖: 15→20 能力达成度
        """
        # 覆盖率
        total_types = len(self.PHASE_TRANSITIONS)
        total_transitions = sum(len(v) for v in self.PHASE_TRANSITIONS.values())

        # 孤立节点检测（有转换但目标没有后续转换的阶段）
        all_targets: set[str] = set()
        all_sources: set[str] = set(self.PHASE_TRANSITIONS.keys())
        for transitions in self.PHASE_TRANSITIONS.values():
            for t in transitions:
                all_targets.add(str(t.get("phase", "")))

        orphan_targets = all_targets - all_sources  # 有入无出
        orphan_sources = all_sources - all_targets   # 有出无入（根节点）

        # 历史深度
        history_depth = len(self._history)
        history_grade = "🟢 充足" if history_depth >= 20 else (
            "🟡 一般" if history_depth >= 5 else "🔴 不足"
        )

        # 反馈质量
        total_outcomes = len(self._outcome_log)
        success_count = sum(1 for o in self._outcome_log if o.get("success"))
        failure_count = total_outcomes - success_count
        feedback_grade = "🟢 健康" if total_outcomes >= 10 else (
            "🟡 积累中" if total_outcomes >= 3 else "🔴 无反馈"
        )

        # 进化状态
        solidified_count = sum(len(v) for v in self._solidified_transitions.values())
        agent_rules_count = len(self._agent_local_transitions)

        # 能力清单
        all_capabilities = [
            ("cross_domain", True),
            ("parallel_branch", True),
            ("urgency_scoring", True),
            ("completion_tracking", True),
            ("history_learning", True),
            ("recursive_projection", True),
            ("conditional_branching", True),
            ("mermaid_visualization", True),
            ("weight_adaptation", True),
            ("multi_path_scoring", True),
            ("temporal_awareness", True),
            ("backward_decomposition", True),
            ("adversarial_risk", True),
            ("parallel_detection", True),
            ("context_aware", self._db is not None),
            ("llm_discovery", self._llm is not None),
            ("auto_solidification", True),
            ("reinforcement_feedback", total_outcomes >= 3),
            ("agent_local_rules", agent_rules_count > 0),
            ("dag_compilation", True),
            ("counterfactual", True),
            ("intent_clustering", history_depth >= 3),
            ("narrative_explanation", True),
            ("predictive_precompute", history_depth >= 2),
            ("self_diagnostic", True),
        ]

        active = sum(1 for _, v in all_capabilities if v)
        inactive = [name for name, v in all_capabilities if not v]

        # 健康评分
        health_score = 0
        health_score += min(total_types / 15, 1.0) * 20       # 覆盖率 20分
        health_score += min(history_depth / 20, 1.0) * 20     # 历史深度 20分
        health_score += min(total_outcomes / 10, 1.0) * 20    # 反馈质量 20分
        health_score += (active / len(all_capabilities)) * 20  # 能力激活 20分
        health_score += max(1.0 - len(orphan_targets) / max(total_types, 1), 0) * 20  # 图完整度 20分

        if health_score >= 80:
            health_grade = "🟢 优秀"
        elif health_score >= 50:
            health_grade = "🟡 良好"
        else:
            health_grade = "🔴 待提升"

        suggestions: list[str] = []
        if history_depth < 5:
            suggestions.append("增加使用量以积累历史数据")
        if total_outcomes < 3:
            suggestions.append("记录执行结果 (record_outcome) 以启用强化学习")
        if self._db is None:
            suggestions.append("连接 SurrealDB 以启用上下文感知推演")
        if self._llm is None:
            suggestions.append("注入 LLM 调用器以启用动态转换发现")
        if orphan_targets:
            suggestions.append(f"为 {len(orphan_targets)} 个终端节点添加后续转换")

        return {
            "health_score": round(health_score),
            "health_grade": health_grade,
            "engine_version": "V6.0",
            "coverage": {
                "intent_types": total_types,
                "total_transitions": total_transitions,
                "orphan_targets": list(orphan_targets)[:5],
                "root_nodes": list(orphan_sources)[:5],
            },
            "history": {
                "depth": history_depth,
                "grade": history_grade,
            },
            "feedback": {
                "total_outcomes": total_outcomes,
                "success": success_count,
                "failure": failure_count,
                "grade": feedback_grade,
            },
            "evolution": {
                "solidified_rules": solidified_count,
                "agent_local_rules": agent_rules_count,
            },
            "capabilities": {
                "active": active,
                "total": len(all_capabilities),
                "inactive": inactive,
                "coverage_pct": f"{round(active / len(all_capabilities) * 100)}%",
            },
            "suggestions": suggestions,
        }

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║  V7: 元学习层 — 引擎优化自身                                  ║
    # ╚═══════════════════════════════════════════════════════════════╝

    # ════════════════════════════════════════════════════════════════
    #  V7.1: 自调参 (Self-Tuning Hyperparameters)
    # ════════════════════════════════════════════════════════════════

    # 可调超参数及其默认值
    _HYPERPARAMS: dict[str, float] = {
        "fast_confidence_threshold": 0.7,    # Fast Path 直接返回的置信度阈值
        "default_depth": 5.0,                # 默认推演深度
        "urgency_risk_weight": 0.3,          # 紧急度计算中风险权重
        "urgency_keyword_weight": 0.5,       # 紧急度计算中关键词权重
        "reinforce_promote_threshold": 0.7,  # 强化学习提升阈值
        "reinforce_demote_threshold": 0.3,   # 强化学习降级阈值
        "parallel_check_window": 3.0,        # 并行检测的相邻窗口大小
        "context_boost_domain": 0.1,         # 上下文域频率增强幅度
        "context_boost_memory": 0.15,        # 上下文记忆关联增强幅度
    }

    def self_tune(self, min_outcomes: int = 5) -> dict[str, object]:
        """
        引擎自调参 — 基于历史 outcome 数据自动优化超参数。

        原理:
          1. 分析 outcome_log 中的成功/失败模式
          2. 计算不同置信度区间的准确率
          3. 自动调整阈值: 如果低置信度命中率高 → 降低阈值以加速
          4. 计算最优推演深度: 基于实际完成的步长
          5. 调整强化阈值: 基于成功率分布

        这是真正的"引擎优化自身" — 参数不是人工调的，
        而是引擎从自己的表现中学到的。
        """
        if len(self._outcome_log) < min_outcomes:
            return {
                "status": f"样本不足: {len(self._outcome_log)}/{min_outcomes}",
                "tuned": False,
            }

        adjustments: dict[str, dict[str, float]] = {}

        # ── 1. 置信度阈值调参 ──
        # 统计不同置信度区间的成功率
        conf_buckets: dict[str, list[bool]] = {
            "0.0-0.3": [], "0.3-0.5": [], "0.5-0.7": [], "0.7-1.0": [],
        }
        for outcome in self._outcome_log:
            phase = str(outcome.get("phase", ""))
            success = bool(outcome.get("success"))
            # 查找该 phase 在历史中的平均置信度
            phase_confs = [h.confidence for h in self._history if h.intent_type == phase]
            if phase_confs:
                avg_conf = sum(phase_confs) / len(phase_confs)
                if avg_conf < 0.3:
                    conf_buckets["0.0-0.3"].append(success)
                elif avg_conf < 0.5:
                    conf_buckets["0.3-0.5"].append(success)
                elif avg_conf < 0.7:
                    conf_buckets["0.5-0.7"].append(success)
                else:
                    conf_buckets["0.7-1.0"].append(success)

        # 如果 0.5-0.7 区间成功率 > 80%, 可以降低阈值
        mid_bucket = conf_buckets["0.5-0.7"]
        if len(mid_bucket) >= 3:
            mid_success_rate = sum(mid_bucket) / len(mid_bucket)
            if mid_success_rate > 0.8:
                old_val = self._HYPERPARAMS["fast_confidence_threshold"]
                new_val = max(0.5, old_val - 0.05)
                if new_val != old_val:
                    adjustments["fast_confidence_threshold"] = {"old": old_val, "new": new_val}
                    self._HYPERPARAMS["fast_confidence_threshold"] = new_val

        # ── 2. 推演深度调参 ──
        # 基于实际完成的步长统计
        durations = [o.get("duration_min", 0) for o in self._outcome_log if o.get("duration_min")]
        if durations:
            avg_duration = sum(int(float(str(d))) for d in durations) / len(durations)
            # 平均耗时短 → 可以增加推演深度（反正执行快）
            if avg_duration < 30:
                old_depth = self._HYPERPARAMS["default_depth"]
                new_depth = min(8.0, old_depth + 1.0)
                if new_depth != old_depth:
                    adjustments["default_depth"] = {"old": old_depth, "new": new_depth}
                    self._HYPERPARAMS["default_depth"] = new_depth
            elif avg_duration > 90:
                old_depth = self._HYPERPARAMS["default_depth"]
                new_depth = max(3.0, old_depth - 1.0)
                if new_depth != old_depth:
                    adjustments["default_depth"] = {"old": old_depth, "new": new_depth}
                    self._HYPERPARAMS["default_depth"] = new_depth

        # ── 3. 强化阈值调参 ──
        # 计算成功率分布的标准差来调整阈值
        phase_rates: dict[str, float] = {}
        for outcome in self._outcome_log:
            phase = str(outcome.get("phase", ""))
            if phase not in phase_rates:
                phase_outcomes = [o for o in self._outcome_log if o.get("phase") == phase]
                if len(phase_outcomes) >= 2:
                    rate = sum(1 for o in phase_outcomes if o.get("success")) / len(phase_outcomes)
                    phase_rates[phase] = rate

        if len(phase_rates) >= 3:
            rates = list(phase_rates.values())
            mean_rate = sum(rates) / len(rates)
            # 如果整体成功率高，可以提高提升阈值（更严格）
            if mean_rate > 0.75:
                old_promote = self._HYPERPARAMS["reinforce_promote_threshold"]
                new_promote = min(0.85, old_promote + 0.05)
                if new_promote != old_promote:
                    adjustments["reinforce_promote_threshold"] = {"old": old_promote, "new": new_promote}
                    self._HYPERPARAMS["reinforce_promote_threshold"] = new_promote

        return {
            "tuned": len(adjustments) > 0,
            "adjustments": adjustments,
            "current_params": dict(self._HYPERPARAMS),
            "sample_size": len(self._outcome_log),
            "phase_success_rates": phase_rates,
        }

    # ════════════════════════════════════════════════════════════════
    #  V7.2: 因果链推理 (Causal Chain Inference)
    # ════════════════════════════════════════════════════════════════

    def infer_causal_chains(self, min_observations: int = 3) -> dict[str, object]:
        """
        因果链推理 — 超越 N-gram 相关性，识别真正的因果关系。

        与 cluster_intents (V6) 的区别:
          - cluster_intents: A 之后经常出现 B (相关性)
          - infer_causal_chains: A 导致 B 成功/失败 (因果性)

        方法:
          1. 条件概率: P(B成功 | A成功) vs P(B成功 | A失败)
          2. 提升度 (Lift): 如果 lift > 1.5，则 A→B 有强因果关系
          3. 因果链发现: 沿着高 lift 路径构建因果图
          4. 反因果分析: 找到"成功阻断器"（B 失败后 A 也会失败的场景）

        Returns:
            {
                "causal_pairs": [{"cause": "A", "effect": "B", "lift": 2.3, ...}],
                "success_chains": [...],
                "failure_chains": [...],
                "blockers": [...],
            }
        """
        if len(self._outcome_log) < min_observations:
            return {"status": f"样本不足 ({len(self._outcome_log)}/{min_observations})"}

        # 建立 phase → outcomes 映射
        phase_outcomes: dict[str, list[bool]] = {}
        for o in self._outcome_log:
            phase = str(o.get("phase", ""))
            phase_outcomes.setdefault(phase, []).append(bool(o.get("success")))

        # 基于历史序列构建前后关系
        sequence_pairs: list[tuple[str, bool, str, bool]] = []
        for i in range(len(self._outcome_log) - 1):
            a = self._outcome_log[i]
            b = self._outcome_log[i + 1]
            sequence_pairs.append((
                str(a.get("phase", "")), bool(a.get("success")),
                str(b.get("phase", "")), bool(b.get("success")),
            ))

        # 计算条件概率和 Lift
        causal_pairs: list[dict[str, object]] = []

        phases = list(phase_outcomes.keys())
        for cause in phases:
            for effect in phases:
                if cause == effect:
                    continue

                # P(effect 成功)
                effect_data = phase_outcomes.get(effect, [])
                if len(effect_data) < 2:
                    continue
                p_effect_success = sum(effect_data) / len(effect_data)

                # P(effect 成功 | cause 成功)
                after_cause_success: list[bool] = []
                after_cause_failure: list[bool] = []
                for a_phase, a_success, b_phase, b_success in sequence_pairs:
                    if a_phase == cause and b_phase == effect:
                        if a_success:
                            after_cause_success.append(b_success)
                        else:
                            after_cause_failure.append(b_success)

                if len(after_cause_success) < 2:
                    continue

                p_effect_given_cause = sum(after_cause_success) / len(after_cause_success)

                # Lift = P(B|A) / P(B)
                lift = p_effect_given_cause / max(p_effect_success, 0.01)

                # 反向: P(effect 成功 | cause 失败)
                p_effect_given_no_cause = (
                    sum(after_cause_failure) / len(after_cause_failure)
                    if after_cause_failure else p_effect_success
                )

                # 因果强度 = lift * (差异比)
                causal_strength = lift * abs(p_effect_given_cause - p_effect_given_no_cause)

                if lift > 1.0:  # 有正向因果
                    causal_pairs.append({
                        "cause": cause,
                        "effect": effect,
                        "lift": round(lift, 2),
                        "p_effect_given_cause": round(p_effect_given_cause, 2),
                        "p_effect_given_no_cause": round(p_effect_given_no_cause, 2),
                        "causal_strength": round(causal_strength, 2),
                        "observations": len(after_cause_success),
                        "interpretation": (
                            f"{cause} 成功 → {effect} 成功率 {p_effect_given_cause:.0%}"
                            f" (基准 {p_effect_success:.0%}, lift={lift:.1f}x)"
                        ),
                    })

        # 排序
        causal_pairs.sort(key=lambda x: -float(str(x.get("causal_strength", 0))))

        # 提取成功链和失败链
        success_chains = [p for p in causal_pairs if float(str(p.get("lift", 0))) >= 1.5]
        failure_blockers = [
            p for p in causal_pairs
            if float(str(p.get("p_effect_given_no_cause", 1))) < 0.3
        ]

        return {
            "causal_pairs": causal_pairs[:10],
            "strong_causal_count": len(success_chains),
            "success_chains": success_chains[:5],
            "blockers": failure_blockers[:5],
            "total_observations": len(self._outcome_log),
        }

    # ════════════════════════════════════════════════════════════════
    #  V7.5: 深度思考引擎 (Deep Thinking Engine)
    # ════════════════════════════════════════════════════════════════

    async def deep_think(self, goal: str, context: list[dict[str, object]] | None = None) -> str:
        """
        深度思考 — 在行动前进行元认知分析。
        产生一段 Chain-of-Thought 推理，指导后续的拆解与执行。
        """
        if not self._llm:
            return "Fast-Path Mode: Skipping deep cognitive reflection."

        prompt = f"""你现在是 Coda V7 深度推理内核。
在处理以下目标之前，请进行深思熟虑（Chain-of-Thought）。

目标: "{goal}"

请分析:
1. 目标的真实意图与潜在边界。
2. 达成此目标的关键挑战与技术难点。
3. 推荐的执行策略：是激进（快速并行）还是保守（分步校验）？
4. 风险预判：哪里最容易出错？

输出要求:
- 语言简练但也需要专业深度。
- 使用中文输出。
- 不要输出 JSON，直接输出思考段落。
"""
        messages: list[dict[str, object]] = [
            {"role": "system", "content": "You are the Brain, a meta-learning autonomous engine."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self._llm.call(messages, temperature=0.3)
            return response.text
        except Exception as e:
            logger.error(f"Deep Think failed: {e}")
            return "Cognitive bypass: LLM reasoning failed, proceeding with heuristic plan."

    # ════════════════════════════════════════════════════════════════
    #  V7.3: 自然语言目标拆解 (Natural Language Goal Decomposition)
    # ════════════════════════════════════════════════════════════════

    def decompose_natural_goal(self, goal: str, max_steps: int = 8) -> dict[str, object]:
        """
        自然语言目标拆解 — 给定一段自然语言描述的目标，
        引擎自主将其拆解为可执行的意图链。

        流程:
          1. 用 _fast_classify 识别目标所在的域和类型
          2. 用 decompose_from_goal 反向寻找到达路径
          3. 用 build_temporal_roadmap 计算时间
          4. 用 analyze_risks 评估风险
          5. 用 compile_to_dag 编译为 DAG
          6. 用 explain_projection 生成叙事说明

        这是 IntentEngine 的终极形态 — 一句话进来，完整执行计划出去。

        Example:
            ie.decompose_natural_goal("完成新客户的贷款审批全流程")
            → 自动生成 7 步路线图 + DAG + 风险分析 + 叙事报告
        """
        # Step 1: 识别目标
        intent = self._fast_classify(goal)
        self._history.append(intent)

        # Step 2: 获取推演链
        projections = self.project_forward(intent, depth=max_steps)
        phases = [p for p in projections if not p.intent_type.startswith("[branch]")]

        # Step 3: 时间感知
        temporal = self.build_temporal_roadmap(intent, depth=max_steps)
        temp_data = temporal.get("temporal", {})

        # Step 4: 风险分析
        risks = self.analyze_risks(intent, depth=max_steps)

        # Step 5: 并行优化
        parallelism = self.detect_parallelism(intent, depth=max_steps)

        # Step 6: DAG 编译
        dag = self.compile_to_dag(intent, depth=max_steps)
        layers = dag.topological_sort()

        # Step 7: 叙事解释
        narrative = self.explain_projection(intent, depth=max_steps)

        # Step 8: 预测下一步（在执行完后可能需要什么）
        predictions = self.predict_next_intent(top_k=3) if len(self._history) >= 2 else []

        # 构建执行计划
        execution_plan: list[dict[str, object]] = []
        for i, phase in enumerate(phases[:max_steps]):
            execution_plan.append({
                "step": i + 1,
                "phase": phase.intent_type,
                "domain": phase.domain,
                "risk": phase.risk_level,
                "duration_min": self.PHASE_DURATION.get(phase.intent_type, 15),
                "agents": phase.suggested_agents,
                "hints": phase.proactive_hints[:2],
            })

        serial_time = int(temp_data.get("serial_duration_min", 0)) if isinstance(temp_data, dict) else 0
        optimized_time = int(temp_data.get("optimized_duration_min", 0)) if isinstance(temp_data, dict) else 0

        return {
            "goal": goal,
            "intent_classification": {
                "type": intent.intent_type,
                "domain": intent.domain,
                "confidence": intent.confidence,
            },
            "execution_plan": execution_plan,
            "total_steps": len(execution_plan),
            "time": {
                "serial_min": serial_time,
                "optimized_min": optimized_time,
                "savings": str(parallelism.get("savings", "0%")),
            },
            "risk": {
                "overall": str(risks.get("overall_assessment", "未评估")),
                "high_risk_phases": risks.get("high_risk_phases", []),
                "score": f"{risks.get('risk_score', 0)}/{risks.get('max_score', 0)}",
            },
            "dag": {
                "nodes": len(dag.nodes),
                "layers": len(layers),
                "parallel_groups": parallelism.get("parallel_groups", []),
            },
            "narrative": narrative,
            "predictions": predictions,
            "engine_version": "V7.0",
        }
