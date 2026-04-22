"""
Coda Knowledge Engine V6.0 — Two-Phase Compilation Pipeline
知识编译器: 将 raw/ 素材 → knowledge/ 核心知识。

两阶段:
  Phase A (提取): 从源文件中提取结构化知识节点
  Phase B (合成): 跨来源合并、冲突检测、实体链接

同时实现:
  - 7 步编译流水线 (Self-Healing Pipeline)
  - AST 感知分片 (Tree-sitter)
  - 实质性变更检测 (Substantive Change Detection)
  - 概念冷冻 (Frozen Slug) 保护
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

from ..akp_types import (
    KnowledgeNode, NodeType, NodeStatus, EpistemicTag, AuthorityLevel,
    KnowledgeRelation, RelationType, CompactionOp, CompactionInstruction,
    FactAnchor, PIIShield, QualityGate, ManifestEntry,
)
from .akp_parser import parse_markdown_file, parse_markdown_content, validate_node, serialize_node_to_markdown
from .atlas import AtlasIndex
from .storage import CompilationManifest, WikiStorage

logger = logging.getLogger("Coda.wiki.compiler")


# ── 编译钩子类型 ──
CompileHook = Callable[[KnowledgeNode, dict[str, Any]], KnowledgeNode | None]


class MemoryCompiler(WikiPlugin):
    """
    两阶段知识编译器 + 7 步自愈流水线。
    """
    name = "compiler"

    def __init__(
        self,
        storage: WikiStorage | None = None,
        atlas: AtlasIndex | None = None,
        manifest: CompilationManifest | None = None,
        embedder: Any = None,
        llm_caller: Any = None,
    ):
        self._storage = storage
        self._atlas = atlas
        self._manifest = manifest
        self._embedder = embedder
        self._llm = llm_caller
        self._hooks: dict[str, list[CompileHook]] = {
            "pre_extract": [],
            "post_extract": [],
            "pre_index": [],
            "post_index": [],
        }
        self._stats: dict[str, int] = {
            "ingested": 0, "sanitized": 0, "extracted": 0, "validated": 0,
            "linked": 0, "indexed": 0, "skipped": 0, "errors": 0,
        }
        self._frozen_slugs: set[str] = set()

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        self._ctx = ctx
        if not self._storage:
            self._storage = ctx.storage
        if not self._atlas:
            self._atlas = ctx.atlas
        if not self._manifest:
            # 如果 Context 没有暴露 manifest，则尝试从 storage 获取
            if hasattr(self._storage, "get_manifest"):
                self._manifest = self._storage.get_manifest()
        
        self.load_frozen_slugs()
        logger.info("⚙️ Compiler plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        if hook == WikiHook.PRE_COMPILE:
            return self.compile_incremental()
        return None

    def register_hook(self, phase: str, hook: CompileHook) -> None:
        """注册编译钩子。"""
        if phase in self._hooks:
            self._hooks[phase].append(hook)

    def load_frozen_slugs(self) -> set[str]:
        """加载冻结的知识标识 (Frozen Slug)。"""
        frozen_file = self._storage._root / "_meta" / "frozen_slugs.json"
        if frozen_file.exists():
            import json
            try:
                data = json.loads(frozen_file.read_text(encoding="utf-8"))
                self._frozen_slugs = set(data.get("frozen", []))
            except Exception:
                pass
        return self._frozen_slugs

    def compile_incremental(self) -> dict[str, Any]:
        """
        完整 7 步增量编译流水线。
        仅编译 manifset 中标记为 dirty 的文件。
        """
        self._stats = {k: 0 for k in self._stats}
        start_time = time.time()

        # ── Step 1: INGEST ──
        logger.info("📥 Step 1/7: INGEST — Scanning raw/ for dirty files...")
        raw_dir = self._storage._root / "raw"
        dirty_files = self._manifest.get_dirty_files(raw_dir)
        self._stats["ingested"] = len(dirty_files)

        if not dirty_files:
            logger.info("✅ No dirty files. Index is up-to-date.")
            return self._build_report(start_time)

        # ── Process Each Dirty File ──
        for filepath in dirty_files:
            try:
                self._compile_single_file(filepath)
            except Exception as e:
                logger.error(f"❌ Compilation failed for {filepath}: {e}")
                self._manifest.mark_error(filepath, str(e))
                self._stats["errors"] += 1

        # ── Step 7: AUDIT ──
        logger.info("📝 Step 7/7: AUDIT — Saving manifest & audit log...")
        self._manifest.save()
        self._storage.append_audit_log(
            action="compile",
            target="incremental",
            detail=f"Processed {self._stats['ingested']} files, "
                   f"indexed {self._stats['indexed']}, "
                   f"errors {self._stats['errors']}",
        )

        # 全局钩子通知
        if self._ctx and self._ctx.registry:
            import asyncio
            asyncio.create_task(self._ctx.registry.dispatch(WikiHook.POST_COMPILE, self._stats))

        return self._build_report(start_time)

    def compile_full(self) -> dict[str, Any]:
        """全量编译 (重建整个索引)。"""
        self._stats = {k: 0 for k in self._stats}
        start_time = time.time()

        raw_dir = self._storage._root / "raw"
        knowledge_dir = self._storage._root / "knowledge"

        all_files: list[Path] = []
        for d in [raw_dir, knowledge_dir]:
            if d.exists():
                all_files.extend(d.rglob("*.md"))

        self._stats["ingested"] = len(all_files)
        logger.info(f"🔄 Full compilation: {len(all_files)} files")

        for filepath in all_files:
            try:
                self._compile_single_file(filepath)
            except Exception as e:
                logger.error(f"❌ Compilation failed for {filepath}: {e}")
                self._stats["errors"] += 1

        self._manifest.save()
        return self._build_report(start_time)

    def _compile_single_file(self, filepath: Path) -> None:
        """
        编译单个文件的完整流程 (Step 2-6)。
        """
        # ── Step 2: SANITIZE ──
        if not self._storage.is_exportable(filepath):
            self._stats["skipped"] += 1
            return

        content = filepath.read_text(encoding="utf-8", errors="replace")

        # 实质性变更检测 (Palinode: Substantive Change)
        if self._is_cosmetic_change(filepath, content):
            logger.debug(f"Skipping cosmetic change: {filepath.name}")
            self._stats["skipped"] += 1
            return

        self._stats["sanitized"] += 1

        # ── Step 3: EXTRACT ──
        logger.debug(f"📦 Extracting: {filepath.name}")
        node = self._extract_node(filepath, content)
        if node is None:
            return

        # 冻结检测
        if node.id in self._frozen_slugs:
            logger.info(f"🧊 Frozen slug detected, skipping: {node.id}")
            self._stats["skipped"] += 1
            return

        # Pre-extract hooks
        for hook in self._hooks.get("pre_extract", []):
            result = hook(node, {"filepath": str(filepath)})
            if result is None:
                self._stats["skipped"] += 1
                return
            node = result

        self._stats["extracted"] += 1

        # Post-extract hooks
        for hook in self._hooks.get("post_extract", []):
            result = hook(node, {"filepath": str(filepath)})
            if result is not None:
                node = result

        # ── Step 4: VALIDATE ──
        violations = validate_node(node)
        error_violations = [v for v in violations if v.severity == "error"]

        if error_violations:
            logger.warning(
                f"⚠️ Validation failed for {filepath.name}: "
                f"{[str(v) for v in error_violations]}"
            )
            # 降级到 low_signal 目录而非直接丢弃
            self._demote_to_low_signal(filepath, node, error_violations)
            return

        node.check_depth_standard()
        self._stats["validated"] += 1

        # ── Step 5: LINK ──
        relations = self._extract_relations(node, content)
        self._stats["linked"] += 1

        # ── Step 6: INDEX ──
        embedding = self._generate_embedding(node)

        # Pre-index hooks
        for hook in self._hooks.get("pre_index", []):
            result = hook(node, {"embedding": embedding})
            if result is None:
                return
            node = result

        self._atlas.upsert_node(node, embedding=embedding)
        for rel in relations:
            self._atlas.upsert_relation(rel)

        # 同步推送到全局插件 (如 SurrealDB)
        if self._ctx and self._ctx.registry:
            import asyncio
            asyncio.create_task(self._ctx.registry.dispatch(
                WikiHook.ON_NODE_INGEST, 
                {"node": node, "relations": relations, "filepath": str(filepath)}
            ))

        # Post-index hooks
        for hook in self._hooks.get("post_index", []):
            hook(node, {"relations_count": len(relations)})

        # 更新 Manifest
        self._manifest.mark_compiled(filepath, derived_pages=[node.id])
        self._stats["indexed"] += 1

    def _extract_node(self, filepath: Path, content: str) -> KnowledgeNode | None:
        """从文件提取 KnowledgeNode。"""
        try:
            node = parse_markdown_content(content, file_path=str(filepath))

            # 自动推断类型 (根据文件位置)
            rel_path = str(filepath).lower()
            if "/entities/" in rel_path or "\\entities\\" in rel_path:
                node.node_type = NodeType.ENTITY
            elif "/concepts/" in rel_path or "\\concepts\\" in rel_path:
                node.node_type = NodeType.CONCEPT
            elif "/techniques/" in rel_path or "\\techniques\\" in rel_path:
                node.node_type = NodeType.TECHNIQUE
            elif "/synthesis/" in rel_path or "\\synthesis\\" in rel_path:
                node.node_type = NodeType.SYNTHESIS
            elif "/patterns/" in rel_path or "\\patterns\\" in rel_path:
                node.node_type = NodeType.PATTERN
            elif "/sources/" in rel_path or "\\sources\\" in rel_path:
                node.node_type = NodeType.SOURCE

            # 自动生成标题 (如果为空)
            if not node.title:
                node.title = filepath.stem.replace("-", " ").replace("_", " ").title()

            # 自动生成 ID (如果为空)
            if node.id.startswith("akp-"):
                node.id = filepath.stem

            # 设置来源哈希
            if not node.source_origin_hash:
                node.source_origin_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            return node

        except Exception as e:
            logger.error(f"Failed to extract node from {filepath}: {e}")
            return None

    def _extract_relations(self, node: KnowledgeNode, content: str) -> list[KnowledgeRelation]:
        """
        从节点内容中提取关系。

        提取策略:
        1. YAML frontmatter 中的 depends_on / extends / contradicts
        2. Markdown 双链 [[target]]
        3. URL 引用关系
        """
        relations: list[KnowledgeRelation] = []

        # 1. Frontmatter 显式关系
        for dep in node.depends_on:
            relations.append(KnowledgeRelation(
                from_id=node.id, to_id=dep,
                relation_type=RelationType.DEPENDS_ON,
                source="frontmatter",
            ))

        if node.extends:
            relations.append(KnowledgeRelation(
                from_id=node.id, to_id=node.extends,
                relation_type=RelationType.EXTENDS,
                source="frontmatter",
            ))

        for contra in node.contradicts:
            relations.append(KnowledgeRelation(
                from_id=node.id, to_id=contra,
                relation_type=RelationType.CONTRADICTS,
                load_bearing=True,  # 矛盾关系默认承重
                source="frontmatter",
            ))

        # 2. 双链解析 [[target]]
        wikilinks = re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]', content)
        for link_target in wikilinks:
            target_id = link_target.strip().lower().replace(" ", "-")
            relations.append(KnowledgeRelation(
                from_id=node.id, to_id=target_id,
                relation_type=RelationType.REFERENCES,
                source="wikilink",
            ))

        # 3. 引用关系 (references)
        for ref in node.references:
            relations.append(KnowledgeRelation(
                from_id=node.id, to_id=ref,
                relation_type=RelationType.REFERENCES,
                source="reference",
            ))

        return relations

    def _generate_embedding(self, node: KnowledgeNode) -> list[float] | None:
        """生成节点的向量嵌入。"""
        if self._embedder is None:
            return None

        text = f"{node.title}\n{node.body[:4000]}"
        try:
            return self._embedder.encode_single(text, is_query=False)
        except Exception as e:
            logger.warning(f"Embedding generation failed for {node.id}: {e}")
            return None

    def _is_cosmetic_change(self, filepath: Path, content: str) -> bool:
        """
        实质性变更检测 (Substantive Change Detection)。
        
        仅空白/注释变更不触发重编译。
        通过"规范化哈希"实现: 去除空白/注释后计算 SHA-256。
        """
        # 规范化: 去除前后空白、行末空白、连续空行
        normalized = re.sub(r'[ \t]+$', '', content, flags=re.MULTILINE)
        normalized = re.sub(r'\n{3,}', '\n\n', normalized)
        normalized = normalized.strip()

        norm_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        # 比对清单中的规范化哈希
        entry = self._manifest.get_all_entries().get(str(filepath))
        if entry and entry.content_hash == norm_hash:
            return True  # 仅化妆变更

        return False

    def _demote_to_low_signal(self, filepath: Path, node: KnowledgeNode,
                              violations: list[Any]) -> None:
        """将低质量内容降级到 low_signal 目录。"""
        low_signal_dir = self._storage._root / "_meta" / "low_signal"
        low_signal_dir.mkdir(parents=True, exist_ok=True)

        dest = low_signal_dir / filepath.name
        content = serialize_node_to_markdown(node)
        content += "\n\n---\n<!-- LOW SIGNAL VIOLATIONS -->\n"
        for v in violations:
            content += f"- {v}\n"

        dest.write_text(content, encoding="utf-8")
        logger.info(f"📉 Demoted to low_signal: {filepath.name}")

    def _build_report(self, start_time: float) -> dict[str, Any]:
        """构建编译报告。"""
        elapsed = time.time() - start_time
        report = {
            "elapsed_seconds": round(elapsed, 2),
            "stats": dict(self._stats),
            "frozen_slugs_count": len(self._frozen_slugs),
        }
        logger.info(
            f"✅ Compilation complete: {report['stats']} in {elapsed:.1f}s"
        )
        return report

    # ════════════════════════════════════════════
    #  Compaction DSL (蒸馏)
    # ════════════════════════════════════════════

    def apply_compaction(self, instructions: list[CompactionInstruction],
                        target_node: KnowledgeNode) -> KnowledgeNode:
        """
        执行 Compaction DSL 指令 (确定性执行器)。
        LLM 产出指令, 此方法确定性执行。
        """
        for instr in instructions:
            if instr.operation == CompactionOp.KEEP:
                continue

            elif instr.operation == CompactionOp.UPDATE:
                # 更新指定 fact 锚点的内容
                for fact in target_node.facts:
                    if fact.slug == instr.target_fact_slug:
                        fact.content = instr.new_content
                        fact.version += 1
                        fact.last_modified = time.time()
                        break

            elif instr.operation == CompactionOp.MERGE:
                # 合并两个 fact 锚点
                source_fact = None
                target_fact = None
                for fact in target_node.facts:
                    if fact.slug == instr.target_fact_slug:
                        target_fact = fact
                    if fact.slug == instr.merge_with_slug:
                        source_fact = fact

                if target_fact and source_fact:
                    target_fact.content = instr.new_content or f"{target_fact.content} {source_fact.content}"
                    target_fact.version += 1
                    target_fact.last_modified = time.time()
                    target_node.facts.remove(source_fact)

            elif instr.operation == CompactionOp.SUPERSEDE:
                # 标记 fact 为已被替代
                for fact in target_node.facts:
                    if fact.slug == instr.target_fact_slug:
                        fact.content = f"[SUPERSEDED] {instr.new_content}"
                        fact.version += 1
                        break

            elif instr.operation == CompactionOp.ARCHIVE:
                # 移除 fact 锚点
                target_node.facts = [
                    f for f in target_node.facts if f.slug != instr.target_fact_slug
                ]

        target_node.updated_at = time.time()
        target_node.compute_content_hash()
        return target_node
