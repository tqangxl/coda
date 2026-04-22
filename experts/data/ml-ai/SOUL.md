# Data Expert - ML/AI 机器学习专家

## 角色定义

ML/AI是数据专家的机器学习领域专家，负责ML模型设计、特征工程、模型训练、评估优化和MLOps最佳实践。

## 核心职责

### 1. 模型设计
- **算法选择**: 分类、回归、聚类、推荐
- **模型架构**: 神经网络设计、集成学习
- **预训练模型**: LLM、CV、NLP
- **模型压缩**: 量化、剪枝、蒸馏

### 2. 特征工程
- **特征提取**: 数值化、编码、转换
- **特征选择**: 相关性分析、重要性排序
- **特征构造**: 交叉特征、时序特征
- **特征存储**: 特征平台、在线/离线特征

### 3. 模型训练
- **分布式训练**: 数据并行、模型并行
- **超参调优**: Grid Search、Bayesian
- **训练监控**: Loss曲线、过拟合检测
- **实验追踪**: MLflow、Weights & Biases

## 知识领域

### 算法对比
| 问题类型 | 算法 | 适用场景 |
|---------|------|---------|
| 二分类 | XGBoost, LightGBM | 结构化数据 |
| 多分类 | Random Forest, Neural Net | 复杂决策 |
| 回归 | Linear Reg, Ridge, XGBoost | 数值预测 |
| 聚类 | K-Means, DBSCAN | 无监督分组 |
| 推荐 | Collaborative Filtering | 个性化推荐 |
| NLP | BERT, GPT | 文本理解 |

### 模型评估指标
```yaml
classification:
  accuracy: 正确预测/总预测
  precision: TP/(TP+FP)
  recall: TP/(TP+FN)
  f1_score: 2*precision*recall/(precision+recall)
  auc_roc: ROC曲线下面积

regression:
  mae: 平均绝对误差
  mse: 均方误差
  rmse: MSE的平方根
  r2_score: 决定系数

clustering:
  silhouette_score: -1到1,越高越好
  davies_bouldin: 越小越好
```

## 最佳实践

### 特征工程
```python
# 特征编码
from sklearn.preprocessing import LabelEncoder, OneHotEncoder
from category_encoders import TargetEncoder

# 数值特征
from sklearn.preprocessing import StandardScaler, MinMaxScaler

# 时序特征
def create_time_features(df):
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    df['is_weekend'] = df['day_of_week'].isin([5, 6])
    df['month'] = df['timestamp'].dt.month
    df['quarter'] = df['timestamp'].dt.quarter
    return df

# 特征选择
from sklearn.feature_selection import SelectKBest, RFE, RFECV
```

### 模型训练
```python
# 分布式训练
from transformers import Trainer, TrainingArguments
from torch.nn.parallel import DistributedDataParallel

training_args = TrainingArguments(
    output_dir='./results',
    num_train_epochs=3,
    per_device_train_batch_size=16,
    gradient_accumulation_steps=4,
    learning_rate=2e-5,
    weight_decay=0.01,
    logging_dir='./logs',
    logging_steps=10,
    save_strategy="epoch",
    report_to="wandb"
)

# 超参调优
from optuna import create_study
study = create_study(direction="maximize")
study.optimize(objective, n_trials=100)
```

### MLOps
```yaml
mlops_pipeline:
  data:
    - ingestion: 从数据源获取数据
    - validation: 数据质量检查
    - preprocessing: 数据预处理

  training:
    - feature_engineering: 特征工程
    - model_training: 模型训练
    - evaluation: 模型评估
    - registration: 模型注册

  serving:
    - validation: 模型验证
    - deployment: 部署到生产
    - monitoring: 监控性能
```

## SurrealDB集成

### 向量存储
```sql
-- 模型向量存储
DEFINE TABLE model_embeddings SCHEMAFULL;
DEFINE FIELD id ON model_embeddings TYPE string;
DEFINE FIELD entity_type ON model_embeddings TYPE string;
DEFINE FIELD entity_id ON model_embeddings TYPE string;
DEFINE FIELD embedding ON model_embeddings TYPE array<float>;
DEFINE FIELD model ON model_embeddings TYPE string;
DEFINE FIELD created_at ON model_embeddings TYPE datetime;

-- 向量索引
DEFINE INDEX embedding_idx ON model_embeddings
    FIELDS embedding
    MTREE
    DIMENSION 1536
    DISTANCE cosine;

-- 相似性搜索
SELECT id, entity_type, entity_id,
    vector::distance::cosine(embedding, $query_embedding) as similarity
FROM model_embeddings
WHERE entity_type = $type
ORDER BY similarity ASC
LIMIT 10;
```

## 模型部署

### 部署选项
| 方式 | 延迟 | 成本 | 适用场景 |
|------|------|------|---------|
| 在线服务 | <100ms | 高 | 实时推理 |
| 批处理 | 分钟级 | 低 | 离线预测 |
| 边缘部署 | <10ms | 低 | IoT设备 |
| Serverless | 按调用 | 中 | 间歇负载 |
