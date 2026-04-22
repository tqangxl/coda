# Self-Improving - Learning 学习机制

## 角色定义

Learning是Self-Improving Agent的核心学习模块，负责从经验中提取知识、更新记忆和改进系统行为。

## 核心职责

### 1. 经验采集
- **成功经验**: 记录成功的任务执行案例
- **失败教训**: 记录失败和错误案例
- **用户反馈**: 采集用户显式和隐式反馈
- **环境数据**: 采集执行环境信息

### 2. 知识提取
- **模式识别**: 从经验中发现模式
- **规则抽取**: 提取可操作规则
- **最佳实践**: 总结成功方法
- **教训提炼**: 从失败中提炼教训

### 3. 知识更新
- **记忆更新**: 更新MemoryKeeper中的知识
- **规则库更新**: 更新规则库
- **模式库更新**: 更新成功模式库
- **技能库更新**: 优化技能定义

## SurrealDB学习模型

```sql
-- 学习事件
DEFINE TABLE learning_events SCHEMAFULL;
DEFINE FIELD id ON learning_events TYPE string;
DEFINE FIELD event_type ON learning_events TYPE string;
DEFINE FIELD source ON learning_events TYPE string;
DEFINE FIELD task_id ON learning_events TYPE option<string>;
DEFINE FIELD data ON learning_events TYPE object;
DEFINE FIELD extracted_knowledge ON learning_events TYPE option<object>;
DEFINE FIELD processed_at ON learning_events TYPE option<datetime>;
DEFINE FIELD created_at ON learning_events TYPE datetime;

-- 知识条目
DEFINE TABLE knowledge_entries SCHEMAFULL;
DEFINE FIELD id ON knowledge_entries TYPE string;
DEFINE FIELD type ON knowledge_entries TYPE string;
DEFINE FIELD category ON knowledge_entries TYPE string;
DEFINE FIELD content ON knowledge_entries TYPE object;
DEFINE FIELD source_events ON knowledge_entries TYPE array;
DEFINE FIELD confidence ON knowledge_entries TYPE float;
DEFINE FIELD usage_count ON knowledge_entries TYPE int DEFAULT 0;
DEFINE FIELD last_used ON knowledge_entries TYPE option<datetime>;
DEFINE FIELD validation_status ON knowledge_entries TYPE string DEFAULT 'pending';
DEFINE FIELD created_at ON knowledge_entries TYPE datetime;
DEFINE FIELD updated_at ON learning_events TYPE datetime;

-- 学习规则
DEFINE TABLE learning_rules SCHEMAFULL;
DEFINE FIELD id ON learning_rules TYPE string;
DEFINE FIELD name ON learning_rules TYPE string;
DEFINE FIELD trigger ON learning_rules TYPE object;
DEFINE FIELD action ON learning_rules TYPE object;
DEFINE FIELD conditions ON learning_rules TYPE array;
DEFINE FIELD priority ON learning_rules TYPE int DEFAULT 0;
DEFINE FIELD enabled ON learning_rules TYPE bool DEFAULT true;

-- 索引
DEFINE INDEX idx_event_type ON learning_events FIELDS event_type, created_at DESC;
DEFINE INDEX idx_knowledge_type ON knowledge_entries FIELDS type, category;
DEFINE INDEX idx_knowledge_confidence ON knowledge_entries FIELDS confidence, usage_count;
```

## 学习类型

### 1. 监督学习
```python
# 从用户反馈中学习
async def learn_from_feedback(self, task_id, feedback):
    # 1. 记录反馈事件
    event = await self.record_event(
        event_type="user_feedback",
        task_id=task_id,
        data=feedback
    )

    # 2. 提取知识
    knowledge = await self.extract_knowledge(event)

    # 3. 验证并更新
    if knowledge.confidence >= 0.8:
        await self.update_knowledge_base(knowledge)
```

### 2. 强化学习
```python
# 从任务结果中学习
async def learn_from_outcome(self, task_id, outcome):
    # 奖励或惩罚
    reward = 1 if outcome.success else -1

    # 更新相关规则
    for rule in outcome.used_rules:
        await self.update_rule_strength(rule, reward)
```

### 3. 无监督学习
```python
# 从大量数据中发现模式
async def discover_patterns(self, events):
    # 聚类分析
    clusters = self.cluster_events(events)

    # 发现关联
    associations = self.find_associations(clusters)

    # 生成模式
    patterns = self.generate_patterns(associations)

    return patterns
```

## 知识提取流程

```
经验事件 → 预处理 → 特征提取 → 模式识别 → 知识生成 → 验证 → 存储
```

## 知识分类

| 类型 | 说明 | 示例 |
|------|------|------|
| 经验知识 | 从实践中获得 | "处理大文件时分块读取更高效" |
| 规则知识 | 条件-动作映射 | "if 代码量>1000 then 建议拆分" |
| 模式知识 | 常见问题-解决方案 | "登录问题通常与token过期有关" |
| 教训知识 | 失败案例总结 | "未验证输入导致的安全漏洞" |

## 学习触发机制

### Hook自动触发
```python
LEARNING_HOOKS = {
    "task_completed": {
        "condition": "success and duration > 60",
        "action": "learn_from_success"
    },
    "task_failed": {
        "condition": "failure_count >= 3",
        "action": "learn_from_failure"
    },
    "user_feedback": {
        "condition": "rating < 3",
        "action": "learn_from_negative_feedback"
    }
}
```

### 定期学习
```python
# 每日汇总学习
async def daily_learning():
    yesterday_events = await self.get_events(
        since=datetime.now() - timedelta(days=1)
    )

    patterns = await self.discover_patterns(yesterday_events)
    await self.update_pattern_library(patterns)

    # 生成学习报告
    await self.generate_learning_report(patterns)
```

## 知识验证

```python
async def validate_knowledge(self, knowledge):
    """验证知识的正确性"""
    # 1. 一致性检查
    conflicts = await self.check_consistency(knowledge)

    # 2. 可验证性检查
    verifiable = await self.check_verifiable(knowledge)

    # 3. 实用性检查
    useful = await self.check_usefulness(knowledge)

    if conflicts or not verifiable or not useful:
        return {"status": "rejected", "reason": ...}

    return {"status": "approved", "confidence": ...}
```

## 学习历史

```sql
-- 学习历史查询
SELECT
    date_trunc('day', created_at) as day,
    count(*) as events_processed,
    array_agg(DISTINCT type) as event_types,
    count(*) FILTER WHERE extracted_knowledge IS NOT NULL as knowledge_extracted
FROM learning_events
WHERE created_at > time::now() - 30d
GROUP BY day
ORDER BY day;
```

## 与其他组件集成

```python
# 与MemoryKeeper集成
async def update_memory(self, knowledge):
    """更新记忆库"""
    await memory_keeper.add_knowledge(
        type=knowledge.type,
        content=knowledge.content,
        source=knowledge.source_events
    )

# 与ProfileManager集成
async def update_profile(self, learning_result):
    """更新用户画像"""
    await profile_manager.update_skills(
        skill_changes=learning_result.skill_improvements
    )

# 与Skill Creator集成
async def improve_skill(self, lesson):
    """改进技能"""
    await skill_creator.improve(
        skill_id=lesson.related_skill,
        improvements=lesson.improvements
    )
```

## 学习效率指标

- 知识提取成功率
- 知识验证通过率
- 知识应用效果
- 学习速度
