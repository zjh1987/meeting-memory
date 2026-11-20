from app.storage import db


def test_init_db_creates_tables_and_seed_project(cfg):
    conn = db.connect(cfg.db_path)
    try:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"project", "meeting", "action_item", "relation"} <= names
        seed = conn.execute("SELECT id FROM project WHERE name='未归类'").fetchone()
        assert seed is not None
    finally:
        conn.close()


def test_init_db_is_idempotent(cfg):
    db.init_db(cfg.db_path, db.MIGRATIONS_DIR)
    db.init_db(cfg.db_path, db.MIGRATIONS_DIR)
    conn = db.connect(cfg.db_path)
    row = conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()
    assert row["n"] == 1
    conn.close()
