import io
import os
from pathlib import Path
import sqlite3
import stat
import tokenize

from refolith.database import save_index
from refolith.errors import RepositoryError
from refolith.models import IndexResult, ParsedFile, RepositoryInfo, ScanIssue
from refolith.python_parser import parse_python
from refolith.queries import resolve_repository
from refolith.repository import inspect_repository
from refolith.scanner import MAX_FILE_SIZE, open_directory, scan_python_files


def module_name(relative_path: str) -> str:
    parts = list(Path(relative_path).with_suffix("").parts)
    if len(parts) > 1 and parts[0] == "src":
        parts.pop(0)
    if len(parts) > 1 and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _read_source(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    if ".." in relative.parts:
        raise OSError("source path is outside the repository")
    with open_directory(path.parent) as directory:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            file_stat = os.fstat(source.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise OSError("not a regular source file")
            if file_stat.st_size > MAX_FILE_SIZE:
                raise OSError("source file is too large")
            data = source.read(MAX_FILE_SIZE + 1)
    if len(data) > MAX_FILE_SIZE:
        raise OSError("source file is too large")
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding)


def index_repository(connection: sqlite3.Connection, path: str | Path) -> IndexResult:
    repository = inspect_repository(path)
    return _index_repository(connection, repository)


def _index_repository(connection: sqlite3.Connection, repository: RepositoryInfo) -> IndexResult:
    scan_result = scan_python_files(repository.path)
    files = []
    issues = list(scan_result.issues)
    for source_path in scan_result.paths:
        relative = source_path.relative_to(repository.path).as_posix()
        module = module_name(relative)
        try:
            source = _read_source(repository.path, source_path)
        except (OSError, UnicodeError, SyntaxError, LookupError) as error:
            parsed_file = ParsedFile(relative, module, status="skipped", error=str(error))
        else:
            parsed_file = parse_python(source, relative, module)
        files.append(parsed_file)
        if parsed_file.error:
            issues.append(ScanIssue(relative, parsed_file.error))
    repository_id = save_index(connection, repository, files)
    return IndexResult(
        repository_id=repository_id, file_count=len(files),
        symbol_count=sum(len(file.symbols) for file in files),
        import_count=sum(len(file.imports) for file in files), issues=issues,
    )


def reindex_repository(connection: sqlite3.Connection, selector: str) -> IndexResult:
    repository = resolve_repository(connection, selector)
    current = inspect_repository(repository.path)
    if current.path != repository.path:
        raise RepositoryError("Repository root changed; add its new path explicitly.")
    return _index_repository(connection, current)
