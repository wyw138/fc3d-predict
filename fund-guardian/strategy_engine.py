"""
策略引擎 — 六层综合评分系统
Layer 1: 四季分仓 → 仓位比例
Layer 2: 分批进出 → 买卖节奏
Layer 3: 情绪温度 → 反向指标
Layer 4: 行业轮动 → 方向选择
Layer 5: 止损止盈 → 风控底线
Layer 6: 相关性风控 → 真分散
"""
import math
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from config import STRATEGY_CONFIG as CFG, WATCH_FUNDS

# ==================== 基础指标计算 ====================

def calc_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def calc_max_drawdown(series: pd.Series) -> float:
    """最大回撤"""
    cummax = series.expanding().max()
    drawdown = (series - cummax) / cummax
    return float(drawdown.min())

def calc_volatility(series: pd.Series, window: int = 20) -> float:
    """年化波动率"""
    daily_ret = series.pct_change().dropna()
    return float(daily_ret.tail(window).std() * math.sqrt(252))

def calc_var(series: pd.Series, confidence: float = 0.95) -> float:
    """VaR风险价值"""
    returns = series.pct_change().dropna()
    return float(np.percentile(returns, (1 - confidence) * 100))


# ==================== Layer 1: 四季分仓 ====================

def determine_season(
    pe_pct: Optional[float],
    ma_short: Optional[float],
    ma_long: Optional[float],
    index_trend: Optional[float],
) -> str:
    """
    判断当前市场季节
    返回: spring | summer | autumn | winter
    """
    if pe_pct is None or ma_short is None or ma_long is None:
        return "summer"  # 默认均衡

    # 估值判断
    is_cheap = pe_pct <= CFG["pe_low_pct"]
    is_expensive = pe_pct >= CFG["pe_high_pct"]
    is_extreme = pe_pct >= CFG["pe_extreme_pct"]

    # 趋势判断
    trend_up = ma_short > ma_long
    trend_flat = abs(ma_short / ma_long - 1) < 0.005

    if is_cheap and trend_up:
        return "spring"
    elif is_expensive and not trend_up:
        return "winter" if is_extreme else "autumn"
    elif is_expensive and trend_up:
        return "autumn"  # 估值高但还在涨→秋天
    elif is_cheap and not trend_up:
        return "spring"  # 便宜但还没涨→早春
    elif trend_up:
        return "summer"
    else:
        return "autumn"


def get_season_position(season: str) -> float:
    return CFG["seasons"].get(season, {}).get("position", 0.70)


# ==================== Layer 2: 分批进出 ====================

def batch_signal(
    current_signal: str,
    prev_signal: str,
    confirm_days: int = 1,
) -> tuple[str, float]:
    """
    分批执行，返回 (动作, 比例)
    buy_1st → 首批买入30%
    buy_2nd → 二批买入30%
    buy_3rd → 三批买入40%
    sell_1st → 首批卖出33%
    sell_2nd → 二批卖出33%
    sell_3rd → 清仓34%
    """
    if current_signal == "buy":
        if prev_signal != "buy":
            return ("buy_1st", CFG["batch_buy_pcts"][0])
        elif prev_signal == "buy_1st":
            return ("buy_2nd", CFG["batch_buy_pcts"][1])
        else:
            return ("buy_3rd", CFG["batch_buy_pcts"][2])

    elif current_signal == "sell":
        if prev_signal not in ("sell_1st", "sell_2nd", "sell_3rd"):
            return ("sell_1st", CFG["batch_sell_pcts"][0])
        elif prev_signal == "sell_1st":
            return ("sell_2nd", CFG["batch_sell_pcts"][1])
        else:
            return ("sell_3rd", CFG["batch_sell_pcts"][2])

    return ("hold", 0.0)


# ==================== Layer 3: 情绪温度 ====================

def sentiment_adjust(base_score: float, sentiment: float) -> float:
    """
    情绪反向调节
    过热→降分（少买多卖）
    过冷→加分（多买少卖）
    """
    if sentiment >= CFG["sentiment_hot"]:
        # 极度贪婪 → 减分
        adj = -(sentiment - CFG["sentiment_hot"]) / 25 * 15
    elif sentiment <= CFG["sentiment_cold"]:
        # 极度恐惧 → 加分
        adj = +(CFG["sentiment_cold"] - sentiment) / 25 * 15
    else:
        adj = 0
    return max(0, min(100, base_score + adj))


