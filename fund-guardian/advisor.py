"""
投资顾问模块 — 把策略信号翻译成具体金额指令
输出："买XX基金 300元"、"卖XX基金 200元"
"""
from config import WATCH_FUNDS, TOTAL_BUDGET, CASH_RESERVE, STRATEGY_CONFIG as CFG, ROOT_DIR
from portfolio_tracker import load_portfolio

# 资金池分配
STABLE_POOL_RATIO = 0.70   # 稳健池占总资金70%
SWING_POOL_RATIO = 0.30    # 波段池占总资金30%

# 稳健池基金（定投+长期持有）
STABLE_FUNDS = ["110020", "161017", "000085", "090010"]  # 沪深300,中证500,债券,红利
# 波段池基金（等信号）
SWING_FUNDS = ["003095", "001156", "320007", "110022"]   # 医疗,新能源,半导体,消费


def generate_instructions(strategy_report: dict, data: dict) -> list[dict]:
    """
    生成具体买卖指令
    返回每一条：{基金名, 代码, 动作, 金额, 理由}
    """
    instructions = []
    results = strategy_report["results"]
    pf = load_portfolio()
    holdings = pf.get("holdings", {})

    available_cash = TOTAL_BUDGET * (1 - CASH_RESERVE)

    # 计算当前总市值
    current_total = 0
    for code, h in holdings.items():
        if h["total_shares"] > 0:
            nav = 0
            estimate = data.get("funds", {}).get(code, {}).get("estimate", {})
            nav_data = data.get("funds", {}).get(code, {}).get("nav_df")
            if estimate and estimate.get("estimate_nav"):
                nav = estimate["estimate_nav"]
            elif nav_data is not None and not nav_data.empty:
                import pandas as pd
                nav_col = next((c for c in nav_data.columns if "净值" in c), nav_data.columns[-1])
                s = pd.to_numeric(nav_data[nav_col], errors="coerce").dropna()
                if len(s) > 0:
                    nav = float(s.iloc[-1])
            if nav > 0:
                current_total += h["total_shares"] * nav

    # 可用的新资金
    new_cash = max(0, available_cash - current_total)

    # 处理每只基金的信号
    for code, r in results.items():
        name = data["funds"][code]["name"]
        detail = r.get("details", {})
        action = r["action"]
        score = detail.get("score", 50.0)

        h = holdings.get(code, {"total_shares": 0, "total_cost": 0})
        current_shares = h.get("total_shares", 0)
        current_cost = h.get("total_cost", 0)

        # === 卖出信号 ===
        if action.startswith("sell"):
            if current_shares > 0:
                nav = detail["current_nav"]
                if action == "sell_1st":
                    sell_shares = current_shares * CFG["batch_sell_pcts"][0]
                elif action == "sell_2nd":
                    sell_shares = current_shares * CFG["batch_sell_pcts"][1]
                else:
                    sell_shares = current_shares  # 全部清仓
                sell_amount = round(sell_shares * nav, 2)
                if sell_amount > 0:
                    instructions.append({
                        "fund_name": name,
                        "fund_code": code,
                        "action": "卖出",
                        "amount": sell_amount,
                        "reason": detail.get("signals", [""])[0] if detail.get("signals") else "策略卖出信号",
                        "score": score,
                        "pool": "波段" if code in SWING_FUNDS else "稳健",
                    })

        # === 买入信号 ===
        elif action.startswith("buy") and new_cash > 0:
            # 分配买入金额
            if code in STABLE_FUNDS:
                pool_budget = TOTAL_BUDGET * STABLE_POOL_RATIO
                share = pool_budget / len(STABLE_FUNDS)
            else:
                pool_budget = TOTAL_BUDGET * SWING_POOL_RATIO
                share = pool_budget / len(SWING_FUNDS)

            if action == "buy_1st":
                buy_amount = round(share * CFG["batch_buy_pcts"][0], 2)
            elif action == "buy_2nd":
                buy_amount = round(share * CFG["batch_buy_pcts"][1], 2)
            else:
                buy_amount = round(share * CFG["batch_buy_pcts"][2], 2)

            buy_amount = min(buy_amount, new_cash)  # 不超过可用资金
            if buy_amount > 10:  # 最少10元
                instructions.append({
                    "fund_name": name,
                    "fund_code": code,
                    "action": "买入",
                    "amount": buy_amount,
                    "reason": detail.get("signals", [""])[0] if detail.get("signals") else "策略买入信号",
                    "score": score,
                    "pool": "稳健" if code in STABLE_FUNDS else "波段",
                })
                new_cash -= buy_amount

        # === 持有 ===
        else:
            # 稳健池基金如果还没买够，提示定投
            pe_pct = detail.get("pe_pct")
            if code in STABLE_FUNDS and pe_pct is not None and pe_pct <= CFG["pe_low_pct"]:
                share = (TOTAL_BUDGET * STABLE_POOL_RATIO) / len(STABLE_FUNDS)
                dca_amount = round(share * 0.1, 2)  # 定投每次10%份额
                if dca_amount > 10 and new_cash > dca_amount:
                    instructions.append({
                        "fund_name": name,
                        "fund_code": code,
                        "action": "定投买入",
                        "amount": dca_amount,
                        "reason": f"PE分位{pe_pct:.0f}%，低估加倍定投",
                        "score": score,
                        "pool": "稳健",
                    })
                    new_cash -= dca_amount

    # 排序：卖出优先，然后按分数降序
    instructions.sort(key=lambda x: (0 if x["action"] == "卖出" else 1, -x["score"]))
    return instructions


