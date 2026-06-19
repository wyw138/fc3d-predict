"""
数据校验模块 — 格式检查、完整性验证、异常检测
"""

from typing import Optional


def validate_record(record: dict) -> tuple[bool, Optional[str]]:
    """校验单条记录是否合法"""
    # 必填字段
    for field in ["期号", "日期", "号码", "百位", "十位", "个位"]:
        if field not in record:
            return False, f"缺少字段: {field}"

    code = record["号码"]
    if len(code) != 3:
        return False, f"号码长度错误: {code}"

    b, s, g = record["百位"], record["十位"], record["个位"]
    if not (0 <= b <= 9 and 0 <= s <= 9 and 0 <= g <= 9):
        return False, f"数字超出范围: {b},{s},{g}"

    if f"{b}{s}{g}" != code:
        return False, f"号码与各位不一致: {code} vs {b}{s}{g}"

    if record.get("和值") != b + s + g:
        return False, f"和值错误: {record.get('和值')} != {b + s + g}"

    return True, None


def validate_dataset(data: list[dict]) -> dict:
    """校验整个数据集，返回校验报告"""
    report = {"总数": len(data), "错误": [], "警告": [], "期号列表": []}

    seen_issues = set()
    for i, record in enumerate(data):
        ok, err = validate_record(record)
        if not ok:
            report["错误"].append(f"[{i}] {err}")
            continue

        issue = record["期号"]
        if issue in seen_issues:
            report["警告"].append(f"重复期号: {issue}")
        else:
            seen_issues.add(issue)
            report["期号列表"].append(issue)

    # 检查期号连续性
    if report["期号列表"]:
        report["期号列表"].sort(reverse=True)
        gaps = []
        for i in range(len(report["期号列表"]) - 1):
            try:
                curr = int(report["期号列表"][i])
                next_i = int(report["期号列表"][i + 1])
                if curr - next_i > 1:
                    for gap_issue in range(curr - 1, next_i, -1):
                        gaps.append(str(gap_issue))
            except ValueError:
                pass
        if gaps:
            report["警告"].append(f"期号不连续，缺失 {len(gaps)} 期: {gaps[:5]}...")

    report["有效记录"] = len(report["期号列表"])
    return report
