#!/usr/bin/env python
"""
基金守护者 v3 — 预测版
= 量化层（全市场排名+技术指标+估值）+ AI宏观层（世界格局→行业预判）
"""
import sys, io, os, json, warnings, time, re
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

# 从.env加载
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').split('\n'):
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

FEISHU_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
AI_KEY = os.getenv("DEEPSEEK_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
AI_ENABLED = AI_KEY and "your-api-key" not in AI_KEY and len(AI_KEY) > 10

# ============ 宏观数据采集 ============
def get_macro_data() -> dict:
    """采集全球宏观指标"""
    macro = {
        "timestamp": datetime.now().isoformat(),
        "usd_cny": None,        # 美元/人民币
        "gold": None,           # 黄金价格
        "oil": None,            # 原油
        "sh_index": None,       # 上证指数
        "sz_index": None,       # 深证成指
        "us_rates": None,       # 美债收益率
    }

    try:
        # 汇率
        df = ak.currency_boc_safe(symbol='美元')
        if df is not None and not df.empty:
            macro["usd_cny"] = float(df.iloc[-1, -1])
    except: pass

    try:
        # 上证指数
        df = ak.stock_zh_index_daily(symbol='sh000001')
        if df is not None and not df.empty:
            macro["sh_index"] = float(df.iloc[-1]["close"])
            macro["sh_change"] = float((df.iloc[-1]["close"] - df.iloc[-2]["close"]) / df.iloc[-2]["close"] * 100)
    except: pass

    try:
        # 黄金
        df = ak.spot_gold()
        if df is not None and not df.empty:
            macro["gold"] = float(df.iloc[-1, 1]) if df.shape[1] > 1 else None
    except: pass

    return macro


# ============ 新闻采集 ============
def get_world_news() -> list[str]:
    """采集世界宏观新闻"""
    news = []
    try:
        # 财联社电报
        resp = requests.get(
            "https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&sv=8.4.6",
            params={"type": "telegraph", "page": "1", "rn": "50"},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200:
            items = resp.json().get("data", {}).get("roll_data", []) or resp.json().get("data", [])
            for item in items:
                title = item.get("title", "")
                if title:
                    news.append(title)
    except: pass

    return news[:30]


# ============ AI 宏观分析 ============
def ai_analyze_world(news: list[str], macro: dict) -> dict:
    """Claude AI 分析世界格局 → 预判行业影响"""
    if not AI_ENABLED:
        return {"error": "API key not configured"}

    from openai import OpenAI
    client = OpenAI(api_key=AI_KEY, base_url="https://api.deepseek.com")

    prompt = f"""你是全球宏观对冲基金的首席策略师。基于以下信息，判断未来1-4周哪些行业/板块最可能上涨。

**全球宏观数据：**
- 时间：{macro['timestamp']}
- 美元/人民币：{macro.get('usd_cny', 'N/A')}
- 上证指数：{macro.get('sh_index', 'N/A')}
- 黄金：{macro.get('gold', 'N/A')}

**今日宏观信号：**（基于现有数据推断）
- 上证指数当前处于{macro.get('sh_index', 'N/A')}点，近一年大涨，市场情绪亢奋
- 需判断当前是牛市延续还是高位风险

请用 JSON 回复：
{{
  "global_summary": "50字以内的全球格局判断",
  "bullish_sectors": ["看好的行业1", "行业2", "行业3"],
  "bearish_sectors": ["看空的行业1", "行业2"],
  "key_risks": ["主要风险1", "风险2"],
  "macro_stance": "risk_on|risk_off|neutral",
  "reasoning": "100字以内的核心逻辑",
  "fund_keywords": ["科技", "创新", "新能源", "半导体", "医药", "消费", "军工", "数字", "高端制造", "红利", "量化", "成长"]
}}

用中文回复，只输出JSON。"""

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=2000,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"): text = text.split("\n", 1)[1][:-3]
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}


# ============ 量化层 ============
def get_all_funds():
    cache = DATA_DIR / "fund_ranking_cache.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 3600:
        return pd.DataFrame(json.loads(cache.read_text(encoding='utf-8')))
    df = ak.fund_open_fund_rank_em(symbol='全部')
    cache.write_text(df.to_json(orient='records', force_ascii=False), encoding='utf-8')
    return df


def get_nav(code):
    cache = DATA_DIR / f"nav_{code}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 3600:
        vals = [float(v) for v in json.loads(cache.read_text(encoding='utf-8'))]
        return pd.Series(vals)
    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator='单位净值走势')
        nav_col = next((c for c in df.columns if '净值' in str(c)), df.columns[-1])
        vals = pd.to_numeric(df[nav_col], errors='coerce').dropna().tolist()
        vals = [float(v) for v in vals]
        cache.write_text(json.dumps(vals), encoding='utf-8')
        return pd.Series(vals)
    except: return None


