"""加权马尔可夫链策略"""

import random
from collections import defaultdict

from ..base import BaseStrategy


class MarkovChainStrategy(BaseStrategy):
    name = "markov_chain"
    description = "1~5步加权马尔可夫链，基于和值状态转移概率矩阵预测"

    def __init__(self, data: list[dict], max_steps: int = 5):
        super().__init__(data)
        self.max_steps = max_steps

    def _bin_sum(self, s: int) -> int:
        """将和值0-27分为10个状态区间"""
        if s <= 2:  return 0
        if s <= 5:  return 1
        if s <= 8:  return 2
        if s <= 11: return 3
        if s <= 14: return 4
        if s <= 17: return 5
        if s <= 20: return 6
        if s <= 23: return 7
        if s <= 25: return 8
        return 9

    def _state_sequence(self) -> list[int]:
        return [self._bin_sum(d["和值"]) for d in self.data]

    def _transition_matrix(self, step: int) -> list[list[float]]:
        """计算 step 步转移概率矩阵"""
        states = self._state_sequence()
        trans = [[0.0] * 10 for _ in range(10)]
        counts = [[0] * 10 for _ in range(10)]
        row_totals = [0] * 10
        n = len(states)
        for i in range(n - step):
            fr = states[i + step]   # 从更早的期
            to = states[i]          # 到更新的期
            counts[fr][to] += 1
            row_totals[fr] += 1
        for i in range(10):
            if row_totals[i] > 0:
                trans[i] = [c / row_totals[i] for c in counts[i]]
            else:
                trans[i] = [0.1] * 10
        return trans

    def _autocorr(self, step: int) -> float:
        """和值序列的step阶自相关系数（归一化用）"""
        sums = [d["和值"] for d in self.data]
        n = len(sums)
        if n <= step:
            return 0
        mean = sum(sums) / n
        num = sum((sums[i] - mean) * (sums[i + step] - mean) for i in range(n - step))
        den = sum((s - mean) ** 2 for s in sums)
        return abs(num / den) if den > 0 else 0

    def predict(self, n: int = 5) -> list[str]:
        if len(self.data) < self.max_steps + 1:
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]

        current_state = self._bin_sum(self.data[0]["和值"])
        # 各步转移概率 × 自相关系数权重
        final_probs = [0.0] * 10
        total_weight = 0
        for step in range(1, self.max_steps + 1):
            trans = self._transition_matrix(step)
            w = self._autocorr(step)
            if w > 0:
                for j in range(10):
                    final_probs[j] += w * trans[current_state][j]
                total_weight += w

        if total_weight == 0:
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]

        final_probs = [p / total_weight for p in final_probs]
        # 取概率最大的状态，生成该状态下的号码
        best_state = final_probs.index(max(final_probs))
        # 状态反解为和值范围
        sum_ranges = {
            0: (0, 2), 1: (3, 5), 2: (6, 8), 3: (9, 11), 4: (12, 14),
            5: (15, 17), 6: (18, 20), 7: (21, 23), 8: (24, 25), 9: (26, 27),
        }
        lo, hi = sum_ranges[best_state]
        results = set()
        for _ in range(n * 10):
            s = random.randint(lo, hi)
            for __ in range(50):
                b = random.randint(0, 9)
                t = random.randint(0, 9)
                g = s - b - t
                if 0 <= g <= 9:
                    results.add(f"{b}{t}{g}")
                    break
        while len(results) < n:
            results.add(f"{random.randint(0, 999):03d}")
        return sorted(results)[:n]
