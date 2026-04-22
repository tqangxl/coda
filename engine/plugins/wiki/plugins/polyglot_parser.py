"""
Coda Knowledge Engine V6.2 — Polyglot Parser Plugin
基于 tree-sitter 的 15 语言结构化 AST 提取器。

支持语言:
  通用: Python, JavaScript, TypeScript, Java, C, C++, Rust, Go, Ruby, Bash
  标记/数据: JSON, YAML, HTML, CSS, Markdown

职责:
  - 自动检测源语言 (基于文件扩展名)
  - 使用 tree-sitter 进行高保真度 AST 解析
  - 将结构化实体 (函数/类/方法) 映射为 FactAnchor
  - 生成 KnowledgeNode (type=CODE/DATA)
  - 超限文件触发真实 Advisor 咨询
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..akp_types import (
    KnowledgeNode, NodeType, NodeStatus, EpistemicTag,
    AuthorityLevel, PIIShield, FactAnchor,
)

logger = logging.getLogger("Coda.wiki.polyglot")


# ════════════════════════════════════════════
#  语言配置注册表
# ════════════════════════════════════════════

@dataclass(frozen=True)
class LanguageSpec:
    """单一语言的解析规格。"""
    name: str                    # 规范名: "python"
    ts_module: str               # tree-sitter 模块: "tree_sitter_python"
    category: str                # "code" | "data"
    extensions: tuple[str, ...]  # (".py",)
    # tree-sitter 查询中用于提取顶层实体的节点类型
    entity_node_types: tuple[str, ...] = ()
    # 用于提取实体名称的子节点类型
    name_node_type: str = "identifier"


# 15 语言完整配置
LANGUAGE_REGISTRY: dict[str, LanguageSpec] = {}

_LANGUAGE_DEFS: list[LanguageSpec] = [
    # ── 通用编程语言 (10) ──
    LanguageSpec(
        name="python", ts_module="tree_sitter_python", category="code",
        extensions=(".py", ".pyw"),
        entity_node_types=("function_definition", "class_definition", "decorated_definition"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="javascript", ts_module="tree_sitter_javascript", category="code",
        extensions=(".js", ".mjs", ".cjs", ".jsx"),
        entity_node_types=("function_declaration", "class_declaration", "method_definition",
                          "arrow_function", "export_statement"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="typescript", ts_module="tree_sitter_typescript", category="code",
        extensions=(".ts", ".tsx"),
        entity_node_types=("function_declaration", "class_declaration", "method_definition",
                          "interface_declaration", "type_alias_declaration", "enum_declaration"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="java", ts_module="tree_sitter_java", category="code",
        extensions=(".java",),
        entity_node_types=("class_declaration", "method_declaration", "interface_declaration",
                          "enum_declaration", "constructor_declaration"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="c", ts_module="tree_sitter_c", category="code",
        extensions=(".c", ".h"),
        entity_node_types=("function_definition", "struct_specifier", "enum_specifier",
                          "union_specifier", "type_definition"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="cpp", ts_module="tree_sitter_cpp", category="code",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".h"),
        entity_node_types=("function_definition", "class_specifier", "struct_specifier",
                          "namespace_definition", "template_declaration", "enum_specifier"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="rust", ts_module="tree_sitter_rust", category="code",
        extensions=(".rs",),
        entity_node_types=("function_item", "struct_item", "enum_item", "impl_item",
                          "trait_item", "mod_item", "type_item"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="go", ts_module="tree_sitter_go", category="code",
        extensions=(".go",),
        entity_node_types=("function_declaration", "method_declaration", "type_declaration",
                          "type_spec"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="ruby", ts_module="tree_sitter_ruby", category="code",
        extensions=(".rb", ".rake"),
        entity_node_types=("method", "class", "module", "singleton_method"),
        name_node_type="identifier",
    ),
    LanguageSpec(
        name="bash", ts_module="tree_sitter_bash", category="code",
        extensions=(".sh", ".bash", ".zsh"),
        entity_node_types=("function_definition",),
        name_node_type="word",
    ),

    # ── 标记 / 数据语言 (5) ──
    LanguageSpec(
        name="json", ts_module="tree_sitter_json", category="data",
        extensions=(".json", ".jsonc", ".geojson"),
        entity_node_types=("pair",),
        name_node_type="string",
    ),
    LanguageSpec(
        name="yaml", ts_module="tree_sitter_yaml", category="data",
        extensions=(".yaml", ".yml"),
        entity_node_types=("block_mapping_pair",),
        name_node_type="flow_node",
    ),
    LanguageSpec(
        name="html", ts_module="tree_sitter_html", category="data",
        extensions=(".html", ".htm", ".xhtml"),
        entity_node_types=("element",),
        name_node_type="tag_name",
    ),
    LanguageSpec(
        name="css", ts_module="tree_sitter_css", category="data",
        extensions=(".css", ".scss", ".less"),
        entity_node_types=("rule_set", "media_statement", "keyframes_statement"),
        name_node_type="class_name",
    ),
    LanguageSpec(
        name="markdown", ts_module="tree_sitter_markdown", category="data",
        extensions=(".md", ".mdx", ".markdown"),
        entity_node_types=("atx_heading", "setext_heading"),
        name_node_type="inline",
    ),
]

# 构建注册表: name -> spec, extension -> spec
_EXT_MAP: dict[str, LanguageSpec] = {}
for _spec in _LANGUAGE_DEFS:
    LANGUAGE_REGISTRY[_spec.name] = _spec
    for _ext in _spec.extensions:
        # .h 同时被 C 和 C++ 声明, 优先 C
        if _ext not in _EXT_MAP:
            _EXT_MAP[_ext] = _spec


# ════════════════════════════════════════════
#  Tree-Sitter 解析器管理
# ════════════════════════════════════════════

class _TreeSitterPool:
    """
    Tree-Sitter 解析器延迟加载池。

    只在首次解析某语言时才加载对应的 tree-sitter 语法库,
    避免启动时一次性加载 15 种语法所带来的内存和时间开销。
    """

    def __init__(self) -> None:
        self._parsers: dict[str, Any] = {}  # lang_name -> tree_sitter.Parser
        self._languages: dict[str, Any] = {}  # lang_name -> tree_sitter.Language
        self._load_errors: dict[str, str] = {}
        self._lock = threading.Lock()

    def get_parser(self, spec: LanguageSpec) -> Any | None:
        """获取指定语言的 Parser (延迟初始化)。"""
        with self._lock:
            if spec.name in self._load_errors:
                return None
            if spec.name in self._parsers:
                return self._parsers[spec.name]
            return self._init_parser_unlocked(spec)

    def get_language(self, spec: LanguageSpec) -> Any | None:
        """获取指定语言的 Language 对象。"""
        with self._lock:
            if spec.name not in self._languages:
                self._init_parser_unlocked(spec)
            return self._languages.get(spec.name)

    def _init_parser_unlocked(self, spec: LanguageSpec) -> Any | None:
        """真实初始化 (内部方法，需外层加锁): 导入 tree-sitter 模块, 创建 Parser。"""
        try:
            import importlib
            import tree_sitter

            # 动态加载语法模块 (如 tree_sitter_python)
            lang_mod = importlib.import_module(spec.ts_module)

            # tree-sitter >= 0.22 使用 Language(lang_mod.language())
            # 部分模块 (如 typescript) 使用 language_typescript/language_tsx 等命名
            lang_fn = None
            if hasattr(lang_mod, "language"):
                lang_fn = lang_mod.language
            else:
                # 尝试 language_{name} 形式 (如 language_typescript)
                alt_name = f"language_{spec.name}"
                if hasattr(lang_mod, alt_name):
                    lang_fn = getattr(lang_mod, alt_name)
                else:
                    # 扫描所有 language_ 前缀的函数
                    for attr_name in dir(lang_mod):
                        if attr_name.startswith("language_") and callable(getattr(lang_mod, attr_name)):
                            lang_fn = getattr(lang_mod, attr_name)
                            break

            if lang_fn is None:
                raise ImportError(
                    f"Module {spec.ts_module} does not expose a language function. "
                    f"Tried: language(), language_{spec.name}(). "
                    f"Available: {[a for a in dir(lang_mod) if a.startswith('language')]}"
                )

            language = tree_sitter.Language(lang_fn())

            parser = tree_sitter.Parser(language)
            self._parsers[spec.name] = parser
            self._languages[spec.name] = language
            logger.debug(f"✅ Tree-sitter parser loaded: {spec.name}")
            return parser

        except ImportError as e:
            self._load_errors[spec.name] = str(e)
            logger.warning(f"⚠️ Tree-sitter module not available for {spec.name}: {e}")
            return None
        except Exception as e:
            self._load_errors[spec.name] = str(e)
            logger.error(f"❌ Failed to init tree-sitter for {spec.name}: {e}")
            return None

    def loaded_languages(self) -> list[str]:
        """返回已成功加载的语言列表。"""
        return list(self._parsers.keys())

    def failed_languages(self) -> dict[str, str]:
        """返回加载失败的语言及其原因。"""
        return dict(self._load_errors)


# ════════════════════════════════════════════
#  结构化实体提取
# ════════════════════════════════════════════

@dataclass
class ExtractedEntity:
    """从 AST 中提取的结构化实体。"""
    kind: str           # "function" | "class" | "method" | "struct" | "interface" | ...
    name: str           # 实体名称
    start_line: int     # 起始行号 (1-indexed)
    end_line: int       # 截止行号 (1-indexed)
    signature: str      # 签名/首行内容
    language: str       # 源语言
    parent: str = ""    # 父实体名 (嵌套时)


def _extract_entity_name(node: Any, spec: LanguageSpec) -> str:
    """从 AST 节点中提取实体名称。"""
    # 遍历直接子节点, 找到名称节点
    for child in node.children:
        if child.type == spec.name_node_type:
            return child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text

        # Python decorated_definition: 内部包含 function_definition/class_definition
        if child.type in ("function_definition", "class_definition"):
            return _extract_entity_name(child, spec)

    # fallback: 第一个 identifier 子节点
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text

    return "<anonymous>"


def _classify_entity_kind(node_type: str) -> str:
    """将 tree-sitter 节点类型映射为统一的实体类别。"""
    kind_map = {
        # Python
        "function_definition": "function",
        "class_definition": "class",
        "decorated_definition": "decorated",
        # JavaScript / TypeScript
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "arrow_function": "function",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
        "export_statement": "export",
        # Java
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        # C / C++
        "struct_specifier": "struct",
        "union_specifier": "union",
        "type_definition": "typedef",
        "namespace_definition": "namespace",
        "template_declaration": "template",
        "enum_specifier": "enum",
        # Rust
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "impl_item": "impl",
        "trait_item": "trait",
        "mod_item": "module",
        "type_item": "type",
        # Go
        "type_declaration": "type",
        "type_spec": "type",
        # Ruby
        "method": "method",
        "class": "class",
        "module": "module",
        "singleton_method": "method",
        # Bash
        "word": "function",
        # JSON
        "pair": "key",
        # YAML
        "block_mapping_pair": "key",
        # HTML
        "element": "element",
        # CSS
        "rule_set": "rule",
        "media_statement": "media",
        "keyframes_statement": "keyframes",
        # Markdown
        "atx_heading": "heading",
        "setext_heading": "heading",
    }
    return kind_map.get(node_type, "entity")


def extract_entities(
    tree: Any,
    source: bytes,
    spec: LanguageSpec,
    max_depth: int = 2,
) -> list[ExtractedEntity]:
    """
    从 AST 树中提取顶层结构化实体。

    只遍历到 max_depth 深度, 避免对巨型 AST 耗费过多时间。
    """
    entities: list[ExtractedEntity] = []
    target_types = set(spec.entity_node_types)

    def _walk(node: Any, depth: int, parent_name: str = "") -> None:
        if depth > max_depth:
            return

        if node.type in target_types:
            name = _extract_entity_name(node, spec)
            kind = _classify_entity_kind(node.type)

            # 提取签名: 取第一行作为 signature
            start_byte = node.start_byte
            first_newline = source.find(b"\n", start_byte)
            if first_newline == -1:
                first_newline = node.end_byte
            sig = source[start_byte:min(first_newline, start_byte + 200)]
            sig_text = sig.decode("utf-8", errors="replace").strip()

            entities.append(ExtractedEntity(
                kind=kind,
                name=name,
                start_line=node.start_point[0] + 1,  # 转为 1-indexed
                end_line=node.end_point[0] + 1,
                signature=sig_text,
                language=spec.name,
                parent=parent_name,
            ))
            # 递归进入实体内部 (寻找嵌套方法)
            for child in node.children:
                _walk(child, depth + 1, parent_name=name)
        else:
            for child in node.children:
                _walk(child, depth, parent_name=parent_name)

    _walk(tree.root_node, 0)
    return entities


# ════════════════════════════════════════════
#  Complexity Ceiling (复杂度天花板)
# ════════════════════════════════════════════

COMPLEXITY_CEILING_LOC = 5000  # 行数上限
COMPLEXITY_CEILING_BYTES = 500_000  # 字节上限


def check_complexity_ceiling(
    content: bytes,
    filepath: str,
) -> tuple[bool, dict[str, Any]]:
    """
    检查文件是否超过复杂度天花板。

    Returns:
        (exceeded, details): exceeded=True 表示需要 Advisor 审计。
    """
    loc = content.count(b"\n") + 1
    size = len(content)

    exceeded = loc > COMPLEXITY_CEILING_LOC or size > COMPLEXITY_CEILING_BYTES
    details = {
        "filepath": filepath,
        "loc": loc,
        "size_bytes": size,
        "loc_ceiling": COMPLEXITY_CEILING_LOC,
        "bytes_ceiling": COMPLEXITY_CEILING_BYTES,
        "exceeded": exceeded,
        "recommendation": "Truncate to 5000 lines or split file" if exceeded else "None"
    }
    if exceeded:
        logger.warning(
            f"⚠️ ComplexityCeiling exceeded: {filepath} "
            f"(LOC={loc}, Bytes={size})"
        )
    return exceeded, details


# ════════════════════════════════════════════
#  PolyglotParser Plugin (核心插件)
# ════════════════════════════════════════════

class PolyglotParser(WikiPlugin):
    """
    15 语言多态解析器插件。

    职责:
    1. 接受源代码文件路径, 自动识别语言
    2. 使用 tree-sitter 进行 AST 解析
    3. 提取结构化实体 → FactAnchor
    4. 生成 KnowledgeNode (type=CODE/DATA)
    5. 超限文件触发 Advisor 咨询
    """
    name = "polyglot_parser"

    def __init__(self) -> None:
        self._pool = _TreeSitterPool()
        self._ctx: WikiPluginContext | None = None
        self._advisor_router: Any = None  # 真实 AdvisorExecutorRouter (延迟绑定)
        self._stats = {
            "files_parsed": 0,
            "entities_extracted": 0,
            "advisor_consultations": 0,
            "languages_used": set(),
        }

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化: 记录上下文, 不预加载任何语法 (延迟加载)。"""
        self._ctx = ctx
        logger.info(
            f"🌐 PolyglotParser initialized | "
            f"Supported: {len(LANGUAGE_REGISTRY)} languages | "
            f"Extensions: {len(_EXT_MAP)} mappings"
        )

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应编译生命周期钩子。"""
        if hook == WikiHook.ON_NODE_INGEST and payload is not None:
            # 在节点入库前, 检查是否为代码文件并增强元数据
            if isinstance(payload, dict) and "file_path" in payload:
                filepath = payload["file_path"]
                spec = self.detect_language(filepath)
                if spec:
                    payload["language"] = spec.name
                    payload["node_type"] = (
                        NodeType.CODE if spec.category == "code"
                        else NodeType.DATA
                    )
        return None

    # ── Public API ──

    def bind_advisor(self, router: Any) -> None:
        """绑定真实的 AdvisorExecutorRouter 实例。"""
        self._advisor_router = router
        logger.info("🧠 PolyglotParser bound to AdvisorExecutorRouter")

    def detect_language(self, filepath: str | Path) -> LanguageSpec | None:
        """根据文件扩展名检测语言。支持 *.md.* 作为 .md"""
        path = Path(filepath)
        ext = path.suffix.lower()
        spec = _EXT_MAP.get(ext)
        if spec:
            return spec
            
        # 兼容性增强: 支持 *.md.* (如 filename.md.bak, filename.md.txt)
        if ".md." in path.name.lower():
            return LANGUAGE_REGISTRY.get("markdown")
            
        return None

    def supported_languages(self) -> list[str]:
        """返回支持的语言名列表。"""
        return list(LANGUAGE_REGISTRY.keys())

    def supported_extensions(self) -> list[str]:
        """返回支持的文件扩展名列表。"""
        return list(_EXT_MAP.keys())

    def parse_file(self, filepath: str | Path) -> KnowledgeNode | None:
        """
        解析单个源代码文件 → KnowledgeNode。

        流程:
        1. 检测语言
        2. 检查 ComplexityCeiling
        3. Tree-Sitter AST 解析
        4. 实体提取 → FactAnchor
        5. 构建 KnowledgeNode
        """
        path = Path(filepath)
        if not path.exists():
            logger.error(f"File not found: {path}")
            return None

        spec = self.detect_language(path)
        if spec is None:
            logger.debug(f"Unsupported file type: {path.suffix}")
            return None

        # 读取文件内容
        try:
            content = path.read_bytes()
        except Exception as e:
            logger.error(f"Failed to read {path}: {e}")
            return None

        return self.parse_content(content, str(path), spec)

    def parse_content(
        self,
        content: bytes,
        filepath: str,
        spec: LanguageSpec | None = None,
    ) -> KnowledgeNode | None:
        """
        解析源代码内容 → KnowledgeNode。

        参数:
            content: 文件的原始字节内容
            filepath: 文件路径 (用于元数据)
            spec: 语言规格 (如果为 None 则自动检测)
        """
        if spec is None:
            spec = self.detect_language(filepath)
        if spec is None:
            return None

        # ── Step 1: Complexity Ceiling 检查 ──
        exceeded, ceiling_details = check_complexity_ceiling(content, filepath)
        truncated = False
        original_length = len(content)

        if exceeded:
            self._handle_complexity_exceeded(filepath, ceiling_details)
            # 截断到天花板行数
            lines = content.split(b"\n")
            if len(lines) > COMPLEXITY_CEILING_LOC:
                # ── V6.5: 智能截断标记 ──
                # 记录原始行数以便下游追踪
                original_loc = len(lines)
                content = b"\n".join(lines[:COMPLEXITY_CEILING_LOC])
                # 附加显式注释提示解析器
                comment_style = "//" if spec.category == "code" else "#"
                trunc_msg = f"\n\n{comment_style} [TRUNCATED] ComplexityCeiling exceeded ({original_loc} > {COMPLEXITY_CEILING_LOC} lines)."
                content += trunc_msg.encode("utf-8")
                
                truncated = True
                logger.info(
                    f"📐 Truncated {filepath} from {original_loc} to "
                    f"{COMPLEXITY_CEILING_LOC} lines for parsing"
                )

        # ── Step 2: Tree-Sitter 解析 ──
        parser = self._pool.get_parser(spec)
        if parser is None:
            logger.warning(f"No parser available for {spec.name}, creating stub node")
            return self._create_stub_node(content, filepath, spec, truncated, original_length)

        try:
            tree = parser.parse(content)
        except Exception as e:
            logger.error(f"Tree-sitter parse failed for {filepath}: {e}")
            return self._create_stub_node(content, filepath, spec, truncated, original_length)

        # ── Step 3: 实体提取 ──
        entities = extract_entities(tree, content, spec)

        # ── Step 4: 构建 KnowledgeNode ──
        node = self._build_node(content, filepath, spec, entities, truncated, original_length)

        # ── 统计 ──
        self._stats["files_parsed"] += 1
        self._stats["entities_extracted"] += len(entities)
        self._stats["languages_used"].add(spec.name)

        logger.info(
            f"📝 Parsed {filepath} [{spec.name}] → "
            f"{len(entities)} entities, {node.word_count} words"
        )
        return node

    def get_stats(self) -> dict[str, Any]:
        """返回运行时统计信息。"""
        stats = dict(self._stats)
        stats["languages_used"] = sorted(stats["languages_used"])
        stats["loaded_parsers"] = self._pool.loaded_languages()
        stats["failed_parsers"] = self._pool.failed_languages()
        return stats

    # ── Private ──

    def _build_node(
        self,
        content: bytes,
        filepath: str,
        spec: LanguageSpec,
        entities: list[ExtractedEntity],
        truncated: bool,
        original_length: int,
    ) -> KnowledgeNode:
        """从解析结果构建 KnowledgeNode。"""
        text = content.decode("utf-8", errors="replace")
        p = Path(filepath)
        title = p.name

        # ── [V7.1] ID 稳定化策略 ──
        stable_id = None
        parts = p.parts
        try:
            idx = -1
            for i, part in enumerate(parts):
                if part.lower() in ("agents", "wiki", "brain", ".agents"):
                    idx = i
            if idx != -1:
                stable_id = "-".join(parts[idx:]).lower().replace(" ", "-").replace(".", "-")
            else:
                stable_id = str(filepath).lower().replace("/", "-").replace("\\", "-").replace(":", "").replace(" ", "-").replace(".", "-")
        except:
            import hashlib
            stable_id = hashlib.md5(str(filepath).encode()).hexdigest()[:12]

        node = KnowledgeNode(
            id=stable_id,
            title=title,
            node_type=NodeType.CODE if spec.category == "code" else NodeType.DATA,
            status=NodeStatus.VALIDATED,
            confidence=1.0,  # 代码是显式真理
            epistemic_tag=EpistemicTag.CONFIRMED,
            authority=AuthorityLevel.EXPLICIT,
            body=text,
            file_path=filepath,
            language=spec.name,
            truncated=truncated,
            original_length=original_length if truncated else 0,
        )

        # 将实体映射为 FactAnchor
        for entity in entities:
            slug_prefix = {
                "function": "fn",
                "class": "cls",
                "method": "method",
                "struct": "struct",
                "interface": "iface",
                "enum": "enum",
                "trait": "trait",
                "impl": "impl",
                "module": "mod",
                "type": "type",
                "namespace": "ns",
                "key": "key",
                "element": "elem",
                "rule": "rule",
                "heading": "h",
                "export": "export",
                "constructor": "ctor",
                "typedef": "typedef",
                "template": "tmpl",
                "decorated": "dec",
                "media": "media",
                "keyframes": "kf",
            }.get(entity.kind, "entity")

            slug = f"{slug_prefix}:{entity.name}"

            node.facts.append(FactAnchor(
                slug=slug,
                content=entity.signature,
                line_number=entity.start_line,
                entity_type=entity.kind,
                meta={
                    "end_line": entity.end_line,
                    "parent": entity.parent,
                    "language": entity.language
                }
            ))

        node.compute_content_hash()
        node.compute_word_count()
        return node

    def _create_stub_node(
        self,
        content: bytes,
        filepath: str,
        spec: LanguageSpec,
        truncated: bool,
        original_length: int,
    ) -> KnowledgeNode:
        """当 tree-sitter 不可用时, 创建不含实体的基础节点。"""
        text = content.decode("utf-8", errors="replace")
        node = KnowledgeNode(
            title=Path(filepath).name,
            node_type=NodeType.CODE if spec.category == "code" else NodeType.DATA,
            status=NodeStatus.DRAFT,
            confidence=0.7,
            epistemic_tag=EpistemicTag.INFERRED,
            authority=AuthorityLevel.SYSTEM,
            body=text,
            file_path=filepath,
            language=spec.name,
            truncated=truncated,
            original_length=original_length if truncated else 0,
        )
        node.compute_content_hash()
        node.compute_word_count()
        return node

    def _handle_complexity_exceeded(
        self,
        filepath: str,
        details: dict[str, Any],
    ) -> None:
        """
        复杂度超限处理: 触发真实的 Advisor 咨询。

        如果 AdvisorExecutorRouter 已绑定, 将通过 GovernanceEngine
        发起真正的 LLM 咨询以获取处理建议。
        """
        self._stats["advisor_consultations"] += 1

        if self._advisor_router is None:
            logger.info(
                f"📋 ComplexityCeiling exceeded for {filepath} "
                f"(no Advisor bound — defaulting to truncation)"
            )
            return

        # 通过 GovernanceEngine 桥接真实咨询
        try:
            governance = self._ctx.registry.get_plugin("governance") if self._ctx else None
            if governance and hasattr(governance, "consult_advisor"):
                from .skill_tracker import StageGate
                gate = StageGate(
                    gate_id=f"complexity_ceiling_{Path(filepath).name}",
                    phase="pre_parse",
                    conditions=details,
                    passed=False,
                    detail=(
                        f"File {filepath} exceeds ComplexityCeiling: "
                        f"LOC={details['loc']}, Bytes={details['size_bytes']}. "
                        f"Recommend: truncate to {COMPLEXITY_CEILING_LOC} lines or skip."
                    ),
                )
                advice = governance.consult_advisor(gate, details)
                logger.info(
                    f"🧠 Advisor verdict for {filepath}: "
                    f"{advice.decision} (confidence={advice.confidence:.2f})"
                )
            else:
                logger.debug("GovernanceEngine not available for advisor consultation")
        except Exception as e:
            logger.warning(f"Advisor consultation failed for {filepath}: {e}")
