"""关系指标：邻孤传、复隔中"""

from collections import Counter


def adjacent_isolated_passed(data: list[dict]) -> list[dict]:
    """
    邻孤传分析：相对于上一期号码
    - 传码（重码）：与上期相同的号码
    - 邻码：与上期号码相邻（0和9视为相邻）
    - 孤码：其他
    """
    results = []
    for i in range(len(data) - 1):
        curr_digits = {data[i]["百位"], data[i]["十位"], data[i]["个位"]}
        prev_digits = {data[i + 1]["百位"], data[i + 1]["十位"], data[i + 1]["个位"]}
        chuan = curr_digits & prev_digits
        lin = set()
        for p in prev_digits:
            for adj in [(p - 1) % 10, (p + 1) % 10]:
                if adj in curr_digits and adj not in chuan:
                    lin.add(adj)
        gu = curr_digits - chuan - lin
        results.append({
            "期号": data[i]["期号"],
            "传码": sorted(chuan),
            "邻码": sorted(lin),
            "孤码": sorted(gu),
        })
    return results


def repeat_separate_middle(data: list[dict]) -> list[dict]:
    """
    复隔中分析：按遗漏值分类
    - 复码：遗漏值=0（即传码/重码）
    - 隔码：遗漏值=1（上期出现过）
    - 中码：遗漏值>1
    """
    results = []
    for i in range(len(data)):
        curr_digits = {data[i]["百位"], data[i]["十位"], data[i]["个位"]}
        # 统计每个数字最近一次出现在哪
        missing = {}
        for d in range(10):
            for j in range(i, len(data)):
                if d in {data[j]["百位"], data[j]["十位"], data[j]["个位"]}:
                    missing[d] = j - i
                    break
            else:
                missing[d] = len(data)
        fu = {d for d, m in missing.items() if m == 0 and d in curr_digits}
        ge = {d for d, m in missing.items() if m == 1 and d in curr_digits}
        zhong = curr_digits - fu - ge
        results.append({
            "期号": data[i]["期号"],
            "复码": sorted(fu),
            "隔码": sorted(ge),
            "中码": sorted(zhong),
        })
    return results
