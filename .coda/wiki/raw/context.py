"""
Coda V4.0 — Context Discovery & MagicDocs (Pillar 2 & 15)
动态环境感知 + 文档嗅探: 自动感应项目状态, 构建知识图谱。

设计参考:
  - Claude Code `rust/crates/runtime/src/prompt.rs` (ContextDiscoverer)
  - 原始 TS `services/MagicDocs/magicDocs.ts`
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
from pathlib import Path
from typing import Any, cast

from .git_checkpoint import GitCheckpoint

logger = logging.getLogger("Coda.context")

# 指令文件层级递归的最大深度
MAX_INSTRUCTION_DEPTH = 10
# 单个指令文件的字符限制
INSTRUCTION_CHAR_LIMIT = 4000


class ContextDiscoverer:
    """
    动态环境感知 (Pillar 2) + 递归式规则发现 (Pillar 13)。

    启动时自动:
    1. 执行 git status 注入项目状态快照
    2. 向上递归扫描 AGENTS.md / SOUL.md 实现规则继承
    3. 识别项目类型 (Python/Rust/JS...)
    """
    working_dir: Path
    _git: GitCheckpoint
    _system_snippets: list[str]

    def __init__(self, working_dir: str | Path, git: GitCheckpoint):
        self.working_dir = Path(working_dir)
        self._git = git
        self._system_snippets = []

    def discover(self) -> dict[str, Any]:
        """
        执行一次完整的环境发现, 返回结构化上下文。

        用于注入 System Prompt。
        """
        return {
            "git_status": self._git.get_status(),
            "git_hash": self._git.get_current_hash(),
            "project_type": self._detect_project_type(),
            "instruction_files": self._discover_instruction_files(),
            "magic_docs": self._discover_docs(),
            "bootstrapping": self._discover_bootstrapping_info(),
        }

    def inject_system_snippet(self, snippet: str) -> None:
        """注入临时的系统上下文片段 (Pillar 26)。"""
        self._system_snippets.append(snippet)

    def build_system_context(self) -> str:
        """
        [Hermes Pattern] 构建模块化 XML 系统上下文 (Pillar 3: Prompt Pooling)。
        
        采用“核心稳定头 (Stable Headers)”结构:
        1. 环境自举 (Static/Slow-changing) -> 最上方, 增加 Cache 命中率
        2. 指令集 (Modular & Hierarchical) -> 中间
        3. 项目状态与 Git (Dynamic) -> 下方
        4. 被动知识/Docs (Dynamic) -> 最下方
        """
        ctx = self.discover()
        
        # 1. 环境自举 (Stable/Static Head)
        env_parts: list[str] = []
        if ctx["bootstrapping"]:
            bs = cast("dict[str, Any]", ctx["bootstrapping"])
            env_parts.append(f"<os>{bs.get('os', 'unknown')}</os>")
            env_parts.append(f"<available_tools>{bs.get('available_tools', 'unknown')}</available_tools>")
            env_parts.append(f"<directory_snapshot>{bs.get('dir_snapshot', 'unknown')}</directory_snapshot>")
            env_parts.append(f"<cwd>{bs.get('cwd', 'unknown')}</cwd>")

        # 2. 指令集 (Hierarchical Rules)
        instr_parts = []
        for instr in ctx["instruction_files"]:
            try:
                rel_path = Path(instr["name"]).relative_to(self.working_dir)
            except ValueError:
                rel_path = Path(instr["name"]).name
            
            instr_parts.append(
                f"<instruction_file path=\"{rel_path}\" depth=\"{instr['depth']}\">\n"
                f"{instr['content']}\n"
                f"</instruction_file>"
            )

        # 3. 项目核心元数据 (Slightly Dynamic)
        project_parts = []
        project_parts.append(f"<project_type>{ctx['project_type']}</project_type>")
        project_parts.append(f"<git_hash>{ctx['git_hash']}</git_hash>")
        project_parts.append(f"<git_status>\n{ctx['git_status']}\n</git_status>")
        
        # 4. 知识图谱/MagicDocs (Dynamic)
        docs_parts = []
        if ctx["magic_docs"]:
            for doc in ctx["magic_docs"][:5]:
                docs_parts.append(
                    f"<doc path=\"{doc['path']}\" type=\"{doc['type']}\">\n"
                    f"{doc['summary']}\n"
                    f"</doc>"
                )

        # 5. [NEW] Triple-Perspective QA Protocol (Completion Gate)
        qa_protocol = [
            "<qa_protocol>",
            "  <perspective name=\"technical_accuracy\">验证逻辑真实性，严禁幻觉代码。</perspective>",
            "  <perspective name=\"intent_alignment\">验证是否完全解决了用户核心诉求。</perspective>",
            "  <perspective name=\"edge_robustness\">验证异常处理与边缘状态稳定性。</perspective>",
            "</qa_protocol>"
        ]

        # 组合最终 XML (确保顺序以优化 Caching)
        context_xml = [
            "<system_bootstrap>",
            "\n".join(env_parts),
            "</system_bootstrap>",
            "<instruction_registry>",
            "\n".join(instr_parts),
            "</instruction_registry>",
            "<project_state>",
            "\n".join(project_parts),
            "</project_state>",
            "<knowledge_recall>",
            "\n".join(docs_parts),
            "</knowledge_recall>",
            "\n".join(qa_protocol)
        ]
        
        # 注入临时片段
        if self._system_snippets:
            context_xml.append("<dynamic_context_injection>")
            context_xml.extend(self._system_snippets)
            context_xml.append("</dynamic_context_injection>")
            self._system_snippets = [] 
        
        full_context = "\n\n".join(context_xml)
        cache_hash = hashlib.md5(full_context.encode()).hexdigest()[:8]
        
        return f"<meta_hermes_context hash=\"{cache_hash}\" version=\"5.1\">\n{full_context}\n</meta_hermes_context>"

    def get_cache_hash(self) -> str:
        """快速获取当前上下文的哈希值, 用于判断是否需要刷新缓存。"""
        # 仅对 key 维度进行哈希
        key_data = f"{self.working_dir}:{self._git.get_current_hash()}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _discover_instruction_files(self) -> list[dict[str, Any]]:
        """
        递归向上扫描指令文件 (AGENTS.md, SOUL.md, CLAUDE.md)。

        从当前工作目录开始, 向上遍历直到根目录,
        收集所有层级的指令文件, 实现规则继承。
        """
        instruction_names = {"AGENTS.md", "SOUL.md", "CLAUDE.md", ".claude", "GEMINI.md"}
        found: list[dict[str, Any]] = []
        current = self.working_dir.resolve()

        for _depth in range(MAX_INSTRUCTION_DEPTH):
            for name in instruction_names:
                candidate = current / name
                if candidate.is_file():
                    try:
                        content = candidate.read_text(encoding="utf-8", errors="replace")
                        found.append({
                            "name": str(candidate),
                            "content": content[:INSTRUCTION_CHAR_LIMIT],
                            "depth": _depth,
                        })
                    except Exception as e:
                        logger.debug(f"Skipping unreadable instruction file {candidate}: {e}")

            parent = current.parent
            if parent == current:
                break  # 到达根目录
            current = parent

        return found

    def _detect_project_type(self) -> str:
        """检测项目类型 (用于优化 Agent 行为)。"""
        markers = {
            "pyproject.toml": "python",
            "requirements.txt": "python",
            "setup.py": "python",
            "package.json": "javascript",
            "Cargo.toml": "rust",
            "go.mod": "go",
            "pom.xml": "java",
            "build.gradle": "java",
            "Gemfile": "ruby",
        }
        for marker, ptype in markers.items():
            if (self.working_dir / marker).exists():
                return ptype
        return "unknown"

    def _discover_bootstrapping_info(self) -> dict[str, str]:
        """
        环境自举发现 (Bootstrapping): 收集系统基础信息, 减少 LLM 早期探索回合。
        """
        info = {
            "os": platform.system() + " " + platform.release(),
            "cwd": str(self.working_dir),
            "user": os.getlogin() if hasattr(os, "getlogin") else "unknown",
        }
        
        # 2. 增强型工具链探测 (Bootstrapping V5.0)
        tools_specs = []
        check_tools = [
            "python3", "python", "pip3", "pip", 
            "node", "npm", "npx", "yarn", "pnpm",
            "gcc", "g++", "make", "cmake",
            "rustc", "cargo", "go", "java", "javac",
            "git", "surreal", "docker", "kubectl"
        ]
        for t in check_tools:
            if shutil.which(t):
                tools_specs.append(t)
            
        info["available_tools"] = ", ".join(tools_specs)

        # 3. 目录快照 (消除开局 ls)
        try:
            # 优先显示重要文件类型
            items = os.listdir(self.working_dir)
            visible_items = [i for i in items if not i.startswith(".")]
            
            # 排序: 文件夹在前，然后是重要配置文件，最后是普通文件
            dirs = [i for i in visible_items if (self.working_dir / i).is_dir()]
            configs = [i for i in visible_items if i.endswith(('.toml', '.json', '.yaml', '.yml', '.md', '.txt', '.py', '.js', '.ts', '.rs', '.go'))]
            others = [i for i in visible_items if i not in dirs and i not in configs]
            
            sorted_items = dirs[:10] + configs[:15] + others[:5]
            
            if len(visible_items) > len(sorted_items):
                snap = ", ".join(sorted_items) + f" ... ({len(visible_items) - len(sorted_items)} more items)"
            else:
                snap = ", ".join(sorted_items)
            info["dir_snapshot"] = snap
        except Exception:
            info["dir_snapshot"] = "error reading directory"
        
        return info

    def _discover_docs(self) -> list[dict[str, Any]]:
        """
        MagicDocs (Pillar 15): 自动嗅探项目中的文档文件。

        扫描 README, API docs, 代码注释等, 构建可被实时检索的知识快照。
        """
        doc_patterns = [
            "README.md", "README.rst", "CONTRIBUTING.md",
            "docs/*.md", "doc/*.md", "API.md", "CHANGELOG.md",
        ]
        found: list[dict[str, Any]] = []

        for pattern in doc_patterns:
            for path in self.working_dir.glob(pattern):
                if path.is_file():
                    try:
                        content = path.read_text(encoding="utf-8", errors="replace")
                        # 提取前 500 字作为摘要
                        summary = content[:500].strip()
                        found.append({
                            "path": str(path.relative_to(self.working_dir)),
                            "type": "markdown",
                            "summary": summary,
                        })
                    except Exception as e:
                        logger.debug(f"Skipping unreadable documentation file {path}: {e}")

        logger.info(f"MagicDocs: found {len(found)} documentation files")
        return found
