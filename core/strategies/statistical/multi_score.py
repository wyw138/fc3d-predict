"""多指标综合评分策略"""

import random
from collections import Counter

from ..base import BaseStrategy
from ...indicators import basic, distribution


class MultiScoreStrategy(BaseStrategy):
    name = "multi_score"
    description = "对1000个候选号码多维度打分，取总分最高者"

    def predict(self, n: int = 5) -> list[str]:
        if len(self.data) < 10:
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]

        freq_all = basic.digit_frequency(self.data, "all")
        missing_all = basic.missing_since(self.data, "all")
        sum_dist = distribution.sum_distribution(self.data)
        span_dist = distribution.span_distribution(self.data)

        # 采样打分（1000注全打分太慢，随机采样1000个候选）
        total_samples = 2000
        scored = []
        for _ in range(total_samples):
            code = f"{random.randint(0, 999):03d}"
            b, s, g = int(code[0]), int(code[1]), int(code[2])
            score = 0
            # 频率得分
            score += freq_all.get(b, 0) + freq_all.get(s, 0) + freq_all.get(g, 0)
            # 遗漏得分（遗漏越久得分越高）
            score += missing_all.get(b, 0) * 2 + missing_all.get(s, 0) * 2 + missing_all.get(g, 0) * 2
            # 和值得分
            sv = b + s + g
            score += sum_dist.get(sv, 0) // 3
            # 跨度得分
            sp = max(b, s, g) - min(b, s, g)
            score += span_dist.get(sp, 0)
            # 奇偶平衡偏分
            odd = sum(1 for x in (b, s, g) if x % 2)
            if 1 <= odd <= 2:
                score += 5
            # 大小平衡偏分
            big = sum(1 for x in (b, s, g) if x >= 5)
            if 1 <= big <= 2:
                score += 5
            scored.append((code, score))

        scored.sort(key=lambda x: -x[1])
        # 去重取 Top-N
        results = []
        seen = set()
        for code, _ in scored:
            if code not in seen:
                results.append(code)
                seen.add(code)
            if len(results) >= n:
                break
        return results
