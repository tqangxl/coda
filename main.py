import os
import sys
import logging
import asyncio
import psutil
from pathlib import Path
from typing import Any, List, Optional, Dict, cast
from datetime import datetime
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Coda Engine Imports
from engine import (
    SurrealStore, intent_engine, 
    AgentEngine, registry, Doctor, SkillFactory,
    AgentStatus, AdvisorExecutorRouter, AdvisorStrategy, AdvisorVerdict,
    ModelRegistry, ModelTier
)
from engine.base_types import UniversalCognitivePacket

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Coda.main")

db = SurrealStore()
intent = intent_engine.IntentEngine(db=db)
is_db_connected = False

# 引擎实例池 (Session -> Engine)
active_engines: Dict[str, AgentEngine] = {}

# 实时事件总线 (SSE)
class GraphEventBus:
    def __init__(self):
        self.listeners = []
    
    async def subscribe(self):
        queue = asyncio.Queue()
        self.listeners.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self.listeners.remove(queue)

    def broadcast(self, message: str):
        for queue in self.listeners:
            queue.put_nowait(message)

graph_events = GraphEventBus()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── [Startup] ──
    global is_db_connected
    try:
        await db.connect()
        is_db_connected = True
        logger.info("✅ Successfully connected to SurrealDB via SurrealStore")
        
        # 启动维护后台任务
        maintenance_task = asyncio.create_task(maintenance_daemon())
    except Exception as e:
        logger.error(f"❌ Failed to connect to DB: {e}")
        maintenance_task = None
    
    yield
    
    # ── [Shutdown] ──
    if maintenance_task:
        maintenance_task.cancel()
    await db.disconnect()
    logger.info("🛑 Database disconnected")

app = FastAPI(
    title="Coda Engine V7.0 API",
    lifespan=lifespan
)

# CORS 设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# [V7.1] Cognitive Engine Router
# -----------------------------------------------------------------------------
from engine.plugins.wiki.dreamcycle import router as dreamcycle_router
app.include_router(dreamcycle_router)

# -----------------------------------------------------------------------------
# 模型定义
# -----------------------------------------------------------------------------

class QueryRequest(BaseModel):
    text: str
    session_id: Optional[str] = "default"
    metadata: dict[str, Any] = {}
    model: Optional[str] = os.getenv("DEFAULT_MODEL_NAME", "gemini-2.0-pro-exp")
    max_iterations: int = 200
    cost_limit: float = 10.0

class IntentWeights(BaseModel):
    weights: dict[str, float]

# -----------------------------------------------------------------------------
# 后台任务
# -----------------------------------------------------------------------------

async def maintenance_daemon():
    """后台维护进程：处理超时任务、清理僵尸进程等。"""
    logger.info("🚀 Maintenance daemon started.")
    cycle_count = 0
    while True:
        try:
            # ── [V7.1] 自动清理过期图谱脂肪 (Garbage Collection) ──
            if is_db_connected:
                # 找出所有 expires_at 小于当前时间的节点并删除
                cleanup_query = "DELETE wiki_nodes WHERE expires_at != NONE AND expires_at <= time::unix();"
                try:
                    res = await db._safe_query(cleanup_query)
                    # SurrealDB delete 返回被删除的记录
                    deleted = db._extract_result(res)
                    if deleted and len(deleted) > 0:
                        logger.info(f"🧹 Garbage Collection: Purged {len(deleted)} expired knowledge nodes.")
                        graph_events.broadcast("gc_purged")
                except Exception as e:
                    logger.error(f"GC Error: {e}")
            # ── [V7.2] Cognitive Metabolism (DreamCycle 4-Phase) ──
            # 每 10 轮 GC (约 50 分钟) 触发一次自主认知代谢
            if is_db_connected:
                cycle_count += 1
                if cycle_count >= 10:
                    try:
                        from engine.plugins.wiki.plugins.dream_cycle import DreamCycleService
                        from engine.plugins.wiki.base_plugin import WikiPluginRegistry, WikiPluginContext

                        _dream_svc = DreamCycleService()
                        _registry = WikiPluginRegistry(ctx_factory=None)
                        _registry.register_service("db", db)   # inject global SurrealStore
                        _ctx = WikiPluginContext(wiki_dir="", registry=_registry)
                        await _dream_svc.initialize(_ctx)

                        report = await _dream_svc.run_full_cycle(project_id="Coda_core")
                        logger.info(
                            f"🌌 DreamCycle complete: "
                            f"synth={report.synthesis_created} "
                            f"archived={report.nodes_archived} "
                            f"health={report.health.trend}"
                        )
                    except Exception as e:
                        logger.error(f"DreamCycle Error: {e}")
                    cycle_count = 0

            # 模拟心跳与自愈逻辑，每隔 5 分钟执行一次 GC
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Maintenance error: {e}")
            await asyncio.sleep(10)

