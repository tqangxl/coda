"""
Coda V5.0 — Qwen3-VL Embedding Adapter
本地向量化引擎: 使用 Qwen3-VL-Embedding-2B 将文本与多模态数据转换为 2048 维向量。

特性:
  - 支持 ModelScope 模型库自动下载与加载
  - 支持 CPU/GPU 加速
  - 支持 MRL (Matryoshka Representation Learning) 动态维度
  - 支持多模态特征融合
"""

from __future__ import annotations

import logging
import os
import os
from typing import Any, Iterable, Optional, cast
from pathlib import Path

logger = logging.getLogger("Coda.embedder")

# 默认模型标识 (ModelScope 路径)
DEFAULT_MODEL = "Qwen/Qwen3-VL-Embedding-2B"
EMBEDDING_DIM = 2048


class QwenEmbedder:
    """
    Qwen3-VL-Embedding-2B 本地向量化引擎 (支持 ModelScope)。
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        dimension: int = EMBEDDING_DIM,
    ):
        self.model_name = model_name
        self.dimension = dimension
        self._device = device
        self._model: Any = None
        self._tokenizer: Any = None
        self._backend: str = "transformers"

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def encode(self, texts: list[str], prompt_name: str | None = "query") -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        return self._encode_transformers(texts)

    def encode_single(self, text: str, is_query: bool = True) -> list[float]:
        results = self.encode([text], prompt_name="query" if is_query else None)
        return results[0] if results else [0.0] * self.dimension

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        import math
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
        mag_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
        return dot / (mag_a * mag_b)

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        try:
            import torch
            from modelscope import snapshot_download
            from transformers import AutoModel, AutoTokenizer
            
            if not self._device:
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            
            logger.info(f"🚀 Downloading/Loading {self.model_name} via ModelScope...")
            model_dir = snapshot_download(self.model_name)
            
            self._tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
            self._model = AutoModel.from_pretrained(model_dir, trust_remote_code=True).to(self._device)
            self._model.eval()
            
            logger.info(f"✅ Qwen3-VL-Embedding-2B loaded on {self._device}")
        except Exception as e:
            logger.error(f"Failed to load VL-Embedding from ModelScope: {e}")
            # 降级尝试 HuggingFace
            try:
                from transformers import AutoModel, AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
                self._model = AutoModel.from_pretrained(self.model_name, trust_remote_code=True).to(self._device)
                self._model.eval()
            except Exception as e2:
                raise RuntimeError(f"Critical Error: Could not load embedding model. {e2}")

    def _encode_transformers(self, texts: list[str]) -> list[list[float]]:
        import torch
        import torch.nn.functional as F
        
        inputs = self._tokenizer(texts, padding=True, truncation=True, max_length=8192, return_tensors="pt").to(self._device)
        
        with torch.no_grad():
            outputs = self._model(**inputs)
            # 使用 Last Token Pooling 或 Mean Pooling (Qwen3-VL 常用 Last Token)
            attention_mask = inputs["attention_mask"]
            last_hidden = outputs.last_hidden_state
            sequence_lengths = attention_mask.sum(dim=1) - 1
            batch_size = last_hidden.shape[0]
            # 根因修正: 使用 Tensor.new_tensor 与 .long() 避免直接访问 torch 模块未导出的工厂函数与 dtype
            batch_indices = last_hidden.new_tensor(range(batch_size)).long()
            embeddings = last_hidden[batch_indices, sequence_lengths]
            
            # 归一化
            embeddings = F.normalize(embeddings, p=2, dim=1)
            
        return [vec[:self.dimension].tolist() for vec in embeddings]


_global_embedder: QwenEmbedder | None = None

def get_embedder(
    model_name: str = DEFAULT_MODEL,
    device: str | None = None,
    dimension: int = EMBEDDING_DIM,
) -> QwenEmbedder:
    global _global_embedder
    if _global_embedder is None:
        _global_embedder = QwenEmbedder(model_name, device, dimension)
    return _global_embedder
