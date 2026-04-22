"""
Coda V5.2 — Identity Management & Registry (Phase 1)
负责 DID 注册、角色绑定与签名验证。
"""

from __future__ import annotations
import hmac
import hashlib
import json
import logging
import os
import yaml
from pathlib import Path
from typing import Dict, Optional, Any, cast, List, TYPE_CHECKING
from .base_types import SovereignIdentity, UniversalCognitivePacket

if TYPE_CHECKING:
    from .base_types import BaseLLM
from .db import SurrealStore

logger = logging.getLogger("Coda.identity")

class IdentityRegistry:
    """
    主权身份注册表 (V5.2).
    增加持久化支持，确保身份在集群重启后依然有效。
    """
    def __init__(self, store: Optional[SurrealStore] = None, secret_key: str = "Coda_secret_default"):
        self._identities: Dict[str, SovereignIdentity] = {}
        self._store = store
        self._secret_key = secret_key.encode('utf-8')

    async def initialize(self) -> None:
        """从数据库加载已有身份。"""
        if self._store and self._store.is_connected:
            try:
                # 假设身份存储在 agent_identity 表
                from typing import Any
                db = cast(Any, self._store._db)
                identity_data = await db.select("agent_identity")
                if identity_data:
                    for row in identity_data:
                        try:
                            identity = SovereignIdentity.from_dict(row)
                            self._identities[identity.did] = identity
                        except Exception as e:
                            logger.warning(f"Failed to parse identity row: {e}")
                logger.info(f"📋 Loaded {len(self._identities)} identities from DB.")
            except Exception as e:
                logger.error(f"Failed to load identities from DB: {e}")

    async def register(self, identity: SovereignIdentity) -> None:
        """注册并持久化一个主权身份。"""
        self._identities[identity.did] = identity
        
        if self._store and self._store.is_connected:
            try:
                from typing import Any
                db = cast(Any, self._store._db)
                data = identity.to_dict()
                # 使用 DID 作为记录 ID (转义冒号并加反引号)
                safe_did = identity.did.replace(":", "_")
                # 使用 update
                await db.update(f"agent_identity:`{safe_did}`", data)
            except Exception as e:
                logger.error(f"Failed to persist identity {identity.did}: {e}")
                
        logger.info(f"🆔 Identity registered: {identity.to_short_id()} (DID: {identity.did})")

    def get_identity(self, did: str) -> Optional[SovereignIdentity]:
        return self._identities.get(did)

    def sign_packet(self, packet: UniversalCognitivePacket, private_key: str | None = None) -> str:
        """
        为认知包生成 HMAC 签名。
        未来可扩展为真非对称加密签名。
        """
        key = (private_key or self._secret_key.decode('utf-8')).encode('utf-8')
        # 排除签名位本身进行计算，增加指令内容的哈希以防止物理篡改
        msg = f"{packet.source.did}:{packet.objective}:{packet.timestamp}:{packet.instruction}"
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).hexdigest()

    def verify_packet(self, packet: UniversalCognitivePacket) -> bool:
        """验证认知包签名的真实性。"""
        if not packet.signature:
            return False
        
        # 获取源身份
        identity = self.get_identity(packet.source.did)
        if not identity:
            # 如果是外部未知 DID，尝试使用默认密钥验证（或拒绝，根据安全策略）
            logger.warning(f"🚨 Unknown DID signature attempt: {packet.source.did}")
            # return False # 严格模式
        
        # 重新计算期望的签名
        expected_sig = self.sign_packet(packet)
        return hmac.compare_digest(packet.signature, expected_sig)
    def match_capabilities(self, required_caps: list[str]) -> list[SovereignIdentity]:
        """寻找具备指定能力的身份列表。"""
        results = []
        for ident in self._identities.values():
            if all(cap in ident.capabilities for cap in required_caps):
                results.append(ident)
        return results

    def search_specialists(self, query: str) -> list[SovereignIdentity]:
        """基于关键词或意图查询匹配最合适的专家。"""
        query_lower = query.lower()
        scored_results: list[tuple[float, SovereignIdentity]] = []
        
        for ident in self._identities.values():
            score = 0.0
            # 1. 角色名匹配
            if ident.role_id in query_lower or ident.name.lower() in query_lower:
                score += 0.5
            
            # 2. 描述上下文匹配
            if any(term in ident.description.lower() for term in query_lower.split()):
                score += 0.3
            
            # 3. 能力名称匹配
            for cap in ident.capabilities:
                if cap in query_lower:
                    score += 0.2
            
            if score > 0:
                scored_results.append((score * ident.trust_score, ident))
        
        # 按得分排序
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored_results]
        
    def list_all_identities(self) -> list[SovereignIdentity]:
        """获取所有已注册的身份列表。"""
        return list(self._identities.values())
        
    async def scan_agents(self, workspace_dir: Path, llm: Optional[BaseLLM] = None) -> int:
        """
        智能扫描 workspace_dir/agents 目录下的所有专家。
        [V5.2] 优先从 AGENTS.md 提取配置，再合并 SOUL.md。
        """
        agents_path = workspace_dir / "agents"
        manifest_path = agents_path / "AGENTS.md"
        
        # 1. 解析全局清单 (Team Manifesto)
        manifest = self._parse_agents_md(manifest_path) if manifest_path.exists() else {"agents": []}
        manifest_agents = {a.get("id"): a for a in manifest.get("agents", []) if a.get("id")}
        
        if not agents_path.exists():
            logger.warning(f"Agents directory not found: {agents_path}")
            return 0
            
        count = 0
        processed_ids = set()
        
        # 2. 遍历清单中的专家
        for agent_id, m_data in manifest_agents.items():
            processed_ids.add(agent_id)
            soul_file = agents_path / agent_id / "SOUL.md"
            
            ident = None
            if soul_file.exists():
                ident = self.parse_soul_metadata(soul_file, agent_id)
                if not ident and llm:
                    logger.info(f"✨ Inflecting soul metadata for manifest agent: {agent_id}")
                    ident = await self._inflect_soul_metadata(soul_file, agent_id, llm)
            
            if not ident:
                # 注册为 Placeholder (身份占位)
                logger.info(f"🗂️ Registering manifest placeholder for {agent_id}")
                ident = SovereignIdentity(
                    role_id=str(m_data.get("role", agent_id)),
                    instance_id=agent_id,
                    name=str(m_data.get("name", agent_id)),
                    is_active=False # 缺失 SOUL.md 时静默状态
                )
            
            # 应用清单覆盖 (Priority/AutoStart)
            ident.priority = int(m_data.get("priority", 10))
            ident.auto_start = bool(m_data.get("auto_start", True))
            if not ident.auto_start:
                 ident.is_active = False # 如果设置了不自动启动，则设为非活跃
            
            # 保持持久化状态
            existing = self.get_identity(ident.did)
            if existing: ident.is_active = existing.is_active
            
            await self.register(ident)
            count += 1

        # 3. 补充扫描 (处理不在清单中的 legacy 专家)
        for entry in agents_path.iterdir():
            if entry.is_dir() and entry.name not in processed_ids:
                soul_file = entry / "SOUL.md"
                if soul_file.exists():
                    try:
                        # 解析 SOUL.md
                        ident = self.parse_soul_metadata(soul_file, entry.name)
                        
                        # [V5.2] 如果未识别到 Frontmatter 且有 LLM, 尝试感悟修复
                        if not ident and llm:
                            logger.info(f"✨ Inflecting soul metadata for agent: {entry.name}")
                            ident = await self._inflect_soul_metadata(soul_file, entry.name, llm)
                        
                        if ident:
                            # 保持已有的激活状态 (如果是更新)
                            existing = self.get_identity(ident.did)
                            if existing:
                                ident.is_active = existing.is_active
                                
                            await self.register(ident)
                            count += 1
                    except Exception:
                        pass
        
        return count

    def _parse_agents_md(self, path: Path) -> dict[str, Any]:
        """从 AGENTS.md 提取核心 YAML 配置块。"""
        try:
            content = path.read_text(encoding="utf-8")
            # 提取第一个列表所在的 YAML 块 (通常在 团队配置 下)
            import re
            match = re.search(r"```yaml\n(team:.*?)\n```", content, re.DOTALL | re.IGNORECASE)
            if match:
                return cast(dict[str, Any], yaml.safe_load(match.group(1)))
        except Exception as e:
            logger.error(f"Failed to parse AGENTS.md: {e}")
        return {"agents": []}

    async def _inflect_soul_metadata(self, path: Path, agent_id: str, llm: BaseLLM) -> Optional[SovereignIdentity]:
        """使用 LLM 自动补全 SOUL.md 的 YAML 元数据。"""
        try:
            body_text = path.read_text(encoding="utf-8").strip()
            if not body_text:
                return None

            prompt = f"""
你是一个 Coda 专家人格分析器。请根据以下 Agent 的描述文本，提取其工业级专家属性，并以 YAML 格式输出。
你可以根据文本内容“感悟”它的角色定位。

[待分析文本]:
{body_text}

[输出要求]:
只输出 YAML 块，并用 --- 包裹。包含以下字段：
- role: (字符串, 如 coder, writer, analyst, auditor 等)
- name: (人类可读名称)
- description: (简短描述能力)
- capabilities: (字符串列表)
- tools: (该角色可能需要的核心工具列表，如 view_file, run_command 等)
- preferred_model: (留空即可，除非你有明确把握)

[示例]:
---
role: coder
name: Python Expert
description: Expert in Python refactoring and async patterns.
capabilities: [python, refactoring, async]
tools: [run_command, view_file, grep_search]
preferred_model: ""
---
"""
            res = await llm.call([{"role": "user", "content": prompt}], temperature=0.3)
            yaml_match = os.linesep.join(res.text.splitlines()) # 规范化换行
            
            # 简单提取 YAML 部分
            import re
            match = re.search(r"---(.*?)---", yaml_match, re.DOTALL)
            if match:
                meta_yaml = match.group(0)
                # 物理注入到文件顶部
                new_content = f"{meta_yaml}\n{body_text}"
                path.write_text(new_content, encoding="utf-8")
                
                # 重新解析
                return self.parse_soul_metadata(path, agent_id)
            
            return None
        except Exception as e:
            logger.error(f"Failed to inflect soul metadata for {agent_id}: {e}")
            return None

    def parse_soul_metadata(self, path: Path, agent_id: str) -> Optional[SovereignIdentity]:
        """解析 SOUL.md 的 YAML Frontmatter 元数据。"""
        try:
            content = path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    meta = yaml.safe_load(parts[1])
                    if not meta: return None
                    
                    # 构建身份
                    return SovereignIdentity(
                        role_id=str(meta.get("role", "general")),
                        instance_id=agent_id,
                        name=str(meta.get("name", agent_id)),
                        description=str(meta.get("description", "")),
                        capabilities=list(meta.get("capabilities", [])),
                        tools=list(meta.get("tools", [])),
                        preferred_model=str(meta.get("preferred_model", ""))
                    )
            return None
        except Exception as e:
            logger.error(f"Soul metadata parse error ({path}): {e}")
            return None

    async def toggle_status(self, did_or_role: str, active: bool) -> int:
        """激活或停用专家 (支持 DID 或 Role 前缀)。"""
        targets = []
        for ident in self._identities.values():
            if ident.did == did_or_role or ident.role_id == did_or_role:
                targets.append(ident)
            # 支持 role:* 通配符 (简单实现)
            elif did_or_role.endswith("*") and ident.role_id.startswith(did_or_role[:-1]):
                targets.append(ident)
        
        for ident in targets:
            ident.is_active = active
            await self.register(ident)
            
        return len(targets)

    def set_store(self, store: SurrealStore) -> None:
        """设置持久化存储引擎。"""
        self._store = store
        logger.debug("📦 Persistence store attached to IdentityRegistry.")

# 全局单例
registry = IdentityRegistry()
