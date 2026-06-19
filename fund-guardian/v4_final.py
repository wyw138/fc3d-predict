#!/usr/bin/env python
"""
FUND GUARDIAN v4 — 预测版（买入时机 + 卖出信号 + 回测 + 持仓监控）
"""
import sys, io, os, json, warnings, time
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import akshare as ak
import pandas as pd
import numpy as np
import requests

# ============ 配置 ============
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').split('\n'):
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

FEISHU_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
AI_KEY = os.getenv("DEEPSEEK_API_KEY", "")
AI_ON = AI_KEY and len(AI_KEY) > 10
PORTFOLIO_FILE = DATA_DIR / "portfolio_v4.json"

# ============ 持仓追踪 ============
def load_pf():
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8'))
    return {"holdings": {}, "trades": []}

def save_pf(pf):
    PORTFOLIO_FILE.write_text(json.dumps(pf, ensure_ascii=False, indent=2), encoding='utf-8')

def record_buy(code, name, amount, nav=None):
    pf = load_pf()
    h = pf["holdings"].setdefault(code, {"name": name, "cost": 0, "shares": 0, "buy_nav": 0, "highest_nav": 0})
    h["cost"] += amount
    if nav:
        h["shares"] += amount / nav
        h["buy_nav"] = nav
        h["highest_nav"] = max(h["highest_nav"], nav)
    pf["trades"].append({"type": "buy", "code": code, "name": name, "amount": amount, "nav": nav, "time": datetime.now().isoformat()})
    save_pf(pf)

def record_sell(code, amount, nav=None):
    pf = load_pf()
    h = pf["holdings"].get(code, {})
    if h.get("shares", 0) > 0 and nav:
        sold_shares = min(amount / nav, h["shares"])
        h["shares"] -= sold_shares
        h["cost"] = max(0, h["cost"] - amount)
        if h["shares"] <= 0.001:
            del pf["holdings"][code]
    pf["trades"].append({"type": "sell", "code": code, "name": h.get("name", ""), "amount": amount, "nav": nav, "time": datetime.now().isoformat()})
    save_pf(pf)

# ============ 回测引擎 ============
def backtest(nav_series, buy_condition, sell_condition, cash=1000):
    """回测：按买入/卖出条件模拟交易"""
    if len(nav_series) < 60:
        return {"return": 0, "trades": 0, "win_rate": 0, "max_dd": 0, "sharpe": 0}

    cash_orig = cash
    shares = 0; cost = 0; trades = 0; wins = 0
    values = [cash]

    for i in range(60, len(nav_series)):
        price = float(nav_series.iloc[i])
        window = nav_series.iloc[max(0,i-60):i]

        # 买入信号
        if shares == 0 and buy_condition(window, nav_series, i):
            shares = cash / price
            cost = price
            cash = 0
            trades += 1

        # 卖出信号
        elif shares > 0:
            pnl = (price - cost) / cost
            # 止盈 +10% 或 止损 -8%
            if sell_condition(window, nav_series, i, price, cost) or pnl >= 0.10 or pnl <= -0.08:
                cash = shares * price
                if price > cost: wins += 1
                shares = 0
                cost = 0

        values.append(cash + shares * price)

    final = cash + shares * nav_series.iloc[-1]
    ret = (final - cash_orig) / cash_orig * 100
    wr = wins / max(trades, 1) * 100
    arr = np.array(values)
    dd = float(np.min((arr - np.maximum.accumulate(arr)) / np.maximum.accumulate(arr))) * 100
    r = np.diff(arr) / (arr[:-1] + 1e-10)
    sharpe = float(np.mean(r) / max(np.std(r), 1e-10)) * np.sqrt(252)

    return {"return": round(ret, 1), "trades": trades, "win_rate": round(wr, 1),
            "max_dd": round(dd, 1), "sharpe": round(sharpe, 1)}

# ============ 买入条件（找刚要涨的，不买已经飞天的）============
def is_buy_signal(window, full_series, idx):
    """买入信号：回调到均线附近，趋势未破"""
    if len(window) < 30: return False
    current = float(window.iloc[-1])

    # 价格回落到MA20附近（±5%）
    ma20 = float(window.rolling(20).mean().iloc[-1])
    if abs(current - ma20) / ma20 > 0.05:
        return False

    # RSI不能极端（允许牛市50-75）
    d = window.diff(); g=d.where(d>0,0.).ewm(alpha=1/14,adjust=False).mean()
    l=(-d).where(d<0,0.).ewm(alpha=1/14,adjust=False).mean()
    rs=g/l.replace(0,1e-10); rsi=100-100/(1+float(rs.iloc[-1]))
    if rsi > 78 or rsi < 30:
        return False

    # MA5拐头
    ma5 = float(window.rolling(5).mean().iloc[-1])
    if ma5 <= float(window.rolling(5).mean().iloc[-2]):
        return False

    return True