# ==================== Layer 4: 行业轮动 ====================

def sector_signal(fund_name: str, sectors: list[dict]) -> float:
    """根据基金名称匹配行业动量"""
    if not sectors:
        return 0

    # 关键词映射
    name_lower = fund_name.lower()
    keywords = {
        "医疗": "医药", "医药": "医药", "健康": "医药",
        "新能源": "电力设备", "汽车": "汽车",
        "半导体": "电子", "芯片": "电子", "科技": "电子",
        "消费": "食品饮料", "白酒": "食品饮料",
        "红利": "煤炭", "银行": "银行",
    }

    target_sector = None
    for kw, sector in keywords.items():
        if kw in name_lower:
            target_sector = sector
            break

    if not target_sector:
        return 0

    total = len(sectors)
    for rank, s in enumerate(sectors):
        if target_sector in s["name"]:
            pct_rank = rank / total * 100
            if pct_rank <= CFG["sector_oversold_pct"]:
                return +10  # 超跌→加分
            elif pct_rank >= CFG["sector_overbought_pct"]:
                return -10  # 过热→减分
            break

    return 0


# ==================== Layer 5: 风控底线 ====================

def risk_check(
    current_nav: float,
    cost_nav: float,
    highest_nav: float,
    latest_navs: pd.Series,
) -> dict:
    """
    止损止盈检查
    返回 {"action": "sell"|"hold", "reason": str}
    """
    if cost_nav <= 0:
        return {"action": "hold", "reason": ""}

    pnl = (current_nav - cost_nav) / cost_nav * 100

    # 硬止损
    if pnl <= CFG["stop_loss_pct"]:
        return {"action": "sell", "reason": f"硬止损触发 ({pnl:.1f}%)"}

    # 主动止盈
    if pnl >= CFG["take_profit_pct"]:
        return {"action": "sell", "reason": f"主动止盈触发 (+{pnl:.1f}%)"}

    # 回撤止损（从最高点回落）
    if highest_nav > 0:
        drawdown = (current_nav - highest_nav) / highest_nav * 100
        if drawdown <= -CFG["trailing_stop_pct"]:
            return {"action": "sell", "reason": f"回撤止损触发 ({drawdown:.1f}%)"}

    return {"action": "hold", "reason": ""}


# ==================== Layer 6: 相关性风控 ====================

def correlation_check(fund_navs: dict[str, pd.Series]) -> list[str]:
    """检查基金间相关性，返回警告列表"""
    warnings = []
    codes = list(fund_navs.keys())

    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            s1 = fund_navs[codes[i]]
            s2 = fund_navs[codes[j]]
            if len(s1) < 20 or len(s2) < 20:
                continue
            # 对齐时间
            common_idx = s1.index.intersection(s2.index)
            if len(common_idx) < 10:
                continue
            r1 = s1.loc[common_idx].pct_change().dropna()
            r2 = s2.loc[common_idx].pct_change().dropna()
            if len(r1) < 10:
                continue
            corr = r1.corr(r2)
            if corr >= CFG["correlation_warn"]:
                name_i = ""
                name_j = ""
                for n, c in WATCH_FUNDS.items():
                    if c == codes[i]: name_i = n
                    if c == codes[j]: name_j = n
                warnings.append(f"⚠️ {name_i} ↔ {name_j} 相关性 {corr:.2f}，伪分散风险！")

    return warnings


# ==================== 主评分引擎 ====================

