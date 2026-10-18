"""Inspect and import dated match tabs from the historical Google Sheets XLSX export.

Dry run:
    .venv/bin/python scripts/import_history.py --xlsx /path/to/export.xlsx

Write to a selected database:
    FCZHK_DATABASE_URL=sqlite:///./.local/demo.db \
      .venv/bin/python scripts/import_history.py --xlsx /path/to/export.xlsx --apply --replace-demo
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from fczhk.db import Base, database
from fczhk.models import (
    Audit,
    GameTemplate,
    Match,
    MatchResult,
    Player,
    RatingState,
    ResultGoal,
    ResultParticipant,
)
from fczhk.ratings import lock_ratings
from fczhk.services import MOSCOW
from fczhk.xlsx import read_sheets

UNKNOWN_AUTHORS = {"", "хз кто"}
DEMO_URL = "sqlite:///./.local/demo.db"


def integer(cell: str, value: str) -> int:
    try:
        number = float(value)
        if not number.is_integer() or number < 0:
            raise ValueError
        return int(number)
    except ValueError as exc:
        raise ValueError(
            f"{cell}: ожидалось целое неотрицательное число, получено {value!r}"
        ) from exc


def own_goal_author(raw: str) -> str | None:
    match = re.fullmatch(r"автогол\s*\((.+)\)", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.fullmatch(r"автогол\s+(.+)", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.fullmatch(r"(.+?)\s+автогол", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def source_corrections(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("spreadsheet_id"):
        raise ValueError("В файле поправок нужен spreadsheet_id")
    return data


def apply_cell_corrections(name: str, raw: dict[str, str], corrections: dict) -> dict[str, str]:
    cells = raw.copy()
    for fix in corrections.get("cell_corrections", []):
        if fix["sheet"] != name:
            continue
        cell = fix["cell"]
        current = cells.get(cell)
        if current == fix["expected_source_value"]:
            cells[cell] = fix["corrected_value"]
        elif current != fix["corrected_value"]:
            raise ValueError(
                f"{name}!{cell}: ожидалось {fix['expected_source_value']!r} или "
                f"{fix['corrected_value']!r}, найдено {current!r}"
            )
    return cells


def parse_game(
    name: str,
    raw: dict[str, str],
    corrections: dict,
    *,
    previous: bool = False,
    game_day: str | None = None,
) -> dict:
    cells = apply_cell_corrections(name, raw, corrections)
    aliases = corrections.get("aliases", {})

    def canonical(value):
        return aliases.get(value, value)

    issues = []
    teams = {}
    roster_columns = (
        (("white", "M"), ("black", "P")) if previous else (("white", "A"), ("black", "E"))
    )
    first_row, keeper_row = (3, 11) if previous else (2, 10)
    keeper_resolutions = corrections.get("keeper_resolutions", {}).get(name, {})
    for side, column in roster_columns:
        field = [canonical(cells.get(f"{column}{r}", "")) for r in range(first_row, keeper_row)]
        field = [player for player in field if player]
        keeper_raw = cells.get(f"{column}{keeper_row}", "")
        if side in keeper_resolutions:
            if not keeper_raw:
                issues.append(f"{column}{keeper_row}: есть поправка к пустой ячейке")
            keepers = keeper_resolutions[side]
        elif keeper_raw and ("/" in keeper_raw or "(" in keeper_raw):
            issues.append(f"{column}{keeper_row}: уточнить вратарей: {keeper_raw!r}")
            keepers = []
        else:
            keepers = [keeper_raw] if keeper_raw else []
        if any(not isinstance(player, str) or not player.strip() for player in keepers):
            issues.append(f"{column}{keeper_row}: некорректное разрешение списка вратарей")
        teams[side] = {
            "field": field,
            "keeper": [canonical(p) for p in keepers],
            "keeper_raw": keeper_raw,
        }
    all_names = [
        player
        for team in teams.values()
        for position in ("field", "keeper")
        for player in team[position]
    ]
    for player, count in Counter(all_names).items():
        if count > 1:
            issues.append(f"Игрок {player!r} встречается в составах {count} раза")
    score_cells = {"white": "E2", "black": "C2"} if previous else {"white": "C14", "black": "E14"}
    final_score = {
        side: integer(f"{name}!{cell}", cells.get(cell, "")) for side, cell in score_cells.items()
    }
    ignored_assists = {
        item["cell"]: item
        for item in corrections.get("unverified_assists", [])
        if item["sheet"] == name
    }
    switched_assists = {
        item["cell"]: item
        for item in corrections.get("cross_team_assists", [])
        if item["sheet"] == name
    }
    goals = []
    score = {"white": 0, "black": 0}
    for row in range(3, 48) if previous else range(15, 48):
        if f"C{row}" not in cells and f"E{row}" not in cells:
            continue
        goal_columns = (
            (("white", "E", "F", "G"), ("black", "C", "A", "B"))
            if previous
            else (("white", "C", "A", "B"), ("black", "E", "F", "G"))
        )
        for side, score_col, author_col, assist_col in goal_columns:
            current = integer(f"{name}!{score_col}{row}", cells.get(f"{score_col}{row}", ""))
            change = current - score[side]
            if change not in (0, 1):
                issues.append(f"{score_col}{row}: счёт изменился на {change}, ожидалось 0 или 1")
                score[side] = current
                continue
            author_raw = cells.get(f"{author_col}{row}", "")
            assist_cell = f"{assist_col}{row}"
            assist_raw = cells.get(assist_cell, "")
            if change == 0 and (author_raw or assist_raw):
                issues.append(f"{author_col}{row}:{assist_cell}: есть автор/передача без гола")
            if change == 1:
                own_author = own_goal_author(author_raw)
                kind = "own_goal" if own_author or author_raw.casefold() == "автогол" else "goal"
                author = (
                    own_author
                    if kind == "own_goal"
                    else (None if author_raw.casefold() in UNKNOWN_AUTHORS else author_raw)
                )
                assist = assist_raw or None
                if assist_cell in ignored_assists:
                    if assist_raw != ignored_assists[assist_cell]["source_value"]:
                        issues.append(f"{assist_cell}: спорная передача изменилась в источнике")
                    assist = None
                switched = switched_assists.get(assist_cell)
                if switched and (
                    assist_raw != switched["source_value"]
                    or author_raw != switched["goal_author"]
                    or side != switched["team"]
                ):
                    issues.append(
                        f"{assist_cell}: подтверждённая передача при смене команды изменилась"
                    )
                goals.append(
                    {
                        "team": side,
                        "kind": kind,
                        "author": canonical(author) if author else None,
                        "assist": canonical(assist) if assist else None,
                        "source_row": row,
                        "source_kind": "score_progression",
                        "raw_author": author_raw,
                        "raw_assist": assist_raw,
                        "assist_team_switch": bool(switched),
                    }
                )
            score[side] = current
    for side in ("white", "black"):
        difference = final_score[side] - score[side]
        if difference < 0:
            issues.append(f"Итоговый счёт {side} меньше накопительного")
        elif difference and name not in corrections.get("score_only_goals_allowed", []):
            issues.append(f"Не хватает {difference} голов {side} до итогового счёта")
        else:
            for index in range(difference):
                goals.append(
                    {
                        "team": side,
                        "kind": "goal",
                        "author": None,
                        "assist": None,
                        "source_row": None,
                        "source_kind": f"score_only_{index + 1}",
                        "raw_author": "",
                        "raw_assist": "",
                    }
                )
    for goal in goals:
        side = (
            "black"
            if goal["kind"] == "own_goal" and goal["team"] == "white"
            else ("white" if goal["kind"] == "own_goal" else goal["team"])
        )
        if goal["author"] and goal["author"] not in (teams[side]["field"] + teams[side]["keeper"]):
            issues.append(
                f"Гол, строка {goal['source_row']}: автор {goal['author']!r} не в составе {side}"
            )
        if (
            goal["assist"]
            and goal["assist"] not in (teams[goal["team"]]["field"] + teams[goal["team"]]["keeper"])
            and not (goal.get("assist_team_switch") and goal["assist"] in all_names)
        ):
            issues.append(
                f"Гол, строка {goal['source_row']}: ассистент {goal['assist']!r} "
                f"не в составе {goal['team']}"
            )
        if goal["kind"] == "own_goal" and goal["assist"]:
            issues.append(f"Автогол, строка {goal['source_row']}: передача недопустима")
    if Counter(goal["team"] for goal in goals) != Counter(final_score):
        issues.append("Количество событий не совпадает с итоговым счётом")
    return {
        "game_day": game_day or name,
        "sheet": name,
        "season": corrections.get("season", (game_day or name)[:4]),
        "teams": teams,
        "final_score": final_score,
        "goals": goals,
        "source_info": {
            key: raw.get(key, "") for key in ("A51", "B51", "C51", "D51", "E51", "F51")
        },
        "source_cells": {
            cell: value
            for cell, value in raw.items()
            if (match := re.fullmatch(r"([A-GMP])(\d+)", cell)) and int(match.group(2)) <= 51
        },
        "issues": issues,
    }


def parse_workbook(path: Path, corrections: dict) -> tuple[list[dict], list[str]]:
    if corrections.get("layout") != "previous_season":
        return [
            parse_game(name, cells, corrections)
            for name, cells in sorted(read_sheets(path).items())
        ], []
    # Dates are explicitly confirmed, never inferred from the current year or month.
    dates = corrections["sheet_dates"]
    excluded = set(corrections["excluded_tournaments"])
    games, skipped = [], []
    for name, cells in read_sheets(path, dated_only=False).items():
        if not re.fullmatch(r"\d{2}\.\d{2}", name):
            continue
        if name not in dates:
            raise ValueError(f"Для листа {name} не подтверждён год")
        parsed = date.fromisoformat(dates[name])
        if parsed.strftime("%d.%m") != name:
            raise ValueError(f"Дата {parsed} не соответствует названию листа {name}")
        day = parsed.isoformat()
        ordinary = cells.get("A1") == "Черные" and cells.get("F1") == "Белые"
        if name in excluded:
            if ordinary:
                raise ValueError(f"Лист {name} изменился: вместо турнира обычная игра")
            skipped.append(name)
        elif not ordinary:
            raise ValueError(f"Неизвестный формат листа {name}")
        else:
            games.append(parse_game(name, cells, corrections, previous=True, game_day=day))
    if set(dates) != {g["sheet"] for g in games} | set(skipped):
        raise ValueError("Набор листов не совпадает с подтверждённым источником")
    return sorted(games, key=lambda game: game["game_day"]), skipped


def backup_sqlite(path: Path) -> Path:
    output = (
        path.parent
        / "backups"
        / f"{path.stem}-before-history-{datetime.now().strftime('%Y%m%dT%H%M%S')}.sqlite3"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(path)
    target = sqlite3.connect(output)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return output


def import_games(
    games: list[dict], db_url: str, corrections: dict, source_hash: str, replace_demo: bool
) -> dict:
    if replace_demo and db_url != DEMO_URL:
        raise ValueError("--replace-demo разрешён только для sqlite:///./.local/demo.db")
    if replace_demo:
        print(f"Резервная копия: {backup_sqlite(Path('.local/demo.db'))}")
    engine, factory = database(db_url)
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    if not games or any(game["issues"] for game in games):
        raise ValueError("Пустой импорт или нерешённые замечания")
    dates = [game["game_day"] for game in games]
    if len(dates) != len(set(dates)):
        raise ValueError("Повторяющиеся даты в импорте")
    with factory() as db, db.begin():
        if replace_demo:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())
            db.add_all([RatingState(id=1), GameTemplate(id=1)])
            db.flush()
        lock_ratings(db)
        existing = {}
        catalog = {p.id: p for p in db.scalars(select(Player))}

        def resolved(player):
            visited = set()
            while player.merged_into is not None:
                if player.id in visited or player.merged_into not in catalog:
                    raise ValueError("Повреждённая цепочка связанных игроков")
                visited.add(player.id)
                player = catalog[player.merged_into]
            return player

        for source_player in catalog.values():
            player = resolved(source_player)
            existing.setdefault(source_player.alias, {})[player.id] = player
        # New links release the guest's unique alias. Its confirmed identity stays
        # in the audit trail even if the account is renamed after linking.
        for entry in db.scalars(select(Audit).where(Audit.action == "guest.linked")):
            alias = entry.data.get("guest_alias")
            target = catalog.get(entry.data.get("target_id"))
            if alias and target is not None:
                player = resolved(target)
                existing.setdefault(alias, {})[player.id] = player
        existing = {name: list(players.values()) for name, players in existing.items()}
        names = {
            player
            for game in games
            for team in game["teams"].values()
            for position in ("field", "keeper")
            for player in team[position]
        }
        if any(len(existing.get(name, [])) > 1 for name in names):
            duplicates = [name for name in names if len(existing.get(name, [])) > 1]
            raise ValueError(f"Неоднозначные существующие карточки: {sorted(duplicates)}")
        players = {name: existing[name][0] for name in names if name in existing}
        new_players = [Player(alias=name) for name in sorted(names - players.keys())]
        db.add_all(new_players)
        db.flush()
        players.update({player.alias: player for player in new_players})
        for game in games:
            participant_ids = [
                players[name].id
                for team in game["teams"].values()
                for role in ("field", "keeper")
                for name in team[role]
            ]
            if len(participant_ids) != len(set(participant_ids)):
                raise ValueError(f"{game['game_day']}: один связанный игрок указан несколько раз")
        existing_days = set(db.scalars(select(Match.game_day)))
        overlapping = existing_days & {game["game_day"] for game in games}
        if overlapping:
            raise ValueError(f"Игры с такими датами уже есть: {sorted(overlapping)}")
        for game in games:
            day = date.fromisoformat(game["game_day"])
            match = Match(
                game_day=game["game_day"],
                season=game["season"],
                starts_at=datetime.combine(day, time(12, 0), MOSCOW),
                location="Не указано в историческом источнике",
                description="Исторический импорт. Известна дата игры; время начала и место не указаны.",
                field_limit=max(2, sum(len(team["field"]) for team in game["teams"].values())),
                keeper_limit=sum(len(team["keeper"]) for team in game["teams"].values()),
                status="completed",
            )
            notes = corrections.get("match_notes", {}).get(game["game_day"], [])
            if notes:
                match.description += "\n" + "\n".join(notes)
            db.add(match)
            db.flush()
            db.add(MatchResult(match_id=match.id, completed=True))
            for side, team in game["teams"].items():
                for position in ("field", "keeper"):
                    db.add_all(
                        ResultParticipant(
                            match_id=match.id,
                            player_id=players[name].id,
                            team=side,
                            position=position,
                        )
                        for name in team[position]
                    )
            switched_assists = []
            for goal in game["goals"]:
                key = (
                    f"{corrections['spreadsheet_id']}:{game['game_day']}:{goal['team']}:"
                    f"{goal['source_row']}:{goal['source_kind']}"
                )
                goal_id = str(uuid5(NAMESPACE_URL, key))
                if goal.get("assist_team_switch"):
                    switched_assists.append(
                        dict(
                            goal_id=goal_id, player_id=players[goal["assist"]].id, team=goal["team"]
                        )
                    )
                db.add(
                    ResultGoal(
                        match_id=match.id,
                        id=goal_id,
                        team=goal["team"],
                        kind=goal["kind"],
                        author_id=players[goal["author"]].id if goal["author"] else None,
                        assist_id=players[goal["assist"]].id if goal["assist"] else None,
                    )
                )
            db.add(
                Audit(
                    match_id=match.id,
                    action="history.imported",
                    data={
                        "spreadsheet_id": corrections["spreadsheet_id"],
                        "sheet": game.get("sheet", game["game_day"]),
                        "season": game["season"],
                        "aliases": corrections.get("aliases", {}),
                        "xlsx_sha256": source_hash,
                        "date_only": True,
                        "source_info": game["source_info"],
                        "keepers_raw": {
                            side: team["keeper_raw"] for side, team in game["teams"].items()
                        },
                        "placeholder_players": corrections.get("placeholder_players", []),
                        "goals_source": game["goals"],
                        "source_cells": game["source_cells"],
                        "assist_team_switches": switched_assists,
                        "notes": notes,
                    },
                )
            )
        db.flush()
        return {
            "matches": len(games),
            "players_added": len(new_players),
            "players_total": len(players),
            "goals": sum(len(game["goals"]) for game in games),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument(
        "--corrections", type=Path, default=Path("data/historical_import_corrections.json")
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace-demo", action="store_true")
    parser.add_argument("--dates", nargs="+", help="Импортировать только указанные даты YYYY-MM-DD")
    args = parser.parse_args()
    source_hash = hashlib.sha256(args.xlsx.read_bytes()).hexdigest()
    corrections = source_corrections(args.corrections)
    games, skipped = parse_workbook(args.xlsx, corrections)
    if args.dates:
        missing = set(args.dates) - {game["game_day"] for game in games}
        if missing:
            raise ValueError(f"В источнике нет дат: {sorted(missing)}")
        games = [game for game in games if game["game_day"] in args.dates]
    if not games:
        raise ValueError("В файле нет обычных игр с датами")
    if skipped:
        print(f"Пропущены турнирные листы ({len(skipped)}): {', '.join(skipped)}")
    problems = 0
    for game in games:
        score = game["final_score"]
        print(
            f"{game['game_day']}: {score['white']}:{score['black']}, "
            f"{sum(len(team[p]) for team in game['teams'].values() for p in ('field', 'keeper'))} "
            f"участников, {len(game['goals'])} голов"
        )
        for issue in game["issues"]:
            problems += 1
            print(f"  ПРОВЕРИТЬ: {issue}")
    if problems:
        print(f"Импорт не начат: {problems} нерешённых замечаний.")
        return 2
    print(f"Проверка пройдена: {len(games)} игр, SHA-256 {source_hash}")
    if args.apply:
        db_url = os.environ.get("FCZHK_DATABASE_URL")
        if not db_url:
            raise ValueError("Для записи задайте FCZHK_DATABASE_URL")
        print(
            json.dumps(
                import_games(games, db_url, corrections, source_hash, args.replace_demo),
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
