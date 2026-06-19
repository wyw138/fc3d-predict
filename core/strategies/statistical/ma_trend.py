"""移动平均趋势外推策略"""

import random

from ..base import BaseStrategy


class MATrendStrategy(BaseStrategy):
    name = "ma_trend"
    description = "用5/10/30期移动平均交叉判断趋势方向，按趋势加权生成"

    def predict(self, n: int = 5) -> list[str]:
        if len(self.data) < 30:
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]

        # 预计算各位趋势权重
        pos_weights = {}
        for pos in ("百位", "十位", "个位"):
            arr = [d[pos] for d in self.data]
            ma5 = sum(arr[:5]) / 5
            ma10 = sum(arr[:10]) / 10
            if ma5 > ma10:
                w = [1, 1, 1, 1, 1, 2, 3, 4, 5, 6]    # 上升偏大
            elif ma5 < ma10:
                w = [6, 5, 4, 3, 2, 1, 1, 1, 1, 1]    # 下降偏小
            else:
                w = [1] * 10                            # 震荡均匀
            pos_weights[pos] = w

        results = set()
        for _ in range(n * 10):
            code = ""
            for pos in ("百位", "十位", "个位"):
                code += str(random.choices(range(10), weights=pos_weights[pos], k=1)[0])
            results.add(code)

        return sorted(results)[:n]
