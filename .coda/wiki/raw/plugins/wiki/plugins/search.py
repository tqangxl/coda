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
        if not self._atlas:
            self._atlas = ctx.atlas
        # 如果注册表中有 embedder 服务，也可以从这里获取
        # self._embedder = ctx.registry.get_service("embedder")
        logger.info("🔍 Search plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        return None

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """
        执行搜索 (委托 Atlas 4D-Fusion)。
        """
        # 生成查询嵌入
        query_embedding = query.embedding
        if not query_embedding and self._embedder and query.text.strip():
            try:
                query_embedding = self._embedder.encode_single(query.text, is_query=True)
            except Exception as e:
                logger.warning(f"Embedding generation failed for query: {e}")

        # 调用 Atlas
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

    def boolean_ask(self, question: str, threshold: float = 0.6) -> BooleanAskResult:
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
        results = self.search(query)

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
