#!/usr/bin/env python3
"""
福彩3D 预测系统 — 主入口
用法:
  python main.py              # 运行一次预测并推送飞书
  python main.py schedule     # 启动定时调度（每日自动运行）
  python main.py stats        # 仅查看统计分析
  python main.py refresh      # 强制刷新数据
"""

import argparse
import io
import logging
import os
import sys
import yaml

# Windows 控制台 UTF-8 编码修复
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from core.engine import PredictionEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="福彩3D 预测系统")
    parser.add_argument("mode", nargs="?", default="predict",
                        choices=["predict", "schedule", "stats", "refresh", "weekly"],
                        help="运行模式")
    parser.add_argument("--no-push", action="store_true", help="不推送到飞书")
    args = parser.parse_args()

    config = load_config()
    engine = PredictionEngine(config)

    print("\n🎰 福彩3D 预测系统")
    print(f"   {config.get('disclaimer', '')}\n")

    # 初始化数据
    data = engine.init_data(force_refresh=(args.mode == "refresh"))
    if not data:
        print("❌ 无数据，请检查网络连接")
        return 1

    if args.mode == "stats":
        # 仅统计分析
        print(engine.analyzer.summary_text())
        return 0

    elif args.mode == "schedule":
        # 定时调度模式
        print("🕐 启动定时调度...")
        print(f"   开奖后轮询: 每天 {config['schedule']['poll_start']}")
        print(f"   晨间提醒:   每天 {config['schedule']['morning_reminder']}")
        print(f"   截止提醒:   每天 {config['schedule']['cutoff_reminder']}")
        print("   Ctrl+C 停止\n")
        engine.start_scheduler()
        try:
            import signal
            signal.pause()
        except (ImportError, AttributeError):
            import time
            while True:
                time.sleep(60)

    elif args.mode == "predict":
        # 单次预测
        print(f"📊 数据: {len(data)} 期 | 最新: {data[0]['期号']} {data[0]['号码']}\n")
        result = engine.run_prediction()

        # 打印结果
        final = result.get("集成结果", {})
        rec = final.get("共识推荐", [])
        if rec:
            codes = "  ".join(f" {c} " for c in rec)
            print(f"🎯 共识推荐: {codes}\n")

        for method, codes in final.items():
            if method != "共识推荐" and codes:
                c_str = "  ".join(f" {c} " for c in codes[:5])
                print(f"   [{method}] {c_str}")
        print()

        # 推送飞书
        if not args.no_push:
            ok = engine.send_prediction(result)
            if ok:
                print("✅ 已推送到飞书")
            else:
                print("⚠ 飞书推送失败（可能未配置或网络问题）")

        # 打印统计摘要
        if engine.analyzer:
            print("\n" + engine.analyzer.summary_text())

    elif args.mode == "weekly":
        # 周报模式
        print("📊 生成本周预测命中率周报...\n")
        engine.init_data()
        engine._send_weekly_report()
        print("✅ 周报已推送到飞书")

    return 0


if __name__ == "__main__":
    sys.exit(main())
