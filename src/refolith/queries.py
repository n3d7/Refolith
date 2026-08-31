from pathlib import Path, PurePosixPath
import sqlite3

from refolith.errors import QueryError
from refolith.models import FileRecord, Import, Repository, SymbolMatch


SYMBOL_COLUMNS = """
    SELECT r.id AS repository_id, r.name AS repository_name, f.path AS file_path,
           s.name, s.qualified_name, s.kind, s.start_line, s.end_line
    FROM symbols AS s
    JOIN files AS f ON f.id = s.file_id
    JOIN repositories AS r ON r.id = f.repository_id
"""


def list_repositories(connection: sqlite3.Connection) -> list[Repository]:
    rows = connection.execute("SELECT * FROM repositories ORDER BY name, path").fetchall()
    repositories = []
    for row in rows:
        repository = Repository(
            id=row["id"],
            path=Path(row["path"]),
            name=row["name"],
            head=row["head"],
            indexed_at=row["indexed_at"],
        )
        repositories.append(repository)
    return repositories


def resolve_repository(connection: sqlite3.Connection, selector: str) -> Repository:
    repositories = list_repositories(connection)
    for repository in repositories:
        if str(repository.id) == selector:
            return repository
    matches = [repository for repository in repositories if repository.name == selector]
    if len(matches) > 1:
        ids = ", ".join(str(repository.id) for repository in matches)
        raise QueryError(f"Ambiguous repository {selector!r}; use its path or one of these IDs: {ids}.")
    if matches:
        return matches[0]
    try:
        path = Path(selector).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise QueryError(f"Cannot resolve repository path {selector!r}: {error}") from error
    for repository in repositories:
        if repository.path == path:
            return repository
    raise QueryError(f"No repository matches {selector!r}. Run 'refolith repos' to list indexes.")


def list_files(connection: sqlite3.Connection, repository_id: int) -> list[FileRecord]:
    rows = connection.execute(
        "SELECT id, path, module, status, error FROM files WHERE repository_id = ? ORDER BY path",
        (repository_id,),
    ).fetchall()
    return [FileRecord(**dict(row)) for row in rows]


def find_symbols(
    connection: sqlite3.Connection, query: str, repository_id: int | None = None
) -> list[SymbolMatch]:
    if not query.strip():
        raise QueryError("Search query must not be empty.")
    rows = connection.execute(
        SYMBOL_COLUMNS + """
        WHERE (instr(lower(s.name), lower(?)) > 0
               OR instr(lower(s.qualified_name), lower(?)) > 0)
          AND (? IS NULL OR r.id = ?)
        ORDER BY r.name, r.id, f.path, s.start_line, s.id
        """,
        (query, query, repository_id, repository_id),
    ).fetchall()
    return [SymbolMatch(**dict(row)) for row in rows]


def show_symbols(
    connection: sqlite3.Connection, repository_id: int, symbol: str
) -> list[SymbolMatch]:
    rows = connection.execute(
        SYMBOL_COLUMNS + """
        WHERE r.id = ? AND (s.qualified_name = ? OR s.name = ?)
        ORDER BY f.path, s.start_line, s.id
        """,
        (repository_id, symbol, symbol),
    ).fetchall()
    if not rows:
        raise QueryError(f"No symbol matches {symbol!r}; use 'refolith find' for substring search.")
    return [SymbolMatch(**dict(row)) for row in rows]


def list_imports(
    connection: sqlite3.Connection, repository_id: int, file_path: str
) -> list[Import]:
    path = PurePosixPath(file_path)
    if path.is_absolute() or ".." in path.parts:
        raise QueryError("FILE must be a repository-relative path from 'refolith tree'.")
    file = connection.execute(
        "SELECT id, status, error FROM files WHERE repository_id = ? AND path = ?",
        (repository_id, path.as_posix()),
    ).fetchone()
    if file is None:
        raise QueryError(f"No indexed file matches {file_path!r}.")
    if file["status"] != "ok":
        raise QueryError(f"File was not parsed: {file_path}: {file['error']}")
    rows = connection.execute(
        """SELECT module, name, alias, level, start_line, end_line
        FROM imports WHERE file_id = ? ORDER BY start_line, id""", (file["id"],)
    ).fetchall()
    return [Import(**dict(row)) for row in rows]
