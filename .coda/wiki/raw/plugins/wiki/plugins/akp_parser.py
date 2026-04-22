"""
Coda Knowledge Engine V6.0 — AKP Parser
Markdown YAML Frontmatter 解析器 + 语义弱信号拦截器。

职责:
  - 解析 Markdown 文件的 YAML frontmatter → KnowledgeNode
  - 提取 <!-- fact:slug --> 事实锚点
  - 执行 WeakPatterns 语义拦截
  - 序列化 KnowledgeNode → Markdown 文件
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from ..akp_types import (
    KnowledgeNode, NodeType, NodeStatus, EpistemicTag, AuthorityLevel,
    PIIShield, QualityGate, FactAnchor, WeakPatternViolation,
)

logger = logging.getLogger("Coda.wiki.akp_parser")

# ── 模糊动词拦截清单 ──
VAGUE_VERBS_ZH = {"大概", "可能", "似乎", "也许", "好像", "应该", "差不多", "或许"}
VAGUE_VERBS_EN = {"maybe", "perhaps", "probably", "might", "could be", "seems", "apparently"}
VAGUE_PATTERNS = VAGUE_VERBS_ZH | VAGUE_VERBS_EN

# ── YAML Frontmatter 正则 ──
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
FACT_ANCHOR_RE = re.compile(r"<!--\s*fact:(\S+)\s*-->")


class AKPParser(WikiPlugin):
    """
    Markdown YAML Frontmatter 解析器插件。
    """
    name = "akp_parser"

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        logger.info("📄 AKP Parser plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        return None

    def parse_file(self, filepath: str | Path) -> KnowledgeNode:
        return parse_markdown_file(filepath)

    def validate(self, node: KnowledgeNode) -> list[WeakPatternViolation]:
        return validate_node(node)

def _parse_yaml_block(yaml_text: str) -> dict[str, Any]:
    """手动解析简单 YAML (避免强制依赖 PyYAML)。若有 PyYAML 则优先使用。"""
    try:
        import yaml
        return yaml.safe_load(yaml_text) or {}
    except ImportError:
        pass

    result: dict[str, Any] = {}
    current_key = ""
    current_list: list[str] | None = None

    for line in yaml_text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 列表项
        if stripped.startswith("- ") and current_key:
            if current_list is None:
                current_list = []
                result[current_key] = current_list
            current_list.append(stripped[2:].strip().strip("'\""))
            continue

        # Key-value
        if ":" in stripped:
            current_list = None
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()

            if not val:
                current_key = key
                result[key] = []
                current_list = result[key]
                continue

            current_key = key

            # 内联列表 [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                items = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                result[key] = items
                continue

            # Boolean
            if val.lower() in ("true", "yes"):
                result[key] = True
                continue
            if val.lower() in ("false", "no"):
                result[key] = False
                continue

            # Numeric
            try:
                if "." in val:
                    result[key] = float(val)
                else:
                    result[key] = int(val)
                continue
            except ValueError:
                pass

            # String
            result[key] = val.strip("'\"")

    return result


def parse_markdown_file(filepath: str | Path) -> KnowledgeNode:
    """
    解析 Markdown 文件为 KnowledgeNode。

    处理流程:
    1. 提取 YAML frontmatter
    2. 解析所有 <!-- fact:slug --> 锚点
    3. 构建 KnowledgeNode 并计算 content_hash
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Knowledge file not found: {path}")

    raw_content = path.read_text(encoding="utf-8")
    return parse_markdown_content(raw_content, file_path=str(path))


def parse_markdown_content(content: str, file_path: str = "") -> KnowledgeNode:
    """
    从 Markdown 文本解析 KnowledgeNode。
    """
    node = KnowledgeNode(file_path=file_path)

    # ── Step 1: 提取 YAML Frontmatter ──
    fm_match = FRONTMATTER_RE.match(content)
    body = content
    if fm_match:
        yaml_text = fm_match.group(1)
        body = content[fm_match.end():]
        meta = _parse_yaml_block(yaml_text)
        _apply_frontmatter(node, meta)

    node.body = body.strip()

    # ── Step 2: 提取事实锚点 ──
    for match in FACT_ANCHOR_RE.finditer(content):
        slug = match.group(1)
        line_num = content[:match.start()].count("\n") + 1
        # 找到锚点所在行的内容
        line_start = content.rfind("\n", 0, match.start()) + 1
        line_end = content.find("\n", match.end())
        if line_end == -1:
            line_end = len(content)
        line_content = content[line_start:line_end].strip()
        # 移除锚点本身
        clean_content = FACT_ANCHOR_RE.sub("", line_content).strip()

        node.facts.append(FactAnchor(
            slug=slug,
            content=clean_content,
            line_number=line_num,
        ))

    # ── Step 3: 计算哈希与字数 ──
    node.compute_content_hash()
    node.compute_word_count()

    # ── Step 4: 截断诚实标记 ──
    if len(content) > 100_000:
        node.truncated = True
        node.original_length = len(content)

    return node


