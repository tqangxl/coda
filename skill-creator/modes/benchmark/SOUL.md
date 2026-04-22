# Skill Creator - BENCHMARK模式

## 模式定义

BENCHMARK模式是Skill Creator的对比分析引擎，负责在多个方案间进行盲测对比，识别最佳实践并生成对比报告。

## 工作流程

```
方案列表 → 盲测评分 → 对比分析 → 排名输出 → 最佳实践提取
```

## 核心职责

### 1. 方案准备
- **方案收集**: 收集待对比的方案
- **匿名化处理**: 消除方案标识避免偏见
- **环境标准化**: 确保对比在相同环境进行
- **基线设定**: 设定对比基线

### 2. 盲测评分
- **统一评估**: 使用相同的评估标准
- **多维度评分**: 从多个维度评分
- **分数归一化**: 消除评分标准差异
- **异常检测**: 识别异常评分

### 3. 对比分析
- **横向对比**: 各维度横向比较
- **纵向分析**: 历史趋势分析
- **差异识别**: 识别方案间的关键差异
- **模式发现**: 发现成功的模式

### 4. 最佳实践提取
- **成功要素**: 识别成功的关键因素
- **失败教训**: 总结失败的教训
- **改进建议**: 基于对比提出改进建议
- **实践建议**: 生成可操作的实践建议

## Comparator对比器

Comparator是BENCHMARK模式的核心Agent，负责执行方案对比和模式分析。

### SurrealDB模型
```sql
-- Benchmark任务
DEFINE TABLE benchmark_tasks SCHEMAFULL;
DEFINE FIELD id ON benchmark_tasks TYPE string;
DEFINE FIELD name ON benchmark_tasks TYPE string;
DEFINE FIELD description ON benchmark_tasks TYPE string;
DEFINE FIELD solutions ON benchmark_tasks TYPE array;
DEFINE FIELD dimensions ON benchmark_tasks TYPE array;
DEFINE FIELD weights ON benchmark_tasks TYPE object;
DEFINE FIELD baseline_id ON benchmark_tasks TYPE option<string>;
DEFINE FIELD status ON benchmark_tasks TYPE string DEFAULT 'pending';
DEFINE FIELD created_at ON benchmark_tasks TYPE datetime;

-- 对比结果
DEFINE TABLE benchmark_results SCHEMAFULL;
DEFINE FIELD id ON benchmark_results TYPE string;
DEFINE FIELD benchmark_id ON benchmark_results TYPE string;
DEFINE FIELD solution_id ON benchmark_results TYPE string;
DEFINE FIELD scores ON benchmark_results TYPE object;
DEFINE FIELD overall_score ON benchmark_results TYPE float;
DEFINE FIELD rank ON benchmark_results TYPE int;
DEFINE FIELD strengths ON benchmark_results TYPE array;
DEFINE FIELD weaknesses ON benchmark_results TYPE array;
DEFINE FIELD executed_at ON benchmark_results TYPE datetime;

-- 方案对比
DEFINE TABLE solution_comparisons SCHEMAFULL;
DEFINE FIELD id ON solution_comparisons TYPE string;
DEFINE FIELD benchmark_id ON solution_comparisons TYPE string;
DEFINE FIELD solution_a ON solution_comparisons TYPE string;
DEFINE FIELD solution_b ON solution_comparisons TYPE string;
DEFINE FIELD dimension_scores ON solution_comparisons TYPE object;
DEFINE FIELD winner ON solution_comparisons TYPE string;
DEFINE FIELD key_differences ON solution_comparisons TYPE array;
```

### 评估维度定义

```yaml
dimensions:
  correctness:
    weight: 0.40
    metrics:
      - name: "test_pass_rate"
        weight: 0.60
      - name: "assertion_success"
        weight: 0.40

  performance:
    weight: 0.30
    metrics:
      - name: "execution_time"
        weight: 0.40
      - name: "memory_usage"
        weight: 0.30
      - name: "token_efficiency"
        weight: 0.30

  quality:
    weight: 0.20
    metrics:
      - name: "code_complexity"
        weight: 0.30
      - name: "documentation"
        weight: 0.30
      - name: "maintainability"
        weight: 0.40

  innovation:
    weight: 0.10
    metrics:
      - name: "novelty"
        weight: 0.50
      - name: "effectiveness"
        weight: 0.50
```

### 执行流程
```python
class SolutionComparator:
    async def benchmark(self, solutions, dimensions):
        # 1. 匿名化方案
        anonymized = self.anonymize(solutions)

        # 2. 并行评估每个方案
        results = await asyncio.gather(*[
            self.evaluate_solution(sol, dimensions)
            for sol in anonymized
        ])

        # 3. 归一化分数
        normalized = self.normalize_scores(results)

        # 4. 计算加权总分
        ranked = self.calculate_weighted_scores(normalized, dimensions)

        # 5. 成对比较
        comparisons = self.pairwise_compare(ranked)

        # 6. 提取最佳实践
        best_practices = self.extract_best_practices(
            ranked,
            comparisons
        )

        return {
            "rankings": ranked,
            "comparisons": comparisons,
            "best_practices": best_practices
        }
```

### 盲测流程

```python
def anonymize(self, solutions):
    """匿名化方案"""
    return [
        {
            "id": f"solution_{i}",
            "content": sol.content,
            "hidden_metadata": {
                "author": "anonymous",
                "version": "unknown",
                "generation_time": "unknown"
            }
        }
        for i, sol in enumerate(solutions)
    ]
```

### 评分归一化

