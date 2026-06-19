"""
基金守护者 — 主程序
─────────────────────────
六层量化策略 + AI 解读 + 飞书推送
全天24小时监控（实时新闻+盘中估值+日终净值+每周回测）

运行方式：
  python main.py              # 持续运行（定时任务模式）
  python main.py --once       # 只跑一次（测试用）
  python main.py --backtest   # 只跑回测
"""
import argparse
import os
import signal
import sys
import time
import traceback

# Windows UTF-8 编码修复
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from datetime import datetime, timedelta
from pathlib import Path

import schedule
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.text import Text

from config import (
    WATCH_FUNDS, ROOT_DIR, SCHEDULE,
    ANTHROPIC_API_KEY, FEISHU_WEBHOOK_URL,
)
from data_collector import collect_all_data, fetch_all_news, get_index_realtime
from strategy_engine import evaluate_portfolio
from ai_analyzer import analyze_news, analyze_major_event
import notifier
from notifier import send_daily_report, send_urgent_alert, send_simple_msg, is_trade_day
from portfolio_tracker import calculate_pnl, format_pnl_report
from advisor import generate_instructions, format_instructions, get_portfolio_summary, save_recommendations, auto_execute_pending
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")
from backtest import run_weekly_backtest

console = Console()
STATE_FILE = ROOT_DIR / "data" / "state.json"

# ==================== 状态持久化 ====================

def load_state() -> dict:
    if STATE_FILE.exists():
        return __import__("json").loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}

def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        __import__("json").dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

# ==================== 单次运行 ====================

def run_once(verbose: bool = True, push: bool = False):
    """执行一次完整的分析流程"""
    console.print(Panel.fit("基金守护者 — 分析中...", border_style="cyan"))

    # 0. 自动追认昨天的操作
    executed = auto_execute_pending()
    if executed and verbose:
        for e in executed:
            console.print(f"  [dim]✓ {e}[/dim]")

    # 1. 数据采集
    with console.status("[bold yellow]📡 采集数据中...[/bold yellow]"):
        data = collect_all_data()

    if verbose:
        console.print(f"  ✅ 数据采集完成 ({data['elapsed']}s)")
        console.print(f"     📊 {len(data['funds'])} 只基金 | 📰 {len(data['news'])} 条新闻 | 🌡️ 情绪 {data['sentiment']:.0f}")

    # 2. AI 解读新闻
    ai_analysis = None
    if ANTHROPIC_API_KEY and "your-api-key" not in ANTHROPIC_API_KEY:
        with console.status("[bold green]🤖 AI 分析新闻...[/bold green]"):
            try:
                ai_analysis = analyze_news(data["news"])
                if verbose:
                    sent = ai_analysis.get("overall_sentiment", "?")
                    console.print(f"  ✅ AI 分析完成 → 整体情绪: {sent}")
            except Exception as e:
                console.print(f"  ⚠️ AI 分析失败: {e}")

    # 3. 策略评估
    state = load_state()
    with console.status("[bold blue]🧮 策略计算中...[/bold blue]"):
        report = evaluate_portfolio(data, state)

    # 4. 生成具体买卖指令
    instructions = generate_instructions(report, data)
    portfolio = get_portfolio_summary(data)
    save_recommendations(instructions)  # 保存，明天自动追认

    # 5. 显示结果
    if verbose:
        console.print(Panel(format_instructions(instructions), title="[bold green]📋 今日操作[/bold green]"))
        console.print(Panel(portfolio, title="[bold cyan]💼 持仓状态[/bold cyan]"))
        display_results(data, report)

    # 6. 推送
    if push and is_trade_day():
        with console.status("[bold magenta]推送飞书..."):
            pnl = calculate_pnl(data)
            # 飞书消息：操作指令 + 持仓 + 详细分析
            full_msg = (
                format_instructions(instructions) + "\n\n---\n" +
                get_portfolio_summary(data) + "\n\n---\n" +
                notifier.format_daily_report(data, report, ai_analysis, pnl)
            )
            ok = notifier.send_feishu("基金日报", full_msg)
            console.print("  飞书已推送" if ok else "  飞书推送失败")

    # 6. 保存状态
    save_state(report["state"])

    return data, report, ai_analysis