def calc_rsi(s, p=14):
    d = s.diff()
    g = d.where(d>0, 0.).ewm(alpha=1/p, adjust=False).mean()
    l = (-d).where(d<0, 0.).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l.replace(0,1e-10)))


def score_fund(row, nav, ai_bullish_keywords=[], ai_bearish_keywords=[]):
    try:
        code = str(row.iloc[1]); name = str(row.iloc[2])
        m1 = float(row.iloc[8]) if str(row.iloc[8])!='-' else 0
        m3 = float(row.iloc[9]) if str(row.iloc[9])!='-' else 0
        y1 = float(row.iloc[11]) if str(row.iloc[11])!='-' else 0
    except: return None

    score = 50.0; reasons = []

    # --- 趋势评分 ---
    score += min(m1*0.3, 12)
    score += min(m3*0.1, 10)
    score += min(y1*0.015, 8)
    if m3 > m1*1.5: score += 5; reasons.append('趋势加速')
    elif m3 < m1: score -= 3; reasons.append('动能衰减')
    # 过热惩罚：1月涨>50%的降分（高位风险）
    if m1 > 50: score -= 15; reasons.append('短期过热(-15)')
    elif m1 > 40: score -= 8; reasons.append('涨幅偏高(-8)')
    if y1 > 400: score -= 10; reasons.append('年涨幅过大(-10)')

    # --- 技术指标 ---
    if nav is not None and len(nav) > 20:
        rsi = float(calc_rsi(nav).iloc[-1])
        ma5 = float(nav.rolling(5).mean().iloc[-1])
        ma20 = float(nav.rolling(20).mean().iloc[-1])
        dd60 = float(((nav.tail(60) - nav.tail(60).expanding().max()) / nav.tail(60).expanding().max()).min())

        if rsi > 78: score -= 12; reasons.append(f'RSI极度过热')
        elif rsi > 70: score -= 5; reasons.append(f'RSI偏热')
        elif rsi < 35: score += 5; reasons.append('RSI偏冷')

        if ma5 > ma20: score += 3
        else: score -= 5; reasons.append('均线走弱')

        if dd60 > -0.05: score += 5; reasons.append('回撤极小')
        elif dd60 < -0.15: score -= 8; reasons.append(f'回撤过大{dd60:.0%}')

    # --- AI 行业加成（权重加大，真正影响排名）---
    name_lower = name.lower()
    ai_bonus = 0
    for kw in ai_bullish_keywords:
        if kw.lower() in name_lower:
            ai_bonus = 15  # 从+8提到+15
            reasons.append(f'[AI看好:{kw}]')
            break
    for kw in ai_bearish_keywords:
        if kw.lower() in name_lower:
            ai_bonus = -20  # 从-8提到-20
            reasons.append(f'[AI看空:{kw}]')
            break
    score += ai_bonus

    return {'code':code, 'name':name, 'score':round(score,1),
            'm1':m1, 'm3':m3, 'y1':y1, 'reasons':reasons}


