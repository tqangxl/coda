from typing import Any
import re

def calculate_real_compute(text: str) -> int:
    """
    [Coda V5.1] 事实算力审计算法。
    通过字数密度和思维深度评估真实的“认知 Token”，而非 SDK 的通胀报告。
    """
    if not text:
        return 0
        
    # 1. 计算核心思维量 (Thought Weight)
    thought_match = re.search(r'<thought>(.*?)</thought>', text, re.DOTALL | re.IGNORECASE)
    thought_len = len(thought_match.group(1)) if thought_match else 0
    
    # 2. 计算字数分布 (Word-count based)
    chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', text))
    english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))
    
    # 3. 计算代码密度 (Code Block Weight)
    code_blocks = re.findall(r'```.*?```', text, re.DOTALL)
    code_len = sum(len(str(block)) for block in code_blocks)
    
    # [DPI 事实公式]
    # 事实算力 = (非思维字数 * 1.0) + (思维字数 * 0.5) + (代码量 * 0.2)
    base_chars = (chinese_chars + english_words) - (thought_len / 5)
    real_tokens = int(max(0, float(base_chars)) + (thought_len * 0.5) + (code_len * 0.2))
    
    return max(real_tokens, 1)

def audit_completion(content: str) -> dict[str, Any]:
    """对生成内容进行全面算力审计报告。"""
    real_tokens = calculate_real_compute(content)
    return {
        "real_tokens": real_tokens,
        "thought_ratio": float(round(1.0 if "<thought>" in content.lower() else 0.0, 2)),
        "code_density": float(round(len(re.findall(r'```', content)) / (len(content) + 1), 4))
    }
