"""
全市场基金筛选器 — 扫描所有基金，按六层策略评分，推荐最优
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import pandas as pd

from config import STRATEGY_CONFIG as CFG, NAV_DIR
from strategy_engine import evaluate_fund
from data_collector import get_fund_nav, get_fund_valuation, _cache_path, _load_cache, _save_cache


def get_all_funds() -> pd.DataFrame:
    """获取全市场开放式基金列表"""
    cache = _load_cache(NAV_DIR, "all_funds_list", max_age_hours=24)
    if cache and "df" in cache:
        return pd.DataFrame(cache["df"])

    try:
        df = ak.fund_open_fund_daily_em()
        if df is not None and not df.empty:
            # 过滤：成立>1年、规模>1亿、非货币/债券C类
            _save_cache(NAV_DIR, "all_funds_list", {"df": df.to_dict(orient="records")})
            return df
    except Exception as e:
        print(f"  Failed to get fund list: {e}")
    return pd.DataFrame()


def filter_funds(df: pd.DataFrame) -> pd.DataFrame:
    """过滤：只保留值得分析的基金"""
    if df.empty:
        return df

    filtered = df.copy()

    # 列名映射（AKShare可能用不同列名）
    col_map = {}
    for c in filtered.columns:
        cl = c.strip()
        if "代码" in cl or "基金代码" in cl:
            col_map["code"] = c
        elif "名称" in cl:
            col_map["name"] = c
        elif "类型" in cl:
            col_map["type"] = c
        elif "规模" in cl or "资产" in cl:
            col_map["size"] = c
        elif "成立" in cl or "日期" in cl:
            col_map["date"] = c

    # 尝试过滤
    try:
        # 排除货币基金、债券基金
        if "type" in col_map:
            type_col = col_map["type"]
            filtered = filtered[~filtered[type_col].str.contains("货币|债券|短债|中短债", na=False)]

        # 排除成立不满1年的
        if "date" in col_map:
            date_col = col_map["date"]
            filtered[date_col] = pd.to_datetime(filtered[date_col], errors="coerce")
            cutoff = pd.Timestamp.now() - pd.DateOffset(years=1)
            filtered = filtered[filtered[date_col] < cutoff]
    except Exception:
        pass

    return filtered


def score_one_fund(code: str, name: str, sentiment: float = 50) -> dict | None:
    """对单只基金评分"""
    try:
        nav_df = get_fund_nav(code, name)
        if nav_df is None or nav_df.empty:
            return None

        valuation = get_fund_valuation(code)

        result = evaluate_fund(
            fund_code=code,
            fund_name=name,
            nav_df=nav_df,
            estimate=None,
            valuation=valuation,
            sentiment=sentiment,
            sectors=[],
        )
        if result["action"] == "hold" and result["score"] < 50:
            return None  # 太差的跳过

        return {
            "code": code,
            "name": name,
            "score": result["score"],
            "action": result["action"],
            "reason": result["reason"],
            "details": result["details"],
        }
    except Exception:
        return None


def screen_funds(max_funds: int = 100, min_score: int = 55) -> list[dict]:
    """
    扫描全市场基金，返回评分最高的 N 只
    max_funds: 最多分析多少只（默认100，全市场有上万只）
    min_score: 最低评分阈值
    """
    t0 = time.time()

    # 1. 获取基金列表
    all_funds = get_all_funds()
    if all_funds.empty:
        print("  Cannot get fund list, using preset 8 funds only")
        return []

    filtered = filter_funds(all_funds)
    print(f"  Filtered: {len(filtered)} funds from {len(all_funds)} total")

    if len(filtered) > max_funds:
        filtered = filtered.head(max_funds)

    # 2. 并行评分
    results = []
    codes = []
    for _, row in filtered.iterrows():
        code = str(row.iloc[0]) if len(row) > 0 else ""
        name = str(row.iloc[1]) if len(row) > 1 else code
        if len(code) == 6 and code.isdigit():
            codes.append((code, name))

    print(f"  Scoring {len(codes)} funds in parallel...")
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(score_one_fund, code, name, 50): code for code, name in codes}
        for f in as_completed(futures):
            done += 1
            if done % 20 == 0:
                print(f"    {done}/{len(codes)}...")
            try:
                r = f.result()
                if r and r["score"] >= min_score:
                    results.append(r)
            except Exception:
                pass

    # 3. 按评分排序
    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"  Done in {time.time()-t0:.0f}s | Found {len(results)} funds >= {min_score} points")
    return results


def format_screen_results(results: list[dict], top_n: int = 10) -> str:
    """格式化筛选结果"""
    if not results:
        return "No funds meet criteria. Try lowering min_score."

    lines = ["Top Funds (ranked by strategy score):", f"{'='*50}"]
    for i, r in enumerate(results[:top_n]):
        d = r.get("details", {})
        pe = d.get("pe_pct")
        pe_str = f"PE:{pe:.0f}%" if pe else ""
        lines.append(
            f"#{i+1} {r['name']}({r['code']}) | Score:{r['score']:.0f} | {r['action'].upper()} | {pe_str}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    print("Screening all funds...")
    top = screen_funds(max_funds=50, min_score=55)
    print(format_screen_results(top, 10))
