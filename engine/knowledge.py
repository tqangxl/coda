"""
Coda V4.0 — Knowledge Graph & Vector Memory (中重要度 #9 & #11)
结构化知识图谱 + 向量化语义搜索。

替代简单的关键词匹配, 实现真正的"像搜论文一样"检索。
MagicDocs 升级为结构化知识图谱。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger("Coda.knowledge")


class KnowledgeEntity:
    """知识图谱中的一个实体。"""
    def __init__(self, entity_id: str, name: str, entity_type: str, content: str = ""):
        self.entity_id: str = entity_id
        self.name: str = name
        self.entity_type: str = entity_type  # file, function, class, api, concept
        self.content: str = content
        self.properties: dict[str, str] = {}
        self.created_at: float = time.time()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.entity_id,
            "name": self.name,
            "type": self.entity_type,
            "content": self.content,
            "properties": self.properties,
        }


class KnowledgeRelation:
    """实体之间的关系。"""
    def __init__(self, from_id: str, to_id: str, relation_type: str):
        self.from_id: str = from_id
        self.to_id: str = to_id
        self.relation_type: str = relation_type  # imports, calls, inherits, depends_on, documents

    def to_dict(self) -> dict[str, str]:
        return {"from": self.from_id, "to": self.to_id, "type": self.relation_type}


class KnowledgeGraph:
    """
    结构化知识图谱 (MagicDocs 升级版)。

    不再是扁平的文档列表, 而是一个有实体、关系和属性的真正图谱:
    - 文件 → 导入关系 → 其他文件
    - 类 → 继承关系 → 父类
    - 函数 → 调用关系 → 其他函数
    - API → 文档关系 → README
    """

    def __init__(self, storage_path: str | Path | None = None):
        self._entities: dict[str, KnowledgeEntity] = {}
        self._relations: list[KnowledgeRelation] = []
        self._storage_path: Path | None = Path(storage_path) if storage_path else None
        if self._storage_path:
            self._load()

    def add_entity(self, name: str, entity_type: str, content: str = "", **props: str) -> str:
        """添加实体, 返回 entity_id。"""
        eid = hashlib.md5(f"{entity_type}:{name}".encode()).hexdigest()[:12]
        entity = KnowledgeEntity(eid, name, entity_type, content)
        entity.properties = props
        self._entities[eid] = entity
        return eid

    def add_relation(self, from_name: str, to_name: str, relation_type: str) -> None:
        """添加关系。"""
        from_entity = self._find_by_name(from_name)
        to_entity = self._find_by_name(to_name)
        if from_entity and to_entity:
            self._relations.append(KnowledgeRelation(from_entity.entity_id, to_entity.entity_id, relation_type))

    def query(self, query: str, top_k: int = 10) -> list[KnowledgeEntity]:
        """查询知识图谱。"""
        query_lower = query.lower()
        scored = []
        for entity in self._entities.values():
            score = 0.0
            if query_lower in entity.name.lower():
                score += 3.0
            if query_lower in entity.content.lower():
                score += 1.0
            for v in entity.properties.values():
                if query_lower in v.lower():
                    score += 0.5
            # 关系密度加权
            relations = self._get_relations(entity.entity_id)
            score += len(relations) * 0.2
            if score > 0:
                scored.append((score, entity))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def get_neighbors(self, entity_name: str) -> list[dict[str, object]]:
        """获取实体的所有邻居 (关联实体)。"""
        entity = self._find_by_name(entity_name)
        if not entity:
            return []

        neighbors = []
        for rel in self._relations:
            if rel.from_id == entity.entity_id and rel.to_id in self._entities:
                neighbors.append({
                    "entity": self._entities[rel.to_id].to_dict(),
                    "relation": rel.relation_type,
                    "direction": "outgoing",
                })
            elif rel.to_id == entity.entity_id and rel.from_id in self._entities:
                neighbors.append({
                    "entity": self._entities[rel.from_id].to_dict(),
                    "relation": rel.relation_type,
                    "direction": "incoming",
                })
        return neighbors

    def index_python_file(self, filepath: str | Path) -> int:
        """索引 Python 文件: 提取类、函数、导入关系。"""
        path = Path(filepath)
        if not path.exists():
            return 0

        content = path.read_text(encoding="utf-8", errors="replace")
        count = 0

        # 添加文件实体
        file_name = str(path)
        self.add_entity(file_name, "file", content[:500], language="python")
        count += 1

        # 提取类定义
        for match in re.finditer(r'^class\s+(\w+)(?:\(([^)]*)\))?:', content, re.MULTILINE):
            cls_name = match.group(1)
            bases = match.group(2) or ""
            self.add_entity(cls_name, "class", f"class {cls_name}({bases})", file=file_name)
            self.add_relation(file_name, cls_name, "defines")
            count += 1
            # 继承关系
            for base in bases.split(","):
                base = base.strip()
                if base and base not in ("object",):
                    self.add_entity(base, "class", "")
                    self.add_relation(cls_name, base, "inherits")

        # 提取函数定义
        for match in re.finditer(r'^(?:async\s+)?def\s+(\w+)\s*\(', content, re.MULTILINE):
            func_name = match.group(1)
            self.add_entity(func_name, "function", f"def {func_name}()", file=file_name)
            self.add_relation(file_name, func_name, "defines")
            count += 1

        # 提取导入关系
        for match in re.finditer(r'^(?:from\s+([\w.]+)\s+)?import\s+(.+)', content, re.MULTILINE):
            module = match.group(1) or match.group(2).split(",")[0].strip().split(" as ")[0]
            self.add_entity(module, "module", "")
            self.add_relation(file_name, module, "imports")
            count += 1

        return count

    def save(self) -> None:
        """持久化知识图谱。"""
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entities": {k: v.to_dict() for k, v in self._entities.items()},
            "relations": [r.to_dict() for r in self._relations],
        }
        self._storage_path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    def _load(self) -> None:
        if self._storage_path and self._storage_path.exists():
            try:
                data: dict[str, object] = json.loads(self._storage_path.read_text(encoding="utf-8"))
                entities_data = data.get("entities")
                if isinstance(entities_data, dict):
                    for eid, edata in cast(dict[str, object], entities_data).items():
                        if not isinstance(edata, dict):
                            continue
                        _edata = cast(dict[str, object], edata)
                        e = KnowledgeEntity(str(_edata.get("id", "")), str(_edata.get("name", "")), str(_edata.get("type", "")), str(_edata.get("content", "")))
                        props = _edata.get("properties")
                        e.properties = props if isinstance(props, dict) else {}
                        self._entities[str(eid)] = e
                relations_data = data.get("relations")
                if isinstance(relations_data, list):
                    for rdata in cast(list[object], relations_data):
                        if isinstance(rdata, dict):
                            _rdata = cast(dict[str, object], rdata)
                            self._relations.append(KnowledgeRelation(str(_rdata.get("from", "")), str(_rdata.get("to", "")), str(_rdata.get("type", ""))))
            except Exception as e:
                logger.error(f"Failed to load knowledge graph from {self._storage_path}: {e}")
                import shutil, time
                backup_path = f"{self._storage_path}.corrupted_{int(time.time())}"
                try:
                    import shutil
                    shutil.copy2(self._storage_path, backup_path)
                    logger.info(f"Backed up corrupted knowledge graph to {backup_path}")
                except Exception as ex:
                    logger.error(f"Failed to backup corrupted knowledge graph: {ex}")

    def _find_by_name(self, name: str) -> KnowledgeEntity | None:
        for e in self._entities.values():
            if e.name == name:
                return e
        return None

    def _get_relations(self, entity_id: str) -> list[KnowledgeRelation]:
        return [r for r in self._relations if r.from_id == entity_id or r.to_id == entity_id]


# ════════════════════════════════════════════
#  向量化语义搜索 (TF-IDF 轻量实现)
# ════════════════════════════════════════════

class VectorMemory:
    """
    向量化语义搜索引擎 (替代纯关键词匹配)。

    使用 TF-IDF 算法实现轻量级的语义化检索,
    无需外部 embedding 模型, 零依赖纯 Python 实现。

    未来可通过 set_embedder() 接入真正的 embedding 模型。
    """

    def __init__(self):
        self._documents: list[dict[str, object]] = []  # {id, content, metadata}
        self._idf_cache: dict[str, float] = {}
        self._dirty: bool = True

    def add(self, doc_id: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        """添加文档到索引。"""
        self._documents.append({
            "id": doc_id,
            "content": content,
            "metadata": metadata or {},
            "tokens": self._tokenize(content),
        })
        self._dirty = True

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """TF-IDF 语义搜索。"""
        if not self._documents:
            return []

        if self._dirty:
            self._build_idf()
            self._dirty = False

        query_tokens = self._tokenize(query)
        query_vec = self._tfidf(query_tokens)

        scored = []
        for doc in self._documents:
            doc_tokens = doc.get("tokens")
            if not isinstance(doc_tokens, list):
                continue
            doc_vec = self._tfidf(doc_tokens)
            sim = self._cosine_similarity(query_vec, doc_vec)
            if sim > 0:
                scored.append((sim, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": d["id"], "content": d["content"][:500], "score": s, "metadata": d["metadata"]}
            for s, d in scored[:top_k]
        ]

    def _tokenize(self, text: str) -> list[str]:
        """分词: 按空格和标点切分, 转小写。"""
        text = text.lower()
        tokens = re.findall(r'\b\w+\b', text)
        # 去除停用词
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of", "and", "or",
                       "的", "了", "是", "在", "和", "有"}
        return [t for t in tokens if t not in stop_words and len(t) > 1]

    def _build_idf(self) -> None:
        """构建 IDF 索引。"""
        doc_count = len(self._documents)
        df: dict[str, int] = {}
        for doc in self._documents:
            doc_tokens = doc.get("tokens")
            if isinstance(doc_tokens, list):
                unique_tokens = set(cast(list[str], doc_tokens))
                for token in unique_tokens:
                    df[token] = df.get(token, 0) + 1

        self._idf_cache = {
            token: math.log(doc_count / (count + 1)) + 1
            for token, count in df.items()
        }

    def _tfidf(self, tokens: list[str]) -> dict[str, float]:
        """计算 TF-IDF 向量。"""
        tf: dict[str, float] = {}
        total = len(tokens) or 1
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        return {
            t: (count / total) * self._idf_cache.get(t, 1.0)
            for t, count in tf.items()
        }

    def _cosine_similarity(self, vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        """计算余弦相似度。"""
        keys = set(vec_a.keys()) | set(vec_b.keys())
        dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in keys)
        mag_a = math.sqrt(sum(v ** 2 for v in vec_a.values())) or 1
        mag_b = math.sqrt(sum(v ** 2 for v in vec_b.values())) or 1
        return dot / (mag_a * mag_b)
