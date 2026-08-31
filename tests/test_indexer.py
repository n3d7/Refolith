from pathlib import Path
import os
import subprocess

import pytest

from refolith import errors, indexer, queries
from refolith import python_parser


def test_end_to_end_isolates_parse_errors_and_never_executes(git_repo, database):
    marker = git_repo / "executed"
    package = git_repo / "src" / "package"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from .service import Service\n")
    (package / "service.py").write_text(
        f"raise RuntimeError('must not run')\n"
        f"open({str(marker)!r}, 'w').write('bad')\n"
        "class Service:\n    def run(self): pass\n"
    )
    (git_repo / "broken.py").write_text("def broken(:\n")
    result = indexer.index_repository(database, git_repo)
    assert (result.file_count, result.symbol_count, result.import_count) == (3, 2, 1)
    assert any(issue.path == "broken.py" for issue in result.issues)
    assert not marker.exists()
    files = queries.list_files(database, result.repository_id)
    assert [(file.path, file.module, file.status) for file in files] == [
        ("broken.py", "broken", "parse_error"),
        ("src/package/__init__.py", "package", "ok"),
        ("src/package/service.py", "package.service", "ok"),
    ]


def test_reindex_replaces_stale_symbols_and_deleted_files(git_repo, database):
    source = git_repo / "work.py"
    source.write_text("import os\ndef old(): pass\n")
    deleted = git_repo / "gone.py"
    deleted.write_text("def gone(): pass\n")
    first = indexer.index_repository(database, git_repo)
    source.write_text("from pathlib import Path\ndef current(): pass\n")
    deleted.unlink()
    second = indexer.reindex_repository(database, str(first.repository_id))
    assert second.repository_id == first.repository_id
    assert queries.find_symbols(database, "old") == []
    assert queries.find_symbols(database, "gone") == []
    assert [s.qualified_name for s in queries.find_symbols(database, "current")] == ["work.current"]
    assert [i.name for i in queries.list_imports(database, first.repository_id, "work.py")] == ["Path"]
    assert len(queries.list_repositories(database)) == 1


def test_unreadable_and_invalid_encoding_files_do_not_abort(git_repo, database, monkeypatch):
    (git_repo / "good.py").write_text("def good(): pass\n")
    (git_repo / "bad_encoding.py").write_bytes(b"\xff\xfe\xfd")
    unreadable = git_repo / "denied.py"
    unreadable.write_text("def secret(): pass\n")
    original = os.open

    def denied(path, *args, **kwargs):
        if os.fspath(path) == "denied.py":
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", denied)
    result = indexer.index_repository(database, git_repo)
    assert result.symbol_count == 1
    assert {issue.path for issue in result.issues} == {"bad_encoding.py", "denied.py"}


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses filesystem permission checks")
def test_indexing_only_requires_search_permission_on_ancestors(git_repo, database):
    (git_repo / "good.py").write_text("def good(): pass\n")
    parent = git_repo.parent
    original_mode = parent.stat().st_mode
    parent.chmod(0o111)
    try:
        result = indexer.index_repository(database, git_repo)
        assert result.symbol_count == 1
        assert result.issues == []
    finally:
        parent.chmod(original_mode)


def test_encoding_cookie_is_respected(git_repo, database):
    (git_repo / "latin.py").write_bytes(b"# coding: latin-1\n# caf\xe9\ndef hello(): pass\n")
    result = indexer.index_repository(database, git_repo)
    assert result.symbol_count == 1
    assert result.issues == []


