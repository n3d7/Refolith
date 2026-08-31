import pytest

from refolith import database, errors, models, python_parser


def test_persistence_foreign_keys_and_cascade(database, tmp_path):
    connection = database
    from refolith.database import connect_database, remove_repository, save_index

    info = models.RepositoryInfo(tmp_path, "example", "abc123")
    parsed = python_parser.parse_python("import os\ndef hello(): pass\n", "main.py", "main")
    repo_id = save_index(connection, info, [parsed])
    database_path = connection.execute("PRAGMA database_list").fetchone()[2]
    reopened = connect_database(database_path)
    try:
        row = reopened.execute("SELECT * FROM repositories").fetchone()
        assert row["id"] == repo_id
        assert row["path"] == str(tmp_path)
        assert row["head"] == "abc123"
        assert row["indexed_at"]
        assert reopened.execute("SELECT qualified_name FROM symbols").fetchone()[0] == "main.hello"
        assert reopened.execute("SELECT module FROM imports").fetchone()[0] == "os"
        assert reopened.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        remove_repository(reopened, repo_id)
        for table in ("repositories", "files", "symbols", "imports"):
            assert reopened.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        reopened.close()


def test_failed_replacement_rolls_back_whole_index(database, tmp_path):
    from refolith.database import save_index

    info = models.RepositoryInfo(tmp_path, "example", "old-head")
    original = python_parser.parse_python("def original(): pass\n", "old.py", "old")
    repo_id = save_index(database, info, [original])
    invalid = models.ParsedFile("new.py", "new", symbols=[
        models.Symbol("bad", "new.bad", "invalid_kind", 1, 1)
    ])
    with pytest.raises(errors.DatabaseError):
        save_index(database, models.RepositoryInfo(tmp_path, "changed", "new-head"), [invalid])
    assert database.execute("SELECT qualified_name FROM symbols").fetchone()[0] == "old.original"
    row = database.execute("SELECT * FROM repositories").fetchone()
    assert (row["id"], row["name"], row["head"]) == (repo_id, "example", "old-head")


def test_unknown_schema_version_is_rejected(database):
    from refolith.database import connect_database

    path = database.execute("PRAGMA database_list").fetchone()[2]
    with database:
        database.execute("UPDATE metadata SET value = '999' WHERE key = 'schema_version'")
    with pytest.raises(errors.DatabaseError, match="schema version"):
        connect_database(path)
