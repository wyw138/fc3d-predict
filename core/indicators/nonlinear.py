"""非线性动力学指标：Hurst指数、BDS检验"""

import math
from collections import defaultdict


def hurst_exponent(series: list[float], max_lag: int = 20) -> float:
    """
    计算 Hurst 指数（R/S 分析法）
    H ≈ 0.5 → 随机游走
    H > 0.5 → 有趋势/长程记忆
    H < 0.5 → 均值回归
    """
    n = len(series)
    if n < max_lag:
        max_lag = n // 2
    if max_lag < 4:
        return 0.5

    lags = range(2, max_lag + 1)
    rs_values = []
    for lag in lags:
        segments = n // lag
        rs_list = []
        for s in range(segments):
            chunk = series[s * lag:(s + 1) * lag]
            mean = sum(chunk) / len(chunk)
            deviations = [x - mean for x in chunk]
            cum_dev = []
            running = 0
            for dev in deviations:
                running += dev
                cum_dev.append(running)
            r = max(cum_dev) - min(cum_dev)
            std = (sum(d ** 2 for d in deviations) / len(deviations)) ** 0.5
            if std > 0:
                rs_list.append(r / std)
        if rs_list:
            rs_values.append((math.log(lag), math.log(sum(rs_list) / len(rs_list))))

    if len(rs_values) < 3:
        return 0.5
    # 线性回归求斜率 = Hurst 指数
    x_vals = [x for x, _ in rs_values]
    y_vals = [y for _, y in rs_values]
    n_pts = len(x_vals)
    mean_x = sum(x_vals) / n_pts
    mean_y = sum(y_vals) / n_pts
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals))
    den = sum((x - mean_x) ** 2 for x in x_vals)
    return num / den if den > 0 else 0.5


def bds_test(series: list[float], m: int = 3, epsilon: float = None) -> dict:
    """
    BDS 检验：检验序列是否为 i.i.d.
    返回统计量和近似的解释
    简化实现，仅做相关性检验的 proxy
    """
    n = len(series)
    if epsilon is None:
        epsilon = (sum((x - sum(series) / n) ** 2 for x in series) / n) ** 0.5
    if n < m * 2:
        return {"统计量": 0, "p_value_approx": 1.0, "解释": "数据不足"}

    # 构建嵌入向量
    def correlation(dim: int) -> float:
        vectors = []
        for i in range(n - dim + 1):
            vectors.append(tuple(series[i:i + dim]))
        count = 0
        total = len(vectors) * (len(vectors) - 1) / 2
        if total == 0:
            return 0
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                if all(abs(vectors[i][k] - vectors[j][k]) < epsilon for k in range(dim)):
                    count += 1
        return count / total

    c_m = correlation(m)
    c_1 = correlation(1)
    w = (n ** 0.5) * (c_m - c_1 ** m)
    # 简化版 p-value 近似（正态假设）
    # w ~ N(0, σ²)，此处仅报统计量
    return {
        "统计量": round(w, 4),
        "解释": "|w|>1.96 → 拒绝i.i.d.假设（可能存在依赖关系）" if abs(w) > 1.96 else "无法拒绝i.i.d.假设",
        "iid_likely": abs(w) <= 1.96,
    }


def approximate_entropy(series: list[float], m: int = 2, r: float = None) -> float:
    """近似熵：衡量序列的不可预测程度"""
    n = len(series)
    if r is None:
        r = 0.2 * (sum((x - sum(series) / n) ** 2 for x in series) / n) ** 0.5

    def phi(dim):
        patterns = []
        for i in range(n - dim + 1):
            patterns.append(tuple(series[i:i + dim]))
        count = 0
        for i in range(len(patterns)):
            for j in range(i + 1, len(patterns)):
                if all(abs(patterns[i][k] - patterns[j][k]) <= r for k in range(dim)):
                    count += 1
        total = len(patterns) * (len(patterns) - 1) / 2
        return math.log(count / total) if count > 0 and total > 0 else 0

    return phi(m) - phi(m + 1)
