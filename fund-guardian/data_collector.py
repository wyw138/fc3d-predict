"""
数据采集模块 — 所有外部数据源统一入口
"""
import json
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import WATCH_FUNDS, NAV_DIR, NEWS_DIR, STRATEGY_CONFIG

# ==================== 缓存工具 ====================

def _cache_path(subdir: Path, key: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return subdir / f"{h}.json"

def _load_cache(subdir: Path, key: str, max_age_hours: float = 1.0) -> Optional[dict]:
    p = _cache_path(subdir, key)
    if p.exists():
        age = time.time() - p.stat().st_mtime
        if age < max_age_hours * 3600:
            return json.loads(p.read_text(encoding="utf-8"))
    return None

def _save_cache(subdir: Path, key: str, data):
    p = _cache_path(subdir, key)
    p.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")

# ==================== 基金公告数据 ====================

def get_fund_nav(fund_code: str, fund_name: str = "") -> Optional[pd.DataFrame]:
    """拉取基金净值历史（AKShare）"""
    cache = _load_cache(NAV_DIR, f"nav_{fund_code}", max_age_hours=2.0)
    if cache and "df" in cache:
        return pd.DataFrame(cache["df"])

    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df is not None and not df.empty:
            df.columns = [c.strip() for c in df.columns]
            _save_cache(NAV_DIR, f"nav_{fund_code}", {"df": df.to_dict(orient="records")})
            return df
    except Exception as e:
        print(f"  ⚠️ {fund_name}({fund_code}) 净值获取失败: {e}")
    return None


def get_fund_realtime_estimate(fund_code: str) -> Optional[dict]:
    """获取基金盘中实时估值（东方财富）"""
    cache = _load_cache(NAV_DIR, f"estimate_{fund_code}", max_age_hours=0.05)  # 3分钟
    if cache:
        return cache

    try:
        url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js"
        resp = requests.get(url, timeout=10, headers={"Referer": "https://fund.eastmoney.com/"})
        if resp.status_code == 200:
            text = resp.text
            if text.startswith("jsonpgz("):
                text = text[8:-2]
                data = json.loads(text)
                result = {
                    "fund_code": data.get("fundcode", fund_code),
                    "name": data.get("name", ""),
                    "nav": float(data.get("dwjz", 0)),          # 上一日净值
                    "estimate_nav": float(data.get("gsz", 0)),   # 盘中估值
                    "estimate_pct": float(data.get("gszzl", 0)), # 估值涨跌幅
                    "update_time": data.get("gztime", ""),
                    "date": data.get("jzrq", ""),
                }
                _save_cache(NAV_DIR, f"estimate_{fund_code}", result)
                return result
    except Exception as e:
        print(f"  ⚠️ 实时估值获取失败({fund_code}): {e}")
    return None


def get_index_data(index_code: str = "000300") -> Optional[pd.DataFrame]:
    """获取大盘指数历史数据（沪深300=000300, 中证500=000905）"""
    cache = _load_cache(NAV_DIR, f"index_{index_code}", max_age_hours=4.0)
    if cache and "df" in cache:
        return pd.DataFrame(cache["df"])

    try:
        df = ak.stock_zh_index_daily(symbol=f"sh{index_code}" if index_code == "000300" else f"sh{index_code}")
        if df is not None and not df.empty:
            _save_cache(NAV_DIR, f"index_{index_code}", {"df": df.to_dict(orient="records")})
            return df
    except Exception as e:
        print(f"  ⚠️ 指数{index_code}获取失败: {e}")
    return None


def get_index_realtime(index_code: str = "000300") -> Optional[dict]:
    """获取指数实时行情"""
    cache = _load_cache(NAV_DIR, f"idx_realtime_{index_code}", max_age_hours=0.05)
    if cache:
        return cache

    try:
        df = ak.stock_zh_index_spot_em()
        if df is not None:
            row = df[df["代码"] == index_code]
            if not row.empty:
                r = row.iloc[0]
                result = {
                    "code": index_code,
                    "name": r.get("名称", ""),
                    "price": float(r.get("最新价", 0)),
                    "pct_change": float(r.get("涨跌幅", 0)),
                    "volume": float(r.get("成交额", 0)),
                }
                _save_cache(NAV_DIR, f"idx_realtime_{index_code}", result)
                return result
    except Exception as e:
        print(f"  ⚠️ 实时指数获取失败: {e}")
    return None


# ==================== 新闻采集 ====================

def fetch_cls_news() -> list[dict]:
    """抓取财联社电报快讯"""
    cache = _load_cache(NEWS_DIR, "cls_telegraph", max_age_hours=0.08)  # 5分钟
    if cache and "items" in cache:
        return cache["items"]

    news_list = []
    try:
        url = "https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&sv=8.4.6"
        resp = requests.get(
            url,
            params={"type": "telegraph", "page": "1", "rn": "30"},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("roll_data", []) or data.get("data", [])
            for item in items:
                news_list.append({
                    "title": item.get("title", ""),
                    "content": item.get("content", item.get("brief", "")),
                    "ctime": item.get("ctime", ""),
                    "source": "财联社",
                })
    except Exception as e:
        print(f"  ⚠️ 财联社新闻获取失败: {e}")

    _save_cache(NEWS_DIR, "cls_telegraph", {"items": news_list})
    return news_list


def fetch_eastmoney_news(category: str = "fund") -> list[dict]:
    """抓取东方财富基金/宏观新闻"""
    cache = _load_cache(NEWS_DIR, f"em_news_{category}", max_age_hours=0.33)  # 20分钟
    if cache and "items" in cache:
        return cache["items"]

    news_list = []
    try:
        urls = {
            "fund": "https://fund.eastmoney.com/api/News/NewsList?pageIndex=1&pageSize=20&type=1",
            "macro": "https://finance.eastmoney.com/a/czqyw.html",
        }
        if category == "fund":
            resp = requests.get(urls["fund"], timeout=15, headers={"Referer": "https://fund.eastmoney.com/"})
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("Data", {}).get("List", []):
                    news_list.append({
                        "title": item.get("Title", ""),
                        "content": item.get("Summary", ""),
                        "ctime": item.get("ShowDate", ""),
                        "source": "东方财富-基金",
                    })
        else:
            resp = requests.get(urls["macro"], timeout=15, headers={"Referer": "https://finance.eastmoney.com/"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                for item in soup.select(".news-item")[:20]:
                    title_el = item.select_one(".title a")
                    time_el = item.select_one(".time")
                    if title_el:
                        news_list.append({
                            "title": title_el.get_text(strip=True),
                            "content": "",
                            "ctime": time_el.get_text(strip=True) if time_el else "",
                            "source": "东方财富-宏观",
                        })
    except Exception as e:
        print(f"  ⚠️ 东财{category}新闻获取失败: {e}")

    _save_cache(NEWS_DIR, f"em_news_{category}", {"items": news_list})
    return news_list


def fetch_all_news() -> list[dict]:
    """汇总所有新闻源"""
    all_news = []
    all_news.extend(fetch_cls_news())
    all_news.extend(fetch_eastmoney_news("fund"))
    all_news.extend(fetch_eastmoney_news("macro"))

    # 去重（按标题）
    seen = set()
    unique = []
    for n in all_news:
        key = n["title"][:50]
        if key not in seen and n["title"]:
            seen.add(key)
            unique.append(n)
    return sorted(unique, key=lambda x: x.get("ctime", ""), reverse=True)[:50]


# ==================== 估值数据 ====================

def get_fund_valuation(fund_code: str) -> Optional[dict]:
    """获取基金PE/PB估值分位"""
    cache = _load_cache(NAV_DIR, f"val_{fund_code}", max_age_hours=8.0)  # 一天一次
    if cache:
        return cache

    try:
        df = ak.fund_etf_fund_info_em(fund=fund_code)  # 尝试ETF
        # 场外基金用另一种方式
    except Exception:
        pass

    # 对于场外基金，通过指数估值来近似
    # 映射常见基金→对应指数
    fund_index_map = {
        "110020": "000300",  # 沪深300
        "161017": "000905",  # 中证500
        "090010": "000922",  # 中证红利
    }

    idx_code = fund_index_map.get(fund_code)
    if idx_code:
        try:
            df = ak.index_value_hist_funddb(symbol=idx_code, indicator="市盈率")
            if df is not None and not df.empty:
                latest_pe = float(df.iloc[-1].iloc[1])
                pe_values = [float(df.iloc[i].iloc[1]) for i in range(len(df))]
                pe_percentile = sum(1 for v in pe_values if v < latest_pe) / len(pe_values) * 100
                result = {"fund_code": fund_code, "pe": latest_pe, "pe_pct": pe_percentile, "source": "funddb"}
                _save_cache(NAV_DIR, f"val_{fund_code}", result)
                return result
        except Exception:
            pass

    return None


# ==================== 情绪数据 ====================

def get_sentiment_index() -> float:
    """简单的市场情绪指数（0-100），值越高越贪婪"""
    cache = _load_cache(NAV_DIR, "sentiment", max_age_hours=0.5)
    if cache and "value" in cache:
        return cache["value"]

    score = 50.0  # 基准中性

    try:
        # 1. 沪深300成交量相对变化
        df = get_index_data("000300")
        if df is not None and len(df) >= 20:
            recent_vol = df["成交量"].tail(5).mean()
            old_vol = df["成交量"].tail(20).head(15).mean()
            vol_ratio = recent_vol / max(old_vol, 1)
            score += (vol_ratio - 1) * 20  # 量放大→情绪升

        # 2. 百度搜索指数（用东财新闻量代理）
        news_count = len(fetch_eastmoney_news("fund"))
        score += (news_count - 15) * 2  # 新闻多→热度高

        # 3. 日内振幅
        idx_rt = get_index_realtime("000300")
        if idx_rt and abs(idx_rt["pct_change"]) > 2:
            score += 10 if idx_rt["pct_change"] < 0 else 5  # 大跌恐惧+10，大涨贪婪+5
    except Exception:
        pass

    score = max(0, min(100, score))
    _save_cache(NAV_DIR, "sentiment", {"value": score})
    return score


# ==================== 行业轮动 ====================

def get_sector_momentum() -> list[dict]:
    """计算申万行业动量排名"""
    cache = _load_cache(NAV_DIR, "sector_momentum", max_age_hours=6.0)
    if cache and "sectors" in cache:
        return cache["sectors"]

    sectors = []
    try:
        df = ak.stock_sector_spot(indicator="涨幅")
        if df is not None and not df.empty:
            for _, row in df.head(28).iterrows():
                try:
                    name = str(row.get("板块名称", row.get("名称", "")))
                    pct_val = row.get("涨跌幅", 0)
                    sectors.append({"name": name, "pct": float(pct_val) if pct_val else 0})
                except Exception:
                    continue
    except Exception as e:
        print(f"  ⚠️ 行业数据获取失败: {e}")

    result = sorted(sectors, key=lambda x: x["pct"], reverse=True)
    _save_cache(NAV_DIR, "sector_momentum", {"sectors": result})
    return result


# ==================== 汇总接口 ====================

def collect_all_data() -> dict:
    """采集所有需要的数据，返回统一字典（并行版）"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    t0 = time.time()
    data = {
        "timestamp": datetime.now().isoformat(),
        "funds": {},
        "indices": {},
        "news": [],
        "sentiment": 50.0,
        "sectors": [],
    }

    # 基金数据串行获取（py_mini_racer不支持多线程）
    for name, code in WATCH_FUNDS.items():
        try:
            data["funds"][code] = {
                "name": name,
                "nav_df": get_fund_nav(code, name),
                "estimate": get_fund_realtime_estimate(code),
                "valuation": get_fund_valuation(code),
            }
        except Exception as e:
            data["funds"][code] = {"name": name, "nav_df": None, "estimate": None, "valuation": None}

    # 并行拉新闻 + 行业 + 指数（这些不用 V8）
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_news = ex.submit(fetch_all_news)
        f_sectors = ex.submit(get_sector_momentum)
        f_idx300 = ex.submit(get_index_realtime, "000300")
        f_idx905 = ex.submit(get_index_realtime, "000905")

        data["news"] = f_news.result()
        data["sectors"] = f_sectors.result()
        data["indices"]["000300"] = {"realtime": f_idx300.result(), "history": get_index_data("000300")}
        data["indices"]["000905"] = {"realtime": f_idx905.result(), "history": get_index_data("000905")}

    # 情绪最后算（依赖新闻数据）
    data["sentiment"] = get_sentiment_index()

    data["elapsed"] = round(time.time() - t0, 2)
    return data


if __name__ == "__main__":
    # 测试
    print("🔍 数据采集测试...")
    result = collect_all_data()
    print(f"  ✅ 耗时 {result['elapsed']}s")
    print(f"  📊 基金 {len(result['funds'])} 只")
    print(f"  📰 新闻 {len(result['news'])} 条")
    print(f"  🌡️  情绪 {result['sentiment']:.1f}/100")
    print(f"  🏭 行业 {len(result['sectors'])} 个")
