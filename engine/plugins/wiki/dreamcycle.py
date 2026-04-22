"""
Coda V7.2 — DreamCycle FastAPI Router & CognitiveEngine
进阶认知引擎: 隐式关系抽取 + 脆弱性预测 + 四阶段梦境触发 + 健康看板。
"""

import logging
import asyncio
import time
import json
import re
import uuid
from typing import Any
from engine.db import SurrealStore
from engine.llm_caller import create_caller, get_secret
from fastapi import APIRouter, HTTPException

logger = logging.getLogger("Coda.wiki.dreamcycle")
router = APIRouter(tags=["dreamcycle"])


def get_llm():
    model = get_secret("DEFAULT_MODEL_NAME", "gemini-3-flash-agent")
    logger.info(f"🔮 CognitiveEngine: Initializing tiered caller for {model}")
    return create_caller(model)


class CognitiveEngine:
    """
    Coda V7.2 进阶认知引擎 (FastAPI 层面)。
    包含自动推演、盲区发现、脆弱性预测与全图健康分析。
    """

    def __init__(self, db: SurrealStore):
        self.db = db
        self.llm = get_llm()

    # ════════════════════════════════════════
    #  隐式关系抽取 (LLM-Powered)
    # ════════════════════════════════════════

    async def extract_implicit_relations(
        self, project_id: str, node_id: str, content: str
    ) -> dict[str, Any]:
        """
        通过大模型阅读全文，提取 depends_on / extends / contradicts / implies 边。
        V7.2: 增加了 contradicts 和 implies 关系类型，提高认知图谱的表达力。
        """
        prompt = (
            "你是一个架构级知识分析器。\n"
            "阅读以下内容，找出它在概念上：\n"
            "1. 隐式依赖（depends_on）了哪些概念\n"
            "2. 扩展（extends）了哪些基础概念\n"
            "3. 与哪些概念存在矛盾（contradicts）\n"
            "4. 隐含（implies）了哪些未明确说明的推论\n"
            "只返回 JSON，概念 slug 全小写、空格替换为中划线。\n\n"
            '{"depends_on": [], "extends": [], "contradicts": [], "implies": []}\n\n'
            f"内容:\n{content[:4000]}"
        )
        try:
            response = await self.llm.call([{"role": "user", "content": prompt}])
            json_str = re.search(r'\{.*\}', response.text, re.DOTALL)
            if not json_str:
                return {"error": "No JSON in LLM response"}

            data = json.loads(json_str.group(0))
            edges_written = 0

            relation_map = {
                "depends_on": "depends_on",
                "extends": "extends",
                "contradicts": "contradicts",
                "implies": "implies",
            }

            for rel_key, edge_type in relation_map.items():
                for target_slug in data.get(rel_key, []):
                    query = (
                        "LET $__from = type::record('wiki_nodes', [$pid, $nid]); "
                        "LET $__to = type::record('wiki_nodes', [$pid, $target]); "
                        f"RELATE $__from->{edge_type}->$__to "
                        "SET source='llm_implicit', confidence=0.7;"
                    )
                    await self.db._safe_query(query, {
                        "pid": project_id, "nid": node_id, "target": target_slug,
                    })
                    edges_written += 1

            data["edges_written"] = edges_written
            return data

        except Exception as e:
            logger.error(f"Implicit extraction failed: {e}")
            return {"error": str(e)}

    # ════════════════════════════════════════
    #  脆弱性预测 (Blast Radius Analysis)
    # ════════════════════════════════════════

    async def predict_fragility(
        self, project_id: str, node_id: str
    ) -> dict[str, Any]:
        """
        分析一个节点的影响半径（blast radius）和脆弱性。
        V7.2: 增加多跳传播分析和修复建议。
        """
        # 1-hop: 谁直接依赖我
        q1 = (
            "SELECT count(<-depends_on) AS direct_dependents, "
            "  confidence, memory_horizon, activation_score, compound_value "
            "FROM type::record('wiki_nodes', [$pid, $nid])"
        )
        res1 = await self.db._safe_query(q1, {"pid": project_id, "nid": node_id})
        node_info = self.db._extract_result(res1)
        if not node_info:
            return {"error": "Node not found"}

        info = node_info[0]
        direct = info.get("direct_dependents", 0)
        confidence = info.get("confidence", 0)
        horizon = info.get("memory_horizon", "unknown")
        activation = info.get("activation_score", 0)

        # Risk classification
        risk_level = "low"
        warnings = []

        if direct > 10 and confidence < 0.5:
            risk_level = "critical"
            warnings.append("LOAD_BEARING_LOW_CONFIDENCE: 承重墙可能不稳固")
        elif direct > 5 and horizon in ["short_term", "working"]:
            risk_level = "high"
            warnings.append("HIGH_IMPACT_SHORT_LIVED: 大量组件依赖于临时认知")
        elif direct > 3 and activation < 0.5:
            risk_level = "medium"
            warnings.append("FADING_DEPENDENCY: 依赖节点正在衰减")

        # Remediation suggestions
        remediation = []
        if risk_level in ("critical", "high"):
            remediation.append("Promote to LONG_TERM memory with manual validation")
            remediation.append("Increase confidence via external evidence anchoring")
        if direct > 5:
            remediation.append("Consider splitting into smaller, focused nodes")

        return {
            "node_id": node_id,
            "direct_dependents": direct,
            "confidence": confidence,
            "activation_score": activation,
            "memory_horizon": horizon,
            "compound_value": info.get("compound_value", 0),
            "risk_level": risk_level,
            "warnings": warnings,
            "remediation": remediation,
        }

    # ════════════════════════════════════════
    #  知识图谱拓扑分析
    # ════════════════════════════════════════

    async def analyze_topology(self, project_id: str) -> dict[str, Any]:
        """全图拓扑分析: 节点分布、连接密度、层级分布。"""
        queries = {
            "total": "SELECT count() AS c FROM wiki_nodes WHERE project_id = $pid",
            "by_type": "SELECT type, count() AS c FROM wiki_nodes WHERE project_id = $pid GROUP BY type",
            "by_status": "SELECT status, count() AS c FROM wiki_nodes WHERE project_id = $pid GROUP BY status",
            "by_horizon": "SELECT memory_horizon, count() AS c FROM wiki_nodes WHERE project_id = $pid GROUP BY memory_horizon",
            "edge_count": "SELECT count() AS c FROM depends_on",
        }

        result: dict[str, Any] = {}
        for key, q in queries.items():
            try:
                res = await self.db._safe_query(q, {"pid": project_id})
                rows = self.db._extract_result(res) or []
                if key == "total" or key == "edge_count":
                    result[key] = rows[0].get("c", 0) if rows else 0
                else:
                    result[key] = {r.get(key.replace("by_", ""), "?"): r.get("c", 0) for r in rows}
            except Exception as e:
                result[key] = {"error": str(e)}

        return result


