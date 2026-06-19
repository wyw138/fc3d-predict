"""和值回归 + 形态跟随策略"""

import random
from collections import Counter

from ..base import BaseStrategy


class SumRegressionStrategy(BaseStrategy):
    name = "sum_regression"
    description = "根据近期和值移动平均，在±3范围内生成号码"

    def predict(self, n: int = 5) -> list[str]:
        recent_sums = [d["和值"] for d in self.data[:30]]
        if not recent_sums:
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]
        avg_sum = sum(recent_sums) / len(recent_sums)
        target = int(round(avg_sum))

        results = set()
        for _ in range(n * 3):
            delta = random.randint(-3, 3)
            s = max(0, min(27, target + delta))
            for __ in range(100):
                b = random.randint(0, 9)
                t = random.randint(0, 9)
                g = s - b - t
                if 0 <= g <= 9:
                    results.add(f"{b}{t}{g}")
                    break
        while len(results) < n:
            results.add(f"{random.randint(0, 999):03d}")
        return sorted(results)[:n]


class PatternFollowStrategy(BaseStrategy):
    name = "pattern_follow"
    description = "分析近30期最频繁的奇偶/大小/形态组合，按该模式生成"

    def predict(self, n: int = 5) -> list[str]:
        recent = self.data[:min(30, len(self.data))]
        if not recent:
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]

        pattern_counter = Counter()
        for d in recent:
            digits = [d["百位"], d["十位"], d["个位"]]
            odd = "奇多" if sum(1 for x in digits if x % 2) >= 2 else "偶多"
            big = "大多" if sum(1 for x in digits if x >= 5) >= 2 else "小多"
            uniq = len(set(digits))
            shape = {1: "豹子", 2: "组三", 3: "组六"}[uniq]
            pattern_counter[(odd, big, shape)] += 1

        top_patterns = pattern_counter.most_common(3)
        results = set()
        for (odd, big, shape), _ in top_patterns:
            for _ in range(max(1, n // len(top_patterns))):
                code = self._gen_by_pattern(odd, big, shape)
                if code:
                    results.add(code)

        while len(results) < n:
            results.add(f"{random.randint(0, 999):03d}")
        return sorted(results)[:n]

    def _gen_by_pattern(self, odd_label: str, big_label: str, shape: str) -> str:
        odd_pool = [1, 3, 5, 7, 9]
        even_pool = [0, 2, 4, 6, 8]
        for _ in range(500):
            if odd_label == "奇多":
                picks = odd_pool * 2 + even_pool
            else:
                picks = even_pool * 2 + odd_pool
            code = [random.choice(picks) for _ in range(3)]
            uniq = len(set(code))
            if shape == "豹子" and uniq != 1:
                continue
            if shape == "组三" and uniq != 2:
                continue
            if shape == "组六" and uniq != 3:
                continue
            return "".join(str(d) for d in code)
        return ""


class MissingComboStrategy(BaseStrategy):
    name = "missing_combo"
    description = "各位遗漏超过10期的数字交叉组合"

    def predict(self, n: int = 5) -> list[str]:
        def missing_for_pos(key):
            arr = [d[key] for d in self.data]
            return [d for d in range(10) if d not in arr[:min(10, len(arr))]]

        missing_bai = missing_for_pos("百位")
        missing_shi = missing_for_pos("十位")
        missing_ge = missing_for_pos("个位")

        results = set()
        pools = [
            missing_bai if missing_bai else list(range(10)),
            missing_shi if missing_shi else list(range(10)),
            missing_ge if missing_ge else list(range(10)),
        ]
        for _ in range(n * 5):
            code = "".join(str(random.choice(p)) for p in pools)
            results.add(code)
        return sorted(results)[:n]