def _apply_frontmatter(node: KnowledgeNode, meta: dict[str, Any]) -> None:
    """将 YAML 字典映射到 KnowledgeNode 属性。"""
    if "id" in meta:
        node.id = str(meta["id"])
    if "title" in meta:
        node.title = str(meta["title"])

    # 枚举字段安全映射
    type_str = str(meta.get("type", "concept"))
    try:
        node.node_type = NodeType(type_str)
    except ValueError:
        node.node_type = NodeType.CONCEPT

    status_str = str(meta.get("status", "draft"))
    try:
        node.status = NodeStatus(status_str)
    except ValueError:
        node.status = NodeStatus.DRAFT

    epistemic_str = str(meta.get("epistemic_tag", "speculative"))
    try:
        node.epistemic_tag = EpistemicTag(epistemic_str)
    except ValueError:
        node.epistemic_tag = EpistemicTag.SPECULATIVE

    pii_str = str(meta.get("pii_shield", "raw"))
    try:
        node.pii_shield = PIIShield(pii_str)
    except ValueError:
        node.pii_shield = PIIShield.RAW

    # 标量字段
    node.confidence = float(meta.get("confidence", 0.5))
    node.load_bearing = bool(meta.get("load_bearing", False))
    node.falsifiable = bool(meta.get("falsifiable", False))
    node.falsification = str(meta.get("falsification", ""))
    node.source_origin_hash = str(meta.get("source_origin_hash", ""))
    node.verified_by = str(meta.get("verified_by", ""))
    node.insight_density = int(meta.get("insight_density", 5))
    node.last_audit = str(meta.get("last_audit", ""))
    node.extends = str(meta.get("extends", ""))
    node.frozen_reason = str(meta.get("frozen_reason", ""))

    # 列表字段
    if isinstance(meta.get("depends_on"), list):
        node.depends_on = [str(d) for d in meta["depends_on"]]
    if isinstance(meta.get("contradicts"), list):
        node.contradicts = [str(c) for c in meta["contradicts"]]
    if isinstance(meta.get("references"), list):
        node.references = [str(r) for r in meta["references"]]
    if isinstance(meta.get("derived_from_sources"), list):
        node.derived_from_sources = [str(s) for s in meta["derived_from_sources"]]


def serialize_node_to_markdown(node: KnowledgeNode) -> str:
    """
    将 KnowledgeNode 序列化为 Markdown 文件内容。
    生成 YAML frontmatter + 正文。
    """
    try:
        import yaml
        fm_str = yaml.dump(
            node.to_frontmatter_dict(),
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    except ImportError:
        fm_str = _dict_to_simple_yaml(node.to_frontmatter_dict())

    lines = ["---", fm_str.rstrip(), "---", "", node.body]
    return "\n".join(lines)


def _dict_to_simple_yaml(data: dict[str, Any], indent: int = 0) -> str:
    """简单 YAML 序列化 (无外部依赖)。"""
    lines: list[str] = []
    prefix = "  " * indent
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
            else:
                lines.append(f"{prefix}{key}:")
                for item in value:
                    lines.append(f"{prefix}  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_dict_to_simple_yaml(value, indent + 1))
        elif isinstance(value, bool):
            lines.append(f"{prefix}{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{prefix}{key}: {value}")
        elif value == "":
            lines.append(f'{prefix}{key}: ""')
        else:
            lines.append(f"{prefix}{key}: {value}")
    return "\n".join(lines)


# ════════════════════════════════════════════
#  WeakPatterns 语义拦截器
# ════════════════════════════════════════════

def validate_node(node: KnowledgeNode) -> list[WeakPatternViolation]:
    """
    执行 AKP 语义弱信号拦截。

    拦截规则:
    1. 描述长度 ≤ 24 字符 → 拦截
    2. 含模糊动词且无 [Speculative] 标记 → 拦截
    3. 无 source_origin_hash 且 epistemic_tag != speculative → 拦截
    4. 标题为空 → 拦截
    """
    violations: list[WeakPatternViolation] = []

    # Rule 1: 空标题
    if not node.title.strip():
        violations.append(WeakPatternViolation(
            node_id=node.id,
            violation_type="empty_title",
            detail="Knowledge node must have a non-empty title",
            severity="error",
        ))

    # Rule 2: 描述过短 (正文 < 24 字符)
    if len(node.body.strip()) <= 24:
        violations.append(WeakPatternViolation(
            node_id=node.id,
            violation_type="short_description",
            detail=f"Body length ({len(node.body.strip())}) ≤ 24 chars. Too shallow for knowledge base.",
            severity="error",
        ))

    # Rule 3: 模糊动词
    if node.epistemic_tag != EpistemicTag.SPECULATIVE:
        body_lower = node.body.lower()
        found_vague = [v for v in VAGUE_PATTERNS if v in body_lower]
        if found_vague:
            violations.append(WeakPatternViolation(
                node_id=node.id,
                violation_type="vague_verb",
                detail=f"Contains vague terms {found_vague} without [Speculative] tag.",
                severity="warning",
            ))

    # Rule 4: 缺失来源
    if not node.source_origin_hash and node.epistemic_tag != EpistemicTag.SPECULATIVE:
        violations.append(WeakPatternViolation(
            node_id=node.id,
            violation_type="missing_source",
            detail="No source_origin_hash for non-speculative knowledge.",
            severity="warning",
        ))

    # Rule 5: 置信度超过权威层级天花板
    ceiling = node.authority.weight_ceiling
    if node.confidence > ceiling / 10.0:
        violations.append(WeakPatternViolation(
            node_id=node.id,
            violation_type="confidence_ceiling_breach",
            detail=f"Confidence {node.confidence} exceeds authority ceiling {ceiling/10.0} for {node.authority.value}.",
            severity="warning",
        ))

    return violations


def validate_file(filepath: str | Path) -> tuple[KnowledgeNode | None, list[WeakPatternViolation]]:
    """
    解析文件并执行完整校验。
    返回 (解析后的节点, 违规列表)。
    """
    try:
        node = parse_markdown_file(filepath)
    except Exception as e:
        return None, [WeakPatternViolation(
            node_id="unknown",
            violation_type="parse_error",
            detail=str(e),
            severity="error",
        )]

    violations = validate_node(node)
    return node, violations
