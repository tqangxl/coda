---
AIGC:
    ContentProducer: Minimax Agent AI
    ContentPropagator: Minimax Agent AI
    Label: AIGC
    ProduceID: "00000000000000000000000000000000"
    PropagateID: "00000000000000000000000000000000"
    ReservedCode1: 3045022100f8fdd1dd2e977aab3bade86ffbd112bb7636a55c96568822cde541d2d2f60c56022017a92cfb7205686adac295e92818a9acc49769f6022e45a2e71e3def81470481
    ReservedCode2: 3046022100b6a46a67c0da46472a143f9e5e019bb5e5d1fafe3f41d573f644ab8d2b70b23a022100ba5bacb19b660aa67d50ababee8f87315b5790903d9e9abd0150a585220d5d0a
---

# Knowledge Graph - Extraction 实体抽取

## 角色定义

Extraction是Knowledge Graph的实体抽取模块，负责从各种数据源中自动识别和提取实体，构建知识图谱的基础数据。

## 核心职责

### 1. 实体识别
- **命名实体识别**: 识别人名、地名、机构名等
- **概念抽取**: 抽取抽象概念
- **关系实体**: 识别实体间的关系
- **属性抽取**: 抽取实体的属性

### 2. 知识抽取
- **文本抽取**: 从文本中抽取知识
- **结构化抽取**: 从结构化数据中抽取
- **半结构化抽取**: 从HTML/XML等抽取
- **多语言抽取**: 支持多语言内容

### 3. 质量控制
- **去重处理**: 识别和合并重复实体
- **消歧处理**: 实体消歧
- **置信度评估**: 评估抽取置信度
- **人工校验**: 关键实体人工审核

## SurrealDB抽取模型

```sql
-- 抽取任务
DEFINE TABLE extraction_tasks SCHEMAFULL;
DEFINE FIELD id ON extraction_tasks TYPE string;
DEFINE FIELD source_type ON extraction_tasks TYPE string;
DEFINE FIELD source_content ON extraction_tasks TYPE string;
DEFINE FIELD extraction_config ON extraction_tasks TYPE object;
DEFINE FIELD status ON extraction_tasks TYPE string DEFAULT 'pending';
DEFINE FIELD results ON extraction_tasks TYPE option<array>;
DEFINE FIELD created_at ON extraction_tasks TYPE datetime;

-- 抽取结果
DEFINE TABLE extraction_results SCHEMAFULL;
DEFINE FIELD id ON extraction_results TYPE string;
DEFINE FIELD task_id ON extraction_results TYPE string;
DEFINE FIELD entity_type ON extraction_results TYPE string;
DEFINE FIELD entity_name ON extraction_results TYPE string;
DEFINE FIELD surface_forms ON extraction_results TYPE array;
DEFINE FIELD properties ON extraction_results TYPE object;
DEFINE FIELD relations ON extraction_results TYPE array;
DEFINE FIELD confidence ON extraction_results TYPE float;
DEFINE FIELD source ON extraction_results TYPE object;
DEFINE FIELD extracted_at ON extraction_results TYPE datetime;

-- 实体类型定义
DEFINE TABLE entity_types SCHEMAFULL;
DEFINE FIELD name ON entity_types TYPE string;
DEFINE FIELD description ON entity_types TYPE string;
DEFINE FIELD properties_schema ON entity_types TYPE object;
DEFINE FIELD extraction_patterns ON entity_types TYPE array;
```

## 实体类型

### 基础实体
```yaml
entity_types:
  person:
    properties:
      - name
      - title
      - organization
      - role
    patterns:
      - "[A-Z][a-z]+ [A-Z][a-z]+"
      - "CEO|CTO|Engineer"

  organization:
    properties:
      - name
      - type
      - industry
      - location
    patterns:
      - "Inc|LLC|Corp|Ltd"

  technology:
    properties:
      - name
      - category
      - version
      - provider
```

### 领域实体
```yaml
domain_entities:
  security:
    - vulnerability
    - attack_pattern
    - malware
    - cve

  development:
    - api
    - function
    - class
    - module

  data:
    - dataset
    - model
    - feature
```

## 抽取流程

```python
class EntityExtractor:
    async def extract(self, text, config):
        """执行实体抽取"""
        # 1. 预处理
        processed = self.preprocess(text)

        # 2. 基础NER
        named_entities = await self.extract_named_entities(processed)

        # 3. 关系抽取
        relations = await self.extract_relations(processed, named_entities)

        # 4. 属性抽取
        properties = await self.extract_properties(
            processed,
            named_entities
        )

        # 5. 实体消歧
        disambiguated = await self.disambiguate(
            named_entities,
            relations,
            properties
        )

        return {
            "entities": disambiguated,
            "relations": relations,
            "properties": properties
        }
```

## 抽取方法