@app.get("/engine/events")
async def event_stream(request: Request):
    """Server-Sent Events 端口，用于实时通知前端。"""
    from fastapi.responses import StreamingResponse
    
    async def event_generator():
        async for event in graph_events.subscribe():
            if await request.is_disconnected():
                break
            yield f"data: {event}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/engine/notify-update")
async def notify_update(payload: dict):
    """内部接口：当数据更新时通知实时总线。"""
    event_type = payload.get("type", "update")
    graph_events.broadcast(event_type)
    return {"status": "ok"}

@app.post("/engine/session/archive")
async def archive_session(payload: dict):
    """手动或自动归档当前会话摘要。"""
    session_id = payload.get("session_id", "default")
    summary = payload.get("summary", "")
    tasks = payload.get("tasks", [])
    
    res = await db.save_session_report(session_id, summary, tasks)
    if res:
        graph_events.broadcast("session_archived")
        return {"status": "archived", "id": res}
    return {"status": "error"}
# -----------------------------------------------------------------------------
# 核心 API 路由
# -----------------------------------------------------------------------------

@app.get("/status")
async def get_status() -> dict[str, Any]:
    """详细系统状态报告 (800% 标准)。"""
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        # 统计活跃引擎
        engine_stats = {
            "total_active": len(active_engines),
            "sessions": list(active_engines.keys())
        }
        
        return {
            "version": "7.0.0",
            "uptime": str(datetime.now() - datetime.fromtimestamp(process.create_time())),
            "resources": {
                "memory_rss_mb": round(mem_info.rss / 1024 / 1024, 2),
                "cpu_percent": process.cpu_percent(),
                "threads": process.num_threads()
            },
            "database": {
                "connected": is_db_connected,
                "url": os.getenv("SURREAL_URL", "127.0.0.1:11001"),
                "ns": os.getenv("SURREAL_NS", "ai_agents_v2"),
                "db": os.getenv("SURREAL_DB", "federated_knowledge")
            },
            "engines": engine_stats,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agents")
async def list_agents():
    """查看所有注册角色的主权身份状态。"""
    if not is_db_connected:
        raise HTTPException(status_code=503, detail="Database not connected")
    
    try:
        # 确保注册库已加载
        await registry.initialize()
        identities = registry.list_all_identities()
        
        return {
            "count": len(identities),
            "agents": [id.to_dict() for id in identities]
        }
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/engine/run")
async def engine_run(req: QueryRequest):
    """
    提交任务给 V7.0 引擎并执行。
    工作流: 意图分析 -> 军师审计 -> 引擎执行 (HTAS 溯源)。
    """
    try:
        # 1. 意图分析 (Intent Engine)
        intent_result = await intent.analyze(req.text)
        
        # 2. 军师审计 (Advisor)
        # V7.0: 使用 AdvisorExecutorRouter 实例进行咨询
        # 注意: 军师引擎需要 ModelRegistry
        model_registry = ModelRegistry(db=db)
        await model_registry.sync_with_db()
        
        router = AdvisorExecutorRouter(registry=model_registry)
        # consult 接口不支持 context 参数，将 intent 注入到 task_context
        task_context = f"{req.text}\n[Intent: {intent_result.intent_type}]"
        advice = await router.consult(task_context, strategy=AdvisorStrategy.SOLO)
        
        # 3. 引擎实例管理 (Pillar 26: Session Persistence)
        session_id = req.session_id or "default"
        if session_id not in active_engines:
            # 创建新引擎
            new_engine = AgentEngine(
                working_dir="D:/ai/workspace",
                session_id=session_id,
                model_name=req.model,
                max_iterations=req.max_iterations,
                cost_limit=req.cost_limit,
                db=db,
                enable_embedding=True
            )
            # 异步初始化
            await new_engine.initialize()
            active_engines[session_id] = new_engine
            
        engine = active_engines[session_id]
        
        # 4. 物理执行
        # 注入军师裁决进行 Traceability
        # Cast to Any to bridge difference between engine.advisor.AdvisorVerdict and engine.base_types.AdvisorVerdict
        result = await engine.run(req.text, verdict=cast(Any, advice))
        
        return {
            "response": result,
            "session_id": engine.session_id,
            "iteration": engine.store.state.iteration,
            "cost_usd": engine.store.state.usage.total_cost_usd,
            "intent": intent_result.intent_type,
            "advisor_verdict": advice.verdict,
            "db_connected": engine.db.is_connected
        }
    except Exception as e:
        logger.error(f"Engine execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/engine/status")
async def get_engine_status(session_id: str = "default"):
    """监控指定会话的引擎活跃状态。"""
    engine = active_engines.get(session_id)
    if not engine:
        return {"active": False, "message": f"Session {session_id} not initialized"}
        
    state = engine.store.state
    return {
        "active": True,
        "session_id": session_id,
        "status": state.status.value,
        "iteration": state.iteration,
        "model": state.model_name,
        "cost_usd": state.usage.total_cost_usd,
        "matched_soul": engine.identity.name,
        "last_intent": engine.last_intent.intent_type if engine.last_intent else None
    }

@app.get("/engine/skills")
async def get_skills(session_id: str = "default"):
    """聚合本地与数据库技能。"""
    engine = active_engines.get(session_id)
    
    # 基础本地扫描
    local_factory = SkillFactory([Path("D:/ai/workspace/skills")])
    local_skills = local_factory.list_skills()
    
    # DB 技能
    db_skills = []
    if is_db_connected:
        db_skills = await db.load_skills()
        
    return {
        "local_count": len(local_skills),
        "db_count": len(db_skills),
        "local": local_skills,
        "db": db_skills
    }

@app.get("/engine/intent")
async def get_intent_stats():
    """查看 IntentEngine 统计信息。"""
    return {
        "total_analyzed": len(intent._history),
        "weights": intent.get_weights(),
        "recent_intents": [h.intent_type for h in intent._history[-10:]]
    }

@app.get("/engine/doctor")
async def run_diagnostics():
    """执行 32 点全栈环境自愈诊断 (True 800% Standard)。"""
    try:
        doc = Doctor("D:/ai/workspace")
        # ── V7.0: 执行 async 探测 ──
        results = await doc.diagnose()
        
        return {
            "healthy": all(r.healthy for r in results),
            "healthy_count": len([r for r in results if r.healthy]),
            "total_count": len(results),
            "timestamp": datetime.now().isoformat(),
            "results": [r.to_dict() for r in results]
        }
    except Exception as e:
        logger.error(f"Diagnostic flow crashed: {e}")
        raise HTTPException(status_code=500, detail=f"Diagnostic failure: {e}")

@app.get("/engine/intent/weights")
async def get_weights():
    """获取所有意图的认知权重。"""
    weights = await db.load_intent_weights()
    return {"weights": weights}

@app.post("/engine/intent/weights")
async def update_weights(data: IntentWeights):
    """手动调整意图认知权重。"""
    await db.save_intent_weights(data.weights)
    return {"status": "updated"}

# -----------------------------------------------------------------------------
# 知识图谱可视化 (Repair V7.0)
# -----------------------------------------------------------------------------

@app.get("/engine/graph", response_class=HTMLResponse)
async def engine_graph():
    """
    Coda V7.0 Federated Knowledge Graph (Deep-View).
    """
    import json
    db_store = db
    
    vis_nodes = []
    vis_edges = []
    node_ids = set()
    total_nodes = 0
    total_edges = 0
    
    try:
        # 0. 获取全局统计信息 (Pillar 0)
        # 汇总所有核心表的节点数
        total_nodes = 0
        for table in ["wiki_nodes", "agents", "memory_fragment"]:
            res = await db_store._safe_query(f"SELECT count() FROM {table} GROUP ALL")
            counts = db_store._extract_result(res)
            if counts:
                total_nodes += counts[0].get("count", 0)
        
        # 汇总所有关系表的关系数
        total_edges = 0
        rel_tables = ["depends_on", "extends", "contradicts", "references", "part_of", "related_to", "SIMILAR_TO"]
        for rt in rel_tables:
            r_res = await db_store._safe_query(f"SELECT count() FROM {rt} GROUP ALL")
            counts = db_store._extract_result(r_res)
            if counts:
                total_edges += counts[0].get("count", 0)
        # 1. 加载 Agents (Pillar 1)
        agents_res = await db_store._safe_query("SELECT id, name, priority FROM agents LIMIT 100")
        agent_lookup = []
        for agent in db_store._extract_result(agents_res):
            aid = str(agent.get("id", ""))
            name = str(agent.get("name", "Unknown Agent"))
            if aid and aid not in node_ids:
                vis_nodes.append({
                    "id": aid, 
                    "label": name, 
                    "color": "#334155", 
                    "shape": "box",
                    "font": {"color": "#f8fafc", "size": 16},
                    "title": f"Agent ID: {aid}\nPriority: {agent.get('priority')}"
                })
                node_ids.add(aid)
                agent_lookup.append(aid)
        
        # 2. 加载知识 (Pillar 2)
        wiki_res = await db_store._safe_query("SELECT id, title, tags FROM wiki_nodes LIMIT 500")
        for node in db_store._extract_result(wiki_res):
            nid = str(node.get("id", ""))
            if nid and nid not in node_ids:
                vis_nodes.append({
                    "id": nid, "label": node.get("title", "Node")[:30], 
                    "color": "#0284c7", "shape": "dot", "size": 18,
                    "title": f"Knowledge ID: {nid}\nTags: {node.get('tags')}"
                })
                node_ids.add(nid)

        # 3. [V7.1] 加载语义与结构化关系
        # 3.1 语义相似性 (SIMILAR_TO)
        sim_res = await db_store._safe_query("SELECT id, in, out, weight FROM SIMILAR_TO LIMIT 300")
        required_node_ids = set()
        for sim in db_store._extract_result(sim_res):
            fid = str(sim.get("in", ""))
            tid = str(sim.get("out", ""))
            if fid and tid:
                vis_edges.append({
                    "from": fid, "to": tid, 
                    "label": f"similar ({sim.get('weight', 0)})",
                    "color": {"color": "#fbbf24", "opacity": 0.4},
                    "width": float(sim.get("weight", 0.1)) * 3,
                    "dashes": True
                })
                required_node_ids.add(fid)
                required_node_ids.add(tid)

        # 3.2 结构化 Wiki 关系 (depends_on, references, etc.)
        wiki_rel_types = [
            "depends_on", "extends", "contradicts", "supersedes", 
            "grounds", "implies", "tensions_with", "references", 
            "part_of", "related_to", "mentions"
        ]
        for rt in wiki_rel_types:
            try:
                rel_res = await db_store._safe_query(f"SELECT id, in, out, weight FROM {rt} LIMIT 200")
                for rel in db_store._extract_result(rel_res):
                    fid = str(rel.get("in", ""))
                    tid = str(rel.get("out", ""))
                    if fid and tid:
                        # 确定连线颜色
                        edge_color = "#38bdf8" # 默认蓝色
                        if rt == "depends_on": edge_color = "#f43f5e" # 红色依赖
                        if rt == "contradicts": edge_color = "#ef4444" # 冲突
                        
                        vis_edges.append({
                            "from": fid, "to": tid, 
                            "label": rt,
                            "color": {"color": edge_color, "opacity": 0.6},
                            "arrows": "to",
                            "width": 1.5
                        })
                        required_node_ids.add(fid)
                        required_node_ids.add(tid)
            except Exception as e:
                # 某些表可能尚不存在，静默跳过
                continue

        # 3.3 加载涉及到的其他知识节点 (确保连线完整)
        missing_wiki_ids = [nid for nid in required_node_ids if nid.startswith("wiki_nodes:") and nid not in node_ids]
        if missing_wiki_ids:
            batch_size = 50
            for i in range(0, len(missing_wiki_ids), batch_size):
                batch = missing_wiki_ids[i:i+batch_size]
                ids_str = "[" + ",".join(batch) + "]"
                try:
                    missing_res = await db_store._safe_query(f"SELECT * FROM {ids_str}")
                    for row in db_store._extract_result(missing_res):
                        node_id = str(row.get("id", ""))
                        if node_id not in node_ids:
                            vis_nodes.append({
                                "id": node_id,
                                "label": row.get("title") or node_id.split(":")[-1],
                                "group": row.get("project_id", "default"),
                                "title": row.get("body", "")[:200],
                                "font": {"size": 12, "color": "#f8fafc"},
                                "shape": "dot", "size": 15
                            })
                            node_ids.add(node_id)
                except: pass

        # 4. 加载涉及到的记忆碎片 (Memory Fragments)
        if required_node_ids:
            # 过滤出 memory_fragment 类型的 ID
            fragment_ids = [nid for nid in required_node_ids if nid.startswith("memory_fragment:")]
            if fragment_ids:
                # V7.0 Fix: SurrealDB RecordID 数组不支持 JSON 字符串数组，需使用原始 ID 列表
                ids_str = "[" + ",".join(fragment_ids) + "]"
                mems_res = await db_store._safe_query(f"SELECT id, content, tags, agent_id, importance FROM memory_fragment WHERE id INSIDE {ids_str}")
                for mem in db_store._extract_result(mems_res):
                    mid = str(mem.get("id", ""))
                    if mid not in node_ids:
                        vis_nodes.append({
                            "id": mid, "label": mem.get("content", "Memory")[:20] + "...", 
                            "color": "#f59e0b", "shape": "diamond", "size": 15,
                            "title": f"Memory ID: {mid}\nImportance: {mem.get('importance')}\nContent: {mem.get('content')}"
                        })
                        node_ids.add(mid)
                    
                    # [Dynamic Identity Discovery]
                    ag_id = mem.get("agent_id", "")
                    if ag_id:
                        # 如果是 DID 格式，创建一个虚拟 Agent 节点 (如果不在 node_ids 中)
                        if ag_id not in node_ids:
                            vis_nodes.append({
                                "id": ag_id, "label": ag_id.split(":")[-1], 
                                "color": "#475569", "shape": "hexagon", "size": 25,
                                "title": f"External/Virtual Agent: {ag_id}"
                            })
                            node_ids.add(ag_id)
                        
                        # 建立连接
                        vis_edges.append({
                            "from": ag_id, "to": mid, "label": "memory", 
                            "color": {"color": "#fbbf24", "opacity": 0.4}, "arrows": "to", "dashes": [5, 5]
                        })

        # 4.5 [Formal Memory] 注入底层物理操作足迹 (agent_logs)
        # 根据 HTAS 反幻觉准则，提取并渲染真实发生过的交易、拒绝和召回事件
        logs_res = await db_store._safe_query("SELECT * FROM agent_logs ORDER BY timestamp DESC LIMIT 100")
        for log in db_store._extract_result(logs_res):
            lid = str(log.get("id", ""))
            if lid not in node_ids:
                ltype = log.get("type", "UNKNOWN")
                
                # 判定物理属性 (色彩与形状)
                if ltype in ["TRANSACTION", "TRANSFER_REJECTED"]:
                    # 高风险物理介入 (交易/被拦) - 红色三角形
                    shape = "triangle"
                    color = "#ef4444"
                elif ltype in ["MEMORY_RECALLED", "REFLECT_TRIGGERED"]:
                    # 内部思维元认知 - 紫色圆点
                    shape = "dot"
                    color = "#a855f7"
                else:
                    shape = "dot"
                    color = "#94a3b8"
                
                label = log.get("memo") or ltype
                if len(label) > 15:
                    label = label[:15] + "..."
                
                vis_nodes.append({
                    "id": lid, "label": label, 
                    "color": color, "shape": shape, "size": 12,
                    "title": f"Log ID: {lid}\nType: {ltype}\nDetails: {json.dumps({k:v for k,v in log.items() if k not in ['id', 'timestamp']}, default=str, indent=2)}"
                })
                node_ids.add(lid)
                
                # 建立与发起源的连接
                ag_did = log.get("agent_did") or log.get("from")
                if ag_did:
                    # 如果该 DID 节点不存在，则创建虚拟身份
                    if ag_did not in node_ids:
                        vis_nodes.append({
                            "id": ag_did, "label": ag_did.split(":")[-1], 
                            "color": "#475569", "shape": "hexagon", "size": 25,
                            "title": f"External/Virtual Agent: {ag_did}"
                        })
                        node_ids.add(ag_did)
                    
                    vis_edges.append({
                        "from": ag_did, "to": lid, "label": "audit_trail", 
                        "color": {"color": color, "opacity": 0.5}, "arrows": "to"
                    })

        # 5. [Virtual Bridging] 建立跨表虚拟连接 (Wiki ↔ Agents)
        for node in [n for n in vis_nodes if n["id"].startswith("wiki_nodes:")]:
            nid = node["id"]
            # 检查是否有显式项目所有权
            project_id = node.get("project_id", "Unknown")
            # 建立虚拟连接到 Agent (基于 ID 启发式)
            for aid in agent_lookup:
                agent_stem = aid.split(":")[-1]
                if agent_stem.lower() in nid.lower() or agent_stem.lower() in project_id.lower():
                    vis_edges.append({
                        "from": aid, "to": nid, "label": "owns", 
                        "color": {"color": "#38bdf8", "opacity": 0.3}, "arrows": "to", "dashes": True
                    })

        # 6. 回填补全：如果没有发现任何关系，加载最近的一些碎片作为点缀
        if len(vis_nodes) < 20:
            fallback_res = await db_store._safe_query("SELECT id, content FROM memory_fragment LIMIT 50")
            for mem in db_store._extract_result(fallback_res):
                mid = str(mem.get("id", ""))
                if mid not in node_ids:
                    content = mem.get("content") or "Memory Fragment"
                    vis_nodes.append({
                        "id": mid, "label": content[:20], "color": "#f59e0b", "shape": "diamond", "size": 15
                    })
                    node_ids.add(mid)

    except Exception as e:
        logger.error(f"Graph Data Error: {e}")

    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Coda Engine Graph</title>
        <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
        <style>
            body {{ background: #0f172a; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 0; height: 100vh; overflow: hidden; }}
            #mynetwork {{ width: 100vw; height: 100vh; background: radial-gradient(circle at center, #1e293b 0%, #0f172a 100%); }}
            .overlay {{ position: absolute; top: 0; left: 0; right: 0; padding: 20px; z-index: 100; pointer-events: none; display: flex; justify-content: space-between; }}
            .panel {{ background: rgba(30, 41, 59, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.1); padding: 16px 24px; border-radius: 16px; pointer-events: auto; }}
            h1 {{ margin: 0; font-size: 1.25rem; color: #38bdf8; }}
            .stats {{ color: #94a3b8; font-size: 0.75rem; margin-top: 4px; font-family: monospace; }}
            .btn {{ background: #0ea5e9; color: white; border: none; padding: 8px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3); }}
            .btn:hover {{ background: #0284c7; transform: translateY(-1px); }}
            .legend {{ position: absolute; bottom: 24px; left: 24px; pointer-events: none; }}
            .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 0.75rem; margin-bottom: 6px; }}
            .legend-color {{ width: 10px; height: 10px; border-radius: 3px; }}
        </style>
    </head>
    <body>
        <div class="overlay">
            <div class="panel">
                <h1>Coda Federated Graph v7.0</h1>
                <div class="stats">
                    Total: Nodes={total_nodes} Edges={total_edges} | 
                    Displayed: Nodes={len(vis_nodes)} Edges={len(vis_edges)} | 
                    DB: SurrealDB
                </div>
            </div>
            <div style="pointer-events: auto; display: flex; gap: 10px; align-items: center;">
                <div id="live-indicator" style="width: 10px; height: 10px; background: #22c55e; border-radius: 50%; box-shadow: 0 0 8px #22c55e;"></div>
                <span style="font-size: 0.75rem; color: #94a3b8;">Live Sync Active</span>
                <button class="btn" onclick="location.reload()">Manual Reload</button>
            </div>
        </div>
        
        <div class="legend panel">
            <div class="legend-item"><div class="legend-color" style="background: #334155;"></div> Agents</div>
            <div class="legend-item"><div class="legend-color" style="background: #0284c7;"></div> Knowledge (L0-L3)</div>
            <div class="legend-item"><div class="legend-color" style="background: #f59e0b;"></div> Memories (Latent)</div>
            <div class="legend-item"><div class="legend-color" style="background: #fbbf24; height: 2px; margin-top: 8px;"></div> Semantic Links</div>
        </div>

        <div id="mynetwork"></div>

        <script>
            try {{
                const nodes = new vis.DataSet({nodes_json});
                const edges = new vis.DataSet({edges_json});
                
                const container = document.getElementById('mynetwork');
                const data = {{ nodes, edges }};
                const options = {{
                    nodes: {{ shadow: true, borderWidth: 2 }},
                    edges: {{ smooth: {{ type: 'continuous' }}, arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }} }},
                    physics: {{ 
                        barnesHut: {{ gravitationalConstant: -6000, centralGravity: 0.3, springLength: 150 }},
                        stabilization: {{ iterations: 100 }}
                    }}
                }};
                new vis.Network(container, data, options);

                // ── Real-time Update Listener ──
                const eventSource = new EventSource('/engine/events');
                eventSource.onmessage = (event) => {{
                    console.log("Graph update signal received:", event.data);
                    const indicator = document.getElementById('live-indicator');
                    indicator.style.background = '#38bdf8';
                    indicator.style.box_shadow = '0 0 12px #38bdf8';
                    
                    // 延迟 1 秒后自动刷新，给数据库留一点同步时间
                    setTimeout(() => {{
                        location.reload();
                    }}, 1000);
                }};
                
                eventSource.onerror = () => {{
                    document.getElementById('live-indicator').style.background = '#ef4444';
                    document.getElementById('live-indicator').style.box_shadow = 'none';
                }};
            }} catch (e) {{
                console.error(e);
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# -----------------------------------------------------------------------------
# 程序入口
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    if "--diagnose" in sys.argv or "-d" in sys.argv:
        print("🔍 Running pre-flight diagnostics...")
        # Since Doctor is implemented in engine/__init__.py, we use it directly
        from engine import Doctor
        # Note: In some systems Doctor might require path to agents
        WORKSPACE_DIR = os.getcwd()
        doctor = Doctor(WORKSPACE_DIR)
        results = asyncio.run(doctor.diagnose())
        
        healthy = True
        for r in results:
            status = "✅" if r.healthy else "❌"
            print(f"{status} [{r.component}] {r.detail}")
            if not r.healthy:
                healthy = False
        
        if not healthy:
            print("\n⚠️ System is unhealthy.")
            sys.exit(1)
        else:
            print("\n✅ All systems nominal.")
            sys.exit(0)

    import uvicorn
    # V7.0: 支持动态端口
    port = 11002
    try:
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            port = int(sys.argv[idx + 1])
    except:
        pass
    uvicorn.run(app, host="127.0.0.1", port=port)
