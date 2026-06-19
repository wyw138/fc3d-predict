"""分类指标：奇偶、大小、质合、形态（豹子/组三/组六）"""

from collections import Counter


def odd_even_distribution(data: list[dict]) -> dict[str, int]:
    """奇偶比统计"""
    cnt = Counter()
    for d in data:
        odd = sum(1 for x in (d["百位"], d["十位"], d["个位"]) if x % 2 == 1)
        cnt[f"{odd}奇{3-odd}偶"] += 1
    return dict(cnt)


def big_small_distribution(data: list[dict]) -> dict[str, int]:
    """大小比统计（0-4小，5-9大）"""
    cnt = Counter()
    for d in data:
        big = sum(1 for x in (d["百位"], d["十位"], d["个位"]) if x >= 5)
        cnt[f"{big}大{3-big}小"] += 1
    return dict(cnt)


def prime_composite_distribution(data: list[dict]) -> dict[str, int]:
    """质合比统计（质数: 1,2,3,5,7）"""
    primes = {1, 2, 3, 5, 7}
    cnt = Counter()
    for d in data:
        prime = sum(1 for x in (d["百位"], d["十位"], d["个位"]) if x in primes)
        cnt[f"{prime}质{3-prime}合"] += 1
    return dict(cnt)


def shape_distribution(data: list[dict]) -> dict[str, int]:
    """豹子/组三/组六 分布"""
    cnt = Counter()
    for d in data:
        uniq = len({d["百位"], d["十位"], d["个位"]})
        if uniq == 1:
            cnt["豹子"] += 1
        elif uniq == 2:
            cnt["组三"] += 1
        else:
            cnt["组六"] += 1
    return dict(cnt)


def odd_even_pos_distribution(data: list[dict]) -> dict[str, Counter]:
    """各位奇偶独立统计"""
    cnt = {"百位": Counter(), "十位": Counter(), "个位": Counter()}
    for d in data:
        cnt["百位"]["奇" if d["百位"] % 2 else "偶"] += 1
        cnt["十位"]["奇" if d["十位"] % 2 else "偶"] += 1
        cnt["个位"]["奇" if d["个位"] % 2 else "偶"] += 1
    return cnt
