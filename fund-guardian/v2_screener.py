#!/usr/bin/env python
"""
基金守护者 v2 — 全市场扫描版
使用 Python 3.14 + AKShare 拉全市场基金排名，六层策略过滤，飞书推送
"""
import sys, io, os, json, warnings, time, hashlib
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import akshare as ak
import pandas as pd
import numpy as np
import requests

# ============ 配置 ============
DATA_DIR = Path(__file__).parent / "data" if '__file__' in dir() else Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

FEISHU_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/915caf64-a753-469e-b1f3-b6285c2332aa"

# 策略筛选条件
FILTER = {
    "m1_min": 10.0,    # 近1月最低涨幅
    "m1_max": 35.0,    # 近1月最高（防过热）
    "m3_min": 15.0,    # 近3月最低
    "y1_min": 30.0,    # 近1年最低
    "max_funds": 8,    # 最多推荐几只
}

# ============ 数据采集 ============
def get_all_funds_ranking():
    """拉取全市场基金排名"""
    cache_file = DATA_DIR / "fund_ranking_cache.json"
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < 3600:  # 1小时缓存
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            return pd.DataFrame(data)

    print("Fetching fund rankings from Eastmoney...")
    df = ak.fund_open_fund_rank_em(symbol='全部')

    # 保存缓存
    cache_file.write_text(df.to_json(orient='records', force_ascii=False), encoding='utf-8')
    return df


def get_fund_nav_history(code: str, name: str = "") -> pd.Series | None:
    """拉取单只基金净值历史"""
    cache_file = DATA_DIR / f"nav_{code}.json"
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < 7200:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            vals = [float(v) for v in data if v is not None]
            return pd.Series(vals) if vals else None

    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator='单位净值走势')
        if df is not None and not df.empty:
            nav_col = None
            for c in df.columns:
                if '净值' in str(c) or 'NAV' in str(c).upper():
                    nav_col = c
                    break
            if nav_col is None:
                nav_col = df.columns[-1]
            vals = pd.to_numeric(df[nav_col], errors='coerce').dropna().tolist()
            vals_clean = [float(v) for v in vals if not pd.isna(v)]
            cache_file.write_text(json.dumps(vals_clean), encoding='utf-8')
            return pd.Series(vals_clean) if vals_clean else None
    except Exception as e:
        pass
    return None


# ============ 策略指标 ============
def calc_ma(series, window):
    return series.rolling(window=window).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def calc_max_drawdown(series):
    cummax = series.expanding().max()
    return float(((series - cummax) / cummax).min())


def score_fund_quick(row, nav_series=None) -> dict | None:
    """快速评分：近1月/3月/1年收益 + 趋势 + RSI"""
    try:
        code = str(row.iloc[1])
        name = str(row.iloc[2])
        m1 = float(row.iloc[8]) if str(row.iloc[8]) != '-' else 0
        m3 = float(row.iloc[9]) if str(row.iloc[9]) != '-' else 0
        y1 = float(row.iloc[11]) if str(row.iloc[11]) != '-' else 0
    except:
        return None

    score = 50.0
    reasons = []

    # 收益评分
    score += min(m1 * 0.3, 15)    # 近1月最多+15
    score += min(m3 * 0.15, 15)   # 近3月最多+15
    score += min(y1 * 0.02, 10)   # 近1年最多+10

    # 趋势持续性好
    if m3 > m1 * 2:
        score += 5
        reasons.append('趋势加速')
    elif m3 < m1:
        score -= 5
        reasons.append('短期脉冲')

    # RSI 检查（如果有净值数据）
    if nav_series is not None and len(nav_series) > 20:
        rsi = float(calc_rsi(nav_series).iloc[-1])
        if rsi > 75:
            score -= 10
            reasons.append(f'RSI过热({rsi:.0f})')
        elif rsi < 35:
            score += 5
            reasons.append(f'RSI偏低({rsi:.0f})')

        # 均线趋势
        ma5 = float(calc_ma(nav_series, 5).iloc[-1])
        ma20 = float(calc_ma(nav_series, 20).iloc[-1])
        if ma5 > ma20:
            score += 3
        else:
            score -= 5
            reasons.append('短期均线走弱')

        # 回撤惩罚
        dd = calc_max_drawdown(nav_series.tail(60))  # 近60天最大回撤
        if dd < -0.08:
            score += 5  # 涨幅大但回撤小 = 稳健
        elif dd < -0.15:
            score -= 3
        else:
            score -= 8
            reasons.append(f'回撤过大({dd:.0%})')

    return {
        'code': code,
        'name': name,
        'score': round(score, 1),
        'm1': m1, 'm3': m3, 'y1': y1,
        'reasons': reasons,
    }


