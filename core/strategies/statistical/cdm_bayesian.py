"""
Compound-Dirichlet-Multinomial (CDM) 贝叶斯预测模型

基于 Nkomozake (2024) "Predicting Winning Lottery Numbers" (arXiv:2403.12836)
将 1000 个可能的三位数视为多项式类别，用 Dirichlet 先验 + 多项式似然 → 后验预测概率。

公式: π_j = (x_j + α_j) / (n + A)
  x_j = 号码 j 在历史中的出现次数
  α_j = Dirichlet 先验超参数（默认 α_j = n/1000 即经验贝叶斯估计）
  n = 总期数, A = Σα_j
"""

import math
from collections import Counter
from ..base import BaseStrategy


class CDMBayesianStrategy(BaseStrategy):
    name = "cdm_bayesian"
    description = (
        "CDM贝叶斯模型: Dirichlet先验+多项式似然→后验概率分布, "
        "基于Nkomozake(2024)论文方法, 专为pick-3设计"
    )

    def __init__(self, data: list[dict], alpha_method: str = "empirical"):
        super().__init__(data)
        self.alpha_method = alpha_method  # 'uniform' | 'empirical' | 'jeffreys'
        self._posterior = None
        self._compute_posterior()

    def _compute_posterior(self):
        """计算后验预测概率分布 P(code | history)"""
        n = len(self.data)
        if n == 0:
            return

        # 统计每个号码的出现频次
        counts = Counter(d["号码"] for d in self.data)

        # Dirichlet 先验超参数
        if self.alpha_method == "uniform":
            # 无信息先验: 每个类别 α = 1
            alpha = {code: 1.0 for code in (f"{i:03d}" for i in range(1000))}
        elif self.alpha_method == "jeffreys":
            # Jeffreys 先验: α = 0.5
            alpha = {code: 0.5 for code in (f"{i:03d}" for i in range(1000))}
        else:  # empirical
            # 经验贝叶斯: α_j ∝ 全局平均频率 = n / 1000
            base_alpha = n / 1000.0
            alpha = {code: base_alpha for code in (f"{i:03d}" for i in range(1000))}

        A = sum(alpha.values())
        total = n + A

        # 后验期望概率: E[π_j | data] = (count_j + α_j) / (n + A)
        posterior = {}
        for code in (f"{i:03d}" for i in range(1000)):
            posterior[code] = (counts.get(code, 0) + alpha[code]) / total

        # 计算后验方差（用于不确定性量化）
        # Var[π_j | data] = posterior*(1-posterior) / (n+A+1)
        self._posterior = posterior
        self._variance = {
            code: posterior[code] * (1 - posterior[code]) / (total + 1)
            for code in posterior
        }

    def predict(self, n: int = 5) -> list[str]:
        """按后验概率排序取 Top-N"""
        if not self._posterior:
            return []

        # 按后验概率降序排列（概率最高的前 n 个号码）
        sorted_codes = sorted(self._posterior.keys(), key=lambda c: self._posterior[c], reverse=True)
        return sorted_codes[:n]

    def predict_weighted(self, n: int = 5, temperature: float = 1.0) -> list[str]:
        """
        带温度采样的预测 —— 温度越高越随机，越低越集中在高概率区域。
        temperature=0  → 纯 Top-N（确定性最大）
        temperature=1  → 按后验概率采样
        temperature=∞  → 均匀随机
        """
        import random

        if not self._posterior or temperature == 0:
            return self.predict(n)

        codes = list(self._posterior.keys())
        probs = [self._posterior[c] ** (1.0 / max(temperature, 0.01)) for c in codes]
        total = sum(probs)
        probs = [p / total for p in probs]

        results = set()
        while len(results) < n:
            code = random.choices(codes, weights=probs, k=1)[0]
            results.add(code)

        # CDM 的概率排序 + 采样混合：高概率号码排前面
        return sorted(results, key=lambda c: self._posterior.get(c, 0), reverse=True)[:n]

    def get_probability(self, code: str) -> float:
        """查询某个号码的后验预测概率"""
        return self._posterior.get(code, 0.0) if self._posterior else 0.0

    def get_top_probability_codes(self, n: int = 10) -> list[tuple[str, float]]:
        """返回概率最高的 Top-N (号码, 概率)"""
        if not self._posterior:
            return []
        sorted_codes = sorted(self._posterior.keys(), key=lambda c: self._posterior[c], reverse=True)
        return [(c, round(self._posterior[c], 6)) for c in sorted_codes[:n]]
