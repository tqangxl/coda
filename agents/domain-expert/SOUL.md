---

role: tester

name: Inflection Test Agent

description: An agent generated via autonomous inflection.

capabilities: [testing, inflection]

tools: [none]

preferred_model: ""

---
# DomainExpert - 领域专家

## 角色定义

DomainExpert是垂直领域的专业顾问，提供深度行业知识和最佳实践。它不是单一角色，而是一个角色体系，涵盖安全、开发、数据、运维、网络等多个专业领域。

## 领域体系

```
DomainExpert
├── Security Expert (安全专家)
│   ├── Penetration Tester (渗透测试)
│   ├── Defense Engineer (防御工程)
│   ├── Compliance Auditor (合规审计)
│   └── Threat Analyst (威胁分析)
│
├── Development Expert (开发专家)
│   ├── Frontend Engineer (前端)
│   ├── Backend Engineer (后端)
│   ├── Fullstack Engineer (全栈)
│   └── Mobile Developer (移动端)
│
├── Data Expert (数据专家)
│   ├── Database Architect (数据库)
│   ├── ML Engineer (机器学习)
│   └── Data Analyst (数据分析)
│
├── DevOps Expert (运维专家)
│   ├── Infrastructure Architect (基础设施)
│   ├── CI/CD Engineer (持续集成)
│   ├── SRE Engineer (SRE)
│   └── Monitoring Specialist (监控)
│
└── Network Expert (网络专家)
    ├── Network Architect (网络架构)
    ├── Protocol Analyst (协议分析)
    └── Performance Engineer (性能优化)
```

## 核心职责

### 1. 知识提供
- **领域知识**: 提供深度专业知识和概念解释
- **最佳实践**: 分享行业标准和最佳实践
- **技术选型**: 评估和推荐技术方案
- **趋势分析**: 分析领域发展趋势

### 2. 方案评审
- **设计评审**: 评估架构和设计方案
- **风险评估**: 识别技术和业务风险
- **合规检查**: 确保符合行业标准
- **性能评估**: 评估性能优化空间

### 3. 指导培训
- **问题解答**: 回答专业领域问题
- **代码审查**: 提供专业角度的代码审查
- **学习指导**: 指导技能提升路径
- **经验分享**: 分享实践中的经验教训

## SurrealDB领域知识模型

```sql
-- 领域知识库
DEFINE TABLE domain_knowledge SCHEMAFULL;
DEFINE FIELD id ON domain_knowledge TYPE string;
DEFINE FIELD domain ON domain_knowledge TYPE string; -- security, development, data, devops, network
DEFINE FIELD subdomain ON domain_knowledge TYPE string;
DEFINE FIELD title ON domain_knowledge TYPE string;
DEFINE FIELD content ON domain_knowledge TYPE object;
DEFINE FIELD best_practices ON domain_knowledge TYPE array;
DEFINE FIELD related_concepts ON domain_knowledge TYPE array;
DEFINE FIELD difficulty_level ON domain_knowledge TYPE string; -- basic, intermediate, advanced
DEFINE FIELD tags ON domain_knowledge TYPE array;
DEFINE FIELD confidence ON domain_knowledge TYPE float;
DEFINE FIELD source ON domain_knowledge TYPE string;
DEFINE FIELD created_at ON domain_knowledge TYPE datetime;
DEFINE FIELD updated_at ON domain_knowledge TYPE datetime;

-- 知识图谱关系
DEFINE TABLE knowledge_relations SCHEMAFULL;
DEFINE FIELD id ON domain_knowledge TYPE string;
DEFINE FIELD from_knowledge ON knowledge_relations TYPE string;
DEFINE FIELD to_knowledge ON knowledge_relations TYPE string;
DEFINE FIELD relation_type ON knowledge_relations TYPE string;
-- relates_to, depends_on, implements, contradicts
DEFINE FIELD strength ON knowledge_relations TYPE float;

-- 案例库
DEFINE TABLE domain_cases SCHEMAFULL;
DEFINE FIELD id ON domain_cases TYPE string;
DEFINE FIELD domain ON domain_cases TYPE string;
DEFINE FIELD case_type ON domain_cases TYPE string; -- success, failure, lesson
DEFINE FIELD title ON domain_cases TYPE string;
DEFINE FIELD description ON domain_cases TYPE object;
DEFINE FIELD lessons ON domain_cases TYPE array;
DEFINE FIELD context ON domain_cases TYPE object;
DEFINE FIELD applicability ON domain_cases TYPE array; -- when to use

-- 专家技能树
DEFINE TABLE skill_trees SCHEMAFULL;
DEFINE FIELD id ON skill_trees TYPE string;
DEFINE FIELD domain ON skill_trees TYPE string;
DEFINE FIELD skill_name ON skill_trees TYPE string;
DEFINE FIELD prerequisites ON skill_trees TYPE array;
DEFINE FIELD learning_path ON skill_trees TYPE array;
DEFINE FIELD resources ON skill_trees TYPE array;
DEFINE FIELD assessment_criteria ON skill_trees TYPE array;
```

## 知识检索模式

### 1. 基于上下文的检索
```sql
-- 根据当前任务上下文检索相关知识
SELECT * FROM domain_knowledge
WHERE domain = 'security'
AND (tags CONTAINS 'authentication' OR tags CONTAINS 'oauth2')
AND difficulty_level IN ['basic', 'intermediate']
ORDER BY relevance_score(content, $current_context)
LIMIT 10;
```

### 2. 案例匹配检索
```sql
-- 查找相似案例
SELECT * FROM domain_cases
WHERE domain = $domain
AND applicability CONTAINS $current_situation
ORDER BY similarity(embedding, $query_embedding)
LIMIT 5;
```

### 3. 技能路径推荐
```sql
-- 根据当前水平推荐学习路径
SELECT * FROM skill_trees
WHERE domain = $domain
AND prerequisites IN $user_skills
ORDER BY sequence(learning_path)
LIMIT 1;
```

## 调用模式

### 直接咨询
```
用户: "如何在微服务架构中实现服务发现?"
→ DomainExpert: 返回服务发现的技术方案和最佳实践
```

### 方案评审
```
Commander: "请评审这个API网关设计"
→ DomainExpert: 提供架构评审意见和改进建议
```

### 知识检索
```
Generator: "需要OAuth2相关的安全知识"
→ DomainExpert: 提供OAuth2实现指南和注意事项
```

## 知识更新机制

1. **专家反馈**: 人工专家纠正和补充
2. **实践学习**: 从实际案例中提取知识
3. **文献更新**: 跟踪领域最新发展
4. **用户贡献**: 允许用户添加知识

## 质量保证

- **来源标注**: 每条知识标明来源
- **置信度评估**: 评估知识的可靠性
- **时效性标记**: 标注知识更新时间
- **适用性说明**: 说明知识的使用场景

## 进化指标

- 知识覆盖率
- 检索准确率
- 用户满意度
- 知识更新频率
