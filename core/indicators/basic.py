"""基础指标：频率、遗漏、直接号码频率"""

from collections import Counter


def digit_frequency(data: list[dict], position: str = "all") -> Counter:
    """0-9 各数字出现频率统计。position: all | bai | shi | ge"""
    key = {"bai": "百位", "shi": "十位", "ge": "个位"}.get(position)
    if key:
        return Counter(d[key] for d in data)
    return Counter(d["百位"] for d in data) + \
           Counter(d["十位"] for d in data) + \
           Counter(d["个位"] for d in data)


def code_frequency(data: list[dict], top_n: int = 20) -> list[tuple[str, int]]:
    """直接号码 (000-999) 出现频率 Top-N"""
    return Counter(d["号码"] for d in data).most_common(top_n)


def missing_since(data: list[dict], position: str = "all") -> dict[int, int]:
    """每个数字距离最近一次出现隔了多少期"""
    key = {"bai": "百位", "shi": "十位", "ge": "个位"}.get(position)
    missing = {}
    total = len(data)
    for d in range(10):
        if key:
            arr = [r[key] for r in data]
            try:
                missing[d] = arr.index(d)
            except ValueError:
                missing[d] = total
        else:
            # 所有位置中最近的一次
            min_idx = total
            for k in ("百位", "十位", "个位"):
                arr = [r[k] for r in data]
                try:
                    idx = arr.index(d)
                    min_idx = min(min_idx, idx)
                except ValueError:
                    pass
            missing[d] = min_idx if min_idx < total else total
    return missing


def hot_warm_cold(data: list[dict], window: int = 7) -> dict[str, list[int]]:
    """热温冷分析：近 window 期出现>2=热, =2=温, <2=冷"""
    recent = data[:window]
    all_digits = []
    for r in recent:
        all_digits.extend([r["百位"], r["十位"], r["个位"]])
    freq = Counter(all_digits)
    hot = [d for d in range(10) if freq.get(d, 0) > 2]
    warm = [d for d in range(10) if freq.get(d, 0) == 2]
    cold = [d for d in range(10) if freq.get(d, 0) < 2]
    return {"热号": hot, "温号": warm, "冷号": cold}
