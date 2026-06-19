"""
通知模块 — 飞书机器人推送
"""
import json
import time
from datetime import datetime, date

import requests

from config import FEISHU_WEBHOOK_URL, WATCH_FUNDS

# 今日是否工作日
def is_trade_day() -> bool:
    today = date.today()
    if today.weekday() >= 5:
        return False
    # 简单节假日判断（可扩展）
    return True


def send_feishu(title: str, content: str, color: str = "blue") -> bool:
    """发送飞书卡片消息"""
    if not FEISHU_WEBHOOK_URL or "your-token" in FEISHU_WEBHOOK_URL:
        print(f"  📢 [飞书未配置] {title}: {content[:100]}")
        return False

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content,
                }
            ],
        },
    }

    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, json=card, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def send_feishu_text(text: str) -> bool:
    """发送飞书纯文本（紧急通知用）"""
    if not FEISHU_WEBHOOK_URL or "your-token" in FEISHU_WEBHOOK_URL:
        print(f"  📢 {text[:100]}")
        return False

    msg = {"msg_type": "text", "content": {"text": text}}
    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, json=msg, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def format_daily_report(data: dict, strategy_report: dict, ai_analysis: dict = None, pnl: dict = None) -> str:
    """格式化每日完整报告"""
    summary = strategy_report["summary"]
    results = strategy_report["results"]

    # 市场概览
    idx_names = {"000300": "沪深300", "000905": "中证500"}
    idx_lines = []
    for icode, idata in data["indices"].items():
        rt = idata.get("realtime")
        if rt and rt.get("price"):
            emoji = "🔴" if rt["pct_change"] < 0 else "🟢"
            idx_lines.append(f"{emoji} {idx_names.get(icode, icode)}: {rt['price']:.1f} ({rt['pct_change']:+.2f}%)")
        else:
            idx_lines.append(f"⚪ {idx_names.get(icode, icode)}: 今日未开盘")

    # 季节 & 情绪
    season = results.get(list(results.keys())[0], {}).get("details", {}).get("season", "未知") if results else "未知"
    season_emoji = {"spring": "🌱", "summer": "☀️", "autumn": "🍂", "winter": "❄️"}

    # AI 分析摘要
    ai_summary = ""
    if ai_analysis:
        ai_summary = f"\n🤖 **AI 解读**：{ai_analysis.get('summary', '')}"
        risk = ai_analysis.get("risk_alert")
        if risk:
            ai_summary += f"\n⚠️ **风险提示**：{risk}"

    # 基金详情
    fund_lines = []
    for code, r in results.items():
        name = data["funds"][code]["name"]
        detail = r.get("details", {})
        emoji = "🟢" if r["action"].startswith("buy") else ("🔴" if r["action"].startswith("sell") else "⚪")
        action_text = {
            "buy": "→ 买入", "buy_1st": "→ 🥇首批买入30%", "buy_2nd": "→ 🥈二批买入30%", "buy_3rd": "→ 🥉三批买入40%",
            "sell": "→ 卖出", "sell_1st": "→ 🔻首批卖出33%", "sell_2nd": "→ 🔻二批卖出33%", "sell_3rd": "→ 🔻清仓",
            "hold": "→ 持有",
        }.get(r["action"], f"→ {r['action']}")

        s = detail.get('score', 50)
        nav = detail.get('current_nav', 0)
        ma5 = detail.get('ma_short', 0)
        ma20 = detail.get('ma_long', 0)
        rsi = detail.get('rsi', 50)
        vol = detail.get('volatility', 0)
        dd = detail.get('max_drawdown', 0)
        pe = detail.get('pe_pct')
        fund_lines.append(
            f"{emoji} **{name}** | 评分{s:.0f}"
            f"\n净值{nav:.4f} | 5MA>{ma5:.4f} 20MA>{ma20:.4f} | RSI{rsi:.0f}"
            + (f" | PE分位{pe:.0f}%" if pe else "")
            + f"\n波动率{vol}% 回撤{dd}%"
            + f"\n　{action_text}"
        )

    # 相关性警告
    corr_warns = summary.get("correlation_warnings", [])

    # P&L
    pnl_section = ""
    if pnl and pnl.get("funds"):
        from portfolio_tracker import format_pnl_report
        pnl_section = f"\n\n---\n{format_pnl_report(pnl)}"

    report = f"""📊 **基金日报** | {datetime.now().strftime('%Y-%m-%d %H:%M')}
{ai_summary}
---
🏙️ **市场概况**
{chr(10).join(idx_lines)}
{season_emoji.get(season, '⚪')} 季节：{season}　🌡️ 情绪：{data['sentiment']:.0f}/100
综合评分：{summary['avg_score']:.0f}/100
{pnl_section}

---
📌 **基金详情**
{chr(10).join(fund_lines)}"""

    if corr_warns:
        report += f"\n\n---\n🔗 **相关性警告**\n{chr(10).join(corr_warns)}"

    if ai_analysis:
        events = ai_analysis.get("key_events", [])[:5]
        if events:
            event_lines = [f"• [{e.get('impact','')}] {e.get('event','')}" for e in events]
            report += f"\n\n---\n📰 **今日要闻**\n{chr(10).join(event_lines)}"

    return report


def format_urgent_alert(trigger_event: str, ai_result: dict) -> str:
    """格式化紧急通知"""
    severity = ai_result.get("severity", "medium")
    emoji = "🚨" if severity == "high" else "⚠️"
    text = f"{emoji} **紧急市场提醒**\n\n{trigger_event}\n\n"
    text += f"影响程度：{severity}\n"
    text += f"建议操作：{ai_result.get('action', '持有不动')}\n"
    text += f"理由：{ai_result.get('reason', '')}\n"
    affected = ai_result.get("affected_funds", [])
    if affected:
        text += f"影响基金：{', '.join(affected)}"
    return text


def send_daily_report(data, strategy_report, ai_analysis=None, pnl=None):
    """发送每日完整报告"""
    if not is_trade_day():
        return False

    content = format_daily_report(data, strategy_report, ai_analysis, pnl)
    return send_feishu("📊 基金日报", content)


def send_urgent_alert(event, ai_result):
    """发送紧急通知"""
    content = format_urgent_alert(event, ai_result)
    return send_feishu_text(content)


def send_simple_msg(title, text):
    """发送简单消息"""
    return send_feishu(title, text)


if __name__ == "__main__":
    send_simple_msg("🧪 测试", "基金守护者通知测试 ✓")
    print("✅ 飞书测试消息已发送")
