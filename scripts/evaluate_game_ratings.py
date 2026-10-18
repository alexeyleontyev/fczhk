"""Evaluate chronological forecasts trained on all preceding seasons.

Usage: FCZHK_DATABASE_URL=sqlite:///./.local/demo.db \
    .venv/bin/python scripts/evaluate_game_ratings.py [--season 2026]
"""

import argparse
import os

from fczhk.db import database
from fczhk.game_ratings import forecast_history, prediction_error


def display(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "—"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season",
        help="Сезон проверяемых матчей; прогнозы всегда учитывают все предыдущие сезоны",
    )
    args = parser.parse_args()
    url = os.environ.get("FCZHK_DATABASE_URL")
    if not url:
        raise SystemExit("Задайте FCZHK_DATABASE_URL")
    _, factory = database(url)
    with factory() as db:
        for include_keepers in (False, True):
            baseline = None
            mode = "field+keeper_roles" if include_keepers else "field_only"
            for margin in (0.0, 1.0, 2.0, 3.0):
                predictions = forecast_history(
                    db, season=args.season, margin=margin, include_keepers=include_keepers
                )
                if baseline is None and predictions:
                    baseline = sum((0.5 - p["outcome"]) ** 2 for p in predictions) / len(predictions)
                all_error = prediction_error(predictions)
                decisive_error = prediction_error(predictions, decisive_only=True)
                if all_error is None:
                    print("Завершённых игр с полевыми игроками нет")
                    return
                print(
                    f"mode={mode} margin={margin:g} games={len(predictions)} "
                    f"error_all={all_error:.4f} "
                    f"error_decisive={display(decisive_error)} "
                    f"error_after_4={display(prediction_error(predictions[4:]))}"
                )
            print(f"mode={mode} constant_50_error_all={baseline:.4f}")


if __name__ == "__main__":
    main()
