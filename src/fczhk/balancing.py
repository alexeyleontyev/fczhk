"""Exact partition costs; bounded multi-start heuristic for diverse alternatives.

The partition optimum is exhaustive. The triple-selection optimum is NOT guaranteed.
Scores are Fractions throughout the search; floats are only for JSON/display.
"""

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from math import ceil

from .schemas import BalanceSettings

ALGORITHM = "exhaustive-balance/multistart-diversity-v1"


def transform(attack: Fraction, defense: Fraction) -> tuple[Fraction, Fraction]:
    return (attack / 2, defense) if attack < defense else (attack, defense / 2)


def distance(a: int, b: int, count: int) -> int:
    changed = (a ^ b).bit_count()
    return min(changed, count - changed)


def suggested_distance(count: int) -> int:
    # Provisional proportional policy. Even rosters only admit even distances.
    target = ceil(6 * count / 16)
    if count % 2 == 0:
        target = min(2 * ceil(target / 2), 2 * (count // 4))
    else:
        target = min(target, count // 2)
    return max(1, target)


def values(row: dict) -> tuple[Fraction, Fraction] | None:
    if row["attack_fraction"] is None or row["defense_fraction"] is None:
        return None
    return transform(Fraction(*row["attack_fraction"]), Fraction(*row["defense_fraction"]))


def summary(inputs: list[dict], assignments: dict[int, str | None]) -> dict:
    result = {}
    for team in ("white", "black"):
        selected = [r for r in inputs if assignments.get(r["registration_id"]) == team]
        scores = [values(r) for r in selected]
        complete = bool(scores) and all(s is not None for s in scores)
        result[team] = dict(
            count=len(selected),
            attack=float(sum(s[0] for s in scores) / len(scores)) if complete else None,
            defense=float(sum(s[1] for s in scores) / len(scores)) if complete else None,
        )
    complete = all(result[t]["attack"] is not None for t in ("white", "black"))
    # Calculate the displayed cost from exact means, not previously rounded JSON values.
    if complete:
        means = []
        for team in ("white", "black"):
            scores = [values(r) for r in inputs if assignments.get(r["registration_id"]) == team]
            means.append(tuple(sum(s[k] for s in scores) / len(scores) for k in (0, 1)))
        attack_gap, defense_gap = (abs(means[0][k] - means[1][k]) for k in (0, 1))
        result.update(
            attack_gap=float(attack_gap),
            defense_gap=float(defense_gap),
            cost=float(attack_gap + defense_gap),
        )
    else:
        result.update(attack_gap=None, defense_gap=None, cost=None)
    result["unassigned"] = sum(assignments.get(r["registration_id"]) is None for r in inputs)
    return result


@dataclass(frozen=True)
class Partition:
    mask: int
    cost: Fraction


def partitions(inputs: list[dict]) -> list[Partition]:
    count, size = len(inputs), len(inputs) // 2
    scores = [values(r) for r in inputs]
    total_a, total_d = (sum(s[k] for s in scores) for k in (0, 1))
    result = []
    for chosen in combinations(range(count), size):
        # With equal sizes, fix one player to remove color-swapped duplicates.
        # With odd sizes, fixing the smaller team size is already canonical.
        if count % 2 == 0 and 0 not in chosen:
            continue
        a, d = (sum(scores[i][k] for i in chosen) for k in (0, 1))
        cost = abs(a / size - (total_a - a) / (count - size)) + abs(
            d / size - (total_d - d) / (count - size)
        )
        result.append(Partition(sum(1 << i for i in chosen), cost))
    return sorted(result, key=lambda p: (p.cost, p.mask))


def choose(pool: list[Partition], count: int, threshold: int) -> list[Partition]:
    """Deterministic farthest-first multi-start; at most 48 * 2 * pool size scans."""
    if len(pool) <= 1:
        return pool[:]
    anchors = sorted(
        set(range(min(24, len(pool)))) | {i * (len(pool) - 1) // 23 for i in range(24)}
    )
    best = [pool[0]]

    def key(group):
        differences = [distance(a.mask, b.mask, count) for a, b in combinations(group, 2)]
        return (
            -len(group),
            -min(differences, default=0),
            max(p.cost for p in group),
            sum(p.cost for p in group),
            tuple(sorted(p.mask for p in group)),
        )

    for index in anchors:
        first = pool[index]
        second = max(pool, key=lambda p: (distance(first.mask, p.mask, count), -p.cost, -p.mask))
        if distance(first.mask, second.mask, count) < threshold:
            continue
        group = [first, second]
        third = max(
            pool,
            key=lambda p: (
                min(distance(first.mask, p.mask, count), distance(second.mask, p.mask, count)),
                -p.cost,
                -p.mask,
            ),
        )
        if (
            min(distance(first.mask, third.mask, count), distance(second.mask, third.mask, count))
            >= threshold
        ):
            group.append(third)
        if key(group) < key(best):
            best = group
    return sorted(best, key=lambda p: (p.cost, p.mask))


def generate(inputs: list[dict], settings: BalanceSettings) -> dict:
    count = len(inputs)
    if not 2 <= count <= 16:
        raise ValueError("Нужно от 2 до 16 полевых игроков")
    if any(values(r) is None for r in inputs):
        raise ValueError("Не у всех полевых есть обе оценки")
    candidates = partitions(inputs)
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
    for p in selected:
        assignments = {
            r["registration_id"]: "white" if p.mask & (1 << i) else "black"
            for i, r in enumerate(inputs)
        }
        variants.append(dict(assignments=assignments, summary=summary(inputs, assignments)))
    warnings = []
    if len(selected) < 3:
        if len(candidates) < 3:
            warnings.append(
                f"Для {count} полевых существует только {len(candidates)} разбиение без учета цветов."
            )
        else:
            warnings.append(
                f"В пределах допуска {float(epsilon):g} и расстояния {threshold} эвристика нашла {len(selected)} вариант(а). Можно явно изменить настройки или распределить вручную; глобальный максимум разнообразия не гарантируется."
            )
    return dict(
        algorithm=ALGORITHM,
        exhaustive_balance=True,
        diversity_optimum_guaranteed=False,
        partition_count=len(candidates),
        pool_count=len(pool),
        minimum_cost=float(best_cost),
        epsilon_used=float(epsilon),
        min_distance=threshold,
        distances=[[distance(a.mask, b.mask, count) for b in selected] for a in selected],
        variants=variants,
        warnings=warnings,
    )
