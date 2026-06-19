"""
回测自检模块 — 每周自动回测，评估策略有效性
自进化：自动微调参数（±10%），选择最优配置
"""
import json
import math
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from config import BACKTEST_DIR, WATCH_FUNDS, STRATEGY_CONFIG as CFG

# ==================== 简易回测引擎 ====================

def simple_backtest(nav_series: pd.Series, ma_short: int, ma_long: int,
                    stop_loss: float, take_profit: float,
                    initial_cash: float = 10000) -> dict:
    """
    基于双均线策略的简易回测
    返回：总收益、胜率、最大回撤、夏普比率
    """
    if len(nav_series) < ma_long + 1:
        return {"return": 0, "win_rate": 0, "max_dd": 0, "sharpe": 0, "trades": 0}

    ma_s = nav_series.rolling(ma_short).mean()
    ma_l = nav_series.rolling(ma_long).mean()

    cash = initial_cash
    shares = 0
    cost_price = 0
    highest_value = cash
    portfolio = [cash]  # 每日组合价值
    trades = 0
    wins = 0

    for i in range(ma_long, len(nav_series)):
        price = nav_series.iloc[i]
        prev_price = nav_series.iloc[i - 1]

        # 更新最高市值
        current_value = cash + shares * price
        portfolio.append(current_value)
        highest_value = max(highest_value, current_value)

        # 死叉卖出
        if (ma_s.iloc[i - 1] >= ma_l.iloc[i - 1] and ma_s.iloc[i] < ma_l.iloc[i]) or \
           (shares > 0 and cost_price > 0 and (price - cost_price) / cost_price <= stop_loss / 100) or \
           (shares > 0 and cost_price > 0 and (price - cost_price) / cost_price >= take_profit / 100):
            if shares > 0:
                cash = shares * price
                trades += 1
                if price > cost_price:
                    wins += 1
                shares = 0
                cost_price = 0

        # 金叉买入
        elif ma_s.iloc[i - 1] <= ma_l.iloc[i - 1] and ma_s.iloc[i] > ma_l.iloc[i] and shares == 0:
            shares = cash / price
            cost_price = price
            cash = 0

    final_value = cash + shares * nav_series.iloc[-1]
    total_return = (final_value - initial_cash) / initial_cash * 100
    win_rate = wins / max(trades, 1) * 100

    # 最大回撤
    portfolio_arr = np.array(portfolio)
    cummax = np.maximum.accumulate(portfolio_arr)
    drawdowns = (portfolio_arr - cummax) / cummax
    max_dd = float(np.min(drawdowns)) * 100

    # 夏普比率
    returns = np.diff(portfolio_arr) / portfolio_arr[:-1]
    sharpe = (np.mean(returns) / max(np.std(returns), 1e-10)) * math.sqrt(252) if len(returns) > 1 else 0

    return {
        "return": round(total_return, 2),
        "win_rate": round(win_rate, 1),
        "max_dd": round(max_dd, 2),
        "sharpe": round(float(sharpe), 2),
        "trades": trades,
    }


# ==================== 参数优化（自进化） ====================

def optimize_params(nav_series: pd.Series) -> dict:
    """网格搜索最优参数（±20%范围）"""
    base_ma_short = CFG["ma_short"]
    base_ma_long = CFG["ma_long"]
    base_stop_loss = CFG["stop_loss_pct"]
    base_take_profit = CFG["take_profit_pct"]

    param_grid = {
        "ma_short": [int(base_ma_short * r) for r in [0.8, 0.9, 1.0, 1.1, 1.2] if int(base_ma_short * r) >= 3],
        "ma_long": [int(base_ma_long * r) for r in [0.8, 0.9, 1.0, 1.1, 1.2] if int(base_ma_long * r) >= 10],
        "stop_loss": [base_stop_loss * r for r in [0.8, 1.0, 1.2]],
        "take_profit": [base_take_profit * r for r in [0.8, 1.0, 1.2]],
    }

    best = None
    best_score = -float("inf")

    # 限制组合数
    max_combos = 50
    combos = list(product(param_grid["ma_short"], param_grid["ma_long"], param_grid["stop_loss"], param_grid["take_profit"]))
    if len(combos) > max_combos:
        import random
        random.seed(42)
        combos = random.sample(combos, max_combos)

    for ms, ml, sl, tp in combos:
        if ms >= ml:
            continue
        bt = simple_backtest(nav_series, ms, ml, sl, tp)
        # 综合评分：收益 + 夏普 - 回撤惩罚
        score = bt["return"] * 0.3 + bt["sharpe"] * 20 - abs(bt["max_dd"]) * 0.5 + bt["win_rate"] * 0.2
        if score > best_score:
            best_score = score
            best = {"params": {"ma_short": ms, "ma_long": ml, "stop_loss": sl, "take_profit": tp}, **bt, "score": round(score, 2)}

    return best


def run_weekly_backtest(data: dict) -> dict:
    """每周回测所有关注的基金"""
    results = {}
    recommendations = []

    for code, fund_data in data["funds"].items():
        name = fund_data["name"]
        nav_df = fund_data.get("nav_df")
        if nav_df is None or nav_df.empty:
            continue

        # 找净值列
        nav_col = next((c for c in nav_df.columns if "净值" in c or "NAV" in c.upper()), nav_df.columns[-1])
        nav_series = pd.to_numeric(nav_df[nav_col], errors="coerce").dropna()

        if len(nav_series) < 30:
            continue

        # 基准参数回测
        base_result = simple_backtest(nav_series, CFG["ma_short"], CFG["ma_long"],
                                      CFG["stop_loss_pct"], CFG["take_profit_pct"])

        # 优化参数
        optimized = optimize_params(nav_series)

        results[code] = {
            "name": name,
            "base": base_result,
            "optimized": optimized,
        }

        if optimized:
            opt = optimized["params"]
            base_ret = base_result["return"]
            opt_ret = optimized["return"]
            if opt_ret > base_ret:
                recommendations.append({
                    "fund": name,
                    "code": code,
                    "change": f"ma_short {CFG['ma_short']}→{opt['ma_short']}",
                    "expected_improvement": f"{base_ret:.1f}%→{opt_ret:.1f}%",
                })

    # 保存
    timestamp = datetime.now().strftime("%Y%m%d")
    report = {
        "date": timestamp,
        "results": {k: {"name": v["name"], "base": v["base"], "optimized": v["optimized"]} for k, v in results.items()},
        "recommendations": recommendations,
    }
    path = BACKTEST_DIR / f"backtest_{timestamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


if __name__ == "__main__":
    from data_collector import collect_all_data
    data = collect_all_data()
    print("🔄 回测中...")
    report = run_weekly_backtest(data)
    print(f"  ✅ 回测完成，已保存到 {BACKTEST_DIR}")
    for rec in report.get("recommendations", []):
        print(f"  💡 {rec['fund']}: {rec['change']} → {rec['expected_improvement']}")
