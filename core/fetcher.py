"""
数据抓取模块 — 从中国福彩网 API 获取 3D 历史开奖数据
支持增量更新、多页抓取、自动去重、Session Cookie 管理
"""

import json
import os
import time
from typing import Optional

import requests

# ── 配置 ──
BASE_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
MAIN_PAGE = "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"
REQUEST_DELAY = 0.8
MAX_RETRIES = 3

# 全局 Session（维护 Cookie）
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    """获取或创建带 Cookie 的 Session"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        })
        # 先访问主页获取 Cookie
        try:
            _session.get(MAIN_PAGE, timeout=10)
        except Exception:
            pass
    return _session


def _parse_record(item: dict) -> Optional[dict]:
    """解析单条 API 返回记录为标准格式。
    API 返回的 red 字段可能是 '377' 或 '3,7,7' 格式，兼容处理。
    """
    code = item.get("red", "") or item.get("drawCode", "")
    if not code:
        return None

    # 处理逗号分隔格式 "3,7,7" → "377"
    if "," in code:
        parts = code.replace(" ", "").split(",")
        if len(parts) == 3:
            code = "".join(parts)

    if len(code) != 3 or not code.isdigit():
        return None

    b, s, g = int(code[0]), int(code[1]), int(code[2])
    return {
        "期号": item.get("code", ""),
        "日期": item.get("date", ""),
        "号码": code,
        "百位": b,
        "十位": s,
        "个位": g,
        "和值": b + s + g,
        "跨度": max(b, s, g) - min(b, s, g),
        "奇偶比": f"{sum(1 for x in (b,s,g) if x%2)}:{sum(1 for x in (b,s,g) if x%2==0)}",
        "大小比": f"{sum(1 for x in (b,s,g) if x>=5)}:{sum(1 for x in (b,s,g) if x<5)}",
    }


def fetch_page(page_no: int, page_size: int = 30) -> list[dict]:
    """从中国福彩网 API 抓取一页 3D 开奖数据，含重试"""
    params = {
        "name": "3d",
        "issueCount": "",
        "issueStart": "",
        "issueEnd": "",
        "dayStart": "",
        "dayEnd": "",
        "pageNo": page_no,
        "pageSize": page_size,
        "week": "",
        "systemType": "PC",
    }
    session = _get_session()
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("result", []) or []
            records = []
            for item in results:
                r = _parse_record(item)
                if r:
                    records.append(r)
            return records
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                # Session 过期？重建
                global _session
                _session = None
                session = _get_session()
                time.sleep(2 ** attempt)
            else:
                raise e
    return []


def fetch_latest() -> Optional[dict]:
    """只抓取最新一期"""
    records = fetch_page(1, 1)
    return records[0] if records else None


def fetch_all(pages: int = 30, progress_cb=None) -> list[dict]:
    """抓取多页历史数据，按期号去重，返回倒序列表"""
    all_records: dict[str, dict] = {}
    for page in range(1, pages + 1):
        try:
            records = fetch_page(page)
            for r in records:
                if r["期号"] not in all_records:
                    all_records[r["期号"]] = r
            if progress_cb:
                progress_cb(page, len(records), len(all_records))
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            if progress_cb:
                progress_cb(page, 0, len(all_records), error=str(e))
            break
    return sorted(all_records.values(), key=lambda x: x["期号"], reverse=True)


class DataManager:
    """数据管理器：本地缓存 + 增量更新"""

    def __init__(self, cache_file: str = "data/history.json"):
        self.cache_file = cache_file
        self.data: list[dict] = []

    def load(self, force_refresh: bool = False) -> list[dict]:
        """加载数据：优先本地缓存"""
        if not force_refresh and os.path.exists(self.cache_file):
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            return self.data
        self.data = fetch_all()
        self._save()
        return self.data

    def _save(self):
        """保存到本地缓存"""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_latest_issue(self) -> Optional[str]:
        """获取本地最新期号"""
        return self.data[0]["期号"] if self.data else None

    def check_new_data(self) -> Optional[dict]:
        """检查是否有新一期开奖数据（轮询用）"""
        latest = fetch_latest()
        if not latest:
            return None
        local_latest = self.get_latest_issue()
        if local_latest and latest["期号"] <= local_latest:
            return None
        return latest

    def append_new(self, record: dict):
        """追加一期新数据并保存"""
        if self.data and record["期号"] <= self.data[0]["期号"]:
            return
        self.data.insert(0, record)
        self._save()
