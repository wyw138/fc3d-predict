"""
定时任务调度器 — 开奖后自动抓取 → 预测 → 推送
使用 APScheduler 管理所有定时任务
"""

import logging
import time
from datetime import datetime, time as dtime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class PredictionScheduler:
    """3D 预测任务调度器"""

    def __init__(self, config: dict):
        self.config = config
        self.scheduler = BackgroundScheduler(timezone=config.get("schedule", {}).get("timezone", "Asia/Shanghai"))
        self._callbacks = {}
        self._running = False

    def on_event(self, event: str, callback):
        """注册事件回调"""
        self._callbacks[event] = callback

    def _fire(self, event: str, **kwargs):
        cb = self._callbacks.get(event)
        if cb:
            try:
                cb(**kwargs)
            except Exception as e:
                logger.error(f"事件 {event} 回调失败: {e}")

    def setup_daily_schedule(self):
        """配置每日定时任务"""
        sched_cfg = self.config.get("schedule", {})

        # 1. 开奖后轮询 — 第一轮 (21:18)
        for key, default_time in [("poll_start", "21:18"), ("poll_second", "22:00"), ("poll_morning", "06:30")]:
            time_str = sched_cfg.get(key, default_time)
            if not time_str:
                continue
            hour, minute = map(int, time_str.split(":"))
            self.scheduler.add_job(
                lambda: self._fire("poll_new_data"),
                CronTrigger(hour=hour, minute=minute),
                id=f"poll_{key}",
                replace_existing=True,
            )

        # 2. 晨间提醒 (09:00)
        morning = sched_cfg.get("morning_reminder", "09:00")
        hour, minute = map(int, morning.split(":"))
        self.scheduler.add_job(
            lambda: self._fire("morning_reminder"),
            CronTrigger(hour=hour, minute=minute),
            id="morning_reminder",
            replace_existing=True,
        )

        # 3. 截止提醒 (20:50)
        cutoff = sched_cfg.get("cutoff_reminder", "20:50")
        hour, minute = map(int, cutoff.split(":"))
        self.scheduler.add_job(
            lambda: self._fire("cutoff_reminder"),
            CronTrigger(hour=hour, minute=minute),
            id="cutoff_reminder",
            replace_existing=True,
        )

        logger.info("每日定时任务已配置")

    def start_polling(self, check_new_data_fn, on_new_data_fn,
                      interval: int = None, max_duration: int = None):
        """
        开始轮询新数据（开奖后调用）
        """
        sched_cfg = self.config.get("schedule", {})
        interval = interval or sched_cfg.get("poll_interval", 60)
        max_duration = max_duration or sched_cfg.get("poll_max_duration", 1800)
        logger.info(f"开始轮询新数据，间隔 {interval}s，最长 {max_duration}s")
        start = time.time()
        while time.time() - start < max_duration:
            try:
                new_data = check_new_data_fn()
                if new_data:
                    logger.info(f"发现新数据: {new_data['期号']} {new_data['号码']}")
                    on_new_data_fn(new_data)
                    return new_data
            except Exception as e:
                logger.warning(f"轮询异常: {e}")
            time.sleep(interval)
        logger.info("轮询结束，未发现新数据")
        return None

    def start(self):
        """启动调度器"""
        if not self._running:
            self.scheduler.start()
            self._running = True
            logger.info("调度器已启动")

    def stop(self):
        """停止调度器"""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            logger.info("调度器已停止")

    def run_now(self, event: str, **kwargs):
        """立即触发某个事件"""
        self._fire(event, **kwargs)
