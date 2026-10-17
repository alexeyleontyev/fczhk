from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from fczhk.models import Match, Player

spec = spec_from_file_location(
    "import_history", Path(__file__).resolve().parents[1] / "scripts/import_history.py"
)
importer = module_from_spec(spec)
spec.loader.exec_module(importer)


def source():
    cells = {
        "A2": "Администратор",
        "E2": "Игрок",
        "C14": "1",
        "E14": "1",
        "C15": "0",
        "E15": "1",
        "F15": "Игрок",
        "G15": "Администратор",
        "C16": "1",
        "E16": "1",
        "A16": "Автогол",
    }
    corrections = {
        "spreadsheet_id": "test-history",
        "cross_team_assists": [
            {
                "sheet": "2026-10-09",
                "cell": "G15",
                "source_value": "Администратор",
                "goal_author": "Игрок",
                "team": "black",
            }
        ],
        "match_notes": {"2026-10-09": ["Администратор играл за обе команды."]},
    }
    return cells, corrections


def test_confirmed_team_switch_and_unknown_own_goal_keep_source_meaning():
    cells, corrections = source()
    game = importer.parse_game("2026-10-09", cells, corrections)
    assert game["issues"] == []
    assert game["goals"][0]["assist"] == "Администратор"
    assert game["goals"][0]["assist_team_switch"]
    assert game["goals"][1]["kind"] == "own_goal"
    assert game["goals"][1]["author"] is None
    assert game["source_cells"]["A16"] == "Автогол"
    assert importer.parse_game("2026-10-09", cells, {"spreadsheet_id": "test"})["issues"]
    cells["F15"] = "Другой игрок"
    assert any(
        "изменилась" in issue
        for issue in importer.parse_game("2026-10-09", cells, corrections)["issues"]
    )


def test_import_preserves_existing_ids_and_confirmed_assist_can_be_edited(env, call):
    cells, corrections = source()
    game = importer.parse_game("2026-10-09", cells, corrections)
    imported = importer.import_games([game], env[0].database_url, corrections, "a" * 64, False)
    assert imported["players_added"] == 0
    with env[1]() as db:
        match = db.scalar(select(Match).where(Match.game_day == "2026-10-09"))
        assert "играл за обе команды" in match.description
        assert db.get(Player, env[4]["admin"]).alias == "Администратор"
        mid = match.id
    result = call("GET", f"/matches/{mid}/result")
    switch = result["assist_team_switches"][0]
    assert switch["player_id"] == env[4]["admin"]
    body = dict(
        version=result["version"],
        completed=True,
        participants=[
            {k: p[k] for k in ("player_id", "team", "position")} for p in result["participants"]
        ],
        goals=result["goals"],
    )
    saved = call("PUT", f"/matches/{mid}/result", body)
    assert saved["score"] == {"white": 1, "black": 1}
    own = next(g for g in saved["goals"] if g["kind"] == "own_goal")
    assert own["author_id"] is None
    assert call("GET", f"/players/{env[4]['admin']}/stats")["assists"] == 1
    tampered = deepcopy(body)
    tampered["version"] = saved["version"]
    next(g for g in tampered["goals"] if g["assist_id"])["id"] = str(uuid4())
    call("PUT", f"/matches/{mid}/result", tampered, expected=400)
