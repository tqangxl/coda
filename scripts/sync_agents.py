# pyright: basic
import os
import re
import asyncio
from typing import Any
from surrealdb import AsyncSurreal
from datetime import datetime
from dotenv import load_dotenv

# =============================================
# 配置
# =============================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_HOME = os.path.expanduser("~")
ENV_FILE = os.path.join(USER_HOME, ".ai-agents", ".env")

if os.path.exists(ENV_FILE):
    _ = load_dotenv(ENV_FILE)

SURREAL_URL = os.getenv("SURREALDB_URL", "ws://localhost:11001/rpc")
SURREAL_USER = os.getenv("SURREALDB_USER", "root")
SURREAL_PASS = os.getenv("SURREALDB_PASS", "AgentSecurePass2026")
SURREAL_NS = os.getenv("SURREALDB_NAMESPACE", "ai_agents_v2")
SURREAL_DB = os.getenv("SURREALDB_DATABASE", "agent_system")

async def sync_souls():
    print(f"[*] 正在连接到 SurrealDB: {SURREAL_URL}...")
    db = AsyncSurreal(SURREAL_URL)
    try:
        await db.connect(SURREAL_URL)
        _ = await db.signin({"user": SURREAL_USER, "pass": SURREAL_PASS})
        _ = await db.use(SURREAL_NS, SURREAL_DB)
        
        print("[*] 开始扫描工作区中的 SOUL.md 文件...")
        souls = find_soul_files(PROJECT_ROOT)
        print(f"[*] 发现 {len(souls)} 个 Agent 灵魂文件")
        
        for soul_path in souls:
            try:
                agent_data = parse_soul_file(soul_path)
                if agent_data:
                    # 使用路径生成 ID (相对路径，去扩展名，替换分隔符)
                    rel_path = os.path.relpath(soul_path, PROJECT_ROOT)
                    raw_id = rel_path.replace(os.sep, '_').replace('.md', '').lower()
                    # 去掉路径中的 ._ 等特殊字符
                    clean_id = re.sub(r'[^a-z0-9_]', '_', raw_id)
                    agent_id = f"{clean_id}"
                    
                    # 准备数据以符合 SCHEMAFULL 定义
                    agent_metadata = dict(agent_data.get("metadata", {}))  # type: ignore
                    agent_metadata["source_file"] = rel_path
                    
                    now = datetime.now()
                    agent_metadata["last_synced"] = now.isoformat()

                    final_data = {
                        "name": agent_data["name"],
                        "type": agent_data["type"],
                        "status": "offline",
                        "capabilities": agent_data.get("capabilities", []),
                        "metadata": agent_metadata,
                        "created_at": now,
                        "updated_at": now
                    }
                    
                    # 写入数据库 (使用 upsert)
                    _ = await db.upsert(f"agents:{agent_id}", final_data)  # type: ignore
                    print(f"[+] 已同步: {final_data['name']} (ID: {agent_id})")
            except Exception as e:
                print(f"[!] 无法解析 {soul_path}: {e}")
                
        print("[SUCCESS] Agent 灵魂同步完成")
        
    except Exception as e:
        print(f"[ERROR] 同步失败: {e}")
    finally:
        await db.close()

def find_soul_files(root_dir: str) -> list[str]:
    """递归查找所有 SOUL.md 文件"""
    soul_files: list[str] = []
    # 忽略的目录
    ignore_dirs = {'.git', '.venv', 'node_modules', 'surrealdb', 'tmp', '.gemini', 'brain'}
    
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            if file.upper() == "SOUL.MD":
                soul_files.append(os.path.join(root, file))
    return soul_files

def parse_soul_file(file_path: str) -> dict:  # type: ignore
    """解析 SOUL.md 文件内容"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 获取第一行 Header 作为名字 (# Mercer -> Mercer)
    name_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    name = name_match.group(1).strip() if name_match else os.path.basename(os.path.dirname(file_path))
    if name.endswith("灵魂"): name = name.replace("灵魂", "").strip()
    if "Agent" in name: name = name.replace("Agent", "").strip()
    
    # 简单的角色描述提取 (## 核心身份 之后的部分)
    role_match = re.search(r'##\s+核心身份\s*\n\s*(.+)', content, re.MULTILINE)
    role = role_match.group(1).strip() if role_match else "未定义身份"
    
    # 提取能力 (## 你的角色 之后的列表项)
    capabilities = []
    # 查找 ## 你的角色 或 ## 核心职责 之后的内容，直到下一个 ## 标题
    cap_section = re.search(r'##\s+(?:你的角色|核心职责)\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if cap_section:
        cap_content = cap_section.group(1)
        # 查找所有 - 或 * 开头的行
        capabilities = [m.group(1).strip() for m in re.finditer(r'^[-\*]\s+(.+)', cap_content, re.MULTILINE)]

    # 提取分类 (根据路径)
    rel_path = os.path.relpath(file_path, PROJECT_ROOT)
    category = rel_path.split(os.sep)[0] if os.sep in rel_path else "core"

    return {
        "name": name,
        "type": category,
        "capabilities": capabilities,
        "metadata": {
            "summary": role,
            "version": "1.0.0"
        }
    }

if __name__ == "__main__":
    asyncio.run(sync_souls())
