"""
基金守护者 — 配置文件
修改这里的参数来适配你的情况
"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ==================== 目录配置 ====================
DATA_DIR = ROOT_DIR / "data"
NAV_DIR = DATA_DIR / "nav_history"
NEWS_DIR = DATA_DIR / "news"
BACKTEST_DIR = DATA_DIR / "backtest"

for d in [DATA_DIR, NAV_DIR, NEWS_DIR, BACKTEST_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== Claude API 配置 ====================
# 推荐用环境变量，不硬编码
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your-api-key-here")
ANTHROPIC_MODEL = "claude-sonnet-4-6"  # 性价比最高

# ==================== 飞书机器人 ====================
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/your-token-here")

# ==================== 你的投资预算 ====================
TOTAL_BUDGET = 1000  # 总资金（元）
CASH_RESERVE = 0.20   # 永远留20%现金，大跌时抄底

# ==================== 你的基金组合 ====================
# 格式: {"名称": "基金代码", ...}
WATCH_FUNDS = {
    # ===== 稳健池 =====
    "沪深300指数": "110020",       # 易方达沪深300ETF联接A
    "中证500指数": "161017",       # 富国中证500增强
    "纯债稳健": "000085",          # 博时安盈债券C
    "中证红利": "090010",          # 大成中证红利指数

    # ===== 波段池 =====
    "医疗健康": "003095",          # 中欧医疗健康混合A
    "新能源车": "001156",          # 申万菱信新能源汽车
    "半导体": "320007",            # 诺安成长混合（科技）
    "消费龙头": "110022",          # 易方达消费行业
}

# ==================== 策略参数 ====================
STRATEGY_CONFIG = {
    # ----- 四季分仓 -----
    "seasons": {
        "spring": {"position": 0.90, "description": "低估值+趋势转好"},
        "summer": {"position": 0.70, "description": "正常估值+趋势向上"},
        "autumn": {"position": 0.40, "description": "高估值+趋势走平"},
        "winter": {"position": 0.20, "description": "高估值+趋势向下"},
    },
    # 季节判断阈值
    "pe_low_pct": 30.0,       # PE分位低于此→便宜
    "pe_high_pct": 70.0,      # PE分位高于此→贵
    "pe_extreme_pct": 90.0,   # PE分位高于此→极度高估
    "ma_short": 5,             # 短均线天数
    "ma_long": 20,             # 长均线天数

    # ----- 分批进出 -----
    "batch_buy_pcts": [0.30, 0.30, 0.40],   # 三批买入比例
    "batch_sell_pcts": [0.33, 0.33, 0.34],  # 三批卖出比例

    # ----- 情绪温度 -----
    "sentiment_hot": 75,       # 高于此→市场过热
    "sentiment_cold": 25,      # 低于此→市场过冷

    # ----- 行业轮动 -----
    "sector_momentum_weeks": 4,  # 看过去几周
    "sector_overbought_pct": 80, # 涨幅排名前N%视为过热
    "sector_oversold_pct": 20,   # 跌幅排名前N%视为超跌

    # ----- 止损止盈 -----
    "stop_loss_pct": -8.0,       # 单基硬止损线
    "take_profit_pct": 12.0,     # 单基主动止盈线
    "trailing_stop_pct": 5.0,    # 回撤止损：从最高点回落超过N%

    # ----- 相关性风控 -----
    "correlation_warn": 0.75,    # 两只基金相关性高于此→警告
    "max_concentration": 0.40,   # 单只基金最大仓位

    # ----- RSI -----
    "rsi_oversold": 30,          # 超卖
    "rsi_overbought": 70,        # 超买

    # ----- 估值定投 -----
    "dca_normal": 1.0,           # 正常定投倍数
    "dca_double": 2.0,           # 低估加倍
    "dca_half": 0.5,             # 高估减半
    "dca_stop_pct": 80.0,        # PE分位高于此停止定投
}

# ==================== 调度时间 ====================
SCHEDULE = {
    "morning_scan": "09:15",      # 早盘前扫新闻
    "midday_scan": "12:00",       # 午间更新
    "afternoon_scan": "14:30",    # 尾盘监控
    "market_close": "15:30",      # 收盘快报
    "evening_nav": "21:00",       # 净值更新+完整分析
    "weekly_backtest": "sunday 20:00",  # 每周回测
}
