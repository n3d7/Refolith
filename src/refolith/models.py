from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RepositoryInfo:
    path: Path
    name: str
    head: str | None


@dataclass
class Repository:
    id: int
    path: Path
    name: str
    head: str | None
    indexed_at: str


@dataclass
class Symbol:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int | None


@dataclass
class Import:
    module: str | None
    name: str | None
    alias: str | None
    level: int
    start_line: int
    end_line: int | None


@dataclass
class ParsedFile:
    path: str
    module: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None


@dataclass
class FileRecord:
    id: int
    path: str
    module: str
    status: str
    error: str | None


@dataclass
class SymbolMatch:
    repository_id: int
    repository_name: str
    file_path: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int | None


@dataclass
class ScanIssue:
    path: str
    reason: str


@dataclass
class ScanResult:
    paths: list[Path] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)


@dataclass
class IndexResult:
    repository_id: int
    file_count: int
    symbol_count: int
    import_count: int
    issues: list[ScanIssue]
