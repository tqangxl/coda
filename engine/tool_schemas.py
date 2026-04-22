"""
Coda V4.0 — Tool Schema Definitions (致命级 #1)
工具声明: 让 LLM 知道自己有哪些武器可以使用。

没有这些声明, LLM 永远不会生成 function_call, 自主循环等于空转。
"""

from __future__ import annotations
from typing import Any, cast


def get_gemini_tools() -> list[Any]:
    """返回 Gemini 格式的工具声明列表。"""
    try:
        from google.genai import types
        return [types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="run_command",
                description="在工作目录中执行 Shell 命令。用于运行测试、安装依赖、查看 Git 状态等。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "analysis": types.Schema(type=types.Type.STRING, description="对当前状态的深度分析。你看到了什么？已完成了什么？还需要做什么？"),
                        "plan": types.Schema(type=types.Type.STRING, description="接下来的具体计划。你要运行哪些命令，为什么？你期望每个命令达成什么目标？"),
                        "command": types.Schema(type=types.Type.STRING, description="要执行的 Shell 命令"),
                        "cwd": types.Schema(type=types.Type.STRING, description="工作目录 (可选)"),
                        "timeout": types.Schema(type=types.Type.INTEGER, description="超时秒数 (默认 30)"),
                    },
                    required=["analysis", "plan", "command"],
                ),
            ),
            types.FunctionDeclaration(
                name="execute_commands",
                description="[高级结构化工具] 执行一系列命令并附带深度分析。优选此工具以确保思维链完整性。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "analysis": types.Schema(type=types.Type.STRING, description="深度分析"),
                        "plan": types.Schema(type=types.Type.STRING, description="详细计划"),
                        "commands": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "command": types.Schema(type=types.Type.STRING, description="Shell 命令"),
                                    "duration": types.Schema(type=types.Type.NUMBER, description="预期执行时间 (秒)"),
                                },
                                required=["command"],
                            ),
                            description="按顺序执行的一组命令",
                        ),
                    },
                    required=["analysis", "plan", "commands"],
                ),
            ),
            types.FunctionDeclaration(
                name="read_file",
                description="读取文件内容。可指定行范围。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "path": types.Schema(type=types.Type.STRING, description="文件的绝对路径"),
                        "start_line": types.Schema(type=types.Type.INTEGER, description="起始行号 (1-indexed)"),
                        "end_line": types.Schema(type=types.Type.INTEGER, description="结束行号"),
                    },
                    required=["path"],
                ),
            ),
            types.FunctionDeclaration(
                name="write_to_file",
                description="创建或写入文件。如果文件已存在且 overwrite=false 则报错。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "path": types.Schema(type=types.Type.STRING, description="文件路径"),
                        "content": types.Schema(type=types.Type.STRING, description="文件内容"),
                        "overwrite": types.Schema(type=types.Type.BOOLEAN, description="是否覆盖已存在的文件"),
                    },
                    required=["path", "content"],
                ),
            ),
            types.FunctionDeclaration(
                name="edit_file",
                description="编辑文件: 查找并替换指定内容。target 必须精确匹配文件中的文本。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "path": types.Schema(type=types.Type.STRING, description="文件路径"),
                        "target": types.Schema(type=types.Type.STRING, description="要替换的精确内容"),
                        "replacement": types.Schema(type=types.Type.STRING, description="替换后的内容"),
                    },
                    required=["path", "target", "replacement"],
                ),
            ),
            types.FunctionDeclaration(
                name="list_dir",
                description="列出目录中的所有文件和子目录。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "path": types.Schema(type=types.Type.STRING, description="目录路径"),
                    },
                    required=["path"],
                ),
            ),
            types.FunctionDeclaration(
                name="grep_search",
                description="在文件中搜索文本模式。返回匹配行。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "query": types.Schema(type=types.Type.STRING, description="搜索关键词"),
                        "path": types.Schema(type=types.Type.STRING, description="搜索路径"),
                        "includes": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.STRING),
                            description="文件过滤 (如 *.py)",
                        ),
                    },
                    required=["query", "path"],
                ),
            ),
            types.FunctionDeclaration(
                name="ask_user",
                description="向用户提问。当你不确定应该怎么做时, 用这个工具暂停并请求人类指示。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "question": types.Schema(type=types.Type.STRING, description="要问用户的问题"),
                    },
                    required=["question"],
                ),
            ),
            types.FunctionDeclaration(
                name="image_read",
                description="读取并分析图像文件。仅对需要视觉分析的图像文件使用。不要用于普通文本文件。",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "path": types.Schema(type=types.Type.STRING, description="图像文件的绝对路径。支持格式: PNG, JPG, JPEG, GIF, WEBP。"),
                        "instruction": types.Schema(type=types.Type.STRING, description="详细描述你希望从图像中分析出的信息 (例如: '描述 UI 布局', '提取图表数据', '识别异常日志')。"),
                    },
                    required=["path", "instruction"],
                ),
            ),
        ])]
    except ImportError:
        import logging
        logging.getLogger("Coda.schemas").error("google.genai is not installed. Gemini tools are unavailable.")
        return []


