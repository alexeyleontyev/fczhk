"""Import exact defense/attack votes from the community Google Sheet.

Dry run: uv run python scripts/import_community_ratings.py --xlsx PATH
Write: FCZHK_DATABASE_URL=sqlite:///./.local/demo.db \
    uv run python scripts/import_community_ratings.py --xlsx PATH --apply
For PostgreSQL, run `uv run fczhk migrate` before --apply.
"""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, inspect, select

from fczhk.db import database
from fczhk.models import ImportedRating, Player
from fczhk.ratings import lock_ratings
from fczhk.services import audit
from fczhk.xlsx import read_sheets

DEMO_URL = "sqlite:///./.local/demo.db"
MAPPING = Path(__file__).resolve().parents[1] / "data/community_rating_aliases.json"


def column(number: int) -> str:
    letters = ""
    while number:
        number, digit = divmod(number - 1, 26)
        letters = chr(65 + digit) + letters
    return letters


def thousandths(raw: str, cell: str) -> int:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{cell}: нечисловая оценка {raw!r}") from exc
    scaled = value * 1000
    if not value.is_finite() or value < 0 or value > 5 or scaled != int(scaled):
        raise ValueError(f"{cell}: нужна оценка от 0 до 5 с точностью до 0,001: {raw!r}")
    return int(scaled)


def parse_votes(path: Path, settings: dict) -> list[dict]:
    cells = read_sheets(path, dated_only=False)[settings["sheet"]]
    row_numbers = sorted(
        int(match.group(1))
        for cell in cells
        if (match := re.fullmatch(r"A(\d+)", cell)) and int(match.group(1)) >= 3
    )
    if not row_numbers or row_numbers != list(range(3, row_numbers[-1] + 1)):
        raise ValueError("Строки игроков в колонке A должны идти подряд, начиная с A3")
    reviewers = []
    for number in range(6, 42, 2):
        defense_col, attack_col = column(number), column(number + 1)
        raw_name = cells.get(f"{defense_col}1")
        other_name = cells.get(f"{attack_col}1")
        if not raw_name and not other_name:
            if any(
                cells.get(f"{col}{row}") for col in (defense_col, attack_col) for row in row_numbers
            ):
                raise ValueError(f"{defense_col}:{attack_col}: оценки без имени оценщика")
            continue
        if (
            raw_name != other_name
            or cells.get(f"{defense_col}2") != "DEF"
            or cells.get(f"{attack_col}2") != "AT"
        ):
            raise ValueError(f"{defense_col}:{attack_col}: ожидается пара DEF/AT одного оценщика")
        reviewers.append((raw_name, defense_col, attack_col))
    if not reviewers:
        raise ValueError("Оценщики не найдены")
    aliases = settings["reviewer_aliases"]
    votes = []
    seen = set()
    for row in row_numbers:
        target = cells[f"A{row}"].strip()
        if not target:
            raise ValueError(f"A{row}: пустое имя игрока")
        for reviewer, defense_col, attack_col in reviewers:
            defense_cell, attack_cell = f"{defense_col}{row}", f"{attack_col}{row}"
            defense, attack = cells.get(defense_cell), cells.get(attack_cell)
            if defense is None and attack is None:
                continue
            if defense is None or attack is None:
                raise ValueError(f"{defense_cell}/{attack_cell}: неполная пара оценок")
            author = aliases.get(reviewer, reviewer)
            if author == target:
                raise ValueError(f"{defense_cell}/{attack_cell}: самооценка {author}")
            key = (author, target)
            if key in seen:
                raise ValueError(f"Повторная оценка от {author} для {target}")
            seen.add(key)
            votes.append(
                dict(
                    author=author,
                    target=target,
                    defense_milli=thousandths(defense, defense_cell),
                    attack_milli=thousandths(attack, attack_cell),
                    defense_cell=defense_cell,
                    attack_cell=attack_cell,
                )
            )
    return votes


def apply_votes(url: str, votes: list[dict], source_id: str, digest: str) -> dict:
    engine, factory = database(url)
    if url == DEMO_URL:
        ImportedRating.__table__.create(engine, checkfirst=True)
    elif not inspect(engine).has_table(ImportedRating.__tablename__):
        raise ValueError("Сначала примените миграции: uv run fczhk migrate")
    with factory() as db, db.begin():
        names = {name for vote in votes for name in (vote["author"], vote["target"])}
        found = {}
        for player in db.scalars(select(Player).where(Player.alias.in_(names))):
            if player.alias in found:
                raise ValueError(f"Неоднозначное имя игрока в базе: {player.alias}")
            found[player.alias] = player
        missing = sorted(names - found.keys())
        for name in missing:
            player = Player(alias=name)
            db.add(player)
            found[name] = player
        db.flush()
        desired = {(found[vote["author"]].id, found[vote["target"]].id): vote for vote in votes}
        existing = list(
            db.scalars(select(ImportedRating).where(ImportedRating.source_id == source_id))
        )
        same = len(existing) == len(desired) and all(
            row.source_sha256 == digest
            and (vote := desired.get((row.author_id, row.player_id))) is not None
            and row.attack_milli == vote["attack_milli"]
            and row.defense_milli == vote["defense_milli"]
            and row.attack_cell == vote["attack_cell"]
            and row.defense_cell == vote["defense_cell"]
            for row in existing
        )
        if not same:
            lock_ratings(db)
            db.execute(delete(ImportedRating).where(ImportedRating.source_id == source_id))
            db.add_all(
                ImportedRating(
                    source_id=source_id,
                    source_sha256=digest,
                    author_id=author_id,
                    player_id=player_id,
                    position="field",
                    attack_milli=vote["attack_milli"],
                    defense_milli=vote["defense_milli"],
                    attack_cell=vote["attack_cell"],
                    defense_cell=vote["defense_cell"],
                )
                for (author_id, player_id), vote in desired.items()
            )
            audit(
                db,
                None,
                "ratings.imported",
                source_id=source_id,
                source_sha256=digest,
                votes=len(desired),
                new_players=missing,
            )
    engine.dispose()
    return {"votes": len(votes), "new_players": missing, "changed": not same}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = json.loads(MAPPING.read_text(encoding="utf-8"))
    digest = hashlib.sha256(args.xlsx.read_bytes()).hexdigest()
    votes = parse_votes(args.xlsx, settings)
    counts = Counter(vote["author"] for vote in votes)
    print(
        json.dumps(
            {
                "source_sha256": digest,
                "sheet": settings["sheet"],
                "votes": len(votes),
                "reviewers": dict(sorted(counts.items())),
                "targets": len({vote["target"] for vote in votes}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.apply:
        url = os.environ.get("FCZHK_DATABASE_URL")
        if not url:
            raise ValueError("Для записи задайте FCZHK_DATABASE_URL")
        print(
            json.dumps(
                apply_votes(url, votes, settings["spreadsheet_id"], digest), ensure_ascii=False
            )
        )


if __name__ == "__main__":
    main()