def format_instructions(instructions: list[dict]) -> str:
    """格式化为飞书/控制台消息"""
    if not instructions:
        return "📊 今日无需操作，所有基金持有观望"

    lines = ["📋 **今日操作指令**\n"]

    sells = [i for i in instructions if "卖" in i["action"]]
    buys = [i for i in instructions if "买" in i["action"]]

    if sells:
        lines.append("🔴 **卖出**")
        for s in sells:
            lines.append(f"→ {s['fund_name']}({s['fund_code']}) 卖出 **¥{s['amount']:.0f}**\n　{s['reason']}")
        lines.append("")

    if buys:
        lines.append("🟢 **买入**")
        for b in buys:
            lines.append(f"→ {b['fund_name']}({b['fund_code']}) 买入 **¥{b['amount']:.0f}** [{b['pool']}池]\n　{b['reason']}")
        lines.append("")

    total_buy = sum(i["amount"] for i in buys)
    total_sell = sum(i["amount"] for i in sells)
    lines.append(f"💰 买入合计: ¥{total_buy:.0f} | 卖出合计: ¥{total_sell:.0f}")

    return "\n".join(lines)


# ==================== 自动追踪 ====================
import json
PENDING_FILE = ROOT_DIR / "data" / "pending_orders.json"

def save_recommendations(instructions: list[dict]):
    """保存今日推荐，明天自动执行"""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    orders = [{
        "fund_code": i["fund_code"],
        "fund_name": i["fund_name"],
        "action": i["action"],
        "amount": i["amount"],
    } for i in instructions]
    data = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"), "orders": orders}
    PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def auto_execute_pending():
    """自动执行昨天的推荐（如果你没告诉脚本改动了的话）"""
    if not PENDING_FILE.exists():
        return []
    data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    from datetime import datetime
    saved_date = data.get("date", "")
    if not saved_date or saved_date == datetime.now().strftime("%Y-%m-%d"):
        return []
    from portfolio_tracker import record_buy, record_sell
    executed = []
    for o in data.get("orders", []):
        if "买" in o["action"]:
            record_buy(o["fund_code"], o["fund_name"], o["amount"])
            executed.append(f"追认买入 {o['fund_name']} ¥{o['amount']}")
        elif "卖" in o["action"]:
            record_sell(o["fund_code"], o["fund_name"], o["amount"])
            executed.append(f"追认卖出 {o['fund_name']} ¥{o['amount']}")
    PENDING_FILE.unlink()
    return executed


def get_portfolio_summary(data: dict) -> str:
    """获取当前持仓状态简报"""
    from portfolio_tracker import calculate_pnl, load_portfolio
    pf = load_portfolio()
    pnl = calculate_pnl(data)

    lines = ["💼 **你的持仓**\n"]

    has_holdings = False
    for code, h in pf.get("holdings", {}).items():
        if h["total_shares"] > 0:
            has_holdings = True
            name = h["name"]
            fp = pnl.get("funds", {}).get(code, {})
            pnl_str = f"¥{fp.get('pnl', 0):+.2f}" if fp else "?"
            lines.append(f"  {name}({code}) | 份额:{h['total_shares']:.2f} | 盈亏:{pnl_str}")

    if not has_holdings:
        lines.append("  ⚠️ 暂无持仓记录，请先根据买入建议操作")

    total = pnl.get("total", {})
    if total.get("cost", 0) > 0:
        lines.append(f"\n  总成本: ¥{total['cost']:.2f} | 市值: ¥{total['current_value']:.2f} | 盈亏: ¥{total['pnl']:+.2f}")

    return "\n".join(lines)
