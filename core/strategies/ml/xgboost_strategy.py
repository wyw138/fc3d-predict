"""
XGBoost 三分类器策略 — 百位/十位/个位独立预测

基于 LottoProphet 项目 (zhaoyangpp, GitHub) 验证的 XGBoost 方法。
为每个位置训练一个独立的 10 类分类器（0-9），用历史特征预测下一个数字。
"""

import logging
from collections import Counter
from typing import Optional

from ..base import BaseStrategy

logger = logging.getLogger(__name__)

# 延迟导入，xgb 未安装时可优雅降级
_xgb_available = False
try:
    import numpy as np
    _xgb_available = True
except ImportError:
    pass

try:
    import xgboost as xgb
    _xgb_available = True
except ImportError:
    _xgb_available = False


class XGBoostStrategy(BaseStrategy):
    name = "xgboost"
    description = (
        "XGBoost三分类器: 百/十/个位各训一个10类分类器, "
        "特征含滞后+频率+遗漏+滚动统计, 基于LottoProphet验证方法"
    )

    def __init__(self, data: list[dict], n_estimators: int = 200, max_depth: int = 6):
        super().__init__(data)
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self._models: dict[str, Optional[object]] = {"bai": None, "shi": None, "ge": None}
        self._available = _xgb_available
        if self._available and len(data) >= 100:
            self._train()

    def _build_features(self, target_idx: int = 1) -> Optional[dict]:
        """为 data[target_idx] 构建特征向量（用更早的数据）"""
        if target_idx >= len(self.data):
            return None

        history = self.data[target_idx:]
        if len(history) < 10:
            return None

        features = {}

        # 滞后特征 t-1, t-2, t-3, t-5
        for lag in [1, 2, 3, 5]:
            if lag <= len(history):
                d = history[lag - 1]
                features[f"lag{lag}_bai"] = d["百位"]
                features[f"lag{lag}_shi"] = d["十位"]
                features[f"lag{lag}_ge"] = d["个位"]
                features[f"lag{lag}_sum"] = d["和值"]
                features[f"lag{lag}_span"] = d["跨度"]
            else:
                for k in ["bai", "shi", "ge", "sum", "span"]:
                    features[f"lag{lag}_{k}"] = -1

        # 频率特征（前 30 期）
        recent = history[:30]
        all_digits = [d[k] for d in recent for k in ("百位", "十位", "个位")]
        freq = Counter(all_digits)
        total = len(all_digits)
        for d in range(10):
            features[f"freq_{d}"] = freq.get(d, 0) / max(total, 1)

        # 滚动统计（和值）
        sums = [d["和值"] for d in history[:30]]
        if sums:
            features["sum_mean_30"] = sum(sums) / len(sums)
            features["sum_std_30"] = (
                sum((s - features["sum_mean_30"]) ** 2 for s in sums) / len(sums)
            ) ** 0.5
        else:
            features["sum_mean_30"] = 13.5
            features["sum_std_30"] = 5.0

        # 滚动统计（跨度）
        spans = [d["跨度"] for d in history[:30]]
        if spans:
            features["span_mean_30"] = sum(spans) / len(spans)
        else:
            features["span_mean_30"] = 4.5

        # 各位遗漏
        for pos, key in [("bai", "百位"), ("shi", "十位"), ("ge", "个位")]:
            arr = [d[key] for d in history]
            for d in range(10):
                try:
                    features[f"missing_{pos}_{d}"] = arr.index(d)
                except ValueError:
                    features[f"missing_{pos}_{d}"] = len(arr)

        return features

    def _train(self):
        """训练三个位置的 XGBoost 分类器"""
        if not _xgb_available:
            self._available = False
            return
        try:
            import numpy as np
            import xgboost as xgb
        except ImportError:
            self._available = False
            return

        all_features = []
        all_labels = {"bai": [], "shi": [], "ge": []}

        # 从历史中构造训练样本
        # 对每期（从最早的开始），用更早的数据作为特征
        for i in range(len(self.data) - 1, 0, -1):  # 从旧到新
            feats = self._build_features(i + 1)  # i+1 = 往前看
            if feats is None:
                continue
            all_features.append(feats)
            target = self.data[i - 1]  # 本期
            all_labels["bai"].append(target["百位"])
            all_labels["shi"].append(target["十位"])
            all_labels["ge"].append(target["个位"])

        if len(all_features) < 50:
            self._available = False
            return

        # 特征向量化
        keys = sorted(all_features[0].keys())
        X = np.array([[f[k] for k in keys] for f in all_features], dtype=np.float32)

        for pos in ["bai", "shi", "ge"]:
            y = np.array(all_labels[pos], dtype=np.int32)
            try:
                model = xgb.XGBClassifier(
                    n_estimators=min(50, self.n_estimators),
                    max_depth=min(3, self.max_depth),
                    learning_rate=0.1,
                    verbosity=0,
                )
                model.fit(X, y)
                self._models[pos] = model
            except Exception as e:
                logger.warning(f"XGBoost {pos}位训练失败: {e}")
                self._models[pos] = None

        self._feature_keys = keys
        logger.info(f"XGBoost 训练完成: {len(all_features)} 个样本, {len(keys)} 个特征")

    def predict(self, n: int = 5) -> list[str]:
        if not self._available or not self._models["bai"]:
            # 降级为纯随机
            import random
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]

        # 构建最新一期的特征（预测下一期）
        feats = self._build_features(1)  # target_idx=1 表示预测 data[0] 的下一期
        if feats is None:
            import random
            return [f"{random.randint(0, 999):03d}" for _ in range(n)]

        import numpy as np
        X_new = np.array([[feats[k] for k in self._feature_keys]], dtype=np.float32)

        # 各位置预测概率
        probs_bai = self._models["bai"].predict_proba(X_new)[0]
        probs_shi = self._models["shi"].predict_proba(X_new)[0]
        probs_ge = self._models["ge"].predict_proba(X_new)[0]

        # 组合概率: P(code|data) = P(b|data) * P(s|data) * P(g|data)
        # 对 1000 个候选按组合概率排序
        scored = []
        for b in range(10):
            for s in range(10):
                for g in range(10):
                    prob = probs_bai[b] * probs_shi[s] * probs_ge[g]
                    if prob > 0:
                        scored.append((f"{b}{s}{g}", prob))

        scored.sort(key=lambda x: -x[1])
        return [code for code, _ in scored[:n]]