def display_results(data, report):
    """富文本显示结果"""
    summary = report["summary"]

    # 概况
    idx_str = ""
    for icode, idata in data["indices"].items():
        rt = idata.get("realtime")
        if rt and rt.get("price"):
            emoji = "🔴" if rt["pct_change"] < 0 else "🟢"
            idx_str += f"{emoji} {rt['price']:.1f} ({rt['pct_change']:+.2f}%)  "

    console.print(Panel(
        f"{idx_str}\n🌡️ 情绪: {data['sentiment']:.0f}/100 | 综合评分: {summary['avg_score']:.0f}/100\n"
        f"📊 买入信号: {len(summary['buy_signals'])} | 卖出信号: {len(summary['sell_signals'])}",
        title="📊 市场快报",
    ))

    # 基金表格
    table = Table(title="基金评估", show_header=True, header_style="bold")
    table.add_column("基金", style="cyan")
    table.add_column("净值")
    table.add_column("RSI")
    table.add_column("评分")
    table.add_column("动作", style="bold")

    for code, r in report["results"].items():
        name = data["funds"][code]["name"]
        d = r.get("details", {})
        score = d.get("score", 50)
        nav = d.get("current_nav", 0)
        rsi = d.get("rsi", 50)
        table.add_row(
            name,
            f"{nav:.4f}",
            f"{rsi:.0f}",
            f"{score:.0f}",
            r["action"],
        )

    console.print(table)

    # 信号详情
    for code, r in report["results"].items():
        name = data["funds"][code]["name"]
        d = r["details"]
        for sig in d.get("signals", []):
            style = "green" if "📈" in sig or "💚" in sig or "✅" in sig else "red" if "📉" in sig or "❤️" in sig else "yellow"
            console.print(f"  {sig}", style=style)

    # 相关性警告
    corr_warns = summary.get("correlation_warnings", [])
    if corr_warns:
        for w in corr_warns:
            console.print(f"  {w}", style="red")


# ==================== 实时监控 ====================

LAST_AI_CHECK_TIME = {}
SENT_THRESHOLD_KEYWORDS = ["降准", "降息", "加息", "熔断", "暴跌", "暴涨", "崩盘", "危机",
                           "救市", "汇金", "央行", "监管", "窗口指导", "黑天鹅", "地缘",
                           "核", "战争", "疫情", "封锁", "制裁", "突发"]

def check_major_events(news_list: list[dict]) -> list[dict]:
    """检测是否有需要立即关注的大事件"""
    alerts = []
    for n in news_list:
        title = n.get("title", "") + n.get("content", "")
        title_lower = title.lower()
        score = sum(1 for kw in SENT_THRESHOLD_KEYWORDS if kw in title_lower)
        if score >= 2:
            alerts.append(n)
    return alerts


def realtime_scan():
    """实时扫描：新闻+指数+估值"""
    if not is_trade_day():
        return

    t = datetime.now()
    ts = t.strftime("%H:%M")

    # 新闻扫描
    news = fetch_all_news()
    major = check_major_events(news)
    if major:
        console.print(f"\n[bold red]🚨 {ts} 检测到 {len(major)} 个重大事件！[/bold red]")
        for n in major[:5]:
            console.print(f"  • {n['title'][:80]}")
        # AI 分析第一条重大事件
        if ANTHROPIC_API_KEY and "your-api-key" not in ANTHROPIC_API_KEY:
            event_text = "\n".join(n["title"] for n in major[:5])
            try:
                ai_result = analyze_major_event(event_text)
                if ai_result.get("severity") in ("high", "medium"):
                    console.print(f"  🤖 AI建议: {ai_result.get('action', '')} | {ai_result.get('reason', '')}")
                    send_urgent_alert(event_text, ai_result)
            except Exception:
                pass

    # 指数扫描
    for idx_code in ["000300", "000905"]:
        rt = get_index_realtime(idx_code)
        if rt and abs(rt["pct_change"]) >= 2.0:
            emoji = "📉" if rt["pct_change"] < 0 else "📈"
            console.print(f"  {emoji} {rt['name']}({idx_code}) {rt['pct_change']:+.2f}%")
            if abs(rt["pct_change"]) >= 3.0:
                send_simple_msg(
                    f"{emoji} 大盘异动",
                    f"{rt['name']} 变动 {rt['pct_change']:+.2f}%，当前 {rt['price']:.1f}"
                )


# ==================== 定时任务注册 ====================

