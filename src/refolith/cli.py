import argparse
from contextlib import closing
import os
from pathlib import PurePosixPath
import sqlite3
import sys

from refolith import database, indexer, queries
from refolith.config import database_path
from refolith.errors import RefolithError
from refolith.models import FileRecord, IndexResult, SymbolMatch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refolith", description="Inspect Python symbols and imports in local Git repositories."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="index a local Git repository immediately")
    add.add_argument("path", metavar="PATH")
    commands.add_parser("repos", help="list indexed repositories")
    tree = commands.add_parser("tree", help="show the indexed Python file tree")
    tree.add_argument("repo", metavar="REPO")
    find = commands.add_parser("find", help="search symbol names by literal substring")
    find.add_argument("query", metavar="QUERY")
    find.add_argument("--repo", metavar="REPO", help="restrict search to one repository")
    show = commands.add_parser("show", help="show symbols with an exact name or qualified name")
    show.add_argument("repo", metavar="REPO")
    show.add_argument("symbol", metavar="SYMBOL")
    imports = commands.add_parser("imports", help="show imports in an indexed file")
    imports.add_argument("repo", metavar="REPO")
    imports.add_argument("file", metavar="FILE", help="repository-relative path, using /")
    reindex = commands.add_parser("reindex", help="replace an existing repository index")
    reindex.add_argument("repo", metavar="REPO")
    remove = commands.add_parser("remove", help="remove an index; leave source files untouched")
    remove.add_argument("repo", metavar="REPO")
    parser.epilog = "REPO accepts an ID, a unique name, or the repository root path."
    return parser


def _safe(value: object) -> str:
    return "".join(
        character if character.isprintable() else f"\\x{ord(character):02x}"
        for character in str(value)
    )


def _print_index_result(result: IndexResult) -> None:
    print(
        f"Indexed repository {result.repository_id}: {result.file_count} files, "
        f"{result.symbol_count} symbols, {result.import_count} imports."
    )
    for issue in result.issues:
        print(f"warning: {_safe(issue.path)}: {_safe(issue.reason)}", file=sys.stderr)


def _print_tree(files: list[FileRecord]) -> None:
    seen = set()
    for file in files:
        parts = PurePosixPath(file.path).parts
        for depth in range(len(parts) - 1):
            directory = parts[:depth + 1]
            if directory not in seen:
                print("  " * (depth + 1) + _safe(parts[depth]) + "/")
                seen.add(directory)
        note = f" [{file.status}: {_safe(file.error)}]" if file.status != "ok" else ""
        print("  " * len(parts) + _safe(parts[-1]) + note)
    if not files:
        print("  No indexed Python files.")


def _print_symbols(symbols: list[SymbolMatch]) -> None:
    for symbol in symbols:
        lines = str(symbol.start_line)
        if symbol.end_line is not None and symbol.end_line != symbol.start_line:
            lines += f"-{symbol.end_line}"
        print(
            f"{_safe(symbol.repository_name)} [{symbol.repository_id}] "
            f"{_safe(symbol.file_path)}:{lines}  {symbol.kind}  "
            f"{_safe(symbol.qualified_name)}"
        )
    if not symbols:
        print("No matching symbols.")


def main(argv: list[str] | None = None) -> int:
    try:
        try:
            return _run(argv)
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
    except BrokenPipeError:
        descriptor = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(descriptor, sys.stdout.fileno())
            os.dup2(descriptor, sys.stderr.fileno())
        finally:
            os.close(descriptor)
        return 1


def _run(argv: list[str] | None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        with closing(database.connect_database(database_path())) as connection:
            if arguments.command == "add":
                _print_index_result(indexer.index_repository(connection, arguments.path))
            elif arguments.command == "repos":
                repositories = queries.list_repositories(connection)
                for repository in repositories:
                    print(
                        f"{repository.id}  {_safe(repository.name)}  "
                        f"HEAD {_safe(repository.head or '(no commits)')}  "
                        f"indexed {_safe(repository.indexed_at)}"
                    )
                    print(f"   {_safe(repository.path)}")
                if not repositories:
                    print("No indexed repositories. Run 'refolith add PATH' to add one.")
            elif arguments.command == "find":
                repository_id = None
                if arguments.repo is not None:
                    repository_id = queries.resolve_repository(connection, arguments.repo).id
                _print_symbols(queries.find_symbols(connection, arguments.query, repository_id))
            elif arguments.command == "reindex":
                _print_index_result(indexer.reindex_repository(connection, arguments.repo))
            else:
                repository = queries.resolve_repository(connection, arguments.repo)
                if arguments.command == "tree":
                    print(f"{_safe(repository.name)} [{repository.id}]/")
                    _print_tree(queries.list_files(connection, repository.id))
                elif arguments.command == "show":
                    _print_symbols(queries.show_symbols(connection, repository.id, arguments.symbol))
                elif arguments.command == "imports":
                    imports = queries.list_imports(connection, repository.id, arguments.file)
                    for item in imports:
                        if item.name is None:
                            statement = f"import {item.module}"
                        else:
                            module = "." * item.level + (item.module or "")
                            statement = f"from {module} import {item.name}"
                        if item.alias:
                            statement += f" as {item.alias}"
                        print(f"{item.start_line}: {_safe(statement)}")
                    if not imports:
                        print("No imports in this file.")
                elif arguments.command == "remove":
                    database.remove_repository(connection, repository.id)
                    print(f"Removed index for {_safe(repository.name)} [{repository.id}].")
    except (RefolithError, OSError, sqlite3.Error, ValueError) as error:
        print(f"error: {_safe(error)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    return 0
