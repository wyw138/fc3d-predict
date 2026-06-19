"""
飞书机器人通知模块 — 推送预测号码到飞书群
"""

import json
from datetime import datetime, timedelta
from typing import Optional

import requests


class FeishuNotifier:
    """飞书机器人消息推送"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }
        return self._post(payload)

    def send_card(self, header: str, elements: list[dict],
                  header_color: str = "blue", note: str = "") -> bool:
        """发送卡片消息"""
        card = {
            "header": {
                "title": {"tag": "plain_text", "content": header},
                "template": header_color,
            },
            "elements": elements,
        }
        if note:
            card["elements"].append({"tag": "hr"})
            card["elements"].append({
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": note}],
            })
        payload = {"msg_type": "interactive", "card": card}
        return self._post(payload)

    def send_prediction(self, predictions: dict[str, list[str]],
                        latest_draw: Optional[dict],
                        strategy_preds: dict[str, list[str]] = None,
                        next_issue: str = "",
                        next_date: str = "",
                        stats_summary: str = "") -> bool:
        """发送预测号码卡片——按玩法分类展示，标明期号和开奖时间"""
        now = datetime.now()
        now_str = now.strftime("%m/%d %H:%M")
        today_str = now.strftime("%m/%d")

        # 判断是今天还是明天开奖（20:50前=今天，之后=明天）
        draw_hour, draw_minute = 21, 15
        if now.hour < draw_hour or (now.hour == draw_hour and now.minute < draw_minute):
            day_label = "今日"
            draw_date_label = f"今晚 {today_str}"
        else:
            day_label = "明日"
            today = now.date()
            tomorrow = today + timedelta(days=1)
            draw_date_label = f"明晚 {tomorrow.strftime('%m/%d')}"

        issue_display = next_issue or (
            str(int(latest_draw["期号"]) + 1) if latest_draw else "?"
        )

        elements = []

        # ── 预测目标 ──
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"📅 **{day_label}预测**  第 `{issue_display}` 期\n"
                    f"🕘 开奖时间：{draw_date_label} 21:15\n"
                    f"📊 数据来源：中国福利彩票网 (cwl.gov.cn)"
                ),
            },
        })
        elements.append({"tag": "hr"})

        # ── 上期回顾 ──
        if latest_draw:
            prev_shape = self._classify_shape(latest_draw["号码"])
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"📌 **上期开奖** `{latest_draw['期号']}`\n"
                        f"号码：**{latest_draw['号码']}**（{prev_shape}）\n"
                        f"和值 {latest_draw['和值']} | 跨度 {latest_draw['跨度']} | "
                        f"{latest_draw['奇偶比']} | {latest_draw['大小比']}"
                    ),
                },
            })
            elements.append({"tag": "hr"})

        # ── 合并所有策略输出的号码，分类（全部排序，确保确定性） ──
        all_codes = sorted(set(
            code for codes in predictions.values() for code in codes
        ))
        zu3 = sorted([c for c in all_codes if len(set(c)) == 2])
        zu6 = sorted([c for c in all_codes if len(set(c)) == 3])
        baozi = sorted([c for c in all_codes if len(set(c)) == 1])
        zhi_xuan = sorted([c for c in all_codes if c not in set(baozi)])

        # ── 1. 直选推荐 ──
        top_zx = (zhi_xuan if zhi_xuan else ["---"])[:5]
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"🎯 **直选（单选）** 💰 1040元\n"
                    f"号码与位置必须完全相同\n"
                    f"{'  '.join(f'`{c}`' for c in top_zx)}"
                ),
            },
        })

        # ── 2. 组三推荐 ──
        if zu3:
            top_zu3 = zu3[:3]
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"🔹 **组选三** 💰 346元\n"
                        f"两个号码相同，顺序不限\n"
                        f"{'  '.join(f'`{c}`' for c in top_zu3)}"
                    ),
                },
            })

        # ── 3. 组六推荐 ──
        if zu6:
            top_zu6 = zu6[:3]
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"🔸 **组选六** 💰 173元\n"
                        f"三个号码各不相同，顺序不限\n"
                        f"{'  '.join(f'`{c}`' for c in top_zu6)}"
                    ),
                },
            })

        # ── 4. 豹子提示 ──
        if baozi:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"⚠ **豹子号预警** `{' '.join(baozi[:3])}`（历史概率约0.9%，极低）",
                },
            })

        # ── 5. 各策略独立推荐 Top 5 ──
        if strategy_preds:
            elements.append({"tag": "hr"})
            # 策略中文名映射
            name_map = {
                "hot_weighted": "🔥热号加权",
                "cold_rebound": "❄冷号回补",
                "pure_random": "🎲随机基线",
                "sum_regression": "📊和值回归",
                "pattern_follow": "🔄形态跟随",
                "missing_combo": "⏳遗漏组合",
                "markov_chain": "🔗马尔可夫链",
                "multi_score": "📈多维评分",
                "ma_trend": "📉均线趋势",
                "cdm_bayesian": "🧬CDM贝叶斯",
                "xgboost": "🤖XGBoost",
            }
            strategy_lines = ["📋 **各策略独立推荐 Top 5**\n"]
            for sname, codes in strategy_preds.items():
                label = name_map.get(sname, sname)
                top = codes[:5]
                strategy_lines.append(f"{label}：{'  '.join(f'`{c}`' for c in top)}")
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "\n".join(strategy_lines),
                },
            })

        # ── 统计摘要 ──
        if stats_summary:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": stats_summary},
            })

        return self.send_card(
            header=f"🎰 福彩3D · 第{issue_display}期 {day_label}预测",
            elements=elements,
            header_color="blue",
            note=(
                f"📊 数据来源：中国福利彩票网 cwl.gov.cn\n"
                f"⏰ {draw_date_label} 20:50 截止投注  ·  21:15 开奖\n"
                f"💡 直选1040元 | 组三346元 | 组六173元\n"
                f"⚡ 基于900期历史数据的统计分析，非真正预测\n"
                f"⚠ 彩票具有随机性，请理性购彩，量力而行"
            ),
        )

    def send_hit_report(self, predicted: dict, actual: dict) -> bool:
        """推送命中总结卡片 — 对比预测 vs 实际开奖"""
        actual_code = actual["号码"]
        actual_digits = set(actual_code)
        elements = []

        # 开奖结果
        actual_shape = self._classify_shape(actual_code)
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"🎯 **开奖结果** `{actual['期号']}`\n"
                    f"号码：**{actual_code}**（{actual_shape}）\n"
                    f"和值 {actual['和值']} | 跨度 {actual['跨度']} | "
                    f"{actual['奇偶比']} | {actual['大小比']}"
                ),
            },
        })
        elements.append({"tag": "hr"})

        # 回顾预测
        zhi = predicted.get("直选", [])
        zu3_list = predicted.get("组三", [])
        zu6_list = predicted.get("组六", [])

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"📋 **本期预测回顾**（第 `{predicted.get('预测期号','?')}` 期）\n"
                    f"直选：{'  '.join(f'`{c}`' for c in zhi)}\n"
                    f"组三：{'  '.join(f'`{c}`' for c in zu3_list) if zu3_list else '无'}\n"
                    f"组六：{'  '.join(f'`{c}`' for c in zu6_list) if zu6_list else '无'}"
                ),
            },
        })
        elements.append({"tag": "hr"})

        # 命中分析
        all_pred = set(zhi + zu3_list + zu6_list)
        results = []
        score = 0

        # 直选检查
        for c in zhi:
            if c == actual_code:
                results.append(f"🎉 **直选命中！** `{c}` → +1040元")
                score += 1040

        # 组三检查
        if actual_shape == "组三":
            for c in zu3_list:
                if set(c) == actual_digits:
                    results.append(f"✨ **组三命中！** `{c}` → +346元")
                    score += 346

        # 组六检查
        if actual_shape == "组六":
            for c in zu6_list:
                if set(c) == actual_digits:
                    results.append(f"✨ **组六命中！** `{c}` → +173元")
                    score += 173

        # 两码命中
        if not results:
            for c in all_pred:
                common = len(set(c) & actual_digits)
                if common >= 2:
                    results.append(f"👍 两码命中 `{c}`（开奖 `{actual_code}`）")

        # 一码
        if not results:
            one_hit = []
            for c in all_pred:
                common = len(set(c) & actual_digits)
                if common == 1:
                    one_hit.append(c)
            if one_hit:
                results.append(f"👀 一码命中 `{'` `'.join(one_hit[:3])}`")
            else:
                results.append("😔 本期未命中任何号码")

        for r in results:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": r},
            })

        # 累计统计
        elements.append({"tag": "hr"})
        if score > 0:
            color = "green"
            summary = f"💰 理论中奖金额：**{score}元**\n🎊 恭喜！"
        else:
            color = "red"
            summary = "📊 本期未中奖，继续观察\n💡 彩票是概率游戏，长期统计才有参考价值"

        return self.send_card(
            header=f"🎰 福彩3D 开奖复盘 · {actual['期号']}",
            elements=elements,
            header_color=color,
            note=(
                f"📊 预测时间：{predicted.get('预测时间', '?')}\n"
                f"⚠ 仅供娱乐，理性购彩"
            ),
        )

    def send_weekly_report(self, week_records: list[dict], total: int,
                           any_hit: int, zhi_count: int, zu3_count: int,
                           zu6_count: int, total_bonus: int,
                           total_cost: int) -> bool:
        """推送周报卡片"""
        now = datetime.now()
        week_start = (now - timedelta(days=7)).strftime("%m/%d")
        week_end = now.strftime("%m/%d")

        hit_rate = any_hit / total * 100 if total > 0 else 0
        net = total_bonus - total_cost

        elements = []

        # 总览
        color = "green" if net > 0 else ("red" if net < 0 else "blue")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"📅 **统计周期**：{week_start} ~ {week_end}\n"
                    f"📊 **共预测**：{total} 期  |  **命中**：{any_hit} 期\n"
                    f"🎯 **命中率**：**{hit_rate:.1f}%**\n"
                    f"💰 理论奖金：**{total_bonus}元**  |  投入：{total_cost}元  |  净盈亏：**{net:+d}元**"
                ),
            },
        })
        elements.append({"tag": "hr"})

        # 命中明细
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"🎉 直选命中：**{zhi_count}** 次 (+{zhi_count * 1040}元)\n"
                    f"✨ 组三命中：**{zu3_count}** 次 (+{zu3_count * 346}元)\n"
                    f"💫 组六命中：**{zu6_count}** 次 (+{zu6_count * 173}元)"
                ),
            },
        })

        # 每日明细表
        if week_records:
            elements.append({"tag": "hr"})
            table_rows = []
            for r in week_records:
                issue = r.get("预测期号", "?")
                date = r.get("日期", "?")[-5:]  # MM-DD
                actual = r.get("实际号码", "?")
                zhi = "✅" if r.get("直选命中") else "❌"
                zu3 = "✅" if r.get("组三命中") else ("-" if len(set(actual)) != 2 else "❌")
                zu6 = "✅" if r.get("组六命中") else ("-" if len(set(actual)) != 3 else "❌")
                bonus = r.get("中奖金额", 0)
                bonus_str = f"+{bonus}" if bonus > 0 else "0"
                table_rows.append(
                    f"{issue} {date} `{actual}` 直{zhi} 组三{zu3} 组六{zu6} {bonus_str}"
                )
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "📋 **每日明细**\n" + "\n".join(table_rows[-7:]),
                },
            })

        return self.send_card(
            header=f"📊 福彩3D 周报 {week_start}~{week_end}",
            elements=elements,
            header_color=color,
            note=(
                f"命中率：{hit_rate:.1f}% | 净盈亏：{net:+d}元\n"
                f"⚠ 基于历史统计，不代表未来表现\n"
                f"💡 彩票是概率游戏，长期统计才有参考价值"
            ),
        )

    @staticmethod
    def _classify_shape(code: str) -> str:
        uniq = len(set(code))
        if uniq == 1:
            return "豹子"
        elif uniq == 2:
            return "组三"
        return "组六"

    def send_hit_result(self, predicted: list[str], actual: str,
                        issue: str = "") -> bool:
        """发送开奖结果与预测对比"""
        actual_digits = set(actual)
        elements = [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"🎯 **本期开奖 ({issue})**：`{actual}`"},
            },
            {"tag": "hr"},
        ]

        hits = []
        for code in predicted:
            if code == actual:
                hits.append(f"🎉 **直选命中!** `{code}`")
            elif set(code) == actual_digits:
                hits.append(f"✨ 组选命中! `{code}` (开奖 `{actual}`)")
            elif len(set(code) & actual_digits) >= 2:
                hits.append(f"👍 两码命中 `{code}`")

        if hits:
            for h in hits:
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": h},
                })
        else:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "😔 本期未命中，继续加油!"},
            })

        # 推荐号码回顾
        pred_str = "  ".join(f"`{c}`" for c in predicted[:5])
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"📋 本期推荐回顾\n{pred_str}"},
        })

        return self.send_card(
            header=f"🎰 福彩3D 开奖结果 ({issue})",
            elements=elements,
            header_color="green" if hits else "red",
        )

    def _post(self, payload: dict) -> bool:
        """发送 POST 请求"""
        import logging
        logger = logging.getLogger(__name__)
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            result = resp.json()
            ok = result.get("StatusCode") == 0 or result.get("code") == 0
            if not ok:
                logger.warning(f"飞书返回错误: {result}")
            return ok
        except Exception as e:
            logger.exception(f"飞书推送失败: {e}")
            return False
