"""
特征工程管线 — 滞后特征、滚动统计、交叉特征、位间关系特征
"""

from collections import defaultdict
from typing import Optional


def build_features(data: list[dict], target_idx: int = 0, lag_periods: list[int] = None,
                   roll_periods: list[int] = None) -> dict:
    """
    为 data[target_idx] 这一期构建预测特征。
    data 按期号降序排列: data[0] = 最新一期
    target_idx 越大表示越早（用于回测时模拟历史状态）
    """
    if lag_periods is None:
        lag_periods = [1, 2, 3, 5, 10]
    if roll_periods is None:
        roll_periods = [5, 10, 30]

    # 只使用 target_idx 之前（更早）的数据，避免未来信息泄露
    history = data[target_idx + 1:] if target_idx < len(data) - 1 else data[1:]

    features = {}

    # ── 滞后特征：前 N 期的各位数字 ──
    for lag in lag_periods:
        if lag <= len(history):
            d = history[lag - 1]
            features[f"lag{lag}_bai"] = d["百位"]
            features[f"lag{lag}_shi"] = d["十位"]
            features[f"lag{lag}_ge"] = d["个位"]
            features[f"lag{lag}_sum"] = d["和值"]
            features[f"lag{lag}_span"] = d["跨度"]
        else:
            for pos in ["bai", "shi", "ge", "sum", "span"]:
                features[f"lag{lag}_{pos}"] = -1

    # ── 滚动统计特征 ──
    digits_bai = [d["百位"] for d in history]
    digits_shi = [d["十位"] for d in history]
    digits_ge = [d["个位"] for d in history]
    sums = [d["和值"] for d in history]
    spans = [d["跨度"] for d in history]

    for period in roll_periods:
        window = min(period, len(history))
        if window > 0:
            for pos, arr in [("bai", digits_bai), ("shi", digits_shi), ("ge", digits_ge),
                             ("sum", sums), ("span", spans)]:
                w = arr[:window]
                features[f"roll{period}_{pos}_mean"] = sum(w) / len(w)
                features[f"roll{period}_{pos}_std"] = (
                    (sum((x - features[f"roll{period}_{pos}_mean"]) ** 2 for x in w) / len(w)) ** 0.5
                )

    # ── 频率特征：历史各数字出现频率 ──
    all_digits = digits_bai + digits_shi + digits_ge
    freq = defaultdict(int)
    for d in all_digits:
        freq[d] += 1
    total = len(all_digits) if all_digits else 1
    for d in range(10):
        features[f"freq_{d}"] = freq[d] / total

    # ── 遗漏特征 ──
    for pos, arr in [("bai", digits_bai), ("shi", digits_shi), ("ge", digits_ge)]:
        for d in range(10):
            try:
                missing = arr.index(d)
                features[f"missing_{pos}_{d}"] = missing
            except ValueError:
                features[f"missing_{pos}_{d}"] = len(arr)

    # ── 交叉特征 ──
    if len(history) >= 1:
        prev = history[0]
        features["cross_bai_shi"] = prev["百位"] * 10 + prev["十位"]
        features["cross_shi_ge"] = prev["十位"] * 10 + prev["个位"]

    return features
