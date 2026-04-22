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
    MemoryHorizon
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
        embedder: Any = None,
        llm_caller: Any = None,
    ):
        self._storage = storage
        self._atlas = atlas
        self._embedder = embedder
        self._llm = llm_caller
        self._omni = None
        self._hooks: dict[str, list[CompileHook]] = {
            "pre_extract": [],
            "post_extract": [],
            "pre_index": [],
            "post_index": [],
        }
        self._stats: dict[str, int] = {
            "ingested": 0, "sanitized": 0, "extracted": 0, "validated": 0,
            "linked": 0, "indexed": 0, "skipped": 0, "deleted": 0, "errors": 0,
        }
        self._frozen_slugs: set[str] = set()

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        self._ctx = ctx
        self._storage = ctx.storage
        if not self._atlas:
            self._atlas = ctx.atlas
        
        self.load_frozen_slugs()
        
        # 预加载 OmniHarvester 支持
        if self._ctx and hasattr(self._ctx.registry, "get_plugin"):
            self._omni = self._ctx.registry.get_plugin("omni_harvester")
            
        logger.info("⚙️ Compiler plugin initialized")

    @property
    def _manifest(self) -> Any:
        """动态路由到 Context 提供的 Manifest 服务。"""
        return self._ctx.manifest

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        if hook == WikiHook.PRE_COMPILE:
            return self.compile_incremental()
        return None

    def register_hook(self, phase: str, hook: CompileHook) -> None:
        """注册编译钩子。"""
        if phase in self._hooks:
            self._hooks[phase].append(hook)

    def get_stats(self) -> dict[str, int]:
        """获取编译统计数据。"""
        return self._stats

    def load_frozen_slugs(self) -> set[str]:
        """加载冻结的知识标识 (Frozen Slug)。"""
        if not self._storage:
            return self._frozen_slugs
        frozen_file = self._storage._root / "_meta" / "frozen_slugs.json"
        if frozen_file.exists():
            import json
            try:
                data = json.loads(frozen_file.read_text(encoding="utf-8"))
                self._frozen_slugs = set(data.get("frozen", []))
            except Exception:
                pass
        return self._frozen_slugs

    async def compile_incremental(self) -> dict[str, Any]:
        """
        完整 7 步增量编译流水线。
        仅编译 manifset 中标记为 dirty 的文件。
        """
        self._stats = {k: 0 for k in self._stats}
        start_time = time.time()
        
        # ── Step 0: DIFF (Deletion sync) ──
        missing_files = self._manifest.get_missing_files()
        if missing_files:
            logger.info(f"🗑️ Step 0: DIFF — Found {len(missing_files)} deleted files. Pruning...")
            for path_str in missing_files:
                affected_nodes = self._manifest.get_affected_pages(path_str)
                # 触发物理删除钩子
                if self._ctx and self._ctx.registry:
                    for node_id in affected_nodes:
                        await self._ctx.registry.dispatch(
                            WikiHook.ON_NODE_DELETE,
                            {"node_id": node_id, "project_id": self._ctx.project_id}
                        )
                
                self._manifest.remove_entry(path_str)
                self._stats["deleted"] += len(affected_nodes)

        # ── Step 1: INGEST ──
        logger.info("📥 Step 1/7: INGEST — Scanning for dirty files...")
        scan_dirs = self._get_scan_dirs()
        
        dirty_files = []
        for d in scan_dirs:
            dirty_files.extend(self._manifest.get_dirty_files(d))
                
        self._stats["ingested"] = len(dirty_files)

        if not dirty_files and not missing_files:
            logger.info("✅ No changes detected. Index is up-to-date.")
            return self._build_report(start_time)

        # ── Step 2-3: Parse & Extract ──
        for filepath in dirty_files:
            try:
                await self._compile_single_file(filepath)
            except Exception as e:
                logger.error(f"❌ Compilation failed for {filepath}: {e}")
                self._manifest.mark_error(filepath, str(e))
                self._stats["errors"] += 1

        # ── Step 7: AUDIT ──
        logger.info("📝 Step 7/7: AUDIT — Saving manifest & audit log...")
        self._manifest.save()
        if self._storage:
            self._storage.append_audit_log(
                action="compile",
                target="incremental",
                detail=f"Processed {self._stats['ingested']} files, "
                       f"indexed {self._stats['indexed']}, "
                       f"errors {self._stats['errors']}",
            )

        # 全局钩子通知
        if self._ctx and self._ctx.registry:
            await self._ctx.registry.dispatch(WikiHook.POST_COMPILE, self._stats)

        return self._build_report(start_time)

    async def compile_full(self) -> dict[str, Any]:
        """全量编译 (重建整个索引)。"""
        self._stats = {k: 0 for k in self._stats}
        start_time = time.time()

        scan_dirs = self._get_scan_dirs()

        all_files: list[Path] = []
        patterns = ["*.md", "*.md.*"]
        if getattr(self._ctx.config, "enable_polyglot", False):
             patterns.extend(["*.py", "*.js", "*.ts", "*.go", "*.java", "*.cpp", "*.c", "*.h", "*.cs", "*.rs"])
             
        if self._omni:
            patterns.extend([f"*{ext}" for ext in self._omni.supported_extensions])

        for d in scan_dirs:
            for pat in patterns:
                matches = list(d.rglob(pat))
                all_files.extend(matches)

        self._stats["ingested"] = len(all_files)
        logger.info(f"🔄 Full compilation: {len(all_files)} files found in {scan_dirs}")

        # ── 错误类型追踪 (用于精准升级) ──
        storage_errors: list[str] = []  # DB/IO 类错误 (如 malformed)

        for filepath in all_files:
            try:
                await self._compile_single_file(filepath)
            except Exception as e:
                err_msg = str(e).lower()
                logger.error(f"❌ Compilation failed for {filepath}: {e}")
                self._stats["errors"] += 1
                # 识别存储层错误特征
                if any(kw in err_msg for kw in ("malformed", "disk image", "locked", "readonly", "corrupt")):
                    storage_errors.append(str(filepath))

        self._manifest.save()

        # ── 编译后门禁 + 军师咨询 ──
        self._post_compile_gate(storage_errors)

        return self._build_report(start_time)

    def _post_compile_gate(self, storage_errors: list[str]) -> None:
        """
        编译后 StageGate 检查。

        当错误率超过 30% 或检测到存储层故障时，触发 GovernanceEngine 门禁
        并通过环境感知路由自动咨询军师，替代之前无声吞噬错误的行为。
        """
        total = self._stats.get("ingested", 0)
        errors = self._stats.get("errors", 0)
        if total == 0:
            return

        error_rate = errors / total
        has_storage_error = len(storage_errors) > 0

        # 判断是否需要门禁介入
        needs_gate = error_rate > 0.3 or has_storage_error
        if not needs_gate:
            return

        logger.warning(
            f"⚠️ Post-compile gate triggered: error_rate={error_rate:.0%}, "
            f"storage_errors={len(storage_errors)}"
        )

        # 尝试通过 GovernanceEngine 触发军师咨询
        try:
            governance = self._ctx.registry.get_plugin("governance") if self._ctx else None
            if governance and hasattr(governance, "check_post_compile"):
                gate = governance.check_post_compile(self._stats)

                if not gate.passed and hasattr(governance, "consult_advisor"):
                    # 构建上下文 — 存储层错误时提供具体信息
                    context: dict[str, Any] = {
                        "stats": self._stats,
                        "error_rate": f"{error_rate:.0%}",
                        "hint": "storage_error" if has_storage_error else "high_error_rate",
                    }
                    if storage_errors:
                        context["storage_errors_sample"] = storage_errors[:5]
                        context["recommendation"] = (
                            "Detected SQLite 'malformed' errors. Atlas DB may be corrupted. "
                            "Self-healing should have triggered in AtlasIndex.connect(). "
                            "If errors persist, force-remove agents/_meta/atlas.db and restart."
                        )

                    advice = governance.consult_advisor(gate, context)
                    logger.info(
                        f"🧠 Advisor verdict: {advice.decision} "
                        f"(confidence={advice.confidence:.2f}) — {advice.reasoning[:200]}"
                    )
            else:
                # GovernanceEngine 未注册时直接记录警告
                logger.error(
                    f"🚨 Compilation error rate={error_rate:.0%} exceeds threshold. "
                    f"GovernanceEngine not available to escalate. "
                    f"Storage errors: {storage_errors[:3]}"
                )
        except Exception as e:
            logger.warning(f"Post-compile gate failed: {e}")


    def _get_scan_dirs(self) -> list[Path]:
        """
        获取需要扫描的目录列表。

        优先级:
          1. 环境变量 WIKI_SCAN_PATHS (英文分号分隔的绝对路径列表)
          2. WikiEngineConfig.extra_scan_paths (代码级配置)
          3. 默认: storage._root (即 WikiEngineConfig.wiki_dir)

        示例 .env:
          WIKI_SCAN_PATHS=D:\\ai\\workspace\\agents;D:\\notes;C:\\projects\\docs
        """
        import os

        dirs: list[Path] = []

        # ── 优先读取环境变量 ──
        env_paths = os.getenv("WIKI_SCAN_PATHS", "").strip()
        if env_paths:
            for raw in env_paths.split(";"):
                raw = raw.strip()
                if not raw:
                    continue
                p = Path(raw)
                if p.exists() and p.is_dir():
                    dirs.append(p)
                else:
                    logger.warning(f"⚠️ WIKI_SCAN_PATHS: path not found or not a dir, skipping: {p}")

        # ── 次优: config.extra_scan_paths ──
        if not dirs and self._ctx and hasattr(self._ctx.config, "extra_scan_paths"):
            extra: list[str | Path] = getattr(self._ctx.config, "extra_scan_paths", []) or []
            for raw in extra:
                p = Path(raw)
                if p.exists() and p.is_dir():
                    dirs.append(p)
                else:
                    logger.warning(f"⚠️ extra_scan_paths: path not found, skipping: {p}")

        # ── 兜底: storage._root ──
        if not dirs:
            if self._storage:
                dirs.append(self._storage._root)
            return dirs

        # 去重 (保持顺序)
        seen: set[Path] = set()
        unique: list[Path] = []
        for d in dirs:
            resolved = d.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(d)

        logger.info(f"📂 Wiki scan dirs ({len(unique)}): {[str(d) for d in unique]}")
        return unique


    async def _compile_single_file(self, filepath: Path) -> None:
        """
        编译单个文件的完整流程 (Step 2-6)。
        """
        if not self._storage:
            return
        # ── Step 2: SANITIZE ──
        if not self._storage.is_exportable(filepath):
            self._stats["skipped"] += 1
            return

        ext = filepath.suffix.lower()
        is_omni = self._omni and ext in self._omni.supported_extensions

        if not is_omni:
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
                if self._is_cosmetic_change(filepath, content):
                    import logging
                    logger = logging.getLogger("Coda.wiki.compiler")
                    logger.debug(f"Skipping cosmetic change: {filepath.name}")
                    self._stats["skipped"] += 1
                    return
                nodes = [self._extract_node(filepath, content)]
            except Exception as e:
                import logging
                logger = logging.getLogger("Coda.wiki.compiler")
                logger.error(f"Failed to read text file {filepath}: {e}")
                return
        else:
            content = "" # For binary files, relation extraction fallback to empty
            try:
                # [PHASE 2] Omni-Harvester Extraction
                if not self._omni:
                    return
                nodes = self._omni.harvest_file(filepath)
                # 触发高级知识抽取 (NER/Synthesis)
                if self._omni and hasattr(self._omni, "extract_knowledge"):
                    nodes = await self._omni.extract_knowledge(nodes)
            except Exception as e:
                import logging
                logger = logging.getLogger("Coda.wiki.compiler")
                logger.error(f"OmniHarvester failed for {filepath}: {e}")
                return

        self._stats["sanitized"] += 1

        import logging
        logger = logging.getLogger("Coda.wiki.compiler")

        # Process each generated node
        for node in nodes:
            if node is None:
                continue

            # ── Step 3: EXTRACT ──
            logger.debug(f"📦 Extracting node: {node.id}")
            
            # 冻结检测
            if node.id in self._frozen_slugs:
                logger.info(f"🧊 Frozen slug detected, skipping: {node.id}")
                self._stats["skipped"] += 1
                continue

            # 时间维度深度检查
            depth_policy = node.memory_horizon.compile_depth
            if depth_policy == "skip":
                logger.debug(f"⏳ Horizon {node.memory_horizon.value} policy is 'skip', bypassing {node.id}")
                self._stats["skipped"] += 1
                continue

            # Pre-extract hooks
            skip_node = False
            for hook in self._hooks.get("pre_extract", []):
                result = hook(node, {"filepath": str(filepath)})
                if result is None:
                    self._stats["skipped"] += 1
                    skip_node = True
                    break
                node = result

            if skip_node:
                continue

            self._stats["extracted"] += 1

            # Post-extract hooks
            for hook in self._hooks.get("post_extract", []):
                result = hook(node, {"filepath": str(filepath)})
                if result is not None:
                    node = result

            # ── Step 4: VALIDATE ──
            from .akp_parser import validate_node
            violations = validate_node(node)
            error_violations = [v for v in violations if v.severity == "error"]

            if error_violations:
                logger.warning(
                    f"⚠️ Validation failed for {filepath.name} ({node.id}): "
                    f"{[str(v) for v in error_violations]}"
                )
                self._demote_to_low_signal(filepath, node, error_violations)
                continue

            node.check_depth_standard()
            self._stats["validated"] += 1

            # ── Step 5: LINK ──
            if depth_policy in ("shallow", "index"):
                relations = []  # 根据时间维度策略跳过复杂关系抽取
            else:
                relations = self._extract_relations(node, content) if not is_omni else []
                # [V7.1] 真实进阶：LLM 隐式依赖抽取
                if depth_policy == "full" and len(relations) == 0:
                    try:
                        from engine.plugins.wiki.dreamcycle import CognitiveEngine
                        from main import db
                        cog = CognitiveEngine(db)
                        # 触发隐式抽取，并收集补充关系
                        implicit_data = await cog.extract_implicit_relations(node.project_id, node.id, content)
                        if "depends_on" in implicit_data:
                            from ..akp_types import KnowledgeRelation, RelationType
                            for dep in implicit_data["depends_on"]:
                                relations.append(KnowledgeRelation(from_id=node.id, to_id=dep, relation_type=RelationType.DEPENDS_ON, source="llm_implicit"))
                        if "extends" in implicit_data:
                            from ..akp_types import KnowledgeRelation, RelationType
                            for ext in implicit_data["extends"]:
                                relations.append(KnowledgeRelation(from_id=node.id, to_id=ext, relation_type=RelationType.EXTENDS, source="llm_implicit"))
                    except Exception as e:
                        logger.error(f"Failed to run implicit extraction for {node.id}: {e}")
            self._stats["linked"] += 1

            # ── Step 6: INDEX ──
            if depth_policy == "index":
                embedding = None  # 仅更新索引,不生成向量
            else:
                embedding = self._generate_embedding(node)

            # Pre-index hooks
            for hook in self._hooks.get("pre_index", []):
                result = hook(node, {"embedding": embedding})
                if result is None:
                    skip_node = True
                    break
                node = result
            
            if skip_node:
                continue

            if self._atlas:
                self._atlas.upsert_node(node, embedding)
                for rel in relations:
                    self._atlas.upsert_relation(rel)

            # 触发 V7.0 同步事件 (让 surreal_atlas 接管跨项目同步)
            if self._ctx and self._ctx.registry:
                import asyncio
                from ..base_plugin import WikiHook
                asyncio.create_task(self._ctx.registry.dispatch(
                    WikiHook.ON_NODE_INGEST, 
                    {"node": node, "relations": relations, "filepath": str(filepath)}
                ))

            # Post-index hooks
            for hook in self._hooks.get("post_index", []):
                hook(node, {"relations_count": len(relations)})

        # 更新 Manifest (使用所有生成的节点 ID)
        valid_nodes = [n.id for n in nodes if n is not None]
        self._manifest.mark_compiled(filepath, derived_pages=valid_nodes)
        self._stats["indexed"] += len(valid_nodes)

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
            # V7.0 联邦防护: 防止 AGENTS/SOUL 碰撞，使用相对路径增强 ID
            if node.id.startswith("akp-") or node.id in {"AGENTS", "SOUL"}:
                try:
                    if not self._storage:
                        raise ValueError("Storage not initialized")
                    rel_path = filepath.relative_to(self._storage._root)
                    if len(rel_path.parts) > 1:
                        node.id = ":".join(list(rel_path.parts[:-1]) + [rel_path.stem])
                    else:
                        node.id = rel_path.stem
                except Exception:
                    node.id = filepath.stem

            # 设置来源哈希
            if not node.source_origin_hash:
                node.source_origin_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            return node

        except Exception as e:
            logger.error(f"Failed to extract node from {filepath}: [{type(e).__name__}] {e}")
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

        text = f"{node.title}\n{node.body}"
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
        if not self._storage:
            return
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
        """构建编译报告。 V7.0 返回平铺的统计信息。"""
        elapsed = time.time() - start_time
        report = {
            "elapsed_seconds": round(elapsed, 2),
            "frozen_slugs_count": len(self._frozen_slugs),
            **self._stats
        }
        logger.info(
            f"✅ Compilation complete: {self._stats} in {elapsed:.1f}s"
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
