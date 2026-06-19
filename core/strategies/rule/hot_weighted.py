"""热号加权策略：数字出现频率越高，权重越大"""

import random
from collections import Counter

from ..base import BaseStrategy


class HotWeightedStrategy(BaseStrategy):
    name = "hot_weighted"
    description = "以数字频率为权重，每个位置独立加权随机生成"

    def predict(self, n: int = 5) -> list[str]:
        freq_all = Counter()
        for d in self.data:
            freq_all[d["百位"]] += 1
            freq_all[d["十位"]] += 1
            freq_all[d["个位"]] += 1
        weights = [freq_all.get(d, 0) + 1 for d in range(10)]
        results = set()
        max_attempts = n * 20
        attempts = 0
        while len(results) < n and attempts < max_attempts:
            code = "".join(
                str(random.choices(range(10), weights=weights, k=1)[0])
                for _ in range(3)
            )
            results.add(code)
            attempts += 1
        while len(results) < n:
            results.add(f"{random.randint(0, 999):03d}")
        return sorted(results)[:n]


class ColdReboundStrategy(BaseStrategy):
    name = "cold_rebound"
    description = "遗漏越久的数字，回补概率越高（均值回归假设）"

    def predict(self, n: int = 5) -> list[str]:
        # 每个数字在所有位置的遗漏
        missing = {}
        for d in range(10):
            min_idx = len(self.data)
            for key in ("百位", "十位", "个位"):
                arr = [r[key] for r in self.data]
                try:
                    idx = arr.index(d)
                    min_idx = min(min_idx, idx)
                except ValueError:
                    pass
            missing[d] = min_idx

        weights = [missing.get(d, 0) + 1 for d in range(10)]
        results = set()
        max_attempts = n * 20
        attempts = 0
        while len(results) < n and attempts < max_attempts:
            code = "".join(
                str(random.choices(range(10), weights=weights, k=1)[0])
                for _ in range(3)
            )
            results.add(code)
            attempts += 1
        while len(results) < n:
            results.add(f"{random.randint(0, 999):03d}")
        return sorted(results)[:n]


class PureRandomStrategy(BaseStrategy):
    name = "pure_random"
    description = "纯随机生成（对照组基线）"

    def predict(self, n: int = 5) -> list[str]:
        return [f"{random.randint(0, 999):03d}" for _ in range(n)]