# ============ 主流程 ============
def run():
    print("="*60)
    print("FUND GUARDIAN v3 - AI PREDICTOR")
    print(f"AI enabled: {AI_ENABLED}")
    print("="*60)
    t0 = time.time()

    # 1. 宏观 + AI 分析
    macro = get_macro_data()
    news = get_world_news()
    print(f"Macro: SH={macro.get('sh_index')} | News: {len(news)} items")

    ai_bullish = []; ai_bearish = []; ai_report = None

    if AI_ENABLED:
        print("Running AI world analysis...")
        ai_report = ai_analyze_world(news or [], macro)
        if "error" not in ai_report:
            ai_bullish = ai_report.get("bullish_sectors", [])
            ai_bearish = ai_report.get("bearish_sectors", [])
            print(f"  AI bullish: {ai_bullish}")
            print(f"  AI bearish: {ai_bearish}")
        else:
            print(f"  AI error: {ai_report.get('error')}")
    else:
        print("  AI skipped (no API key or no news)")

    # 2. 全市场排名
    df = get_all_funds()
    print(f"Funds: {len(df)}")

    # 3. 筛选 + 评分
    seen = set(); results = []
    count = 0
    for _, row in df.iterrows():
        try:
            name = str(row.iloc[2])
            m1 = float(row.iloc[8]) if str(row.iloc[8])!='-' else 0
            m3 = float(row.iloc[9]) if str(row.iloc[9])!='-' else 0
            y1 = float(row.iloc[11]) if str(row.iloc[11])!='-' else 0
        except: continue

        if '债' in name or '货币' in name: continue
        if m1 < 5 or m3 < 10 or y1 < 15: continue

        base = name.replace('A','').replace('C','')
        if base in seen: continue
        seen.add(base)

        code = str(row.iloc[1])
        nav = get_nav(code)
        r = score_fund(row, nav, ai_bullish, ai_bearish)
        if r and r['score'] >= 55:
            results.append(r)
            count += 1
            if count >= 40: break  # 评分最多40只

    results.sort(key=lambda x: x['score'], reverse=True)
    top = results[:8]

    # 4. 推送飞书
    msg_lines = [f"**FUND GUARDIAN v3 — AI预测**\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]

    if ai_report and "error" not in ai_report:
        msg_lines.append(f"🌍 **全球格局**: {ai_report.get('global_summary','')}")
        msg_lines.append(f"📈 **看好的方向**: {', '.join(ai_bullish)}")
        msg_lines.append(f"⚠️ **风险**: {', '.join(ai_report.get('key_risks',[]))}")
        msg_lines.append(f"🎯 **策略**: {ai_report.get('macro_stance','neutral')}")
        msg_lines.append(f"\n---\n")

    if macro.get('sh_index'):
        msg_lines.append(f"上证: {macro['sh_index']:.0f} ({macro.get('sh_change',0):+.2f}%)")

    msg_lines.append(f"\n**推荐基金 (综合评分):**")
    for i, r in enumerate(top):
        msg_lines.append(
            f"#{i+1} {r['code']} {r['name'][:22]} | 评分{r['score']:.0f}\n"
            f"    1mo:{r['m1']:+6.2f}% | 3mo:{r['m3']:+6.2f}% | 1yr:{r['y1']:+6.2f}%\n"
            f"    {', '.join(r['reasons'])}"
        )

    msg_lines.append(f"\n---\n扫描{len(df)}只 | 评分{len(results)}只 | {time.time()-t0:.0f}秒")

    msg = "\n".join(msg_lines)
    print(msg)

    if FEISHU_URL:
        card = {"msg_type":"interactive","card":{"header":{"title":{"tag":"plain_text","content":"FUND GUARDIAN v3"},"template":"purple"},"elements":[{"tag":"markdown","content":msg}]}}
        try:
            r = requests.post(FEISHU_URL, json=card, timeout=10)
            print(f"\nFeishu: {'OK' if r.status_code==200 else 'FAIL'}")
        except Exception as e:
            print(f"\nFeishu: FAIL ({e})")

    return top


if __name__ == '__main__':
    run()
