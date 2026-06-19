"""
策略基类 + 策略注册表
所有预测策略遵循统一接口
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseStrategy(ABC):
    """预测策略基类"""

    name: str = "base"
    description: str = ""

    def __init__(self, data: list[dict]):
        self.data = data
        self.total = len(data)

    @abstractmethod
    def predict(self, n: int = 5) -> list[str]:
        """生成 n 个候选号码 (格式: '012')"""
        ...

    def predict_digits(self, n: int = 5) -> list[list[int]]:
        """生成 n 个候选号码 (格式: [[0,1,2], ...])"""
        codes = self.predict(n)
        return [[int(c) for c in code] for code in codes]


class StrategyRegistry:
    """策略注册表 — 管理所有可用策略"""

    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy):
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> Optional[BaseStrategy]:
        return self._strategies.get(name)

    def get_all(self) -> dict[str, BaseStrategy]:
        return self._strategies

    def get_enabled(self, config: dict) -> dict[str, BaseStrategy]:
        """根据配置返回启用的策略"""
        enabled = {}
        for name, strat in self._strategies.items():
            cfg = config.get("strategies", {}).get(name, {})
            if cfg.get("enable", True):
                enabled[name] = strat
        return enabled
