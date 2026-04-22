"""
Coda V4.0 — CLI Entry Point (致命级 #3)
命令行入口: 真正启动 Agent 引擎的驾驶舱。

用法:
  python -m engine.cli "帮我重构 main.py"
  python -m engine.cli --model claude-sonnet-4 "修复这个 bug"
  python -m engine.cli --resume session_abc123.json
  python -m engine.cli --interactive
  python -m engine.cli --danger-full-access "全自动重构后端"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_engine import AgentEngine

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Coda.cli")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Coda",
        description="🚀 Coda V4.0 — 全自主、自进化、分布式 Agent 引擎",
    )
    parser.add_argument(
        "message",
        nargs="?",
        default="",
        help="要发送给 Agent 的消息/任务",
    )
    parser.add_argument(
        "--model", "-m",
        default="gemini-2.5-pro",
        help="LLM 模型名称 (gemini-2.5-pro / claude-sonnet-4 / gpt-4o)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API Key (也可通过环境变量设置)",
    )
    parser.add_argument(
        "--working-dir", "-d",
        default=".",
        help="工作目录 (默认当前目录)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=200,
        help="最大自主循环次数 (默认 200)",
    )
    parser.add_argument(
        "--cost-limit",
        type=float,
        default=5.0,
        help="成本熔断线 (USD, 默认 $5.00)",
    )
    parser.add_argument(
        "--danger-full-access",
        action="store_true",
        help="⚠️ 危险模式: 跳过所有安全确认, 全自动执行",
    )
    parser.add_argument(
        "--resume",
        default=None,
        help="从指定的 session 文件恢复",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="交互模式: 持续对话直到输入 /exit",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="禁用 Git 自动快照",
    )
    parser.add_argument(
        "--beta",
        nargs="*",
        default=[],
        help="启用灰度特性 (如 --beta auto_skillify speculative_preload)",
    )
    return parser


async def run_single(engine: AgentEngine, message: str) -> None:
    """单次执行模式。"""
    print(f"\n🤖 Processing: {message[:80]}...")
    print("─" * 60)

    result = await engine.run(message)

    print("─" * 60)
    print(f"\n{result}")
    print("─" * 60)

    # 显示 Buddy 状态
    print(f"\n{engine.buddy.get_status_display()}")
    
    # 触发休眠期自进化 (V7)
    await engine.shutdown()


async def run_interactive(engine: AgentEngine) -> None:
    """交互模式: 持续对话。"""
    print("\n" + "═" * 60)
    print("🚀 Coda V4.0 — Interactive Mode")
    print(f"   Model: {engine.store.state.model_name}")
    print(f"   Dir:   {engine.working_dir}")
    print(f"   Type /help for commands, /exit to quit")
    print("═" * 60)

    while True:
        try:
            user_input = input("\n👤 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit", "/q"):
            print("👋 Session ended.")
            await engine.shutdown()
            break

        # Slash 命令拦截
        if engine.router.is_command(user_input):
            result = engine.router.route(user_input, engine=engine)
            if result is not None:
                print(f"\n{result}")
                continue

        # 正常对话
        print(f"\n🤖 Thinking...")
        result = await engine.run(user_input)
        print(f"\n🤖 Agent:\n{result}")

        # Buddy 状态
        alerts = engine.buddy.check_health()
        if alerts:
            print()
            for a in alerts:
                print(f"  {a}")


async def main():
    parser = create_parser()
    args = parser.parse_args()

    # 延迟导入以加速 --help
    from .agent_engine import AgentEngine

    working_dir = Path(args.working_dir).resolve()

    engine = AgentEngine(
        working_dir=working_dir,
        model_name=args.model,
        api_key=args.api_key,
        max_iterations=args.max_iterations,
        cost_limit=args.cost_limit,
        danger_full_access=args.danger_full_access,
    )

    # Git 开关
    if args.no_git:
        engine.store.update("git_auto_commit", False)

    # 灰度特性
    for flag in args.beta:
        engine.set_beta_flag(flag, True)

    # 恢复会话
    if args.resume:
        if engine.resume(args.resume):
            logger.info(f"Resumed from {args.resume}")
        else:
            logger.warning(f"Failed to resume from {args.resume}")

    # 执行模式
    if args.interactive or not args.message:
        await run_interactive(engine)
    else:
        await run_single(engine, args.message)


def entry():
    """同步入口点 (供 setup.py console_scripts 使用)。"""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
