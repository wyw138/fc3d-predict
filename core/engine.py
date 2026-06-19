"""
预测引擎 — 整合数据、分析、策略、集成、推送的完整 pipeline
"""

import json
import logging
import os
import random
from datetime import datetime, timedelta

from .fetcher import DataManager
from .validator import validate_dataset
from .analyzer import Analyzer
from .notifier import FeishuNotifier
from .scheduler import PredictionScheduler
from .strategies.base import StrategyRegistry
from .strategies.rule.hot_weighted import (
    HotWeightedStrategy, ColdReboundStrategy, PureRandomStrategy
)
from .strategies.rule.sum_pattern import (
    SumRegressionStrategy, PatternFollowStrategy, MissingComboStrategy
)
from .strategies.statistical.markov_chain import MarkovChainStrategy
from .strategies.statistical.multi_score import MultiScoreStrategy
from .strategies.statistical.ma_trend import MATrendStrategy
from .strategies.statistical.cdm_bayesian import CDMBayesianStrategy
from .strategies.ml.xgboost_strategy import XGBoostStrategy
from .ensemble.voting import ensemble_predict

logger = logging.getLogger(__name__)


class PredictionEngine:
    """预测引擎：一站式管理全流程"""

    def __init__(self, config: dict):
        self.config = config
        self.data_manager = DataManager(config.get("data", {}).get("cache_file", "data/history.json"))
        self.notifier = FeishuNotifier(config.get("feishu", {}).get("webhook_url", "")) if config.get("feishu", {}).get("enable") else None
        self.scheduler = PredictionScheduler(config)
        self.analyzer = None
        self.strategies = StrategyRegistry()
        data_dir = os.path.dirname(self.data_manager.cache_file) or "data"
        self._prediction_file = os.path.join(data_dir, "last_prediction.json")
        self._history_file = os.path.join(data_dir, "prediction_history.json")
        self._register_strategies()

    def _register_strategies(self):
        """注册所有可用策略"""
        data = self.data_manager.data
        for cls in [
            HotWeightedStrategy, ColdReboundStrategy, PureRandomStrategy,
            SumRegressionStrategy, PatternFollowStrategy, MissingComboStrategy,
            MarkovChainStrategy, MultiScoreStrategy, MATrendStrategy,
            CDMBayesianStrategy, XGBoostStrategy,
        ]:
            self.strategies.register(cls(data))

    def init_data(self, force_refresh: bool = False) -> list[dict]:
        """初始化数据"""
        data = self.data_manager.load(force_refresh=force_refresh)
        if data:
            report = validate_dataset(data)
            logger.info(f"数据校验: {report['有效记录']} 条有效, {len(report['错误'])} 个错误")
            self.analyzer = Analyzer(data)
            # 重新注册策略（使用新数据）
            self._register_strategies()
        return data

    def run_prediction(self) -> dict:
        """运行完整预测流程"""
        if not self.analyzer or not self.data_manager.data:
            self.init_data()
        if not self.analyzer:
            return {"error": "无可用数据"}

        data = self.data_manager.data

        # ── 固定随机种子：确保同一期预测结果一致 ──
        next_issue = int(data[0]["期号"]) + 1
        random.seed(next_issue)
        logger.info(f"随机种子已固定: issue={next_issue}")

        # 1. 获取启用的策略
        enabled = self.strategies.get_enabled(self.config)
        logger.info(f"使用 {len(enabled)} 个策略: {list(enabled.keys())}")

        # 2. 各策略预测
        all_preds = {}
        for name, strat in enabled.items():
            try:
                cfg = self.config.get("strategies", {}).get(name, {})
                n = cfg.get("samples", 20)
                all_preds[name] = strat.predict(n)
            except Exception as e:
                logger.error(f"策略 {name} 失败: {e}")

        # 3. 集成投票
        ensemble_cfg = self.config.get("ensemble", {})
        top_n = ensemble_cfg.get("top_n", 5)
        final = ensemble_predict(all_preds, ensemble_cfg, top_n)

        return {
            "策略预测": all_preds,
            "集成结果": final,
            "最新期": data[0] if data else None,
        }

    def send_prediction(self, result: dict) -> bool:
        """推送预测到飞书，同时保存预测用于开奖后对比"""
        if not self.notifier:
            logger.warning("飞书通知未启用")
            return False

        # 保存预测（用于开奖后自动对比）
        self._save_prediction(result)

        latest = result.get("最新期")
        predictions = result.get("集成结果", {})

        # 构建统计摘要
        stats_parts = []
        if self.analyzer:
            try:
                freq_all = self.analyzer.full_report().get("频率", {})
                hot = freq_all.get("最热数字", "?")
                cold = freq_all.get("最冷数字", "?")
                stats_parts.append(f"🔥 热号: {hot}   ❄ 冷号: {cold}")
            except Exception:
                pass

        return self.notifier.send_prediction(
            predictions=predictions,
            strategy_preds=result.get("策略预测", {}),
            latest_draw=latest,
            next_issue=str(int(latest["期号"]) + 1) if latest else "",
            stats_summary="\n".join(stats_parts),
        )

    def check_and_notify_new_draw(self) -> dict | None:
        """检查新开奖数据，如有则推送对比结果"""
        new_data = self.data_manager.check_new_data()
        if new_data:
            logger.info(f"发现新开奖: {new_data['期号']} {new_data['号码']}")
            self.data_manager.append_new(new_data)
            # 重新初始化分析器
            self.analyzer = Analyzer(self.data_manager.data)
            return new_data
        return None

    # ── 调度器回调 ──

    def start_scheduler(self):
        """启动定时调度 + 注册事件回调"""
        if not self.data_manager.data:
            self.init_data()
        self.scheduler.on_event("poll_new_data", self._on_poll_new_data)
        self.scheduler.on_event("morning_reminder", self._on_morning_reminder)
        self.scheduler.on_event("cutoff_reminder", self._on_cutoff_reminder)
        self.scheduler.setup_daily_schedule()
        self.scheduler.start()
        logger.info("定时调度已启动，等待开奖时间...")

    def _on_poll_new_data(self):
        """开奖后轮询新数据 → 发现后跑预测 → 推送"""
        logger.info("开始轮询新一期开奖数据...")
        new_data = self.scheduler.start_polling(
            check_new_data_fn=self.data_manager.check_new_data,
            on_new_data_fn=lambda d: self._handle_new_draw(d),
        )

    def _handle_new_draw(self, new_data: dict):
        """处理新一期数据：先对比命中 → 推送总结 → 再预测下一期"""
        self.data_manager.append_new(new_data)
        self.analyzer = Analyzer(self.data_manager.data)
        self._register_strategies()

        # ── 第一步：对比上一期预测 vs 实际开奖 ──
        prev_pred = self._load_prediction()
        if prev_pred:
            self._send_hit_report(prev_pred, new_data)
            self._clear_prediction()

        # ── 第二步：预测下一期 ──
        result = self.run_prediction()
        self._save_prediction(result)
        self.send_prediction(result)
        logger.info(f"预测已推送: {new_data['期号']} → 推荐 {result['集成结果'].get('共识推荐', [])}")

    def _save_prediction(self, result: dict):
        """保存预测结果（用于当夜对比 + 历史记录）"""
        record = {
            "预测期号": str(int(result["最新期"]["期号"]) + 1),
            "上期期号": result["最新期"]["期号"],
            "预测时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "日期": datetime.now().strftime("%Y-%m-%d"),
            "直选": result["集成结果"].get("共识推荐", [])[:5],
            "组三": sorted({c for v in result["集成结果"].values() for c in v if len(set(c)) == 2})[:3],
            "组六": sorted({c for v in result["集成结果"].values() for c in v if len(set(c)) == 3})[:3],
            # 以下字段在开奖后回填
            "实际号码": None,
            "直选命中": None,
            "组三命中": None,
            "组六命中": None,
            "中奖金额": 0,
        }
        try:
            os.makedirs(os.path.dirname(self._prediction_file), exist_ok=True)
            # 快速查找文件
            with open(self._prediction_file, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            # 历史追加
            self._append_history(record)
        except Exception as e:
            logger.warning(f"保存预测记录失败: {e}")

    def _append_history(self, record: dict):
        """追加预测到历史文件"""
        history = []
        if os.path.exists(self._history_file):
            try:
                with open(self._history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass
        # 去重：如果已有同期号记录则覆盖
        history = [h for h in history if h.get("预测期号") != record["预测期号"]]
        history.append(record)
        # 只保留最近 60 天
        cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        history = [h for h in history if h.get("日期", "") >= cutoff]
        with open(self._history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def _load_prediction(self) -> dict | None:
        """加载上次保存的预测"""
        try:
            if os.path.exists(self._prediction_file):
                with open(self._prediction_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _clear_prediction(self):
        """清除已使用的快速查找文件"""
        try:
            if os.path.exists(self._prediction_file):
                os.remove(self._prediction_file)
        except Exception:
            pass

    def _send_hit_report(self, prev_pred: dict, new_data: dict):
        """推送命中总结 + 回填历史记录"""
        if not self.notifier:
            return

        actual_code = new_data["号码"]
        actual_digits = set(actual_code)

        # 计算命中
        zhi_hit = any(c == actual_code for c in prev_pred.get("直选", []))
        zu3_hit = any(set(c) == actual_digits for c in prev_pred.get("组三", [])) if len(set(actual_code)) == 2 else False
        zu6_hit = any(set(c) == actual_digits for c in prev_pred.get("组六", [])) if len(set(actual_code)) == 3 else False

        prev_pred["实际号码"] = actual_code
        prev_pred["直选命中"] = zhi_hit
        prev_pred["组三命中"] = zu3_hit
        prev_pred["组六命中"] = zu6_hit
        prev_pred["中奖金额"] = (1040 if zhi_hit else 0) + (346 if zu3_hit else 0) + (173 if zu6_hit else 0)

        # 回填历史
        self._append_history(prev_pred)

        # 推送
        self.notifier.send_hit_report(predicted=prev_pred, actual=new_data)
        logger.info(f"命中总结已推送: {new_data['期号']} {new_data['号码']}")

        # 如果是周日，推送周报
        if datetime.now().weekday() == 6:  # Sunday
            self._send_weekly_report()

    def _send_weekly_report(self):
        """生成本周命中率周报并推送"""
        if not self.notifier or not os.path.exists(self._history_file):
            return
        try:
            with open(self._history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            return

        # 筛选最近 7 天已开奖的记录
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        week_records = [
            h for h in history
            if h.get("日期", "") >= cutoff and h.get("实际号码") is not None
        ]
        if not week_records:
            return

        total = len(week_records)
        zhi_count = sum(1 for h in week_records if h.get("直选命中"))
        zu3_count = sum(1 for h in week_records if h.get("组三命中"))
        zu6_count = sum(1 for h in week_records if h.get("组六命中"))
        any_hit = sum(1 for h in week_records if h.get("直选命中") or h.get("组三命中") or h.get("组六命中"))
        total_bonus = sum(h.get("中奖金额", 0) for h in week_records)
        total_cost = total * 2  # 每注2元

        self.notifier.send_weekly_report(
            week_records=week_records,
            total=total,
            any_hit=any_hit,
            zhi_count=zhi_count,
            zu3_count=zu3_count,
            zu6_count=zu6_count,
            total_bonus=total_bonus,
            total_cost=total_cost,
        )
        logger.info(f"周报已推送: {total}期, 命中{any_hit}期, 理论奖金{total_bonus}元")

    def _on_morning_reminder(self):
        """晨间提醒"""
        if self.notifier:
            result = self.run_prediction()
            rec = result["集成结果"].get("共识推荐", [])
            codes = "  ".join(f"`{c}`" for c in rec)
            self.notifier.send_text(
                f"🌅 早安！今日福彩3D推荐号码：\n{codes}\n\n⏰ 今晚 20:50 截止投注，21:15 开奖\n⚠ 仅供娱乐，理性购彩"
            )

    def _on_cutoff_reminder(self):
        """截止前提醒"""
        if self.notifier:
            self.notifier.send_text(
                "⚠️ 福彩3D 今晚 20:50 截止投注，21:15 开奖！\n抓紧时间投注，祝好运 🍀\n\n开奖后将自动推送结果对比。"
            )