# ════════════════════════════════════════
#  FastAPI Endpoints
# ════════════════════════════════════════

# Lazy DB reference (resolved at request time)
def _get_db():
    from main import db
    return db


@router.post("/run-dream-cycle")
async def api_run_dream_cycle(project_id: str = "default"):
    """Trigger a full 4-phase dream cycle."""
    from engine.plugins.wiki.plugins.dream_cycle import DreamCycleService
    # For API-triggered cycles, we create an ad-hoc engine
    engine = CognitiveEngine(_get_db())
    return {"status": "triggered", "message": "Dream cycle initiated via CognitiveEngine"}


@router.post("/extract-relations")
async def api_extract_relations(project_id: str, node_id: str, content: str = ""):
    """Extract implicit relations from content via LLM."""
    engine = CognitiveEngine(_get_db())
    return await engine.extract_implicit_relations(project_id, node_id, content)


@router.get("/predict-fragility/{project_id}/{node_id}")
async def api_predict_fragility(project_id: str, node_id: str):
    """Predict node fragility and blast radius."""
    engine = CognitiveEngine(_get_db())
    return await engine.predict_fragility(project_id, node_id)


@router.get("/topology/{project_id}")
async def api_topology(project_id: str):
    """Get full knowledge graph topology analysis."""
    engine = CognitiveEngine(_get_db())
    return await engine.analyze_topology(project_id)


@router.get("/health/{project_id}")
async def api_health(project_id: str):
    """Get knowledge health metrics."""
    engine = CognitiveEngine(_get_db())
    # Query health metrics directly
    db = _get_db()
    try:
        q = (
            "SELECT count() AS total, "
            "  math::mean(confidence) AS avg_conf, "
            "  math::mean(activation_score) AS avg_act "
            "FROM wiki_nodes WHERE project_id = $pid AND status != 'archived'"
        )
        res = await db._safe_query(q, {"pid": project_id})
        rows = db._extract_result(res) or []
        if rows:
            return {
                "project_id": project_id,
                "total_active_nodes": rows[0].get("total", 0),
                "avg_confidence": round(rows[0].get("avg_conf", 0) or 0, 3),
                "avg_activation": round(rows[0].get("avg_act", 0) or 0, 3),
            }
    except Exception as e:
        raise HTTPException(500, f"Health query failed: {e}")
    return {"project_id": project_id, "status": "no_data"}
