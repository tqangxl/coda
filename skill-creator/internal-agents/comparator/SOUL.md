# Skill Creator - Comparator 对比器

## 角色定义

Comparator是Skill Creator内部的对比Agent，负责在多个方案间进行横向对比，识别差异并生成对比报告。

## 核心职责

### 1. 方案对比
- **横向对比**: 多个方案同一维度对比
- **成对比较**: 两两方案详细对比
- **差异识别**: 识别方案间的关键差异
- **优势分析**: 分析各方案的优势

### 2. 排名计算
- **多维度评分**: 各维度分别评分
- **归一化处理**: 消除评分标准差异
- **加权排名**: 按权重计算综合排名
- **稳定性分析**: 分析排名的稳定性

### 3. 报告生成
- **对比报告**: 生成详细的对比报告
- **可视化数据**: 生成对比可视化数据
- **建议输出**: 基于对比给出建议

## SurrealDB模型

```sql
-- 对比任务
DEFINE TABLE comparison_tasks SCHEMAFULL;
DEFINE FIELD id ON comparison_tasks TYPE string;
DEFINE FIELD name ON comparison_tasks TYPE string;
DEFINE FIELD solutions ON comparison_tasks TYPE array;
DEFINE FIELD dimensions ON comparison_tasks TYPE array;
DEFINE FIELD weights ON comparison_tasks TYPE object;
DEFINE FIELD baseline_id ON comparison_tasks TYPE option<string>;
DEFINE FIELD status ON comparison_tasks TYPE string DEFAULT 'pending';
DEFINE FIELD created_at ON comparison_tasks TYPE datetime;

-- 方案评分
DEFINE TABLE solution_scores SCHEMAFULL;
DEFINE FIELD id ON solution_scores TYPE string;
DEFINE FIELD comparison_id ON solution_scores TYPE string;
DEFINE FIELD solution_id ON solution_scores TYPE string;
DEFINE FIELD anonymized_id ON solution_scores TYPE string;
DEFINE FIELD dimension_scores ON solution_scores TYPE object;
DEFINE FIELD overall_score ON solution_scores TYPE float;
DEFINE FIELD rank ON solution_scores TYPE int;
DEFINE FIELD strengths ON solution_scores TYPE array;
DEFINE FIELD weaknesses ON solution_scores TYPE array;

-- 成对对比
DEFINE TABLE pairwise_comparisons SCHEMAFULL;
DEFINE FIELD id ON pairwise_comparisons TYPE string;
DEFINE FIELD comparison_id ON pairwise_comparisons TYPE string;
DEFINE FIELD solution_a ON pairwise_comparisons TYPE string;
DEFINE FIELD solution_b ON pairwise_comparisons TYPE string;
DEFINE FIELD dimension_winners ON pairwise_comparisons TYPE object;
DEFINE FIELD overall_winner ON pairwise_comparisons TYPE string;
DEFINE FIELD win_margin ON pairwise_comparisons TYPE float;
DEFINE FIELD key_differences ON pairwise_comparisons TYPE array;
```

## 对比流程

```python
class Comparator:
    async def compare(self, solutions, dimensions):
        # 1. 匿名化处理
        anonymized = self.anonymize(solutions)

        # 2. 多维度评分
        scores = await self.score_all_dimensions(
            anonymized,
            dimensions
        )

        # 3. 归一化分数
        normalized = self.normalize_scores(scores)

        # 4. 计算综合排名
        rankings = self.calculate_rankings(normalized, dimensions.weights)

        # 5. 成对对比
        pairwise = self.perform_pairwise_comparisons(rankings)

        # 6. 生成报告
        report = self.generate_comparison_report(
            rankings,
            pairwise,
            dimensions
        )

        return report
```

## 匿名化处理

```python
def anonymize(self, solutions):
    """消除偏见，确保公平对比"""
    import hashlib

    anonymized = []
    for i, sol in enumerate(solutions):
        # 生成随机标识
        random_id = hashlib.md5(f"{sol.id}_{i}_{time.time()}".encode()).hexdigest()[:8]

        anonymized.append({
            "anonymized_id": f"方案_{chr(65+i)}",  # 方案A, 方案B, ...
            "content": sol.content,
            "hidden": {
                "original_id": sol.id,
                "author": "anonymous",
                "generation_time": "unknown"
            }
        })

    return anonymized
```

## 归一化处理

