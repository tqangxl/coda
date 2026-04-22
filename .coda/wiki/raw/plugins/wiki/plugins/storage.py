"""
Coda Knowledge Engine V6.0 — Manifest & Storage
增量编译清单 + 四层存储管理器。

Manifest 职责:
  - SHA-256 追踪所有 raw/ 源文件的指纹
  - 记录 source → [wiki_pages] 多对多映射 (反向索引)
  - 判定文件是否 stale (需要重编译)

Storage 职责:
  - 四层存储初始化 (raw/candidates/core/control)
  - 文件路径沙箱校验 (防路径穿越)
  - Privacy Sentinel (.Coda_no_save)
  - 隐私哨兵 (.exportignore) 匹配
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiPluginContext, WikiHook

import hashlib
import json
import logging
import os
import re
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ..akp_types import ManifestEntry, StorageLayer

logger = logging.getLogger("Coda.wiki.storage")


# ════════════════════════════════════════════
#  Manifest: 增量编译清单
# ════════════════════════════════════════════

class CompilationManifest:
    """
    增量编译清单 — 追踪所有源文件的指纹和派生页面。

    核心功能:
    1. SHA-256 哈希判定文件是否 dirty
    2. source → [wiki_pages] 反向索引 (影子更新)
    3. 断点续传支持 (compile-state.json)
    """

    def __init__(self, manifest_path: str | Path):
        self._path = Path(manifest_path)
        self._entries: dict[str, ManifestEntry] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for path, entry_data in data.get("entries", {}).items():
                    self._entries[path] = ManifestEntry(
                        source_path=path,
                        content_hash=entry_data.get("content_hash", ""),
                        file_size=entry_data.get("file_size", 0),
                        mime_type=entry_data.get("mime_type", ""),
                        last_compiled=entry_data.get("last_compiled", 0),
                        derived_pages=entry_data.get("derived_pages", []),
                        status=entry_data.get("status", "pending"),
                        error_message=entry_data.get("error_message", ""),
                        retry_count=entry_data.get("retry_count", 0),
                    )
                logger.info(f"Loaded manifest: {len(self._entries)} entries")
            except Exception as e:
                logger.warning(f"Failed to load manifest: {e}")

    def save(self) -> None:
        """持久化清单到磁盘。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "6.0",
            "updated_at": time.time(),
            "entries": {
                path: entry.to_dict()
                for path, entry in self._entries.items()
            },
        }
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def compute_file_hash(self, filepath: str | Path) -> str:
        """计算文件的 SHA-256 哈希。"""
        path = Path(filepath)
        if not path.exists():
            return ""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def is_stale(self, filepath: str | Path) -> bool:
        """判定文件是否需要重编译。"""
        path_str = str(filepath)
        current_hash = self.compute_file_hash(filepath)
        if not current_hash:
            return False

        entry = self._entries.get(path_str)
        if entry is None:
            return True  # 新文件
        return entry.is_stale(current_hash)

    def get_dirty_files(self, source_dir: str | Path) -> list[Path]:
        """扫描目录, 返回所有需要重编译的文件。"""
        dirty: list[Path] = []
        source_path = Path(source_dir)
        if not source_path.exists():
            return dirty

        for filepath in source_path.rglob("*"):
            if filepath.is_file() and not filepath.name.startswith("."):
                if self.is_stale(filepath):
                    dirty.append(filepath)

        return dirty

    def mark_compiled(self, filepath: str | Path, derived_pages: list[str]) -> None:
        """标记文件编译完成, 记录派生页面。"""
        path_str = str(filepath)
        current_hash = self.compute_file_hash(filepath)
        file_size = Path(filepath).stat().st_size if Path(filepath).exists() else 0

        self._entries[path_str] = ManifestEntry(
            source_path=path_str,
            content_hash=current_hash,
            file_size=file_size,
            mime_type=self._guess_mime(Path(filepath)),
            last_compiled=time.time(),
            derived_pages=derived_pages,
            status="compiled",
        )

    def mark_error(self, filepath: str | Path, error: str) -> None:
        """标记编译失败。"""
        path_str = str(filepath)
        entry = self._entries.get(path_str)
        if entry:
            entry.status = "error"
            entry.error_message = error
            entry.retry_count += 1
        else:
            self._entries[path_str] = ManifestEntry(
                source_path=path_str,
                content_hash="",
                status="error",
                error_message=error,
                retry_count=1,
            )

    def get_affected_pages(self, filepath: str | Path) -> list[str]:
        """获取受影响的 Wiki 页面 (用于影子更新级联)。"""
        entry = self._entries.get(str(filepath))
        return entry.derived_pages if entry else []

    def find_shared_concept_sources(self, concept_page_id: str) -> list[str]:
        """
        找到所有引用同一概念页面的源文件 (影子更新)。
        即使源文件 B 没动, 但如果 A 和 B 都引用概念 X, 且 A 变了, B 也需要重编。
        """
        sources: list[str] = []
        for path, entry in self._entries.items():
            if concept_page_id in entry.derived_pages:
                sources.append(path)
        return sources

    def get_all_entries(self) -> dict[str, ManifestEntry]:
        return dict(self._entries)

    def remove_entry(self, filepath: str | Path) -> None:
        """移除清单条目 (源文件被删除时)。"""
        self._entries.pop(str(filepath), None)

    def _guess_mime(self, path: Path) -> str:
        """基于扩展名推断 MIME 类型。"""
        mime_map = {
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".py": "text/x-python",
            ".js": "text/javascript",
            ".ts": "text/typescript",
            ".json": "application/json",
            ".yaml": "text/yaml",
            ".yml": "text/yaml",
            ".pdf": "application/pdf",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".csv": "text/csv",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".gif": "image/gif",
            ".mp4": "video/mp4",
            ".mp3": "audio/mpeg",
        }
        return mime_map.get(path.suffix.lower(), "application/octet-stream")