### 1. 规则抽取
```python
def rule_based_extraction(self, text):
    """基于规则的抽取"""
    results = []

    for pattern in self.patterns:
        matches = re.finditer(pattern.regex, text)
        for match in matches:
            results.append({
                "type": pattern.entity_type,
                "value": match.group(),
                "confidence": pattern.confidence,
                "method": "rule"
            })

    return results
```

### 2. 模型抽取
```python
async def model_based_extraction(self, text):
    """基于模型的抽取"""
    # 使用NER模型
    entities = await self.ner_model.predict(text)

    # 使用关系抽取模型
    relations = await self.re_model.predict(text, entities)

    return {
        "entities": entities,
        "relations": relations
    }
```

### 3. 混合抽取
```python
async def hybrid_extraction(self, text):
    """混合抽取方法"""
    # 1. 规则快速抽取
    rule_results = self.rule_based_extraction(text)

    # 2. 模型深度抽取
    model_results = await self.model_based_extraction(text)

    # 3. 结果合并
    merged = self.merge_results(rule_results, model_results)

    # 4. 去重消歧
    deduplicated = self.deduplicate(merged)

    return deduplicated
```

## 关系抽取

```python
RELATION_TYPES = {
    "ownership": {
        "patterns": ["拥有", "属于", "持有"],
        "inverse": "owned_by"
    },
    "usage": {
        "patterns": ["使用", "基于", "采用"],
        "inverse": "used_by"
    },
    "causation": {
        "patterns": ["导致", "引起", "造成"],
        "inverse": "caused_by"
    }
}

async def extract_relations(self, text, entities):
    """抽取实体间关系"""
    relations = []

    for rel_type, config in RELATION_TYPES.items():
        for pattern in config["patterns"]:
            matches = re.finditer(
                f"(?P<head>.*?){pattern}(?P<tail>.*?)",
                text
            )
            for match in matches:
                head_entity = self.match_entity(
                    match.group("head"),
                    entities
                )
                tail_entity = self.match_entity(
                    match.group("tail"),
                    entities
                )

                if head_entity and tail_entity:
                    relations.append({
                        "type": rel_type,
                        "from": head_entity.id,
                        "to": tail_entity.id,
                        "confidence": 0.8
                    })

    return relations
```

## 消歧处理

```python
async def disambiguate(self, entities, context):
    """实体消歧"""
    disambiguated = []

    for entity in entities:
        candidates = await self.find_candidates(entity)

        if len(candidates) == 1:
            # 唯一匹配
            disambiguated.append(candidates[0])
        elif len(candidates) > 1:
            # 选择最相关的
            best = await self.select_best_candidate(
                entity,
                candidates,
                context
            )
            disambiguated.append(best)
        else:
            # 创建新实体
            new_entity = await self.create_new_entity(entity)
            disambiguated.append(new_entity)

    return disambiguated
```

## 质量控制

### 去重规则
```python
DEDUPLICATION_RULES = {
    "exact_match": {
        "condition": "name == other.name",
        "action": "merge",
        "strategy": "keep_latest"
    },
    "fuzzy_match": {
        "condition": "levenshtein(name, other.name) < 2",
        "action": "merge",
        "strategy": "keep_highest_confidence"
    }
}
```

### 置信度计算
```python
def calculate_confidence(self, entity, extraction_method):
    """计算抽取置信度"""
    base_confidence = {
        "rule": 0.9,
        "model": 0.85,
        "hybrid": 0.95
    }

    # 上下文影响
    context_score = self.evaluate_context(entity)

    # 一致性影响
    consistency_score = self.check_consistency(entity)

    return (
        base_confidence[extraction_method] * 0.6 +
        context_score * 0.2 +
        consistency_score * 0.2
    )
```

## 输出格式

```json
{
  "extraction_id": "extract_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "entities": [
    {
      "id": "entity_001",
      "type": "technology",
      "name": "SurrealDB",
      "surface_forms": ["SurrealDB", "Surreal DB"],
      "properties": {
        "category": "database",
        "license": "Apache-2.0"
      },
      "confidence": 0.95,
      "source": {
        "document": "doc_xxx",
        "position": {"start": 100, "end": 110}
      }
    }
  ],
  "relations": [
    {
      "id": "rel_001",
      "type": "implements",
      "from": "entity_001",
      "to": "entity_002",
      "confidence": 0.88
    }
  ]
}
```

## 与其他模块集成

```python
# 抽取后存储到图谱
async def on_extraction_complete(self, results):
    """抽取完成后的处理"""
    # 存储实体
    for entity in results.entities:
        await knowledge_graph.add_entity(entity)

    # 存储关系
    for relation in results.relations:
        await knowledge_graph.add_relation(relation)

    # 更新统计
    await statistics.update_extraction_stats(results)
```
