"""Deterministic synthetic inputs; no database, Telegram or real player data."""

from fractions import Fraction
from random import Random
from time import perf_counter

from fczhk.balancing import generate
from fczhk.schemas import BalanceSettings

for seed in (None, 0, 1, 42, 99):
    random = Random(seed)
    inputs = []
    for i in range(16):
        a, d = (
            (Fraction(3), Fraction(3))
            if seed is None
            else (Fraction(random.randrange(51), 10), Fraction(random.randrange(51), 10))
        )
        inputs.append(
            dict(
                registration_id=i,
                attack_fraction=[a.numerator, a.denominator],
                defense_fraction=[d.numerator, d.denominator],
            )
        )
    started = perf_counter()
    result = generate(inputs, BalanceSettings())
    elapsed = perf_counter() - started
    print(
        f"seed={str(seed):>4} | {elapsed:.3f}s | partitions={result['partition_count']} | variants={len(result['variants'])} | epsilon={result['epsilon_used']} | distances={result['distances']}"
    )