# ============ 主流程 ============
def run_screener():
    print("="*60)
    print("FUND GUARDIAN v2 - Full Market Screener")
    print("="*60)

    t0 = time.time()

    # 1. 全市场排名
    df = get_all_funds_ranking()
    print(f"Loaded {len(df)} funds")

    # 2. 初筛（排除债/货币/C类）
    candidates = []
    seen = set()
    for _, row in df.iterrows():
        try:
            name = str(row.iloc[2])
            m1 = float(row.iloc[8]) if str(row.iloc[8]) != '-' else 0
            m3 = float(row.iloc[9]) if str(row.iloc[9]) != '-' else 0
            y1 = float(row.iloc[11]) if str(row.iloc[11]) != '-' else 0
        except:
            continue

        if '债' in name or '货币' in name:
            continue
        if not (FILTER['m1_min'] <= m1 <= FILTER['m1_max']):
            continue
        if m3 < FILTER['m3_min'] or y1 < FILTER['y1_min']:
            continue

        base = name.replace('A', '').replace('C', '')
        if base in seen:
            continue
        seen.add(base)
        candidates.append(row)

    print(f"Filtered to {len(candidates)} candidates")

    # 3. 拉净值 + 评分（串行，避免 py_mini_racer 多线程崩溃）
    print("Scoring...")
    results = []

    for i, row in enumerate(candidates[:30]):
        code = str(row.iloc[1])
        name = str(row.iloc[2])
        try:
            nav = get_fund_nav_history(code, name)
            r = score_fund_quick(row, nav)
            if r and r['score'] >= 50:
                results.append(r)
            if (i+1) % 5 == 0:
                print(f"  {i+1}/{min(len(candidates), 30)} scored...")
        except Exception as e:
            print(f"  {name}({code}) scoring failed: {e}")

    # 4. 排序
    results.sort(key=lambda x: x['score'], reverse=True)

    # 5. 输出
    print()
    print(f"TOP {FILTER['max_funds']} RECOMMENDATIONS ({time.time()-t0:.0f}s)")
    print("="*60)

    report = []
    for i, r in enumerate(results[:FILTER['max_funds']]):
        line = (f"#{i+1} {r['code']} {r['name'][:22]}\n"
                f"    1mo:{r['m1']:+6.2f}% | 3mo:{r['m3']:+6.2f}% | 1yr:{r['y1']:+6.2f}% | Score:{r['score']:.0f}")
        if r['reasons']:
            line += f"\n    {' | '.join(r['reasons'])}"
        print(line)
        report.append(line)

    # 6. 推飞书
    msg = f"**FUND GUARDIAN v2 - Market Screener**\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    msg += "\n\n".join(report)
    msg += f"\n\nFilter: 1mo {FILTER['m1_min']}-{FILTER['m1_max']}% | 3mo>{FILTER['m3_min']}% | 1yr>{FILTER['y1_min']}%"
    msg += f"\nScanned {len(df)} funds, scored {len(candidates)}, recommended {min(len(results), FILTER['max_funds'])}"

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "FUND GUARDIAN v2"}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": msg}],
        },
    }

    try:
        resp = requests.post(FEISHU_URL, json=card, timeout=10)
        print(f"\nFeishu: {'OK' if resp.status_code == 200 else 'FAIL '+str(resp.status_code)}")
    except Exception as e:
        print(f"\nFeishu: FAIL ({e})")

    return results


if __name__ == '__main__':
    run_screener()
