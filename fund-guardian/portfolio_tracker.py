"""
持仓追踪模块 — 记录买卖，自动计算盈亏
每次买入/卖出时登记，脚本自动跟踪净值变动
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import ROOT_DIR

PORTFOLIO_FILE = ROOT_DIR / "data" / "portfolio.json"


def load_portfolio() -> dict:
    """加载持仓记录"""
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return {"trades": [], "holdings": {}}  # holdings: {code: {"name": "", "total_shares": 0, "total_cost": 0, "nav_at_buy": 0}}


def save_portfolio(pf: dict):
    PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORTFOLIO_FILE.write_text(json.dumps(pf, ensure_ascii=False, indent=2), encoding="utf-8")


def record_buy(fund_code: str, fund_name: str, amount_yuan: float,
               buy_nav: Optional[float] = None, buy_date: Optional[str] = None):
    """
    记录一次买入
    amount_yuan: 买入金额（元）
    buy_nav: 买入时的净值（如果不知道，填0，脚本会用当天净值）
    """
    pf = load_portfolio()

    # 确保 holdings 存在
    if fund_code not in pf["holdings"]:
        pf["holdings"][fund_code] = {"name": fund_name, "total_shares": 0, "total_cost": 0}

    h = pf["holdings"][fund_code]
    if buy_nav and buy_nav > 0:
        shares = amount_yuan / buy_nav
        h["total_shares"] += shares
        h["total_cost"] += amount_yuan
    else:
        # 如果没有提供净值，标记为待确认
        h["total_shares"] += 0  # 暂时不加，待净值更新后补
        h["total_cost"] += amount_yuan

    trade = {
        "type": "buy",
        "fund_code": fund_code,
        "fund_name": fund_name,
        "amount": amount_yuan,
        "nav": buy_nav,
        "date": buy_date or datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
    }
    pf["trades"].append(trade)
    save_portfolio(pf)
    return trade


def record_sell(fund_code: str, fund_name: str, amount_yuan: float,
                sell_nav: Optional[float] = None, sell_date: Optional[str] = None):
    """记录一次卖出"""
    pf = load_portfolio()

    if fund_code not in pf["holdings"]:
        return {"error": "没有该基金的持仓记录"}

    h = pf["holdings"][fund_code]
    if sell_nav and sell_nav > 0:
        shares = amount_yuan / sell_nav
        h["total_shares"] = max(0, h["total_shares"] - shares)
        h["total_cost"] = max(0, h["total_cost"] - amount_yuan)

    trade = {
        "type": "sell",
        "fund_code": fund_code,
        "fund_name": fund_name,
        "amount": amount_yuan,
        "nav": sell_nav,
        "date": sell_date or datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
    }
    pf["trades"].append(trade)
    save_portfolio(pf)
    return trade


def calculate_pnl(data: dict) -> dict:
    """
    基于最新净值计算持仓盈亏
    返回每只基金和总体的盈亏
    """
    pf = load_portfolio()
    holdings = pf.get("holdings", {})
    result = {"funds": {}, "total": {"cost": 0, "current_value": 0, "pnl": 0, "pnl_pct": 0}}

    for code, h in holdings.items():
        if h["total_shares"] <= 0:
            continue

        # 获取最新净值
        fund_data = data.get("funds", {}).get(code, {})
        estimate = fund_data.get("estimate", {})
        nav_df = fund_data.get("nav_df")

        current_nav = 0
        if estimate and estimate.get("estimate_nav"):
            current_nav = estimate["estimate_nav"]
        elif nav_df is not None and not nav_df.empty:
            nav_col = next((c for c in nav_df.columns if "净值" in c or "NAV" in c.upper()), nav_df.columns[-1])
            import pandas as pd
            nav_series = pd.to_numeric(nav_df[nav_col], errors="coerce").dropna()
            if len(nav_series) > 0:
                current_nav = float(nav_series.iloc[-1])

        if current_nav <= 0:
            continue

        current_value = h["total_shares"] * current_nav
        cost = h["total_cost"]
        pnl = current_value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0

        result["funds"][code] = {
            "name": h["name"],
            "shares": round(h["total_shares"], 2),
            "cost": round(cost, 2),
            "current_nav": round(current_nav, 4),
            "current_value": round(current_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        }

        result["total"]["cost"] += cost
        result["total"]["current_value"] += current_value

    tc = result["total"]["cost"]
    tv = result["total"]["current_value"]
    result["total"]["pnl"] = round(tv - tc, 2)
    result["total"]["pnl_pct"] = round((tv - tc) / tc * 100, 2) if tc > 0 else 0

    return result


def format_pnl_report(pnl: dict) -> str:
    """格式化盈亏报告（用于飞书推送）"""
    lines = ["💰 **持仓盈亏**\n"]

    for code, f in pnl.get("funds", {}).items():
        emoji = "🟢" if f["pnl"] >= 0 else "🔴"
        lines.append(
            f"{emoji} **{f['name']}**\n"
            f"　持仓: {f['shares']}份 | 成本: ¥{f['cost']:.2f}\n"
            f"　现价: {f['current_nav']:.4f} | 市值: ¥{f['current_value']:.2f}\n"
            f"　盈亏: ¥{f['pnl']:+.2f} ({f['pnl_pct']:+.1f}%)"
        )

    total = pnl["total"]
    emoji = "🟢" if total["pnl"] >= 0 else "🔴"
    lines.append(
        f"\n━━━━━━━━━━\n"
        f"{emoji} **总计**\n"
        f"　成本: ¥{total['cost']:.2f}\n"
        f"　市值: ¥{total['current_value']:.2f}\n"
        f"　累计盈亏: ¥{total['pnl']:+.2f} ({total['pnl_pct']:+.1f}%)"
    )
    return "\n".join(lines)


# ==================== CLI 接口 ====================

def cli():
    """命令行交互：记录买卖"""
    import sys
    if len(sys.argv) < 2:
        print("用法:")
        print("  python portfolio_tracker.py buy <基金代码> <金额> [净值]")
        print("  python portfolio_tracker.py sell <基金代码> <金额> [净值]")
        print("  python portfolio_tracker.py list")
        return

    cmd = sys.argv[1]

    if cmd == "buy":
        code = sys.argv[2]
        amount = float(sys.argv[3])
        nav = float(sys.argv[4]) if len(sys.argv) > 4 else None
        name = {v: k for k, v in __import__("config").WATCH_FUNDS.items()}.get(code, code)
        t = record_buy(code, name, amount, nav)
        print(f"✅ 买入记录: {name}({code}) ¥{amount}")

    elif cmd == "sell":
        code = sys.argv[2]
        amount = float(sys.argv[3])
        nav = float(sys.argv[4]) if len(sys.argv) > 4 else None
        name = {v: k for k, v in __import__("config").WATCH_FUNDS.items()}.get(code, code)
        t = record_sell(code, name, amount, nav)
        print(f"✅ 卖出记录: {name}({code}) ¥{amount}")

    elif cmd == "list":
        pf = load_portfolio()
        print(f"\n📊 持仓 ({len(pf['holdings'])} 只基金)")
        for code, h in pf["holdings"].items():
            if h["total_shares"] > 0:
                print(f"  {h['name']}({code}) | {h['total_shares']:.2f}份 | 成本¥{h['total_cost']:.2f}")
        print(f"\n📜 交易记录 ({len(pf['trades'])} 笔)")
        for t in pf["trades"][-10:]:
            print(f"  {t['date']} {t['type']} {t['fund_name']} ¥{t['amount']}")


if __name__ == "__main__":
    cli()
