"""
Coda Knowledge Engine V6.0 — Search Infrastructure
高级检索基础设施: 4D-Fusion Recall 的高级封装。

实现:
  - Boolean Ask (证据门控查询)
  - Favor Recency (时间偏重)
  - Unique-Source Priority (去重源优先)
  - 上下文感知 reranker
  - 搜索结果组装为 LLM-ready prompt
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..akp_types import KnowledgeNode, EpistemicTag
from .atlas import AtlasIndex

logger = logging.getLogger("Coda.wiki.search")


@dataclass
class SearchQuery:
    """结构化搜索查询。"""
    text: str
    embedding: list[float] | None = None
    top_k: int = 10
    favor_recency: bool = False
    boolean_ask: bool = False   # 是否是 Yes/No 断言检验
    source_diversity: bool = True  # Unique-Source Priority
    status_filter: list[str] | None = None
    node_type_filter: list[str] | None = None
    min_confidence: float = 0.0
    weights: dict[str, float] | None = None


@dataclass
class SearchResult:
    """搜索结果封装。"""
    node_id: str
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    node_type: str = ""
    confidence: float = 0.0
    epistemic_tag: str = ""
    source_hash: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class BooleanAskResult:
    """Boolean Ask 断言检验结果 (Supavector)。"""
    question: str
    answer: bool = False
    confidence: float = 0.0
    supporting_evidence: list[SearchResult] = field(default_factory=list)
    contradicting_evidence: list[SearchResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "confidence": self.confidence,
            "supporting_evidence": [vars(r) for r in self.supporting_evidence],
            "contradicting_evidence": [vars(r) for r in self.contradicting_evidence],
            "is_conclusive": self.is_conclusive
        }

    @property
    def is_conclusive(self) -> bool:
        return self.confidence > 0.7


class WikiSearchEngine(WikiPlugin):
    """
    高级搜索引擎 — 4D-Fusion Recall 的高级封装。
    """
    name = "search"

    def __init__(self, atlas: AtlasIndex | None = None, embedder: Any = None):
        self._atlas = atlas
        self._embedder = embedder

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        self._ctx = ctx
        if not self._atlas:
            self._atlas = ctx.atlas
        # 如果注册表中有 embedder 服务，也可以从这里获取
        # self._embedder = ctx.registry.get_service("embedder")
        logger.info("🔍 Search plugin initialized (Hybrid Engine Ready)")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        return None

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """
        执行五路混合搜索 (向量+BM25+时间+图+权威)。
        如果在联邦模式下(V7.0)，通过 SurrealDB 执行高级召回。
        否则回退到本地 Atlas 4D-Fusion。
        """
        # 生成查询嵌入
        query_embedding = query.embedding
        if not query_embedding and self._embedder and query.text.strip():
            try:
                # Assuming embedder.encode_single might be sync or async
                import inspect
                if inspect.iscoroutinefunction(self._embedder.encode_single):
                    query_embedding = await self._embedder.encode_single(query.text, is_query=True)
                else:
                    query_embedding = self._embedder.encode_single(query.text, is_query=True)
            except Exception as e:
                logger.warning(f"Embedding generation failed for query: {e}")

        # Check for federated SurrealDB storage
        surreal_db = None
        current_project = "default"
        if hasattr(self, "_ctx") and self._ctx and self._ctx.registry:
            surreal_plugin = self._ctx.registry.get_plugin("surreal_atlas")
            if surreal_plugin and surreal_plugin._db and surreal_plugin._db.is_connected:
                surreal_db = surreal_plugin._db
                current_project = surreal_plugin._project_id

        raw_results = []
        if surreal_db:
            logger.debug("🌐 Triggering Federated Hybrid Search (SurrealDB)")
            try:
                # [超级进阶] Query Rewriter: 语义扩展
                rewritten_text = await self._rewrite_query(query.text)
                if rewritten_text != query.text:
                    logger.debug(f"🔄 Query Rewritten: {query.text} -> {rewritten_text}")
                
                raw_results = await surreal_db.federated_search_nodes(
                    project_id=current_project,
                    keyword=rewritten_text,
                    query_embedding=query_embedding,
                    weights=query.weights,
                    limit=query.top_k * 3 # 取更多候选项供重排
                )
                
                # Transform to format identical to Atlas
                for rr in raw_results:
                    rr["search_score"] = rr.get("hybrid_score", 1.0)
                    rr["source_origin_hash"] = rr.get("source_origin_hash", "")
                    rr["snippet"] = rr.get("body", "")[:200]
                    # handle surrogate ID from Surreal ([project, id]) -> just id
                    surreal_id = str(rr.get("id", ""))
                    if "wiki_nodes:" in surreal_id:
                        import ast
                        try:
                            # Parse wiki_nodes:['project', 'id']
                            parts = ast.literal_eval(surreal_id.replace("wiki_nodes:", ""))
                            rr["id"] = parts[1] if len(parts) > 1 else surreal_id
                        except:
                            rr["id"] = surreal_id
                    else:
                        rr["id"] = surreal_id

                # [超级进阶] Dynamic Reranker: 动态重排
                if raw_results:
                    raw_results = await self._rerank_results(query.text, raw_results)
                    raw_results = raw_results[:query.top_k]

            except Exception as e:
                logger.error(f"Federated search failed: {e}. Falling back to local Atlas.")
                surreal_db = None

        # ── [Phase 3] Graph Expansion (Active Graph Walk) ──
        if surreal_db and raw_results:
            try:
                top_ids = [r["id"] for r in raw_results[:5]] # Take top 5 for walk
                graph_neighbors = await surreal_db.federated_graph_walk(
                    start_nodes=top_ids,
                    project_id=current_project,
                    max_hops=1,
                    limit=query.top_k
                )
                
                # Merge neighbors into raw_results with a decay factor
                existing_ids = {r["id"] for r in raw_results}
                for neighbor in graph_neighbors:
                    if neighbor["id"] not in existing_ids:
                        neighbor["search_score"] = 0.5 # Default score for neighbors
                        neighbor["snippet"] = neighbor.get("body", "")[:200]
                        raw_results.append(neighbor)
            except Exception as e:
                logger.warning(f"Graph expansion failed: {e}")

        if not surreal_db:
            # 降级调用本地 Atlas
            if not self._atlas:
                return []
            raw_results = self._atlas.search(
                query=query.text,
                query_embedding=query_embedding,
                top_k=query.top_k * 2,  # 请求更多用于后过滤
                weights=query.weights,
                favor_recency=query.favor_recency,
                status_filter=query.status_filter,
            )

        # 组装 SearchResult
        results: list[SearchResult] = []
        for rd in raw_results:
            result = SearchResult(
                node_id=rd.get("id", ""),
                title=rd.get("title", ""),
                snippet=rd.get("snippet", rd.get("body_preview", "")[:200]),
                score=rd.get("search_score", 0.0),
                node_type=rd.get("node_type", ""),
                confidence=rd.get("confidence", 0.0),
                epistemic_tag=rd.get("epistemic_tag", ""),
                source_hash=rd.get("source_origin_hash", ""),
                meta=rd,
            )
            results.append(result)

        # ── 后过滤 ──

        # 最低置信度
        if query.min_confidence > 0:
            results = [r for r in results if r.confidence >= query.min_confidence]

        # 节点类型过滤
        if query.node_type_filter:
            results = [r for r in results if r.node_type in query.node_type_filter]

        # Unique-Source Priority (去重)
        if query.source_diversity:
            results = self._deduplicate_by_source(results)

        return results[:query.top_k]

    async def boolean_ask(self, question: str, threshold: float = 0.6) -> BooleanAskResult:
        """
        Boolean Ask (Supavector): 对知识库进行 Yes/No 断言检验。

        工作流:
        1. 搜索与断言相关的知识
        2. 分析支持/反对的证据
        3. 基于证据权重给出结论
        """
        query = SearchQuery(
            text=question,
            boolean_ask=True,
            top_k=10,
            source_diversity=True,
        )
        results = await self.search(query)

        # 简化的证据分析 (基于关键词匹配)
        supporting: list[SearchResult] = []
        contradicting: list[SearchResult] = []

        question_lower = question.lower()
        negation_words = {"不", "没有", "无法", "cannot", "not", "no", "never", "dont"}

        for result in results:
            snippet_lower = result.snippet.lower()

            # 提取核心术语
            has_negation_in_question = any(w in question_lower for w in negation_words)
            has_negation_in_snippet = any(w in snippet_lower for w in negation_words)

            # 如果问题是否定的, 且答案也是否定的 → 支持
            # 如果问题是肯定的, 且答案是肯定的 → 支持
            if has_negation_in_question == has_negation_in_snippet:
                supporting.append(result)
            else:
                contradicting.append(result)

        # 计算置信度
        total_evidence = len(supporting) + len(contradicting)
        if total_evidence == 0:
            confidence = 0.0
            answer = False
        else:
            support_weight = sum(r.score * r.confidence for r in supporting)
            contra_weight = sum(r.score * r.confidence for r in contradicting)
            total_weight = support_weight + contra_weight

            if total_weight == 0:
                confidence = 0.0
                answer = False
            else:
                confidence = support_weight / total_weight
                answer = confidence >= threshold

        return BooleanAskResult(
            question=question,
            answer=answer,
            confidence=confidence,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
        )

    def build_llm_context(
        self,
        results: list[SearchResult],
        max_tokens: int = 4000,
        include_metadata: bool = True,
    ) -> str:
        """
        将搜索结果组装为 LLM-ready 上下文。

        格式:
        ```
        [Source: title (confidence: 0.8, type: entity)]
        snippet content...
        ---
        ```
        """
        context_parts: list[str] = []
        estimated_tokens = 0

        for result in results:
            header = f"[Source: {result.title}"
            if include_metadata:
                header += f" | conf={result.confidence:.1f}"
                header += f" | type={result.node_type}"
                if result.epistemic_tag:
                    header += f" | {result.epistemic_tag}"
            header += "]"

            snippet = result.snippet
            part = f"{header}\n{snippet}\n---"

            # 粗略估算 token (1 char ≈ 0.5 token for Chinese, 0.25 for English)
            est = len(part) // 2
            if estimated_tokens + est > max_tokens:
                break

            context_parts.append(part)
            estimated_tokens += est

        return "\n\n".join(context_parts)

    def _deduplicate_by_source(self, results: list[SearchResult]) -> list[SearchResult]:
        """
        Unique-Source Priority (Supavector):
        同一来源 (source_hash) 只保留得分最高的结果。
        """
        seen_sources: dict[str, SearchResult] = {}
        deduped: list[SearchResult] = []

        for result in results:
            if not result.source_hash:
                deduped.append(result)
                continue

            existing = seen_sources.get(result.source_hash)
            if existing is None:
                seen_sources[result.source_hash] = result
                deduped.append(result)
            elif result.score > existing.score:
                # 替换为更高分的
                deduped = [r for r in deduped if r is not existing]
                deduped.append(result)
                seen_sources[result.source_hash] = result

        return deduped

    async def _rewrite_query(self, query_text: str) -> str:
        """[超级进阶] 利用 LLM 扩展查询意图。"""
        if not self._ctx or not self._ctx.registry:
            return query_text
        
        # 尝试获取 llm 服务
        llm = self._ctx.registry.get_service("llm")
        if not llm:
            return query_text
            
        prompt = f"你是一个高级搜索助手。请将用户的原始查询扩展为包含同义词、相关概念和潜在关键词的复合搜索词组，仅输出扩展后的关键词串。原始查询：'{query_text}'"
        try:
            expanded = await llm.generate(prompt, max_tokens=32)
            # 清洗结果，保留核心关键词
            return expanded.strip() or query_text
        except:
            return query_text

    async def _rerank_results(self, query_text: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """[超级进阶] 动态重排逻辑：基于片段内容的语义对齐。"""
        if not self._embedder or not results:
            return results
            
        try:
            # 计算查询向量
            q_vec = await self._embedder.encode_single(query_text, is_query=True)
            
            # 对每个结果的片段计算余弦相似度，并与原始分数融合
            import math
            def cosine_similarity(v1, v2):
                if not v1 or not v2: return 0
                dot = sum(a*b for a, b in zip(v1, v2))
                m1 = math.sqrt(sum(a*a for a in v1))
                m2 = math.sqrt(sum(b*b for b in v2))
                return dot / (m1 * m2) if m1 * m2 > 0 else 0

            for res in results:
                snippet = res.get("snippet", "") or res.get("body", "")[:400]
                if snippet:
                    s_vec = await self._embedder.encode_single(snippet, is_query=False)
                    semantic_score = cosine_similarity(q_vec, s_vec)
                    # 融合分数: 4D 混合分 (70%) + 片段语义分 (30%)
                    res["search_score"] = res.get("search_score", 0.0) * 0.7 + semantic_score * 0.3
            
            # 按新分数排序
            results.sort(key=lambda x: x.get("search_score", 0.0), reverse=True)
            return results
        except Exception as e:
            logger.warning(f"Reranking failed: {e}")
            return results
