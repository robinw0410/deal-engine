"""Relist detection (core/insights.find_relist)."""
import pytest

from core import history
from core.insights import find_relist


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-20")
    c = history.connect(tmp_path / "h.db")
    yield c
    c.close()


def add(con, uid, title, price, location, grp="Xbox Series S", image=None, source="src", published="2026-06-15",
        gone=None, distance=45):
    con.execute("""INSERT INTO listing(uid, source, source_id, search, grp, title, published, first_seen, last_seen,
                   first_price, price, distance_km, image, location, status, gone_date)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, source, uid, "s", grp, title, published, published, gone or "2026-06-20", price, price,
                 distance, image, location, "gone" if gone else "active", gone))


def test_same_place_similar_title_and_price(con):
    add(con, "old", "Xbox Series S 512GB HDMI port damaged", 130, "Oakdale", published="2026-05-20", gone="2026-06-01")
    add(con, "new", "Xbox Series S 512GB HDMI port damaged white", 125, "Oakdale")
    assert find_relist(con, "s", "new")["by"] == "text"


def test_demo_false_positive_different_place_same_distance(con):
    # the case from the demo: similar title and price, both ~45 km from home, but different towns
    add(con, "old", "Xbox Series S console – HDMI port damaged", 130, "Eastbrook", published="2026-05-20",
        gone="2026-06-01", distance=46)
    add(con, "new", "Xbox Series S 512GB – HDMI port damaged", 135, "Stonebridge", distance=43)
    assert find_relist(con, "s", "new") is None


def test_gone_after_the_new_one_appeared_is_no_relist(con):
    add(con, "old", "Xbox Series S 512GB HDMI port damaged", 130, "Oakdale", published="2026-06-01", gone="2026-06-18")
    add(con, "new", "Xbox Series S 512GB HDMI port damaged", 130, "Oakdale", published="2026-06-15")
    assert find_relist(con, "s", "new") is None


def test_same_photo_is_strong_signal(con):
    add(con, "old", "Console, works", 200, "Hillcrest", image="https://img.example.invalid/a.jpg",
        published="2026-05-01", gone="2026-06-01")
    add(con, "new", "Xbox Series S for sale", 150, "Lakeview", image="https://img.example.invalid/a.jpg")
    assert find_relist(con, "s", "new")["by"] == "photo"


def test_other_source_does_not_count(con):
    add(con, "old", "Xbox Series S 512GB HDMI port damaged", 130, "Oakdale", source="other",
        image="https://img.example.invalid/a.jpg", published="2026-05-20", gone="2026-06-01")
    add(con, "new", "Xbox Series S 512GB HDMI port damaged", 130, "Oakdale", image="https://img.example.invalid/a.jpg")
    assert find_relist(con, "s", "new") is None


def test_price_and_title_must_be_close(con):
    add(con, "old", "Xbox Series S 512GB HDMI port damaged", 200, "Oakdale", published="2026-05-20", gone="2026-06-01")
    add(con, "new", "Xbox Series S 512GB HDMI port damaged", 130, "Oakdale")
    assert find_relist(con, "s", "new") is None
    add(con, "old2", "Xbox Series S carbon black 1TB like new boxed", 130, "Oakdale", published="2026-05-20",
        gone="2026-06-01")
    assert find_relist(con, "s", "new") is None


def test_old_database_gets_location_column(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript(history.SCHEMA)   # schema before the location column
    assert "location" not in [r[1] for r in c.execute("PRAGMA table_info(listing)")]
    c.close()
    con = history.connect(db)
    assert "location" in [r[1] for r in con.execute("PRAGMA table_info(listing)")]
    con.close()
