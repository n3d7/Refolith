from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from refolith.errors import DatabaseError
from refolith.models import ParsedFile, RepositoryInfo


SCHEMA_VERSION = "1"
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS repositories (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        head TEXT,
        indexed_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        module TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('ok', 'parse_error', 'skipped')),
        error TEXT,
        UNIQUE (repository_id, path)
    )""",
    """CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN (
            'class', 'function', 'async_function', 'method', 'async_method'
        )),
        start_line INTEGER NOT NULL CHECK (start_line > 0),
        end_line INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
        module TEXT,
        name TEXT,
        alias TEXT,
        level INTEGER NOT NULL CHECK (level >= 0),
        start_line INTEGER NOT NULL CHECK (start_line > 0),
        end_line INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS symbols_file_id ON symbols(file_id)",
    "CREATE INDEX IF NOT EXISTS imports_file_id ON imports(file_id)",
)


def connect_database(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error as error:
        raise DatabaseError(f"Cannot open database: {error}") from error
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            version_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version_row is not None and version_row[0] != SCHEMA_VERSION:
                raise DatabaseError(
                    f"Unsupported database schema version {version_row[0]!r}; expected {SCHEMA_VERSION}."
                )
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute(
                "INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
    except (sqlite3.Error, DatabaseError) as error:
        connection.close()
        raise DatabaseError(f"Cannot initialize database: {error}") from error
    return connection


def save_index(
    connection: sqlite3.Connection, repository: RepositoryInfo, files: list[ParsedFile]
) -> int:
    indexed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with connection:
            connection.execute(
                """INSERT INTO repositories (path, name, head, indexed_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name, head = excluded.head, indexed_at = excluded.indexed_at""",
                (str(repository.path), repository.name, repository.head, indexed_at),
            )
            repository_row = connection.execute(
                "SELECT id FROM repositories WHERE path = ?", (str(repository.path),)
            ).fetchone()
            repository_id = repository_row[0]
            connection.execute("DELETE FROM files WHERE repository_id = ?", (repository_id,))
            for file in files:
                cursor = connection.execute(
                    """INSERT INTO files (repository_id, path, module, status, error)
                    VALUES (?, ?, ?, ?, ?)""",
                    (repository_id, file.path, file.module, file.status, file.error),
                )
                file_id = cursor.lastrowid
                connection.executemany(
                    """INSERT INTO symbols
                    (file_id, name, qualified_name, kind, start_line, end_line)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    [(file_id, symbol.name, symbol.qualified_name, symbol.kind,
                      symbol.start_line, symbol.end_line) for symbol in file.symbols],
                )
                connection.executemany(
                    """INSERT INTO imports
                    (file_id, module, name, alias, level, start_line, end_line)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [(file_id, imported.module, imported.name, imported.alias, imported.level,
                      imported.start_line, imported.end_line) for imported in file.imports],
                )
    except sqlite3.Error as error:
        raise DatabaseError(f"Could not save index; previous index retained: {error}") from error
    return repository_id


def remove_repository(connection: sqlite3.Connection, repository_id: int) -> None:
    try:
        with connection:
            connection.execute("DELETE FROM repositories WHERE id = ?", (repository_id,))
    except sqlite3.Error as error:
        raise DatabaseError(f"Could not remove repository: {error}") from error