def evaluate_fund(
    fund_code: str,
    fund_name: str,
    nav_df: Optional[pd.DataFrame],
    estimate: Optional[dict],
    valuation: Optional[dict],
    sentiment: float,
    sectors: list[dict],
    prev_signal: str = "hold",
    cost_nav: float = 0,
    highest_nav: float = 0,
    all_fund_navs: dict[str, pd.Series] = None,
) -> dict:
    """
    综合六层评分
    返回完整评估结果
    """
    score = 50.0  # 基准中性
    signals = []
    warnings = []
    action = "hold"
    action_pct = 0.0

    # ---- 数据准备 ----
    if nav_df is None or nav_df.empty:
        return {"action": "hold", "score": 50, "reason": "数据不足，等待净值更新", "details": {}}

    # 找净值列
    nav_col = None
    for c in nav_df.columns:
        if "净值" in c or "NAV" in c.upper() or "单位" in c:
            nav_col = c
            break
    if nav_col is None:
        nav_col = nav_df.columns[-1]

    nav_series = pd.to_numeric(nav_df[nav_col], errors="coerce").dropna()
    if len(nav_series) < CFG["ma_long"]:
        return {"action": "hold", "score": 50, "reason": f"净值数据不足({len(nav_series)}天)", "details": {}}

    current_nav = float(nav_series.iloc[-1])
    ma_short_val = float(calc_ma(nav_series, CFG["ma_short"]).iloc[-1])
    ma_long_val = float(calc_ma(nav_series, CFG["ma_long"]).iloc[-1])
    rsi_val = float(calc_rsi(nav_series).iloc[-1])
    volatility = calc_volatility(nav_series)
    max_dd = calc_max_drawdown(nav_series)
    var_95 = calc_var(nav_series)

    # ---- Layer 1: 四季分仓 ----
    pe_pct = valuation.get("pe_pct") if valuation else None
    season = determine_season(pe_pct, ma_short_val, ma_long_val, None)
    position_pct = get_season_position(season)
    if season == "spring":
        score += 20
    elif season == "summer":
        score += 5
    elif season == "autumn":
        score -= 10
    else:
        score -= 20
    signals.append(f"🌤️ 季节:{season} 仓位:{position_pct:.0%}")

    # ---- Layer 2: 趋势 + RSI ----
    is_golden_cross = (ma_short_val > ma_long_val and
                       float(calc_ma(nav_series, CFG["ma_short"]).iloc[-2]) <=
                       float(calc_ma(nav_series, CFG["ma_long"]).iloc[-2]))
    is_death_cross = (ma_short_val < ma_long_val and
                      float(calc_ma(nav_series, CFG["ma_short"]).iloc[-2]) >=
                      float(calc_ma(nav_series, CFG["ma_long"]).iloc[-2]))

    if is_golden_cross:
        score += 15
        signals.append("📈 金叉买入信号")
    elif is_death_cross:
        score -= 15
        signals.append("📉 死叉卖出信号")
    elif ma_short_val > ma_long_val:
        score += 5
    else:
        score -= 5

    # RSI
    rsi = float(calc_rsi(nav_series).iloc[-1]) if not pd.isna(calc_rsi(nav_series).iloc[-1]) else 50
    if rsi <= CFG["rsi_oversold"]:
        score += 10
        signals.append(f"💚 超卖区 RSI={rsi:.0f}")
    elif rsi >= CFG["rsi_overbought"]:
        score -= 10
        signals.append(f"❤️ 超买区 RSI={rsi:.0f}")

    # ---- Layer 3: 情绪反向 ----
    score = sentiment_adjust(score, sentiment)
    if sentiment >= CFG["sentiment_hot"]:
        signals.append(f"🌡️ 市场过热({sentiment:.0f})，谨慎买入")
    elif sentiment <= CFG["sentiment_cold"]:
        signals.append(f"🥶 市场恐惧({sentiment:.0f})，机会出现")

    # ---- Layer 4: 行业轮动 ----
    sector_adj = sector_signal(fund_name, sectors)
    score += sector_adj
    if sector_adj > 0:
        signals.append("🏭 行业超跌，加分")
    elif sector_adj < 0:
        signals.append("🏭 行业过热，减分")

    # ---- Layer 5: 风控检查 ----
    risk = risk_check(current_nav, cost_nav, max(highest_nav, current_nav), nav_series)
    if risk["action"] == "sell":
        action = "sell"
        action_pct = 1.0
        signals.append(f"⛔ {risk['reason']}")
        score = min(score, 30)  # 强制低分

    # ---- Layer 6: 相关性（不评分，只警告） ----
    if all_fund_navs:
        corr_warns = correlation_check(all_fund_navs)
        warnings.extend(corr_warns)

    # ---- 估值定投信号 ----
    if pe_pct is not None:
        if pe_pct <= CFG["pe_low_pct"]:
            signals.append(f"📊 PE分位{pe_pct:.0f}% → 建议加倍定投")
        elif pe_pct >= CFG["dca_stop_pct"]:
            signals.append(f"📊 PE分位{pe_pct:.0f}% → 建议停止定投")
        elif pe_pct >= CFG["pe_high_pct"]:
            signals.append(f"📊 PE分位{pe_pct:.0f}% → 建议减半定投")

    # ---- 最终判定 ----
    if action != "sell":
        if score >= 70:
            action = "buy"
            # 分批
            action, action_pct = batch_signal("buy", prev_signal)
        elif score >= 55:
            action = "hold"
            signals.append("✅ 建议持有")
        elif score <= 30:
            action = "sell"
            action, action_pct = batch_signal("sell", prev_signal)
        else:
            action = "hold"

    # 细节
    details = {
        "season": season,
        "position_pct": position_pct,
        "score": score,
        "current_nav": current_nav,
        "ma_short": round(ma_short_val, 4),
        "ma_long": round(ma_long_val, 4),
        "rsi": round(rsi, 1),
        "volatility": round(volatility * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "var_95": round(var_95 * 100, 2),
        "pe_pct": round(pe_pct, 1) if pe_pct else None,
        "sentiment": round(sentiment, 1),
        "action": action,
        "action_pct": round(action_pct, 3),
        "signals": signals,
        "warnings": warnings,
    }

    return {
        "action": action,
        "action_pct": round(action_pct, 3),
        "score": round(score, 1),
        "reason": "; ".join(signals),
        "details": details,
    }


# ==================== 批量评估 ====================

def evaluate_portfolio(data: dict, state: dict = None) -> dict:
    """
    对整个基金组合进行评估
    state: 上次评估的状态（用于分批）
    """
    if state is None:
        state = {}

    results = {}
    all_navs = {}
    for code, fund_data in data["funds"].items():
        nav_df = fund_data.get("nav_df")
        if nav_df is not None:
            nav_col = next((c for c in nav_df.columns if "净值" in c or "NAV" in c.upper()), nav_df.columns[-1])
            all_navs[code] = pd.to_numeric(nav_df[nav_col], errors="coerce").dropna()

    for code, fund_data in data["funds"].items():
        name = fund_data["name"]
        prev = state.get(code, {})
        results[code] = evaluate_fund(
            fund_code=code,
            fund_name=name,
            nav_df=fund_data.get("nav_df"),
            estimate=fund_data.get("estimate"),
            valuation=fund_data.get("valuation"),
            sentiment=data["sentiment"],
            sectors=data["sectors"],
            prev_signal=prev.get("prev_action", "hold"),
            cost_nav=prev.get("cost_nav", 0),
            highest_nav=prev.get("highest_nav", 0),
            all_fund_navs=all_navs,
        )

    # 更新状态
    for code, r in results.items():
        cur_nav = r.get("details", {}).get("current_nav", 0)
        state[code] = {
            "prev_action": r["action"],
            "cost_nav": state.get(code, {}).get("cost_nav", cur_nav),
            "highest_nav": max(
                state.get(code, {}).get("highest_nav", 0),
                cur_nav,
            ),
        }

    # 汇总
    scores = [r["score"] for r in results.values()]
    summary = {
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 50,
        "buy_signals": [c for c, r in results.items() if r["action"] in ("buy", "buy_1st", "buy_2nd", "buy_3rd")],
        "sell_signals": [c for c, r in results.items() if r["action"] in ("sell", "sell_1st", "sell_2nd", "sell_3rd")],
        "correlation_warnings": [],
    }

    # 合并相关性警告
    for r in results.values():
        summary["correlation_warnings"].extend(r["details"].get("warnings", []))

    return {"results": results, "summary": summary, "state": state}


if __name__ == "__main__":
    from data_collector import collect_all_data
    data = collect_all_data()
    report = evaluate_portfolio(data)
    # 打印结果
    for code, r in report["results"].items():
        name = data["funds"][code]["name"]
        emoji = "🟢" if r["action"].startswith("buy") else ("🔴" if r["action"].startswith("sell") else "⚪")
        print(f"\n{emoji} {name}({code}) | 评分:{r['score']:.0f} | {r['action']} {r['action_pct']:.0%}")
        print(f"  {r['reason']}")
