"""振幅指标：定位振幅、和值振幅、跨度振幅、和尾振幅、位差位和、两码合差"""

from collections import Counter


def position_amplitude(data: list[dict]) -> list[dict]:
    """各位与上期的绝对值差"""
    results = []
    for i in range(len(data) - 1):
        results.append({
            "期号": data[i]["期号"],
            "百位振幅": abs(data[i]["百位"] - data[i + 1]["百位"]),
            "十位振幅": abs(data[i]["十位"] - data[i + 1]["十位"]),
            "个位振幅": abs(data[i]["个位"] - data[i + 1]["个位"]),
        })
    return results


def sum_amplitude(data: list[dict]) -> list[dict]:
    """和值振幅：本期和值与上期和值差的绝对值"""
    results = []
    for i in range(len(data) - 1):
        amp = abs(data[i]["和值"] - data[i + 1]["和值"])
        direction = "升" if data[i]["和值"] > data[i + 1]["和值"] else \
                    ("降" if data[i]["和值"] < data[i + 1]["和值"] else "平")
        results.append({
            "期号": data[i]["期号"],
            "和值振幅": amp,
            "方向": direction,
        })
    return results


def span_amplitude(data: list[dict]) -> list[dict]:
    """跨度振幅"""
    results = []
    for i in range(len(data) - 1):
        amp = abs(data[i]["跨度"] - data[i + 1]["跨度"])
        results.append({"期号": data[i]["期号"], "跨度振幅": amp})
    return results


def position_diff_sum(data: list[dict]) -> dict:
    """位差位和统计"""
    diff = Counter()
    sum_ = Counter()
    for d in data:
        b, s, g = d["百位"], d["十位"], d["个位"]
        diff[(b - s) % 10] += 1
        diff[(b - g) % 10] += 1
        diff[(s - g) % 10] += 1
        sum_[(b + s) % 10] += 1
        sum_[(b + g) % 10] += 1
        sum_[(s + g) % 10] += 1
    return {"位差": dict(diff), "位和": dict(sum_)}