def get_generic_tool_schemas() -> list[dict[str, Any]]:
    """返回通用 JSON 格式的工具 Schema (用于 Claude / OpenAI)。"""
    from typing import Any
    return [
        {
            "name": "run_command",
            "description": "执行单个 Shell 命令并附加结构化分析。优选执行此命令以确保逻辑闭环。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "analysis": {"type": "string", "description": "对当前状态的深度分析。你看到了什么？已完成了什么？还需要做什么？"},
                    "plan": {"type": "string", "description": "接下来的具体计划。你要运行哪些命令，为什么？你期望每个命令达成什么目标？"},
                    "command": {"type": "string", "description": "要执行的命令"},
                    "cwd": {"type": "string", "description": "工作目录 (可选)"},
                    "timeout": {"type": "integer", "description": "超时秒数 (默认 30)"},
                },
                "required": ["analysis", "plan", "command"],
            },
        },
        {
            "name": "execute_commands",
            "description": "[高级结构化工具] 执行一系列命令并附带深度分析。优选此工具以确保思维链完整性。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "analysis": {"type": "string", "description": "深度分析"},
                    "plan": {"type": "string", "description": "详细计划"},
                    "commands": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Shell 命令"},
                                "duration": {"type": "number", "description": "预期执行时间 (秒)"},
                            },
                            "required": ["command"],
                        },
                    },
                },
                "required": ["analysis", "plan", "commands"],
            },
        },
        {
            "name": "read_file",
            "description": "读取文件内容。可指定行范围。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "start_line": {"type": "integer", "description": "起始行"},
                    "end_line": {"type": "integer", "description": "结束行"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_to_file",
            "description": "创建或写入文件。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "内容"},
                    "overwrite": {"type": "boolean", "description": "是否覆盖"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "edit_file",
            "description": "编辑文件: 精确查找并替换内容。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "target": {"type": "string", "description": "要替换的内容"},
                    "replacement": {"type": "string", "description": "替换后的内容"},
                },
                "required": ["path", "target", "replacement"],
            },
        },
        {
            "name": "list_dir",
            "description": "列出目录内容。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "grep_search",
            "description": "搜索文件内容。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索词"},
                    "path": {"type": "string", "description": "搜索路径"},
                },
                "required": ["query", "path"],
            },
        },
        {
            "name": "ask_user",
            "description": "向用户提问, 请求人类确认或输入。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "问题内容"},
                },
                "required": ["question"],
            },
        },
        {
            "name": "image_read",
            "description": "读取并分析图像文件。仅对需要视觉分析的图像文件使用。不要用于普通文本文件。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "图像文件的绝对路径。"},
                    "instruction": {"type": "string", "description": "详细描述你希望从图像中分析出的信息 (例如: '描述 UI 布局', '提取图表数据', '识别异常日志')。"},
                },
                "required": ["path", "instruction"],
            },
        },
    ]


def get_openai_tool_schemas() -> list[dict[str, Any]]:
    """返回 OpenAI 格式的工具声明。"""
    from typing import Any
    generic = get_generic_tool_schemas()
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in generic
    ]
