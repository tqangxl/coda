

# Skill Creator - Analyzer 分析器

## 角色定义

Analyzer是Skill Creator内部的分析Agent，负责深度分析评估和对比结果，发现隐藏模式，生成优化建议。

## 核心职责

### 1. 结果分析
- **模式识别**: 从大量结果中发现模式
- **趋势分析**: 分析历史表现趋势
- **异常检测**: 识别异常表现
- **关联分析**: 发现因素间的关联

### 2. 问题诊断
- **根因分析**: 找出问题的根本原因
- **影响评估**: 评估问题的影响范围
- **优先级排序**: 确定问题处理优先级
- **建议生成**: 生成可操作的改进建议

### 3. 最佳实践提取
- **成功要素**: 识别成功的关键因素
- **失败教训**: 总结失败的教训
- **模式推广**: 将成功模式推广

## SurrealDB模型

```sql
-- 分析任务
DEFINE TABLE analysis_tasks SCHEMAFULL;
DEFINE FIELD id ON analysis_tasks TYPE string;
DEFINE FIELD task_type ON analysis_tasks TYPE string;
DEFINE FIELD input_data ON analysis_tasks TYPE object;
DEFINE FIELD analysis_type ON analysis_tasks TYPE string;
DEFINE FIELD results ON analysis_tasks TYPE object;
DEFINE FIELD patterns ON analysis_tasks TYPE array;
DEFINE TABLE analysis_results SCHEMAFULL;
DEFINE FIELD id ON analysis_results TYPE string;
DEFINE FIELD task_id ON analysis_results TYPE string;
DEFINE FIELD pattern_type ON analysis_results TYPE string;
DEFINE FIELD description ON analysis_results TYPE string;
DEFINE FIELD evidence ON analysis_results TYPE array;
DEFINE FIELD confidence ON analysis_results TYPE float;
DEFINE FIELD impact ON analysis_results TYPE object;
DEFINE FIELD recommendations ON analysis_results TYPE array;
DEFINE FIELD analyzed_at ON analysis_results TYPE datetime;

-- 模式库
DEFINE TABLE pattern_library SCHEMAFULL;
DEFINE FIELD id ON pattern_library TYPE string;
DEFINE FIELD name ON pattern_library TYPE string;
DEFINE FIELD category ON pattern_library TYPE string;
DEFINE FIELD description ON pattern_library TYPE string;
DEFINE FIELD conditions ON pattern_library TYPE array;
DEFINE FIELD success_rate ON pattern_library TYPE float;
DEFINE FIELD frequency ON pattern_library TYPE int;
DEFINE FIELD last_used ON pattern_library TYPE datetime;
```

## 分析类型

### 1. 评估结果分析
```python
async def analyze_evaluation(self, eval_results):
    """分析评估结果"""
    # 1. 维度分析
    dimension_analysis = self.analyze_dimensions(eval_results)

    # 2. 趋势分析
    trend_analysis = self.analyze_trends(eval_results)

    # 3. 根因分析
    root_cause = self.find_root_causes(eval_results)

    # 4. 生成建议
    recommendations = self.generate_recommendations(
        dimension_analysis,
        trend_analysis,
        root_cause
    )

    return {
        "dimension_analysis": dimension_analysis,
        "trend_analysis": trend_analysis,
        "root_causes": root_cause,
        "recommendations": recommendations
    }
```

### 2. 对比结果分析
```python
async def analyze_comparison(self, comparison_results):
    """分析对比结果"""
    # 1. 成功要素提取
    success_factors = self.extract_success_factors(comparison_results)

    # 2. 关键差异识别
    key_differences = self.identify_key_differences(comparison_results)

    # 3. 最佳实践总结
    best_practices = self.summarize_best_practices(
        success_factors,
        key_differences
    )

    return {
        "success_factors": success_factors,
        "key_differences": key_differences,
        "best_practices": best_practices
    }
```

## 模式识别算法

### 聚类分析
```python
from sklearn.cluster import KMeans

def identify_patterns(self, data_points):
    """使用K-Means识别模式"""
    # 特征提取
    features = self.extract_features(data_points)

    # 聚类
    kmeans = KMeans(n_clusters=5, random_state=42)
    clusters = kmeans.fit_predict(features)

    # 分析每个聚类
    patterns = []
    for i in range(5):
        cluster_points = [p for p, c in zip(data_points, clusters) if c == i]
        pattern = self.analyze_cluster(cluster_points, i)
        patterns.append(pattern)

    return patterns
```

