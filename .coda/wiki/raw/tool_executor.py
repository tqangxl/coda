"""
Coda V4.0 — Tool Executor (致命级 #3 / Pillar 5)
工具执行引擎: 封装本地命令、文件读写、MCP 扩展与多模态分析。
"""

from __future__ import annotations

import asyncio
import os
import time
import base64
import logging
from collections.abc import Sequence, Mapping, Callable, Coroutine
from pathlib import Path
from typing import cast, TYPE_CHECKING, Any

from .commands import XMLProtocol, SecuritySandbox, MCPRegistry

logger = logging.getLogger("Coda.tools")


class ToolExecutor:
    """
    统一工具执行器 (Pillar 5)。
    
    负责调度 run_command, write_file 等核心原子工具, 
    并集成了 Security Sandbox (Pillar 7) 与 Smart Polling (Hermes)。
    """

    _xml: XMLProtocol
    _sandbox: SecuritySandbox
    _mcp: MCPRegistry
    _file_locks: dict[Path, asyncio.Lock]

    def __init__(self, working_dir: str = ".") -> None:
        self.working_dir = Path(working_dir).absolute()
        self._marker_seq = 0
        self._xml = XMLProtocol()
        self._sandbox = SecuritySandbox()
        self._mcp = MCPRegistry()
        self._file_locks = {}
        
        self.dispatch: dict[str, Callable[[dict[str, object]], Coroutine[Any, Any, str]]] = {
            "run_command": self._run_command,
            "execute_commands": self._run_command,
            "write_file": self._write_file,
            "replace_file_content": self._write_file,
            "read_file": self._read_file,
            "view_file": self._read_file,
            "edit_file": self._edit_file,
            "multi_replace_file_content": self._edit_file,
            "multi_edit_file": self._edit_file,
            "replace_file": self._edit_file,
            "list_dir": self._list_dir,
            "grep_search": self._grep_search,
            "search": self._grep_search,
            "ask_user": self._ask_user,
            "input": self._ask_user,
            "image_read": self._image_read,
        }

    async def execute(self, tool_name: str, args: dict[str, object]) -> str:
        """执行指定工具。"""
        handler = self.dispatch.get(tool_name)
        if not handler:
            return f"ERROR: Unknown tool '{tool_name}'. Available: {', '.join(self.dispatch.keys())}"
        
        try:
            return await handler(args)
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name} with {args} -> {e}")
            return f"ERROR: Exception executing {tool_name}: {e}"

    async def _image_read(self, args: dict[str, object]) -> str:
        path_str = cast(str | None, args.get("path") or args.get("AbsolutePath"))
        instruction = cast(str, args.get("instruction") or args.get("Prompt", "分析该图像"))
        if not path_str:
            return "ERROR: No image path specified"

        path = Path(path_str)
        if not path.is_absolute():
            path = self.working_dir / path

        if not path.exists():
            return f"ERROR: Image file not found: {path}"

        try:
            with open(path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
            ext = path.suffix.lower()
            mime_map = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp",
            }
            mime_type = mime_map.get(ext, "image/png")
            return f"__MULTIMODAL_IMAGE__{b64_data}__{mime_type}__{instruction}__"
        except Exception as e:
            return f"ERROR reading image '{path}': {e}"

    async def _run_command(self, args: dict[str, object]) -> str:
        cmd = cast(str, args.get("command") or args.get("CommandLine") or args.get("cmd", ""))
        cwd = cast(str, args.get("cwd") or args.get("Cwd") or str(self.working_dir))
        timeout = int(cast(int, args.get("timeout", 60)))
        duration_sec = float(cast(float, args.get("duration", 1.0)))

        if not cmd:
            return "ERROR: No command specified"

        start_time = time.monotonic()
        
        if self._sandbox.is_dangerous(cmd):
            logger.warning(f"🛡️ Security Sandbox: Dangerous command detected: {cmd}")
            cmd = self._sandbox.wrap_command(cmd)
            logger.info(f"🛡️ Command wrapped for security: {cmd}")

        try:
            self._marker_seq += 1
            marker = f"__Coda_CMD_END_{self._marker_seq}__"
            if os.name == "nt":
                full_cmd = f"{cmd} && echo {marker}"
            else:
                full_cmd = f"{cmd} ; echo {marker}"
            
            process = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env={**os.environ, "PAGER": "cat", "TERM": "xterm-256color"},
            )
            
            output_buffer: list[str] = []
            stderr_buffer: list[str] = []
            
            async def _poll_stream(stream: asyncio.StreamReader | None, buffer: list[str], is_stdout: bool = True) -> None:
                nonlocal marker
                if not stream: return
                while True:
                    try:
                        line_raw = await asyncio.wait_for(stream.readline(), timeout=0.05)
                        if not line_raw: break
                        line = line_raw.decode("utf-8", errors="replace")
                        
                        if is_stdout and marker.strip() in line.strip():
                            break
                        
                        buffer.append(line)
                        if sum(len(l) for l in buffer) > 2_000_000:
                            buffer.append("\n[BUFFER LIMIT: TRUNCATED]\n")
                            break
                    except asyncio.TimeoutError:
                        if process.returncode is not None: break
                await asyncio.sleep(0.01)

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _poll_stream(process.stdout, output_buffer, True),
                        _poll_stream(process.stderr, stderr_buffer, False)
                    ),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    await process.wait()
                except Exception as e:
                    logger.debug(f"Failed to terminate timed-out process: {e}")
                output_buffer.append(f"\n\n[TIMEOUT: Command exceeded {timeout}s limit]")
            
            actual_duration = time.monotonic() - start_time
            
            final_stdout = "".join(output_buffer).strip()
            # Clean up marker if it somehow stayed in buffer
            if marker in final_stdout:
                final_stdout = final_stdout.split(marker)[0].strip()

            final_stderr = "".join(stderr_buffer).strip()
            
            MAX_OUT = 20000
            if len(final_stdout) > MAX_OUT:
                half = MAX_OUT // 2
                final_stdout = final_stdout[:half] + f"\n\n... [TRUNCATED] ...\n\n" + final_stdout[-half:]

            result = final_stdout
            if final_stderr:
                result += f"\n[STDERR]\n{final_stderr}"
            if process.returncode != 0 and process.returncode is not None:
                result += f"\n[EXIT CODE: {process.returncode}]"

            logger.debug(f"Command finished in {actual_duration:.2f}s (target: {duration_sec}s)")
            return result.strip() or "(no output)"
        except Exception as e:
            return f"ERROR executing command: {e}"


    async def _get_file_lock(self, path: Path) -> asyncio.Lock:
        """获取指定路径的异步排他锁 (FileLockManager)。"""
        abs_path = path.absolute()
        if abs_path not in self._file_locks:
            self._file_locks[abs_path] = asyncio.Lock()
        return self._file_locks[abs_path]

    async def _write_file(self, args: dict[str, object]) -> str:
        filepath = cast(str, args.get("path") or args.get("TargetFile") or args.get("file", ""))
        content = cast(str, args.get("content") or args.get("CodeContent") or "")
        overwrite = bool(args.get("overwrite", args.get("Overwrite", False)))
        if not filepath: return "ERROR: No file path specified"
        path = Path(filepath)
        if not path.is_absolute(): path = self.working_dir / path
        
        async with await self._get_file_lock(path):
            if path.exists() and not overwrite:
                return f"ERROR: File {path} already exists."
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Created {path} ({len(content)} chars)"

    async def _read_file(self, args: dict[str, object]) -> str:
        filepath = cast(str, args.get("path") or args.get("AbsolutePath") or args.get("file", ""))
        if not filepath: return "ERROR: No path"
        path = Path(filepath)
        if not path.is_absolute(): path = self.working_dir / path
        if not path.exists(): return f"ERROR: File {path} not found"
        
        # 读取不加排他锁，允许并发读
        content = path.read_text(encoding="utf-8", errors="replace")
        MAX_READ = 30000
        if len(content) > MAX_READ:
            half = MAX_READ // 2
            return content[:half] + f"\n\n... [TRUNCATED] ...\n\n" + content[-half:]
        return content

    async def _edit_file(self, args: dict[str, object]) -> str:
        filepath = cast(str, args.get("path") or args.get("TargetFile") or args.get("file", ""))
        if not filepath: return "ERROR: No file path specified"
        path = Path(filepath)
        if not path.is_absolute(): path = self.working_dir / path
        if not path.exists(): return f"ERROR: File {path} not found"

        async with await self._get_file_lock(path):
            content = path.read_text(encoding="utf-8")
            
            chunks = args.get("ReplacementChunks")
            if chunks and isinstance(chunks, list):
                new_content = content
                for chunk_obj in chunks:
                    chunk = cast(dict[str, object], chunk_obj)
                    target = cast(str, chunk.get("TargetContent"))
                    replacement = cast(str, chunk.get("ReplacementContent"))
                    if target and replacement:
                        if target not in new_content:
                            return f"ERROR: Target content not found in {path}"
                        limit = 1 if not chunk.get("AllowMultiple") else -1
                        new_content = new_content.replace(target, replacement, limit)
                path.write_text(new_content, encoding="utf-8")
                return f"Multi-edit completed on {path} with {len(chunks)} chunks"

            target = cast(str, args.get("target") or args.get("TargetContent"))
            replacement = cast(str, args.get("replacement") or args.get("ReplacementContent"))
            if target is None or replacement is None:
                return "ERROR: Both 'target' and 'replacement' must be specified"
            
            if target not in content:
                return f"ERROR: Exact target match not found in {path}"
                
            new_content = content.replace(target, replacement)
            path.write_text(new_content, encoding="utf-8")
            return f"Successfully edited {path}"

    async def _list_dir(self, args: dict[str, object]) -> str:
        path_str = cast(str, args.get("path") or args.get("DirectoryPath") or ".")
        path = Path(path_str)
        if not path.is_absolute(): path = self.working_dir / path
        if not path.exists(): return f"ERROR: Dir {path} not found"
        items = os.listdir(path)
        return "\n".join(items)

    async def _grep_search(self, args: dict[str, object]) -> str:
        query = cast(str, args.get("query") or args.get("Query", ""))
        path_str = cast(str, args.get("path") or args.get("SearchPath") or ".")
        includes = cast(list[str], args.get("includes") or args.get("Includes", []))
        
        if not query: return "ERROR: No search query"
        
        search_path = Path(path_str)
        if not search_path.is_absolute(): search_path = self.working_dir / search_path
        
        matches: list[str] = []
        try:
            for root, _, files in os.walk(search_path):
                for file in files:
                    if includes and not any(file.endswith(inc.replace("*", "")) for inc in includes):
                        continue
                    f_path = Path(root) / file
                    try:
                        f_content = f_path.read_text(encoding="utf-8", errors="ignore")
                        if query in f_content:
                            lines = f_content.splitlines()
                            for i, line in enumerate(lines):
                                if query in line:
                                    matches.append(f"{f_path.relative_to(self.working_dir)}:{i+1}: {line.strip()}")
                                    if len(matches) > 100: break
                    except Exception: continue
                    if len(matches) > 100: break
                if len(matches) > 100: break
                
            return "\n".join(matches) if matches else "No matches found"
        except Exception as e:
            return f"ERROR during search: {e}"

    def get_schemas(self) -> list[dict[str, object]]:
        """获取所有可用工具的 Schema 文档 (Pillar 8)。"""
        from .tool_schemas import get_generic_tool_schemas
        return cast(list[dict[str, object]], get_generic_tool_schemas())

    async def _ask_user(self, args: dict[str, object]) -> str:
        question = cast(str, args.get("question") or args.get("Prompt") or "Waiting for user input...")
        print(f"\n[INTERACTION REQUIRED]: {question}")
        try:
            logger.info(f"Engine waiting for user: {question}")
            import sys
            if sys.stdin.isatty():
                user_input = input(">> ")
                return user_input
            else:
                return f"ERROR: Non-interactive environment. Cannot ask user: {question}"
        except Exception as e:
            return f"ERROR during interaction: {e}"