# ════════════════════════════════════════════
#  Storage: 四层存储管理器
# ════════════════════════════════════════════

class WikiStorage(WikiPlugin):
    """
    四层纵深存储管理器。
    
    层级:
      L0: raw/       — 原始素材 (只读)
      L1: candidates/ — 待验证
      L2: knowledge/  — 核心知识
      L3: _meta/      — 系统控制
    """
    name = "storage"

    CORE_SUBDIRS = ["entities", "concepts", "techniques", "kyp", "synthesis", "patterns", "sources"]

    def __init__(self, wiki_root: str | Path | None = None):
        if wiki_root:
            self._root = Path(wiki_root)
        else:
            self._root = Path(".") # Will be set in initialize by context
        self._exportignore_patterns: list[str] = []
        self._privacy_disabled = False

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        self._root = Path(ctx.wiki_dir)
        res = self._initialize_structure()
        logger.info(f"💾 Storage plugin initialized: {res}")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        if hook == WikiHook.ON_SHUTDOWN:
            logger.info("💾 Storage plugin shutting down")
        return None

    def _initialize_structure(self) -> dict[str, int]:
        """原 initialize 逻辑 (重命名避免冲突)。"""
        created = 0
        existed = 0

        dirs_to_create = [
            self._root / "raw",
            self._root / "_meta" / "candidates",
            self._root / "_meta" / "extracted",  # 影子镜像输出
            self._root / "_meta" / "pending_writes",  # 失败重试队列
            self._root / "_meta" / "low_signal",  # 低质量内容降级
        ]

        # L2: Core 子目录
        for subdir in self.CORE_SUBDIRS:
            dirs_to_create.append(self._root / "knowledge" / subdir)

        for d in dirs_to_create:
            if d.exists():
                existed += 1
            else:
                d.mkdir(parents=True, exist_ok=True)
                created += 1

        # 加载 .exportignore
        self._load_exportignore()

        # 检查 Privacy Sentinel
        self._privacy_disabled = (self._root / ".Coda_no_save").exists()
        if self._privacy_disabled:
            logger.warning("🔒 Privacy Sentinel ACTIVE: MemoryCompiler disabled")

        return {"created": created, "existed": existed}

    @property
    def is_privacy_disabled(self) -> bool:
        """Privacy Sentinel: .Coda_no_save 存在时返回 True。"""
        return self._privacy_disabled

    # ── 路径解析 ──

    def get_layer_path(self, layer: StorageLayer) -> Path:
        paths = {
            StorageLayer.RAW: self._root / "raw",
            StorageLayer.CANDIDATES: self._root / "_meta" / "candidates",
            StorageLayer.CORE: self._root / "knowledge",
            StorageLayer.CONTROL: self._root / "_meta",
        }
        return paths[layer]

    def resolve_safe_path(self, relative_path: str, layer: StorageLayer = StorageLayer.CORE) -> Path:
        """
        解析安全路径 (防目录穿越攻击)。

        实现 Centro 的双重防御:
        1. 正则清理标识符
        2. 检查解析后路径是否在 wiki_dir 内
        """
        # Step 1: 清理危险字符
        clean = re.sub(r'[<>:"|?*]', '_', relative_path)
        clean = clean.replace('..', '_')

        # Step 2: 解析路径
        base = self.get_layer_path(layer)
        candidate = (base / clean).resolve()

        # Step 3: 父级校验 (Centro: L240)
        if base.resolve() not in candidate.parents and candidate != base.resolve():
            raise PermissionError(
                f"Path traversal blocked: {candidate} is outside {base.resolve()}"
            )

        return candidate

    def get_atlas_db_path(self) -> Path:
        return self._root / "_meta" / "atlas.db"

    def get_manifest_path(self) -> Path:
        return self._root / "_meta" / "manifest.json"

    def get_log_path(self) -> Path:
        return self._root / "_meta" / "log.md"

    def get_session_db_path(self) -> Path:
        return self._root / "_meta" / "session.db"

    # ── 文件操作 ──

    def write_knowledge_file(self, relative_path: str, content: str,
                             layer: StorageLayer = StorageLayer.CORE) -> Path:
        """安全写入知识文件。"""
        if self._privacy_disabled:
            raise PermissionError("Privacy Sentinel active: writes disabled")

        filepath = self.resolve_safe_path(relative_path, layer)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def read_knowledge_file(self, relative_path: str,
                            layer: StorageLayer = StorageLayer.CORE) -> str:
        """安全读取知识文件。"""
        filepath = self.resolve_safe_path(relative_path, layer)
        if not filepath.exists():
            raise FileNotFoundError(f"Knowledge file not found: {filepath}")
        return filepath.read_text(encoding="utf-8")

    def list_knowledge_files(self, layer: StorageLayer = StorageLayer.CORE,
                             pattern: str = "*.md") -> list[Path]:
        """列出指定层的所有知识文件。"""
        base = self.get_layer_path(layer)
        if not base.exists():
            return []
        return sorted(base.rglob(pattern))

    def is_exportable(self, filepath: str | Path) -> bool:
        """检查文件是否可被索引/导出 (.exportignore 匹配)。"""
        rel_path = str(filepath)
        for pattern in self._exportignore_patterns:
            if fnmatch(rel_path, pattern):
                return False
        return True

    # ── Sync-and-Prune (Centro: 增量清理) ──

    def sync_and_prune(self, valid_ids: set[str], knowledge_dir: str = "knowledge") -> list[str]:
        """
        同步清理: 删除不在 valid_ids 中的孤儿文件。
        
        Returns: 被删除的文件路径列表。
        """
        pruned: list[str] = []
        knowledge_path = self._root / knowledge_dir

        if not knowledge_path.exists():
            return pruned

        for md_file in knowledge_path.rglob("*.md"):
            stem = md_file.stem
            if stem not in valid_ids and stem != "index" and stem != "README":
                md_file.unlink()
                pruned.append(str(md_file))
                logger.info(f"Pruned orphan file: {md_file}")

        return pruned

    # ── 审计日志写入 ──

    def append_audit_log(self, action: str, target: str = "", detail: str = "") -> None:
        """追加审计日志到 log.md (基于动词的日志)。"""
        from ..akp_types import AuditLogEntry
        entry = AuditLogEntry(action=action, target=target, detail=detail)
        log_path = self.get_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry.to_markdown_block())

    # ── 失败持久化 (Pending Writes) ──

    def save_pending_write(self, task_id: str, data: dict[str, Any]) -> Path:
        """
        保存失败的写入请求 (断点续传)。
        """
        pending_dir = self._root / "_meta" / "pending_writes"
        pending_dir.mkdir(parents=True, exist_ok=True)
        filepath = pending_dir / f"{task_id}.json"
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return filepath

    def load_pending_writes(self) -> list[dict[str, Any]]:
        """加载所有待处理的失败写入。"""
        pending_dir = self._root / "_meta" / "pending_writes"
        if not pending_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for json_file in pending_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                data["_pending_file"] = str(json_file)
                results.append(data)
            except Exception as e:
                logger.warning(f"Failed to load pending write {json_file}: {e}")

        return results

    def clear_pending_write(self, filepath: str) -> None:
        """清除已完成的待处理写入。"""
        path = Path(filepath)
        if path.exists():
            path.unlink()

    # ── 内部方法 ──

    def _load_exportignore(self) -> None:
        """加载 .exportignore 规则。"""
        ignore_file = self._root / ".exportignore"
        if ignore_file.exists():
            self._exportignore_patterns = [
                line.strip()
                for line in ignore_file.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