```python
def normalize_scores(self, results):
    """Min-Max归一化"""
    all_scores = {}
    for result in results:
        for dim, score in result.dimensions.items():
            if dim not in all_scores:
                all_scores[dim] = []
            all_scores[dim].append(score)

    normalized = []
    for result in results:
        norm_result = {"id": result.id}
        for dim, scores in all_scores.items():
            min_s, max_s = min(scores), max(scores)
            if max_s > min_s:
                norm_result[dim] = (result.dimensions[dim] - min_s) / (max_s - min_s)
            else:
                norm_result[dim] = 1.0
        normalized.append(norm_result)

    return normalized
```

### 加权总分计算

```python
def calculate_weighted_scores(self, normalized, dimensions):
    """计算加权总分"""
    results = []
    for item in normalized:
        total_score = 0
        for dim, weight in dimensions.weights.items():
            total_score += item.get(dim, 0) * weight

        results.append({
            "id": item["id"],
            "dimensions": item,
            "overall_score": total_score
        })

    return sorted(results, key=lambda x: x["overall_score"], reverse=True)
```

## 对比报告格式

```json
{
  "benchmark_id": "bench_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "solutions_count": 5,
  "rankings": [
    {
      "rank": 1,
      "solution_id": "solution_2",
      "overall_score": 0.92,
      "dimensions": {
        "correctness": 0.95,
        "performance": 0.88,
        "quality": 0.90,
        "innovation": 0.85
      },
      "strengths": [
        "测试通过率最高",
        "代码质量优秀"
      ],
      "weaknesses": [
        "执行时间略长"
      ]
    },
    {
      "rank": 2,
      "solution_id": "solution_0",
      "overall_score": 0.87,
      ...
    }
  ],
  "pairwise_comparisons": [
    {
      "solution_a": "solution_2",
      "solution_b": "solution_0",
      "winner": "solution_2",
      "win_margin": 0.05,
      "key_differences": [
        "solution_2在正确性上显著优于solution_0",
        "solution_0在性能上略有优势"
      ]
    }
  ],
  "best_practices": {
    "code_structure": [
      "使用类型提示提高可读性",
      "模块化设计降低耦合"
    ],
    "error_handling": [
      "统一的异常处理模式",
      "详细的错误信息"
    ],
    "performance": [
      "避免重复计算",
      "使用缓存优化"
    ]
  },
  "recommendations": [
    {
      "priority": "high",
      "action": "采用solution_2的错误处理模式"
    },
    {
      "priority": "medium",
      "action": "优化solution_2的执行时间"
    }
  ]
}
```

## 最佳实践提取

### 模式发现算法
```python
def extract_best_practices(self, ranked, comparisons):
    """从对比结果中提取最佳实践"""
    # 1. 从TOP方案中提取共同特征
    top_features = self.extract_common_features(ranked[:2])

    # 2. 分析胜出方案的优势
    winning_advantages = self.analyze_winning_advantages(comparisons)

    # 3. 分析失败方案的教训
    failure_lessons = self.analyze_failure_lessons(comparisons)

    # 4. 生成实践建议
    practices = self.generate_practices(
        top_features,
        winning_advantages,
        failure_lessons
    )

    return {
        "successful_patterns": top_features,
        "key_success_factors": winning_advantages,
        "lessons_learned": failure_lessons,
        "actionable_recommendations": practices
    }
```

### 实践分类

```yaml
practices:
  code_style:
    - "一致的命名规范"
    - "统一的代码格式"

  architecture:
    - "清晰的模块边界"
    - "适当的抽象层次"

  error_handling:
    - "防御性编程"
    - "优雅的错误恢复"

  performance:
    - "必要的优化"
    - "避免过早优化"

  testing:
    - "高测试覆盖率"
    - "边界条件测试"
```

## 历史对比

### 趋势分析
```sql
SELECT
    date_trunc('day', executed_at) as day,
    avg(overall_score) as avg_score,
    max(overall_score) as best_score,
    min(overall_score) as worst_score,
    count(*) as total_benchmarks
FROM benchmark_results
WHERE timestamp > time::now() - 30d
GROUP BY day
ORDER BY day;
```

### 方案演进追踪
```sql
SELECT
    solution_id,
    array_agg(overall_score ORDER BY executed_at) as score_history,
    array_agg(overall_score ORDER BY executed_at)[0] as first_score,
    array_agg(overall_score ORDER BY executed_at)[-1] as latest_score,
    array_agg(overall_score ORDER BY executed_at)[-1] -
    array_agg(overall_score ORDER BY executed_at)[0] as improvement
FROM benchmark_results
WHERE solution_id IN $solution_ids
GROUP BY solution_id;
```

## 与其他模式集成

### 完整质量流程
```python
async def complete_quality_flow(tasks):
    # 1. 生成多个方案
    solutions = await generator.batch_create(tasks, count=3)

    # 2. 基准对比
    bench_result = await benchmark_mode.compare(solutions)

    # 3. 选择最佳方案
    best = bench_result.rankings[0]

    # 4. 进一步评估
    eval_result = await eval_mode.evaluate(best)

    # 5. 如需改进
    if eval_result.score < 0.9:
        improved = await improve_mode.improve(eval_result, best)
        return improved

    return best
```

### A/B测试集成
```python
async def ab_test(solution_a, solution_b, production_ratio=(0.5, 0.5)):
    """生产环境A/B测试"""
    # 1. 部署两个版本
    deploy("version_a", solution_a, ratio=production_ratio[0])
    deploy("version_b", solution_b, ratio=production_ratio[1])

    # 2. 收集指标
    metrics_a = collect_metrics("version_a")
    metrics_b = collect_metrics("version_b")

    # 3. 统计显著性分析
    significance = analyze_significance(metrics_a, metrics_b)

    # 4. 决策
    if significance.p_value < 0.05:
        winner = "a" if metrics_a.performance > metrics_b.performance else "b"
        return {"winner": winner, "confidence": significance.confidence}
```
