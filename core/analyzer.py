"""
统计分析引擎 — 整合所有指标，输出统一分析报告
"""

from collections import Counter

from .indicators import basic, distribution, classification, relation, amplitude, nonlinear
from .preprocessor import build_features


class Analyzer:
    """3D 数据统计分析器"""

    def __init__(self, data: list[dict]):
        self.data = data
        self.total = len(data)

    # ── 快捷属性 ──
    @property
    def bai(self): return [d["百位"] for d in self.data]

    @property
    def shi(self): return [d["十位"] for d in self.data]

    @property
    def ge(self):  return [d["个位"] for d in self.data]

    @property
    def codes(self): return [d["号码"] for d in self.data]

    @property
    def sums(self):  return [d["和值"] for d in self.data]

    # ── 综合报告 ──
    def full_report(self) -> dict:
        """生成完整的统计分析报告"""
        latest = self.data[0] if self.data else None
        return {
            "数据量": self.total,
            "最新期": latest,
            "频率": self._freq_report(),
            "和值分布": distribution.sum_distribution(self.data),
            "跨度分布": distribution.span_distribution(self.data),
            "和尾分布": distribution.sum_tail_distribution(self.data),
            "012路": distribution.route_012_distribution(self.data),
            "AC值分布": distribution.ac_distribution(self.data),
            "奇偶比": classification.odd_even_distribution(self.data),
            "大小比": classification.big_small_distribution(self.data),
            "质合比": classification.prime_composite_distribution(self.data),
            "形态": classification.shape_distribution(self.data),
            "热温冷": basic.hot_warm_cold(self.data),
            "位差位和": amplitude.position_diff_sum(self.data),
            "非线性": self._nonlinear_report(),
        }

    def _freq_report(self) -> dict:
        freq_all = basic.digit_frequency(self.data, "all")
        freq_bai = basic.digit_frequency(self.data, "bai")
        freq_shi = basic.digit_frequency(self.data, "shi")
        freq_ge = basic.digit_frequency(self.data, "ge")
        missing = basic.missing_since(self.data, "all")
        top_codes = basic.code_frequency(self.data, 10)
        total_digits = sum(freq_all.values())
        return {
            "全位频率": {str(d): freq_all.get(d, 0) for d in range(10)},
            "百位频率": {str(d): freq_bai.get(d, 0) for d in range(10)},
            "十位频率": {str(d): freq_shi.get(d, 0) for d in range(10)},
            "个位频率": {str(d): freq_ge.get(d, 0) for d in range(10)},
            "最热数字": max(range(10), key=lambda d: freq_all.get(d, 0)),
            "最冷数字": min(range(10), key=lambda d: freq_all.get(d, 0)),
            "遗漏": {str(d): missing.get(d, 0) for d in range(10)},
            "最大遗漏数字": max(range(10), key=lambda d: missing.get(d, 0)),
            "高频号码Top10": [(c, n) for c, n in top_codes],
        }

    def _nonlinear_report(self) -> dict:
        andata = self.sums[:200] if len(self.sums) > 200 else self.sums
        if len(andata) < 30:
            return {"Hurst指数": 0.5, "BDS": {}, "近似熵": 0, "备注": "数据不足"}
        hurst = nonlinear.hurst_exponent(andata)
        bds = nonlinear.bds_test(andata)
        apen = nonlinear.approximate_entropy(andata)
        return {
            "Hurst指数": round(hurst, 4),
            "Hurst解释": "随机游走" if abs(hurst - 0.5) < 0.1 else ("趋势性" if hurst > 0.5 else "均值回归"),
            "BDS检验": bds,
            "近似熵": round(apen, 4),
        }

    def summary_text(self) -> str:
        """生成人类可读的统计摘要"""
        r = self.full_report()
        freq = r["频率"]
        latest = r["最新期"]
        lines = [
            "=" * 50,
            "  福彩3D 历史数据统计摘要",
            "=" * 50,
        ]
        if not latest:
            lines.append("  暂无数据")
            lines.append("=" * 50)
            return "\n".join(lines)

        lines.append("  数据量: %d 期" % r['数据量'])
        lines.append("  最新期: %s  开奖 %s  (%s)" % (latest['期号'], latest['号码'], latest['日期']))
        lines.append("  上一期: 和值%d  跨度%d  %s  %s" % (latest['和值'], latest['跨度'], latest['奇偶比'], latest['大小比']))
        lines.append("")
        # 频率
        lines.append("  ▸ 数字频率 (0-9):")
        lines.append("    " + "  ".join("%d:%4d" % (d, freq['全位频率'].get(str(d), 0)) for d in range(5)))
        lines.append("    " + "  ".join("%d:%4d" % (d, freq['全位频率'].get(str(d), 0)) for d in range(5, 10)))
        hot = freq.get('最热数字', '?')
        cold = freq.get('最冷数字', '?')
        lines.append("  ▸ 最热: %s  最冷: %s" % (hot, cold))
        lines.append("")
        # 遗漏
        lines.append("  ▸ 遗漏 (距上次出现):")
        lines.append("    " + "  ".join("%d:%4d" % (d, freq['遗漏'].get(str(d), 0)) for d in range(5)))
        lines.append("    " + "  ".join("%d:%4d" % (d, freq['遗漏'].get(str(d), 0)) for d in range(5, 10)))
        max_miss = freq.get('最大遗漏数字', '?')
        miss_val = freq['遗漏'].get(str(max_miss), '?')
        lines.append("  ▸ 最大遗漏: %s (%s期)" % (max_miss, miss_val))
        lines.append("")
        # 高频号码
        lines.append("  ▸ 高频号码 Top-5:")
        for i, (code, cnt) in enumerate(freq.get("高频号码Top10", [])[:5], 1):
            lines.append("      %d. %s → %d 次" % (i, code, cnt))
        lines.append("")
        lines.append("  ▸ 出现最多的和值: %s" % max(r.get('和值分布', {}), key=r.get('和值分布', {}).get, default='?'))
        lines.append("  ▸ 形态分布: %s" % r.get('形态', {}))
        lines.append("  ▸ 奇偶比: %s" % r.get('奇偶比', {}))
        hwc = r.get('热温冷', {})
        lines.append("  ▸ 热号: %s" % hwc.get('热号', []))
        lines.append("  ▸ 冷号: %s" % hwc.get('冷号', []))

        nl = r.get("非线性", {})
        if nl.get("Hurst指数"):
            lines.append("")
            lines.append("  ▸ Hurst指数: %s (%s)" % (nl['Hurst指数'], nl.get('Hurst解释', '')))
        if nl.get("近似熵") is not None:
            lines.append("  ▸ 近似熵: %s" % nl['近似熵'])
        bds = nl.get("BDS检验", {})
        if bds.get("解释"):
            lines.append("  ▸ BDS检验: %s" % bds['解释'])

        lines.append("=" * 50)
        return "\n".join(lines)

    def get_features(self, target_idx: int = 0) -> dict:
        """为指定期数构建 ML 特征"""
        return build_features(self.data, target_idx)
