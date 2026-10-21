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


def test_previous_layout_preserves_orientation_roles_and_original_cells():
    cells = dict(
        A1="Черные",
        F1="Белые",
        C2="1",
        E2="1",
        M3="Рус",
        P3="Игрок",
        M11="Серега ВР",
        C3="0",
        E3="1",
        F3="Рус",
        G3="Серега ВР",
        C4="1",
        E4="1",
        A4="Автогол",
        B4="Игрок",
    )
    corrections = dict(
        spreadsheet_id="old",
        season="2024-2025",
        aliases={"Рус": "Рус не придет", "Серега ВР": "Серега"},
        unverified_assists=[dict(sheet="24.01", cell="B4", source_value="Игрок")],
    )
    game = importer.parse_game("24.01", cells, corrections, previous=True, game_day="2025-01-24")
    assert not game["issues"]
    assert game["season"] == "2024-2025" and game["game_day"] == "2025-01-24"
    assert game["teams"]["white"]["keeper"] == ["Серега"]
    assert game["teams"]["white"]["field"] == ["Рус не придет"]
    assert game["goals"][0]["author"] == "Рус не придет"
    assert game["goals"][0]["assist"] == "Серега"
    assert game["goals"][1]["assist"] is None
    assert game["goals"][1]["raw_assist"] == "Игрок"
    assert game["source_cells"]["M3"] == "Рус" and game["source_cells"]["B4"] == "Игрок"


def test_previous_workbook_requires_explicit_years_and_excludes_only_confirmed_tournaments(
    monkeypatch,
):
    import pytest

    cells = dict(A1="Черные", F1="Белые", C2="0", E2="0", M3="Один", P3="Другой")
    sheets = {"03.11": {"A1": "Тур"}, "24.01": cells}
    monkeypatch.setattr(importer, "read_sheets", lambda *args, **kwargs: sheets)
    corrections = dict(
        layout="previous_season",
        season="2024-2025",
        sheet_dates={"03.11": "2024-11-03", "24.01": "2025-01-24"},
        excluded_tournaments=["03.11"],
    )
    games, skipped = importer.parse_workbook(Path("fixture.xlsx"), corrections)
    assert skipped == ["03.11"] and [g["game_day"] for g in games] == ["2025-01-24"]
    sheets["31.01"] = cells
    with pytest.raises(ValueError, match="не подтверждён год"):
        importer.parse_workbook(Path("fixture.xlsx"), corrections)
    del sheets["31.01"]
    sheets["03.11"] = cells
    with pytest.raises(ValueError, match="вместо турнира обычная игра"):
        importer.parse_workbook(Path("fixture.xlsx"), corrections)


def test_import_reuses_linked_historical_alias_and_rejects_repeat_atomically(env, call):
    import pytest
    from sqlalchemy import func

    from fczhk.models import Audit, ResultParticipant

    guest = call("POST", "/players/guests", {"alias": "Старое имя"}, expected=201)
    call("POST", f"/players/{guest['id']}/link", {"target_id": env[4]["player"]})
    call("PATCH", "/me", {"alias": "Новое имя"}, role="player")
    cells = dict(
        A2="Администратор", E2="Старое имя", C14="0", E14="1", C15="0", E15="1", F15="Старое имя"
    )
    corrections = dict(spreadsheet_id="test-old", season="2024-2025")
    game = importer.parse_game("2025-01-24", cells, corrections)
    assert not game["issues"]
    summary = importer.import_games([game], env[0].database_url, corrections, "a" * 64, False)
    assert summary["players_added"] == 0
    with env[1]() as db:
        match = db.scalar(select(Match).where(Match.game_day == "2025-01-24"))
        assert match.season == "2024-2025"
        assert env[4]["player"] in db.scalars(
            select(ResultParticipant.player_id).where(ResultParticipant.match_id == match.id)
        )
        assert (
            db.scalar(select(Audit).where(Audit.match_id == match.id)).data["season"] == "2024-2025"
        )
        before = db.scalar(select(func.count()).select_from(Player))
    with pytest.raises(ValueError, match="уже есть"):
        importer.import_games([game], env[0].database_url, corrections, "a" * 64, False)
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(Player)) == before
        assert db.scalar(select(func.count()).select_from(Match)) == 1
    unsafe = deepcopy(game)
    unsafe["issues"] = ["Нерешённое уточнение"]
    with pytest.raises(ValueError, match="замечания"):
        importer.import_games([unsafe], env[0].database_url, corrections, "a" * 64, False)


def test_corrected_archive_date_does_not_allow_reimporting_the_same_source_sheet(env, call):
    import pytest
    from sqlalchemy import func

    cells, corrections = source()
    game = importer.parse_game("2026-10-09", cells, corrections)
    importer.import_games([game], env[0].database_url, corrections, "a" * 64, False)
    match = call("GET", "/matches")[0]
    call(
        "PUT",
        f"/matches/{match['id']}/archive-details",
        dict(
            version=match["version"],
            game_day="2026-10-08",
            start_time=None,
            location="",
            season="2026",
        ),
    )
    with pytest.raises(ValueError, match="уточнённой датой"):
        importer.import_games([game], env[0].database_url, corrections, "a" * 64, False)
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(Match)) == 1
        assert db.scalar(select(Match)).game_day == "2026-10-08"