def test_non_utf8_filenames_do_not_abort_reindex(git_repo, database):
    source = git_repo / "good.py"
    source.write_text("def old(): pass\n")
    first = indexer.index_repository(database, git_repo)
    source.write_text("def current(): pass\n")
    (git_repo / os.fsdecode(b"bad\xff.py")).write_text("def bad(): pass\n")
    directory = git_repo / os.fsdecode(b"bad\xfe")
    directory.mkdir()
    (directory / "nested.py").write_text("def nested(): pass\n")

    result = indexer.reindex_repository(database, str(first.repository_id))

    assert result.repository_id == first.repository_id
    assert [symbol.name for symbol in queries.find_symbols(database, "current")] == ["current"]
    assert queries.find_symbols(database, "old") == []
    assert [file.path for file in queries.list_files(database, result.repository_id)] == ["good.py"]
    assert len(result.issues) == 2
    assert all("UTF-8" in issue.reason for issue in result.issues)


def test_parser_memory_error_does_not_abort_other_files(git_repo, database, monkeypatch):
    (git_repo / "exhausted.py").write_text("values = [0]\n")
    (git_repo / "good.py").write_text("def good(): pass\n")
    original = python_parser.ast.parse

    def memory_limited_parse(source, filename="<unknown>", *args, **kwargs):
        if filename == "exhausted.py":
            raise MemoryError
        return original(source, filename, *args, **kwargs)

    monkeypatch.setattr(python_parser.ast, "parse", memory_limited_parse)
    result = indexer.index_repository(database, git_repo)

    assert result.symbol_count == 1
    assert [symbol.name for symbol in queries.find_symbols(database, "good")] == ["good"]
    assert len(result.issues) == 1
    assert result.issues[0].path == "exhausted.py"
    assert "memory" in result.issues[0].reason.lower()
    assert queries.list_files(database, result.repository_id)[0].status == "parse_error"


def test_failed_reindex_preserves_previous_index(git_repo, database):
    (git_repo / "work.py").write_text("def kept(): pass\n")
    first = indexer.index_repository(database, git_repo)
    git_repo.rename(git_repo.with_name("moved"))
    with pytest.raises(errors.RepositoryError):
        indexer.reindex_repository(database, str(first.repository_id))
    assert len(queries.find_symbols(database, "kept")) == 1


def test_reindex_does_not_switch_to_an_enclosing_repository(git_repo, database, monkeypatch):
    (git_repo / "work.py").write_text("def inside(): pass\n")
    first = indexer.index_repository(database, git_repo)
    parent = git_repo.parent
    subprocess.run(["git", "init", "--quiet", str(parent)], check=True)
    (parent / "outside.py").write_text("def outside(): pass\n")
    original = indexer.inspect_repository
    marker = git_repo / ".git"

    def remove_marker_after_inspection(path):
        info = original(path)
        if marker.exists():
            marker.rename(git_repo / ".old-git")
        return info

    monkeypatch.setattr(indexer, "inspect_repository", remove_marker_after_inspection)
    result = indexer.reindex_repository(database, str(first.repository_id))

    assert result.repository_id == first.repository_id
    assert len(queries.list_repositories(database)) == 1
    assert queries.find_symbols(database, "outside") == []


@pytest.mark.parametrize("swap_directory", [False, True])
def test_source_reader_rejects_symlink_swap(tmp_path, monkeypatch, swap_directory):
    root = tmp_path / "root"
    package = root / "package"
    package.mkdir(parents=True)
    source = package / "work.py"
    source.write_text("def inside(): pass\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "work.py").write_text("def outside_marker(): pass\n")
    original_path_open = Path.open
    original_os_open = os.open
    swapped = False

    def swap():
        nonlocal swapped
        if swapped:
            return
        swapped = True
        if swap_directory:
            package.rename(root / "old_package")
            package.symlink_to(outside, target_is_directory=True)
        else:
            source.unlink()
            source.symlink_to(outside / "work.py")

    def path_open(path, *args, **kwargs):
        if path == source:
            swap()
        return original_path_open(path, *args, **kwargs)

    def descriptor_open(path, *args, **kwargs):
        target = "package" if swap_directory else "work.py"
        if os.fspath(path) == target:
            swap()
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", path_open)
    monkeypatch.setattr(os, "open", descriptor_open)
    with pytest.raises(OSError):
        indexer._read_source(root, source)
    assert swapped
