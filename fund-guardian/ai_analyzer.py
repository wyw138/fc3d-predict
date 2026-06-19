"""
AI 分析模块 — 使用 Claude API 解读新闻和政策
"""
import json
from datetime import datetime

from openai import OpenAI

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

_client = None

def _get_client():
    global _client
    if _client is None:
        if ANTHROPIC_API_KEY == "your-api-key-here" or not ANTHROPIC_API_KEY:
            return None
        _client = OpenAI(
            api_key=ANTHROPIC_API_KEY,
            base_url="https://api.anthropic.com/v1",
        )
    return _client

SYSTEM_PROMPT = """你是一个专业的基金投资分析师。用户会给你一系列今天的财经新闻和政策动态。

请从以下维度分析每条新闻对基金投资的影响：

1. **宏观政策** — 央行政策、财政政策、监管变化
2. **行业影响** — 哪些行业受益、哪些受损
3. **市场情绪** — 该消息会如何影响短期市场情绪
4. **操作建议** — 基于该消息，应该加仓、减仓还是持有

输出 JSON 格式：
{
  "summary": "今日新闻总体摘要，50字以内",
  "overall_sentiment": "positive|negative|neutral",
  "key_events": [
    {
      "event": "事件简述",
      "impact": "利好/利空/中性",
      "severity": "high|medium|low",
      "affected_sectors": ["行业1", "行业2"],
      "action_advice": "具体操作建议"
    }
  ],
  "portfolio_advice": {
    "稳健池": "建议",
    "波段池": "建议"
  },
  "risk_alert": "需要警惕的风险，没有则填null"
}

注意：不要给出具体的买卖金额建议，只给方向性建议。用中文回复。"""


def analyze_news(news_list: list[dict]) -> dict:
    """用 Claude 分析新闻列表，返回结构化分析"""
    if not news_list:
        return {
            "summary": "今日无重大新闻",
            "overall_sentiment": "neutral",
            "key_events": [],
            "portfolio_advice": {"稳健池": "正常定投", "波段池": "等待信号"},
            "risk_alert": None,
        }

    # 构建新闻文本摘要（控制在 3000 字内）
    news_texts = []
    total_chars = 0
    for n in news_list[:40]:
        line = f"[{n.get('source', '')}] {n['title']} {n.get('content', '')}"
        if total_chars + len(line) > 3000:
            news_texts.append(line[:3000 - total_chars])
            break
        news_texts.append(line)
        total_chars += len(line)

    news_batch = "\n---\n".join(news_texts)

    try:
        cl = _get_client()
        if cl is None:
            return {"summary": "AI未配置", "overall_sentiment": "neutral", "key_events": [], "portfolio_advice": {}, "risk_alert": None}
        resp = cl.chat.completions.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            temperature=0.3,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"请分析以下今日财经新闻：\n\n{news_batch}"},
            ],
        )
        text = resp.choices[0].message.content

        # 尝试解析 JSON（可能被 markdown 包裹）
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)

    except json.JSONDecodeError:
        return {
            "summary": "分析结果解析失败",
            "overall_sentiment": "neutral",
            "key_events": [],
            "portfolio_advice": {"稳健池": "正常定投", "波段池": "等待信号"},
            "risk_alert": None,
            "raw": text,
        }
    except Exception as e:
        return {
            "summary": f"AI分析调用失败: {e}",
            "overall_sentiment": "neutral",
            "key_events": [],
            "portfolio_advice": {},
            "risk_alert": None,
            "error": str(e),
        }


def analyze_major_event(event_text: str) -> dict:
    """实时重大事件分析（触发式）"""
    try:
        cl = _get_client()
        if cl is None:
            return {"summary": "AI未配置", "overall_sentiment": "neutral", "key_events": [], "portfolio_advice": {}, "risk_alert": None}
        resp = cl.chat.completions.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1000,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个快速响应的基金风控分析师。收到重大市场事件后，用 JSON 回复：{\"severity\": \"high|medium|low\", \"action\": \"加仓|减仓|持有不动|紧急关注\", \"reason\": \"一句话理由\", \"affected_funds\": [\"基金名称\"]}",
                },
                {"role": "user", "content": f"分析此事件对基金的影响：{event_text}"},
            ],
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1][:-3]
        return json.loads(text)
    except Exception:
        return {"severity": "medium", "action": "持有不动", "reason": "无法分析", "affected_funds": []}


if __name__ == "__main__":
    from data_collector import fetch_all_news
    news = fetch_all_news()
    print(f"📰 分析 {len(news)} 条新闻...")
    result = analyze_news(news)
    print(json.dumps(result, ensure_ascii=False, indent=2))