```python
def normalize_scores(self, scores):
    """Min-Max归一化"""
    normalized = {}

    for dim in scores[0].dimension_scores.keys():
        values = [s.dimension_scores[dim] for s in scores]
        min_val, max_val = min(values), max(values)

        for s in scores:
            if max_val > min_val:
                normalized.setdefault(s.anonymized_id, {})[dim] = \
                    (s.dimension_scores[dim] - min_val) / (max_val - min_val)
            else:
                normalized.setdefault(s.anonymized_id, {})[dim] = 1.0

    return normalized
```

## 加权排名

```python
def calculate_rankings(self, normalized_scores, weights):
    """计算加权综合得分并排名"""
    rankings = []

    for sol_id, scores in normalized_scores.items():
        # 计算加权总分
        total_score = sum(
            scores.get(dim, 0) * weights.get(dim, 0)
            for dim in weights.keys()
        )

        rankings.append({
            "solution_id": sol_id,
            "scores": scores,
            "overall_score": total_score
        })

    # 按总分排序
    rankings.sort(key=lambda x: x["overall_score"], reverse=True)

    # 添加排名
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    return rankings
```

## 成对对比

```python
def perform_pairwise_comparisons(self, rankings):
    """两两方案对比"""
    comparisons = []

    for i, sol_a in enumerate(rankings):
        for sol_b in rankings[i+1:]:
            comparison = {
                "solution_a": sol_a["solution_id"],
                "solution_b": sol_b["solution_id"],
                "dimension_winners": {},
                "overall_winner": None,
                "win_margin": 0
            }

            # 各维度对比
            for dim in sol_a["scores"].keys():
                if sol_a["scores"][dim] > sol_b["scores"][dim]:
                    comparison["dimension_winners"][dim] = sol_a["solution_id"]
                elif sol_b["scores"][dim] > sol_a["scores"][dim]:
                    comparison["dimension_winners"][dim] = sol_b["solution_id"]
                else:
                    comparison["dimension_winners"][dim] = "tie"

            # 总体胜出
            if sol_a["overall_score"] > sol_b["overall_score"]:
                comparison["overall_winner"] = sol_a["solution_id"]
                comparison["win_margin"] = sol_a["overall_score"] - sol_b["overall_score"]
            else:
                comparison["overall_winner"] = sol_b["solution_id"]
                comparison["win_margin"] = sol_b["overall_score"] - sol_a["overall_score"]

            comparisons.append(comparison)

    return comparisons
```

## 对比报告格式

```json
{
  "comparison_id": "comp_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "solutions_count": 4,
  "dimensions": ["correctness", "performance", "quality"],

  "rankings": [
    {
      "rank": 1,
      "solution_id": "方案A",
      "overall_score": 0.92,
      "scores": {
        "correctness": 0.95,
        "performance": 0.88,
        "quality": 0.92
      },
      "strengths": [
        "正确性最高",
        "质量优秀"
      ],
      "weaknesses": [
        "性能略低于方案C"
      ]
    }
  ],

  "pairwise_comparisons": [
    {
      "solution_a": "方案A",
      "solution_b": "方案B",
      "dimension_winners": {
        "correctness": "方案A",
        "performance": "方案A",
        "quality": "方案B"
      },
      "overall_winner": "方案A",
      "win_margin": 0.12,
      "key_differences": [
        "方案A在正确性和性能上显著优于方案B",
        "方案B在代码质量上略有优势"
      ]
    }
  ],

  "summary": {
    "best_overall": "方案A",
    "best_correctness": "方案A",
    "best_performance": "方案C",
    "best_quality": "方案B"
  }
}
```

## 统计显著性

```python
def analyze_significance(self, comparison_results):
    """分析对比结果的统计显著性"""
    # 计算置信区间
    confidence_interval = self.calculate_confidence_interval(
        comparison_results
    )

    # 判断显著性
    is_significant = confidence_interval > 0.95

    return {
        "is_significant": is_significant,
        "confidence_level": confidence_interval,
        "p_value": self.calculate_p_value(comparison_results)
    }
```

## 与其他Agent协作

```python
# Benchmark模式调用Comparator
async def benchmark_solutions(solutions):
    # 调用Comparator进行对比
    comparison = await comparator.compare(
        solutions,
        get_benchmark_dimensions()
    )

    # 提取最佳实践
    best_practices = await analyzer.extract_patterns(comparison)

    return {
        "comparison": comparison,
        "best_practices": best_practices
    }
```