def register_schedule():
    """注册所有定时任务"""
    # 交易日扫描
    schedule.every().monday.at(SCHEDULE["morning_scan"]).do(realtime_scan)
    schedule.every().tuesday.at(SCHEDULE["morning_scan"]).do(realtime_scan)
    schedule.every().wednesday.at(SCHEDULE["morning_scan"]).do(realtime_scan)
    schedule.every().thursday.at(SCHEDULE["morning_scan"]).do(realtime_scan)
    schedule.every().friday.at(SCHEDULE["morning_scan"]).do(realtime_scan)

    schedule.every().monday.at(SCHEDULE["midday_scan"]).do(realtime_scan)
    schedule.every().tuesday.at(SCHEDULE["midday_scan"]).do(realtime_scan)
    schedule.every().wednesday.at(SCHEDULE["midday_scan"]).do(realtime_scan)
    schedule.every().thursday.at(SCHEDULE["midday_scan"]).do(realtime_scan)
    schedule.every().friday.at(SCHEDULE["midday_scan"]).do(realtime_scan)

    schedule.every().monday.at(SCHEDULE["afternoon_scan"]).do(realtime_scan)
    schedule.every().tuesday.at(SCHEDULE["afternoon_scan"]).do(realtime_scan)
    schedule.every().wednesday.at(SCHEDULE["afternoon_scan"]).do(realtime_scan)
    schedule.every().thursday.at(SCHEDULE["afternoon_scan"]).do(realtime_scan)
    schedule.every().friday.at(SCHEDULE["afternoon_scan"]).do(realtime_scan)

    # 收盘快报
    schedule.every().monday.at(SCHEDULE["market_close"]).do(lambda: run_once(verbose=True, push=False))
    schedule.every().tuesday.at(SCHEDULE["market_close"]).do(lambda: run_once(verbose=True, push=False))
    schedule.every().wednesday.at(SCHEDULE["market_close"]).do(lambda: run_once(verbose=True, push=False))
    schedule.every().thursday.at(SCHEDULE["market_close"]).do(lambda: run_once(verbose=True, push=False))
    schedule.every().friday.at(SCHEDULE["market_close"]).do(lambda: run_once(verbose=True, push=False))

    # 日终完整分析 + 推送
    schedule.every().monday.at(SCHEDULE["evening_nav"]).do(lambda: run_once(verbose=True, push=True))
    schedule.every().tuesday.at(SCHEDULE["evening_nav"]).do(lambda: run_once(verbose=True, push=True))
    schedule.every().wednesday.at(SCHEDULE["evening_nav"]).do(lambda: run_once(verbose=True, push=True))
    schedule.every().thursday.at(SCHEDULE["evening_nav"]).do(lambda: run_once(verbose=True, push=True))
    schedule.every().friday.at(SCHEDULE["evening_nav"]).do(lambda: run_once(verbose=True, push=True))

    # 每周回测（周日）
    schedule.every().sunday.at("20:00").do(lambda: run_weekly_backtest(collect_all_data()))

    console.print("[green]✅ 定时任务已注册[/green]")
    _print_schedule()


def _print_schedule():
    console.print(Text(f"""
⏱️  定时任务一览：
  📡 实时扫描：交易日 {SCHEDULE['morning_scan']} / {SCHEDULE['midday_scan']} / {SCHEDULE['afternoon_scan']}
  📊 收盘快报：交易日 {SCHEDULE['market_close']}
  📈 日终分析：交易日 {SCHEDULE['evening_nav']}（含飞书推送）
  🔄 每周回测：周日 20:00
  """, style="dim"))


# ==================== 入口 ====================

def main():
    parser = argparse.ArgumentParser(description="📊 基金守护者 — 量化分析 + AI 监控")
    parser.add_argument("--once", action="store_true", help="只运行一次（测试模式）")
    parser.add_argument("--backtest", action="store_true", help="只运行回测")
    parser.add_argument("--push", action="store_true", help="强制推送飞书（与--once配合）")
    args = parser.parse_args()

    # 配置检查
    ai_ok = ANTHROPIC_API_KEY and 'your-api-key' not in ANTHROPIC_API_KEY
    feishu_ok = FEISHU_WEBHOOK_URL and 'your-token' not in FEISHU_WEBHOOK_URL
    console.print(Panel.fit(
        f"基金守护者 v1.0\n"
        f"{'='*30}\n"
        f"监控基金: {len(WATCH_FUNDS)} 只\n"
        f"AI分析: {'已配置' if ai_ok else '未配置(跳过AI分析)'}\n"
        f"飞书推送: {'已配置' if feishu_ok else '未配置(跳过推送)'}\n"
        f"运行目录: {ROOT_DIR}",
        title="[bold]基金守护者[/bold]",
        border_style="cyan",
    ))

    if args.once:
        console.print("[cyan]🔍 单次分析模式[/cyan]")
        run_once(verbose=True, push=args.push)
        return

    if args.backtest:
        console.print("[cyan]🔄 回测模式[/cyan]")
        data = collect_all_data()
        run_weekly_backtest(data)
        return

    # 持续运行模式
    console.print("[cyan]🟢 持续监控模式[/cyan]")
    register_schedule()

    # 启动时先跑一次
    console.print("\n[bold]📡 初始扫描...[/bold]")
    realtime_scan()
    console.print("[bold]📊 初始数据分析...[/bold]")
    run_once(verbose=True, push=False)

    # 主循环
    console.print("\n[dim]按 Ctrl+C 停止...[/dim]\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # 每30秒检查一次
    except KeyboardInterrupt:
        console.print("\n[bold yellow]⏹️  基金守护者已停止[/bold yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
