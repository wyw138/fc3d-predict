"""分布指标：和值、跨度、012路、AC值、和尾"""

from collections import Counter


def sum_distribution(data: list[dict]) -> dict[int, int]:
    """和值 0-27 分布"""
    cnt = Counter(d["和值"] for d in data)
    return {s: cnt.get(s, 0) for s in range(28)}


def span_distribution(data: list[dict]) -> dict[int, int]:
    """跨度 0-9 分布"""
    cnt = Counter(d["跨度"] for d in data)
    return {s: cnt.get(s, 0) for s in range(10)}


def sum_tail_distribution(data: list[dict]) -> dict[int, int]:
    """和尾 0-9 分布"""
    cnt = Counter(d["和值"] % 10 for d in data)
    return {t: cnt.get(t, 0) for t in range(10)}


def route_012_distribution(data: list[dict]) -> dict[str, Counter]:
    """012路分布：百/十/个位 + 整体"""
    routes = {"0路": [0, 3, 6, 9], "1路": [1, 4, 7], "2路": [2, 5, 8]}

    def classify(digit):
        for route_name, route_digits in routes.items():
            if digit in route_digits:
                return route_name
        return "?"

    results = {}
    for pos, key in [("百位", "bai"), ("十位", "shi"), ("个位", "ge")]:
        cnt = Counter(classify(d[pos]) for d in data)
        results[key] = cnt

    # 整体 012 路组合 (如 "102" 表示百1路+十0路+个2路)
    combo = Counter()
    for d in data:
        c = classify(d["百位"])[0] + classify(d["十位"])[0] + classify(d["个位"])[0]
        combo[c] += 1
    results["组合"] = combo
    return results


def ac_value(code: str) -> int:
    """计算单注号码的 AC 值（算术复杂度）"""
    digits = [int(c) for c in code]
    diffs = set()
    for i in range(3):
        for j in range(i + 1, 3):
            diffs.add(abs(digits[i] - digits[j]))
    return len(diffs) - 2  # 3D的AC值可能为0、1、2


def ac_distribution(data: list[dict]) -> dict[int, int]:
    """AC值分布"""
    cnt = Counter(ac_value(d["号码"]) for d in data)
    return {a: cnt.get(a, 0) for a in range(3)}
