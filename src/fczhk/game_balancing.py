"""Exact field-player partitions by OpenSkill expected strength."""

from fractions import Fraction
from itertools import combinations

from .balancing import Partition, choose, distance, suggested_distance, summary
from .schemas import BalanceSettings

ALGORITHM = "openskill-field-sum/multistart-diversity-v1"


def game_summary(inputs: list[dict], assignments: dict[int, str | None]) -> dict | None:
    sides = {
        side: [Fraction(str(row["game_mu"])) for row in inputs if assignments.get(row["registration_id"]) == side]
        for side in ("white", "black")
    }
    if not all(sides.values()) or sum(map(len, sides.values())) != len(inputs):
        return None
    white_total, black_total = (sum(sides[side]) for side in ("white", "black"))
    return {
        "white_mu": float(white_total / len(sides["white"])),
        "black_mu": float(black_total / len(sides["black"])),
        "white_total": float(white_total),
        "black_total": float(black_total),
        "mu_gap": float(abs(white_total - black_total) / Fraction(len(inputs), 2)),
    }


def generate(inputs: list[dict], settings: BalanceSettings) -> dict:
    count = len(inputs)
    if not 2 <= count <= 16:
        raise ValueError("Нужно от 2 до 16 полевых игроков")
    size = count // 2
    ratings = [Fraction(str(row["game_mu"])) for row in inputs]
    total = sum(ratings)
    candidates = []
    for chosen in combinations(range(count), size):
        if count % 2 == 0 and 0 not in chosen:
            continue
        white = sum(ratings[i] for i in chosen)
        # OpenSkill combines team mu by summing players. Divide by the average
        # roster size only to keep the setting's tolerance on a per-player scale.
        cost = abs(white - (total - white)) / Fraction(count, 2)
        candidates.append(Partition(sum(1 << i for i in chosen), cost))
    candidates.sort(key=lambda p: (p.cost, p.mask))
    best_cost = candidates[0].cost
    threshold = settings.min_distance or suggested_distance(count)
    epsilon, ceiling, step = map(
        Fraction, (settings.epsilon, settings.max_epsilon, settings.epsilon_step)
    )
    while True:
        pool = [p for p in candidates if p.cost <= best_cost + epsilon]
        selected = choose(pool, count, threshold)
        if len(selected) == 3 or epsilon == ceiling or len(pool) == len(candidates):
            break
        epsilon = min(ceiling, epsilon + step)
    variants = []
    for partition in selected:
        assignments = {
            row["registration_id"]: "white" if partition.mask & (1 << i) else "black"
            for i, row in enumerate(inputs)
        }
        variants.append(
            {
                "assignments": assignments,
                "summary": summary(inputs, assignments),
                "game_rating": game_summary(inputs, assignments),
            }
        )
    warnings = [
        "Экспериментальный рейтинг: проверка на импортированной истории пока не показала преимущества перед ориентиром 50/50."
    ]
    if len(selected) < 3:
        warnings.append(
            f"В пределах допуска {float(epsilon):g} найдено {len(selected)} вариант(а) с расстоянием {threshold}."
        )
    return {
        "algorithm": ALGORITHM,
        "exhaustive_balance": True,
        "diversity_optimum_guaranteed": False,
        "partition_count": len(candidates),
        "pool_count": len(pool),
        "minimum_cost": float(best_cost),
        "epsilon_used": float(epsilon),
        "min_distance": threshold,
        "distances": [[distance(a.mask, b.mask, count) for b in selected] for a in selected],
        "variants": variants,
        "warnings": warnings,
    }