### 关联规则挖掘
```python
def find_associations(self, data):
    """发现数据间的关联"""
    # 转换为事务格式
    transactions = self.to_transactions(data)

    # 挖掘关联规则
    rules = apriori(transactions, min_support=0.1, min_confidence=0.8)

    # 格式化结果
    return [
        {
            "antecedent": list(rule.lhs),
            "consequent": list(rule.rhs),
            "support": rule.support,
            "confidence": rule.confidence
        }
        for rule in rules
    ]
```

## 趋势分析

```python
def analyze_trends(self, historical_data):
    """分析历史趋势"""
    # 1. 时间序列分解
    decomposition = self.decompose_time_series(
        historical_data,
        period=7  # 周周期
    )

    # 2. 趋势检测
    trend = self.detect_trend(decomposition.trend)

    # 3. 季节性分析
    seasonality = self.analyze_seasonality(decomposition.seasonal)

    # 4. 异常检测
    anomalies = self.detect_anomalies(decomposition.residuals)

    return {
        "trend": trend,  # increasing, decreasing, stable
        "trend_value": decomposition.trend,
        "seasonality": seasonality,
        "anomalies": anomalies,
        "forecast": self.forecast(decomposition)
    }
```

## 根因分析

### 5 Why分析
```python
def five_why_analysis(self, problem):
    """5 Why根因分析"""
    root_cause = problem
    whys = []

    for i in range(5):
        why_question = f"为什么{i+1}: {root_cause}"
        possible_causes = self.find_possible_causes(root_cause)
        selected_cause = self.select_most_likely(possible_causes)

        whys.append({
            "level": i + 1,
            "question": why_question,
            "cause": selected_cause
        })

        root_cause = selected_cause

    return {
        "problem": problem,
        "root_cause": root_cause,
        "whys": whys
    }
```

### 鱼骨图分析
```python
def fishbone_analysis(self, problem):
    """鱼骨图分析"""
    categories = [
        "人",  # People
        "机器",  # Machine
        "方法",  # Method
        "材料",  # Material
        "测量",  # Measurement
        "环境"   # Environment
    ]

    causes = {}
    for category in categories:
        causes[category] = self.find_causes_in_category(
            problem,
            category
        )

    return {
        "effect": problem,
        "causes": causes
    }
```

## 分析报告格式

```json
{
  "analysis_id": "analysis_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "analysis_type": "evaluation_summary",

  "patterns_identified": [
    {
      "pattern_id": "pattern_001",
      "type": "performance_degradation",
      "description": "在处理大数据集时性能显著下降",
      "confidence": 0.92,
      "evidence": [
        "数据集>10000条时响应时间增加300%",
        "内存使用量与数据量呈线性关系"
      ],
      "impact": {
        "severity": "high",
        "affected_tasks": 45,
        "estimated_cost": 120
      },
      "recommendations": [
        "实现分页处理",
        "增加缓存机制"
      ]
    }
  ],

  "trends": {
    "overall_quality": {
      "direction": "improving",
      "change_rate": 0.05,
      "confidence": 0.85
    },
    "execution_time": {
      "direction": "stable",
      "change_rate": -0.02,
      "confidence": 0.78
    }
  },

  "root_causes": [
    {
      "cause": "缺少数据预处理优化",
      "evidence_count": 3,
      "affected_metrics": ["performance", "efficiency"]
    }
  ],

  "recommendations": [
    {
      "priority": "high",
      "action": "优化数据处理流程",
      "expected_improvement": 0.15,
      "effort": "medium"
    }
  ]
}
```

## 与其他Agent协作

```python
# IMPROVE模式调用Analyzer
async def improve_with_analysis(eval_result):
    # Analyzer分析评估结果
    analysis = await analyzer.analyze_evaluation(eval_result)

    # 基于分析生成改进计划
    improvement_plan = create_plan(analysis.recommendations)

    return improvement_plan

# Benchmark模式调用Analyzer
async def extract_best_practices(comparison_result):
    # Analyzer提取最佳实践
    practices = await analyzer.extract_best_practices(comparison_result)

    return practices
```

## 模式库更新

```python
async def update_pattern_library(self, new_patterns):
    """更新模式库"""
    for pattern in new_patterns:
        # 检查是否已存在
        existing = await self.find_similar_pattern(pattern)

        if existing:
            # 更新现有模式
            existing.success_rate = (
                existing.success_rate * existing.frequency +
                pattern.success_rate
            ) / (existing.frequency + 1)
            existing.frequency += 1
            await self.save(existing)
        else:
            # 添加新模式
            await self.add_pattern(pattern)
```
