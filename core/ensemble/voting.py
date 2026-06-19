"""集成投票引擎 — 多策略结果融合"""

from collections import Counter


def frequency_vote(all_predictions: dict[str, list[str]], top_n: int = 5) -> list[str]:
    """
    频率投票：所有策略输出的号码中，出现次数最多的 Top-N。
    all_predictions: {策略名: [号码列表]}
    """
    counter = Counter()
    for strategy_name, codes in all_predictions.items():
        for code in codes:
            counter[code] += 1
    return [code for code, _ in counter.most_common(top_n)]


def position_vote(all_predictions: dict[str, list[str]], top_n: int = 5) -> list[str]:
    """
    位选投票：各位独立统计出现频率最高的数字，然后交叉组合。
    """
    pos_counter = {0: Counter(), 1: Counter(), 2: Counter()}
    for codes in all_predictions.values():
        for code in codes:
            if len(code) == 3:
                pos_counter[0][code[0]] += 1
                pos_counter[1][code[1]] += 1
                pos_counter[2][code[2]] += 1

    # 各位取最频繁的 3 个数字
    top_bai = [d for d, _ in pos_counter[0].most_common(3)]
    top_shi = [d for d, _ in pos_counter[1].most_common(3)]
    top_ge = [d for d, _ in pos_counter[2].most_common(3)]

    # 交叉组合
    results = []
    for b in top_bai:
        for s in top_shi:
            for g in top_ge:
                results.append(f"{b}{s}{g}")
                if len(results) >= top_n:
                    return results
    return results[:top_n]


def weighted_vote(all_predictions: dict[str, list[str]],
                  weights: dict[str, float], top_n: int = 5) -> list[str]:
    """
    加权投票：每种策略按其权重计票。
    weights: {策略名: 权重}
    """
    counter = Counter()
    for strategy_name, codes in all_predictions.items():
        w = weights.get(strategy_name, 1.0)
        for code in codes:
            counter[code] += w
    return [code for code, _ in counter.most_common(top_n)]


def ensemble_predict(all_predictions: dict[str, list[str]],
                     config: dict = None, top_n: int = 5) -> dict[str, list[str]]:
    """
    运行所有投票方式，返回 {投票方式: 号码列表}
    """
    if config is None:
        config = {"voting_methods": ["frequency", "position", "weighted"]}

    result = {}
    methods = config.get("voting_methods", ["frequency", "position", "weighted"])
    weights = config.get("strategy_weights", {})

    if "frequency" in methods:
        result["频率投票"] = frequency_vote(all_predictions, top_n)
    if "position" in methods:
        result["位选投票"] = position_vote(all_predictions, top_n)
    if "weighted" in methods and weights:
        result["加权投票"] = weighted_vote(all_predictions, weights, top_n)

    # 综合共识（三种投票的结果再投一次票）
    all_final = []
    for codes in result.values():
        all_final.extend(codes)
    consensus = Counter(all_final)
    result["共识推荐"] = [code for code, _ in consensus.most_common(top_n)]

    return result