def is_sell_signal(window, full_series, idx, price, cost):
    """卖出信号：死叉 或 RSI超买 或 回撤过大"""
    if len(window) < 30: return False

    # MA5 下穿 MA20
    ma5 = float(window.rolling(5).mean().iloc[-1])
    ma20 = float(window.rolling(20).mean().iloc[-1])
    ma5_prev = float(window.rolling(5).mean().iloc[-2])
    ma20_prev = float(window.rolling(20).mean().iloc[-2])

    if ma5_prev >= ma20_prev and ma5 < ma20:
        return True

    # RSI > 75 超买
    delta = window.diff()
    gain = delta.where(delta>0,0.).ewm(alpha=1/14,adjust=False).mean()
    loss = (-delta).where(delta<0,0.).ewm(alpha=1/14,adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    rsi = 100 - 100/(1+float(rs.iloc[-1]))
    if rsi > 78:
        return True

    return False


# ============ AI 宏观分析 ============
def ai_predict():
    if not AI_ON: return {}
    from openai import OpenAI
    client = OpenAI(api_key=AI_KEY, base_url="https://api.deepseek.com")

    prompt = """你是量化基金经理，判断未来2-4周哪些板块会上涨。

考虑当前环境：上证指数在4000点附近，经历了一年的大涨。
判断哪些方向还有空间，哪些已经过热。

输出JSON：
{
  "verdict": "上证4000点处于什么阶段，还能不能涨",
  "hot_sectors": ["真正还有上涨空间的行业名，2-4个"],
  "cold_sectors": ["已经过热该回避的行业，2-3个"],
  "entry_timing": "现在适合入场还是等待回调",
  "risk_level": "high|medium|low",
  "keywords": ["匹配基金名的关键词", "用于自动筛选"]
}

用中文，只输出JSON。"""

    try:
        resp = client.chat.completions.create(model="deepseek-chat", max_tokens=2000, temperature=0.3,
                                               messages=[{"role": "user", "content": prompt}])
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"): text = text.split("\n", 1)[1].replace("```", "")
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}


# ============ 基金评分（找买点，不是找高点）============
def score_for_entry(row, nav_series, ai_keywords):
    try:
        code = str(row.iloc[1]); name = str(row.iloc[2])
        m1 = float(row.iloc[8]) if str(row.iloc[8])!='-' else 0
        m3 = float(row.iloc[9]) if str(row.iloc[9])!='-' else 0
    except: return None

    score = 50; reasons = []

    # 趋势持续性（不要脉冲）
    if 8 <= m1 <= 25 and m3 >= 15:
        score += 10; reasons.append('稳健趋势')
    elif m1 > 35:
        score -= 20; reasons.append('短期过热')
    elif m1 < 3:
        return None

    if nav_series is None or len(nav_series) < 60:
        return None

    # RSI（牛市放宽到30-75都行，但不同区间打分不同）
    d = nav_series.diff(); g=d.where(d>0,0.).ewm(alpha=1/14,adjust=False).mean()
    l=(-d).where(d<0,0.).ewm(alpha=1/14,adjust=False).mean()
    rs=g/l.replace(0,1e-10); rsi=100-100/(1+float(rs.iloc[-1]))

    if 45 <= rsi <= 60: score += 15; reasons.append(f'RSI健康({rsi:.0f})')
    elif 35 <= rsi < 45: score += 10; reasons.append(f'RSI偏低({rsi:.0f})')
    elif 60 < rsi <= 72: score += 3; reasons.append(f'RSI偏强({rsi:.0f})')
    elif rsi > 72: score -= 8; reasons.append(f'RSI过热({rsi:.0f})')
    else: score += 5; reasons.append(f'RSI超卖({rsi:.0f})')

    # 均线
    ma5 = float(nav_series.rolling(5).mean().iloc[-1])
    ma20 = float(nav_series.rolling(20).mean().iloc[-1])
    price = float(nav_series.iloc[-1])
    high60 = float(nav_series.tail(60).max())

    # 价格相对MA20位置
    dist_ma20 = (price - ma20) / ma20 * 100
    if -1 <= dist_ma20 <= 3: score += 12; reasons.append(f'MA20附近({dist_ma20:+.1f}%)')
    elif dist_ma20 < -3: score += 8; reasons.append(f'MA20下方(超跌)')
    elif dist_ma20 > 8: score -= 8; reasons.append('远离MA20')

    # 距60高点
    dist_high = (price - high60) / high60 * 100
    if -10 <= dist_high <= -2: score += 10; reasons.append(f'从高点回调({dist_high:.0f}%)')
    elif dist_high > -1: score -= 3

    # 回撤
    dd60 = float(((nav_series.tail(60) - nav_series.tail(60).expanding().max()) / nav_series.tail(60).expanding().max()).min())
    if dd60 > -0.08: score += 5; reasons.append('回撤控制好')
    else: score -= 5

    # AI 方向
    name_lo = name.lower()
    for kw in ai_keywords:
        if kw.lower() in name_lo:
            score += 12; reasons.append(f'AI看好:{kw}')
            break

    # 回测验证（20日为窗口的快速回测）
    bt = backtest(nav_series.tail(120), is_buy_signal, is_sell_signal)
    if bt["return"] > 5 and bt["sharpe"] > 0.3:
        score += 8; reasons.append(f'回测OK(+{bt["return"]:.0f}%)')
    elif bt["return"] < -5:
        score -= 5

    return {'code':code, 'name':name, 'score':round(score,1), 'm1':m1, 'm3':m3,
            'rsi':round(rsi,1), 'price':round(price,4), 'ma5':round(ma5,4),
            'dist_from_high':round(dist_high,1), 'reasons':reasons, 'backtest':bt}


# ============ 主流程 ============
def run():
    print("="*60)
    print("FUND GUARDIAN v4 — ENTRY TIMING + BACKTEST")
    print(f"AI: {'ON' if AI_ON else 'OFF'}")
    print("="*60)
    t0 = time.time()

    # 1. AI 判断
    ai = ai_predict() if AI_ON else {}
    ai_kw = ai.get("keywords", []) if "keywords" in ai else ["科技", "创新", "成长"]
    print(f"AI: {ai.get('entry_timing','N/A')} | Risk: {ai.get('risk_level','N/A')}")
    print(f"   Hot: {ai.get('hot_sectors',[])}")

    # 2. 全市场
    cache = DATA_DIR / "fund_ranking_cache.json"
    if cache.exists() and time.time()-cache.stat().st_mtime < 3600:
        df = pd.DataFrame(json.loads(cache.read_text(encoding='utf-8')))
    else:
        df = ak.fund_open_fund_rank_em(symbol='全部')
        cache.write_text(df.to_json(orient='records', force_ascii=False), encoding='utf-8')

    # 3. 评分（限制数量以加速）
    seen = set(); results = []; count = 0
    for _, row in df.iterrows():
        try:
            name = str(row.iloc[2])
            code = str(row.iloc[1])
            m1 = float(row.iloc[8]) if str(row.iloc[8])!='-' else 0
            m3 = float(row.iloc[9]) if str(row.iloc[9])!='-' else 0
            if '债' in name or '货币' in name or m1 < 3 or m3 < 5:
                continue
            base = name.replace('A','').replace('C','')
            if base in seen: continue
            seen.add(base)
        except: continue

        # 拉净值
        nav_cache = DATA_DIR / f"nav_{code}.json"
        nav = None
        if nav_cache.exists():
            vals = json.loads(nav_cache.read_text(encoding='utf-8'))
            if vals and len(vals) > 30:  # 至少30个数据点
                nav = pd.Series([float(v) for v in vals])

        if nav is None:
            try:
                ndf = ak.fund_open_fund_info_em(symbol=code, indicator='单位净值走势')
                nc = next((c for c in ndf.columns if '净值' in str(c) and '日期' not in str(c)), ndf.columns[-1])
                vals = pd.to_numeric(ndf[nc], errors='coerce').dropna().tolist()
                vals = [float(v) for v in vals]
                if vals and len(vals) > 30:
                    nav_cache.write_text(json.dumps(vals), encoding='utf-8')
                    nav = pd.Series(vals)
                    print(f'  Downloaded: {code} ({len(vals)} points)')
            except Exception as e:
                print(f'  Failed {code}: {e}')
                continue

        r = score_for_entry(row, nav, ai_kw)
        if r and r['score'] >= 60:
            results.append(r)
        count += 1
        if len(results) >= 8 or count >= 200:  # 扫200只或找到8个
            break

    results.sort(key=lambda x: x['score'], reverse=True)
    top = results[:6]

    # 4. 持仓监控（确保有净值数据）
    pf = load_pf()
    for code, h in pf.get("holdings", {}).items():
        if h.get("shares", 0) <= 0: continue
        nc = DATA_DIR / f"nav_{code}.json"
        if not nc.exists() or len(json.loads(nc.read_text(encoding='utf-8'))) < 30:
            try:
                ndf = ak.fund_open_fund_info_em(symbol=code, indicator='单位净值走势')
                ncol = next((c for c in ndf.columns if '净值' in str(c) and '日期' not in str(c)), ndf.columns[-1])
                vals = pd.to_numeric(ndf[ncol], errors='coerce').dropna().tolist()
                vals = [float(v) for v in vals]
                if vals:
                    nc.write_text(json.dumps(vals), encoding='utf-8')
            except: pass

    holdings_report = []
    total_pnl = 0
    for code, h in pf.get("holdings", {}).items():
        if h.get("shares", 0) <= 0: continue
        # 找净值
        nc = DATA_DIR / f"nav_{code}.json"
        if nc.exists():
            vals = [float(v) for v in json.loads(nc.read_text(encoding='utf-8'))]
            cur_nav = vals[-1]
            current_val = h["shares"] * cur_nav
            pnl = current_val - h["cost"]
            pnl_pct = (current_val / h["cost"] - 1) * 100 if h["cost"] > 0 else 0
            total_pnl += pnl
            signal = ""
            s = pd.Series(vals)
            if is_sell_signal(s.tail(60), s, len(s)-1, cur_nav, h.get("buy_nav", cur_nav)):
                signal = " ⚠️ 卖出信号!"
            elif pnl_pct <= -8:
                signal = " 🛑 止损触发!"
            elif pnl_pct >= 10:
                signal = " 💰 止盈建议"
            holdings_report.append(f"  {h['name']}({code}) | 持仓¥{current_val:.0f} | 盈亏{pnl_pct:+.1f}%{signal}")

    # 5. 构建操作指令
    risk = ai.get("risk_level", "medium") if ai else "medium"
    available = 400  # 现金

    # 算出现金
    total_invested = sum(h.get("cost",0) for h in pf.get("holdings",{}).values())
    available = 1000 - total_invested

    msg = [f"**FUND GUARDIAN v4**\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]

    if ai and "verdict" in ai:
        msg.append(f"🔮 **AI判断**: {ai.get('verdict','')}")
        msg.append(f"🎯 风险: {risk} | {ai.get('entry_timing','')}")

    # ---- 仓位 ----
    msg.append(f"\n💼 **当前持仓** | 总资产: ¥{total_invested + total_pnl + available:.0f}")
    if holdings_report:
        for h in holdings_report:
            msg.append(h)
    else:
        msg.append("  空仓")
    msg.append(f"  现金: ¥{available}")

    # ---- 操作指令 ----
    msg.append(f"\n📋 **操作指令**")

    # 卖出检查
    has_sell = False
    for h_line in holdings_report:
        if '卖出' in h_line or '止损' in h_line or '止盈' in h_line:
            has_sell = True
            # Extract fund name and signal
            msg.append(f"  {h_line.strip()}")

    # 买入推荐
    if risk == "high":
        msg.append(f"  ✋ **暂不买入** — AI判断高位风险，持有现金等待回调")
    elif top:
        buy_per_fund = min(200, available // max(len(top[:3]), 1))
        if buy_per_fund >= 50:
            for i, r in enumerate(top[:3]):
                msg.append(
                    f"  🟢 **买入 {r['code']} {r['name'][:15]} {buy_per_fund}元**\n"
                    f"     评分{r['score']:.0f} RSI{r['rsi']:.0f} | {r['reasons'][0] if r['reasons'] else ''}"
                )
        else:
            msg.append(f"  💤 现金不足，等待卖出后再买入")
    else:
        msg.append(f"  💤 暂未发现符合条件的买点")

    msg.append(f"\n---\n{len(df)}只 | {time.time()-t0:.0f}秒 | 下次9:00自动")

    full_msg = "\n".join(msg)
    print(full_msg)

    # 6. 推飞书
    if FEISHU_URL:
        card = {"msg_type":"interactive","card":{"header":{"title":{"tag":"plain_text","content":"FUND GUARDIAN v4"},"template":"purple"},"elements":[{"tag":"markdown","content":full_msg}]}}
        try:
            r = requests.post(FEISHU_URL, json=card, timeout=10)
            print(f"\nFeishu: {'OK' if r.status_code==200 else 'FAIL'}")
        except Exception as e:
            print(f"\nFeishu FAIL: {e}")


# ============ 持仓同步 ============
def sync_portfolio():
    """将之前v1的持仓迁移到v4"""
    old = DATA_DIR / "portfolio.json"
    if old.exists():
        old_pf = json.loads(old.read_text(encoding='utf-8'))
        pf = load_pf()
        for code, h in old_pf.get("holdings", {}).items():
            if h.get("total_cost", 0) > 0 and code not in pf["holdings"]:
                pf["holdings"][code] = {"name": h["name"], "cost": h["total_cost"], "shares": 0, "buy_nav": 0, "highest_nav": 0}
        save_pf(pf)

sync_portfolio()

if __name__ == '__main__':
    run()
