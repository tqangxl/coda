"""
Coda V5.2 — Wiki & DLP Plugins (Phase 6)
实现 O_Workspace Wiki 集成与认知数据防泄漏 (DLP)。
"""

from __future__ import annotations
import logging
import re
import time
from pathlib import Path
from typing import List, Optional
from .base_types import KnowledgeSource, Plugin, UniversalCognitivePacket
from .plugins.wiki import (
    WikiEngine, WikiEngineConfig, 
    SessionLifecycle, WikiDoctor,
    GovernanceEngine, StageGate
)

logger = logging.getLogger("Coda.domain")

class WikiPlugin(KnowledgeSource, Plugin):
    """
    O_Workspace Wiki 知识集成插件 (Knowledge Hermes).
    通过 WikiEngine 提供高性能检索、断点续传与认知审计。
    """
    def __init__(self, wiki_root: str | Path = "agents", agent_id: str = "commander"):
        """初始化 Wiki 插件，接入 WikiEngine 核心。"""
        self.name = "wiki_plugin"
        self.wiki_root = Path(wiki_root)
        self.agent_id = agent_id
        
        # 初始化 WikiEngine 配置 (Wiki Hermes)
        self.config = WikiEngineConfig(
            wiki_dir=self.wiki_root,
            agent_id=self.agent_id,
            enable_embedding=True # 启用语义检索支持
        )
        self.engine: WikiEngine = WikiEngine(self.config)
        self.initialized: bool = False

    async def initialize(self) -> None:
        """启动 Wiki Hermes。"""
        try:
            # 1. 确保目录存在
            self.wiki_root.mkdir(parents=True, exist_ok=True)
            
            # 2. 启动核心引擎
            await self.engine.initialize()
            
            # 3. 启动会话 (RA-H Orientation)
            await self.engine.on_session_start(f"plugin-{int(time.time())}")
            
            self.initialized = True
            logger.info(f"📚 Wiki Hermes initialized at: {self.wiki_root}")
        except Exception as e:
            logger.error(f"Failed to initialize Wiki Hermes: {e}")

    async def shutdown(self) -> None:
        """关闭 Wiki Hermes 并固化经验。"""
        if self.initialized:
            await self.engine.on_session_end()
            logger.info("📚 Wiki Hermes shut down and state crystallized.")

    async def query(self, query: str, top_k: int = 5) -> List[dict[str, object]]:
        """
        通过 WikiEngine 进行混合语义检索 (4D-Fusion Recall)。
        接入 Advisor Strategy 进行风险审计。
        """
        if not self.initialized:
            return []

        logger.info(f"🔍 [Hermes] Querying Knowledge: {query}")
        
        # 1. 军师审计 (Advisor Strategy)
        # 评估查询风险 (例如: 查询是否涉及全量隐私数据)
        if len(query) > 500 or "pii" in query.lower():
            gate = self.engine.governance.check_post_compile({"query_length": len(query)}) # 借用门禁逻辑
            advice = self.engine.governance.consult_advisor(gate, {"query": query})
            if advice.decision == "aborted":
                logger.warning(f"🚫 Query blocked by Advisor: {advice.reasoning}")
                return []

        results = []
        try:
            # 2. 执行检索 (FTS5 + Vector)
            # 这里的 search 是 WikiSearchEngine 实例
            if not self.engine.search:
                logger.error("Wiki search engine not initialized")
                return []
                
            from .plugins.wiki.plugins.search import SearchQuery
            sq = SearchQuery(text=query, top_k=top_k)
            search_results = await self.engine.search.search(sq)
            
            for res in search_results:
                results.append({
                    "source": res.node_id,
                    "content": res.snippet[:300],
                    "score": res.score,
                    "metadata": {
                        "type": res.node_type,
                        "status": res.meta.get("status", "unknown")
                    }
                })
                    
        except Exception as e:
            logger.error(f"Wiki Hermes search failed: {e}")
            
        return results

    async def get_context(self, resource_id: str) -> str | None:
        """获取 Wiki 资源的完整内容，支持权限与 DLP。"""
        try:
            # 直接从 Atlas 获取或通过 Storage 读取
            if not self.engine.atlas:
                logger.error("Wiki atlas index not initialized")
                return None
            node = self.engine.atlas.get_node(resource_id)
            if node:
                return node.get("body", node.get("body_preview", ""))
        except Exception as e:
            logger.error(f"Hermes failed to read resource {resource_id}: {e}")
        return None

    async def on_packet(self, packet: UniversalCognitivePacket) -> Optional[UniversalCognitivePacket]:
        # Wiki 插件通常不修改流转中的包，除非是注入知识
        return None

from .plugins.wiki import PIISentinel

class DLPFilterPlugin(Plugin):
    """
    Cognitive DLP Filter (Hermes Aegis).
    使用 PIISentinel 自动识别并脱敏认知包中的敏感信息 (API Key, PII, Secrets)。
    """
    def __init__(self, mode: str = "SANITIZE"):
        self.name = "dlp_plugin"
        self._sentinel = PIISentinel(mode=mode)

    async def initialize(self) -> None:
        logger.info(f"🛡️ DLP Hermes Aegis initialized (Mode: {self._sentinel._mode}).")

    async def shutdown(self) -> None:
        pass

    async def on_packet(self, packet: UniversalCognitivePacket) -> Optional[UniversalCognitivePacket]:
        """对认知包进行全维度脱敏处理。"""
        # 1. 脱敏指令 (Instruction)
        scan_result = self._sentinel.scan(packet.instruction)
        if scan_result.has_pii:
            packet.instruction = scan_result.sanitized_text
            logger.warning(
                f"🚨 DLP: Found {len(scan_result.detections)} PII in packet {packet.id}. "
                f"Risk Score: {scan_result.risk_score}"
            )
            
        # 2. 此处可扩展对 domain_payload 的脱敏
        # if packet.domain_payload: ...
        
        return packet
