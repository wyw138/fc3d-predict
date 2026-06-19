"""
温度采样 (Temperature Sampling) — 控制预测的确定性与多样性

原理（来自 LottoProphet + 深度学习温度采样）:
  temperature → 0: 仅取 Top-N（最确定、最少样化）
  temperature = 1: 按原始概率采样（自然分布）
  temperature → ∞: 趋近均匀随机（最不确定、最多样化）

用法: 对任何策略输出的 (号码, 分数/概率) 列表，施加温度后重新采样。
"""

import math
import random
from typing import Optional


def apply_temperature(
    scored_codes: list[tuple[str, float]],
    n: int = 5,
    temperature: float = 1.0,
    seed: Optional[int] = None,
) -> list[str]:
    """
    对加权分数列表施加温度采样。

    scored_codes: [(code, score), ...]  分数越高越优先
    temperature: 0=纯TopN, 1=概率采样, >5≈均匀
    """
    if not scored_codes:
        return []

    if seed is not None:
        random.seed(seed)

    if temperature <= 0.01:
        # 纯 Top-N
        codes_sorted = sorted(scored_codes, key=lambda x: -x[1])
        return [c for c, _ in codes_sorted[:n]]

    # 将 score 转换为概率: softmax(score / temperature)
    scores = [s for _, s in scored_codes]
    max_score = max(scores) if scores else 1
    # 数值稳定: exp((score - max) / temp)
    scaled = [math.exp((s - max_score) / temperature) for s in scores]
    total = sum(scaled)
    if total == 0:
        return [c for c, _ in scored_codes[:n]]

    probs = [s / total for s in scaled]
    codes = [c for c, _ in scored_codes]

    results = set()
    attempts = 0
    while len(results) < n and attempts < n * 10:
        code = random.choices(codes, weights=probs, k=1)[0]
        results.add(code)
        attempts += 1

    # 不够 n 个时从高到低补齐
    sorted_all = sorted(scored_codes, key=lambda x: -x[1])
    for code, _ in sorted_all:
        if len(results) >= n:
            break
        results.add(code)

    # 按原始分数排序输出
    score_map = {c: s for c, s in scored_codes}
    return sorted(results, key=lambda c: score_map.get(c, 0), reverse=True)[:n]


def temperature_sampling(
    codes: list[str],
    scores: list[float],
    n: int = 5,
    temperature: float = 0.5,
) -> list[str]:
    """简化接口：从 codes + scores 中按温度采样"""
    return apply_temperature(list(zip(codes, scores)), n, temperature)
