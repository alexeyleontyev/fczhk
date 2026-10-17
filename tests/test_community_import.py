from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import func, select

from fczhk.models import ImportedRating, Player

spec = spec_from_file_location(
    "import_community_ratings",
    Path(__file__).resolve().parents[1] / "scripts/import_community_ratings.py",
)
importer = module_from_spec(spec)
spec.loader.exec_module(importer)


def test_source_pairs_keep_zero_and_thousandths(monkeypatch, tmp_path):
    source = {
        "A3": "Игрок",
        "A4": "Оценщик",
        "F1": "Оценщик",
        "G1": "Оценщик",
        "F2": "DEF",
        "G2": "AT",
        "F3": "0.0",
        "G3": "4.239",
    }
    monkeypatch.setattr(importer, "read_sheets", lambda *_args, **_kwargs: {"Оценки": source})
    settings = {"sheet": "Оценки", "reviewer_aliases": {}}
    votes = importer.parse_votes(tmp_path / "source.xlsx", settings)
    assert [(v["defense_milli"], v["attack_milli"]) for v in votes] == [(0, 4239)]
    del source["G3"]
    with pytest.raises(ValueError, match="неполная пара"):
        importer.parse_votes(tmp_path / "source.xlsx", settings)


def test_imported_votes_are_public_precise_idempotent_and_overridden(env, call):
    admin, player = env[4]["admin"], env[4]["player"]
    votes = [
        dict(
            author="Администратор",
            target="Игрок",
            attack_milli=4239,
            defense_milli=0,
            attack_cell="G3",
            defense_cell="F3",
        ),
        dict(
            author="Новый оценщик",
            target="Игрок",
            attack_milli=3000,
            defense_milli=5000,
            attack_cell="I3",
            defense_cell="H3",
        ),
        dict(
            author="Администратор",
            target="Новый игрок",
            attack_milli=5000,
            defense_milli=0,
            attack_cell="G4",
            defense_cell="F4",
        ),
    ]
    url = env[0].database_url
    imported = importer.apply_votes(url, votes, "test-source", "a" * 64)
    assert imported == {
        "votes": 3,
        "new_players": ["Новый игрок", "Новый оценщик"],
        "changed": True,
    }
    assert importer.apply_votes(url, votes, "test-source", "a" * 64)["changed"] is False
    board = call("GET", "/leaderboards", role="player")["community"]["boards"]
    row = next(r for r in board["field_total"] if r["player_id"] == player)
    assert (row["attack"], row["defense"], row["score"]) == (3.6195, 2.5, 6.1195)
    detail = call("GET", f"/players/{player}/ratings/field")
    assert detail["imported_own"] == {"attack": 4.239, "defense": 0}
    assert len(detail["reviews"]) == 2
    assert all(review["source"] == "sheet" for review in detail["reviews"])
    assert "reviews" not in call("GET", f"/players/{player}/ratings/field", role="player")
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(ImportedRating)) == 3
        new_player = db.scalar(select(Player).where(Player.alias == "Новый игрок"))
        new_author = db.scalar(select(Player).where(Player.alias == "Новый оценщик"))
        assert new_player.telegram_id is None and new_author.telegram_id is None
        new_author_id = new_author.id
    assert (
        next(p for p in call("GET", "/players", role="player") if p["id"] == new_player.id)[
            "ratings"
        ]["field"]["attack"]
        == 5
    )

    # A new in-app vote replaces the historical vote from the same author.
    call(
        "PUT", f"/players/{player}/ratings", dict(position="field", attack=4, defense=2, revision=0)
    )
    updated = call("GET", "/leaderboards", role="player")["community"]["boards"]
    row = next(r for r in updated["field_total"] if r["player_id"] == player)
    assert (row["attack"], row["defense"], row["score"]) == (3.5, 3.5, 7)
    call("POST", f"/players/{new_author_id}/link", {"target_id": admin})
    linked = call("GET", f"/players/{player}/ratings/field")["averages"]
    assert (linked["attack"], linked["defense"]) == (4, 2)

    revised = deepcopy(votes)
    revised[0]["attack_milli"] = 4000
    assert importer.apply_votes(url, revised, "test-source", "b" * 64)["changed"] is True
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(ImportedRating)) == 3
