import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env", override=True)
except ImportError:
    pass  # python-dotenv 未安装时跳过，直接使用系统环境变量

from engine.plugins.wiki.engine import WikiEngine, WikiEngineConfig


def _resolve_scan_paths() -> tuple[Path, list[Path]]:
    """
    解析 WIKI_SCAN_PATHS 环境变量，返回 (primary_dir, extra_dirs)。

    WIKI_SCAN_PATHS 格式: 英文分号分隔的绝对路径
    示例: D:\\ai\\workspace\\agents;D:\\notes;C:\\projects\\docs

    - 第一个路径作为 wiki_dir (主目录，Atlas DB 存放位置)
    - 其余路径作为 extra_scan_paths
    - 若变量未设置，默认使用 agents/ 目录
    """
    raw = os.getenv("WIKI_SCAN_PATHS", "").strip()
    paths: list[Path] = []

    if raw:
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            p = Path(part)
            if p.exists() and p.is_dir():
                paths.append(p.resolve())
            else:
                print(f"  ⚠️  WIKI_SCAN_PATHS: 路径不存在或非目录，已跳过: {p}")

    if not paths:
        # 默认: agents/ 目录
        default = project_root / "agents"
        if default.exists():
            paths.append(default.resolve())
        else:
            print(f"  ❌  默认目录不存在: {default}")

    if not paths:
        raise RuntimeError("没有有效的扫描路径，请检查 WIKI_SCAN_PATHS 配置")

    primary = paths[0]
    extras = paths[1:]
    return primary, extras


async def seed_wiki() -> None:
    print("🚀 Starting Wiki Seeding Process...")

    
    # 我们扫描 agents/ 目录，那里存放了 Agent 的核心资产与角色定义 (L2/L3)
    primary_dir, extra_dirs = _resolve_scan_paths()

    all_dirs = [primary_dir] + extra_dirs
    print(f"📂 Will index {len(all_dirs)} director{'y' if len(all_dirs) == 1 else 'ies'}:")
    for i, d in enumerate(all_dirs):
        tag = "(primary)" if i == 0 else f"(extra {i})"
        print(f"   {tag}  {d}")

    # project_id 会自动根据目录推断，或者我们可以显式指定
    # 核心资产通常设为 L2 (团队层)
    cfg = WikiEngineConfig(
        wiki_dir=primary_dir,
        project_id="Coda_core",  # 设置主项目 ID
        layer=2, # 核心资产通常设为 L2 (团队层)
        extra_scan_paths=[str(p) for p in extra_dirs],   # 额外路径传入 config
    )

    engine = WikiEngine(cfg)
    
    # 初始化引擎 (连接 DB + 插件加载)
    # 注意: WikiEngine.initialize 现在依赖于具体的实现，我们直接手动拉起 compiler
    await engine.initialize()

    print("🧠 Connected to SurrealDB. Starting compilation...")

    # 执行全量/增量编译
    # 这会将 wiki_root 及其子目录下的 .md 文件解析并 UPSERT 到 SurrealDB 的 wiki_nodes 表中
    try:
        
        #ine.compile(full=True) 统一入口
        # 这会触发完整的影子镜像 -> PII -> 编译 -> 链接 -> 联邦同步流程
        #res = await engine.compile(full=True)
        
        # 使用 engine.compile(full=False) 进行增量编译
        # 只有被修改的文件才会被重新处理，大幅节省启动时间和资源
        res = await engine.compile(full=False)
        print(f"✅ Compilation finished!")
        print(
            f"📊 Stats: "
            f"Processed={res.files_processed}, "
            f"Nodes Created/Updated={res.nodes_indexed}, "
            f"Nodes Deleted={res.nodes_deleted}, "
            f"Relations={res.relations_extracted}, "
            f"Errors={res.errors}"
        )
    except Exception as e:
        print(f"❌ Compilation failed: {e}")
    finally:
        if engine.session:
            engine.session.on_session_end(["Seeding completed"])


if __name__ == "__main__":
    asyncio.run(seed_wiki())
