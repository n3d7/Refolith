# Refolith

Refolith v0.1 is a small CLI that indexes **local Python Git repositories** and
lets you inspect their files, symbols, and imports. It reads Python source with
the standard-library `ast` parser and stores the results in SQLite. Indexed code
is never imported or executed. There are no runtime dependencies.

## Install

Requires Python 3.11 or newer, Git on `PATH`, and Linux/macOS for indexing.
Directory-descriptor support is required to prevent symlink-swap races.
From this checkout:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
refolith --help
```

For an installation without pytest, use `python -m pip install .` instead.
Both `refolith` and `python -m refolith` run the same CLI.

## Commands

```sh
refolith add /path/to/my-project
refolith repos
refolith tree my-project
refolith find Worker
refolith find run --repo my-project
refolith show my-project Worker
refolith show my-project package.worker.Worker.run
refolith imports my-project src/package/worker.py
refolith reindex my-project
refolith remove my-project
```

- `add` accepts a repository root or a directory within it and indexes immediately.
  Repeating `add` on the same root refreshes its existing index.
- `REPO` accepts a numeric ID from `repos`, a unique repository name, or its root
  path. IDs take priority over names; use an ID or path for duplicate names.
- `tree` shows indexed Python files, including recorded read/parse failures.
- `find` is a literal substring search on names and qualified names. ASCII letters
  are matched case-insensitively; `%` and `_` are ordinary search characters.
- `show` lists kinds, qualified names, paths, and source line ranges for all exact
  short-name or qualified-name matches. It does not print source text.
- `imports` takes a repository-relative file path using `/` and displays imports,
  imported names, aliases, and relative levels. It does not resolve imports.
- `reindex` fully replaces stored files, symbols, and imports in one transaction.
  A fatal failure preserves the previous index. Individual read/parse failures
  are recorded and do not stop other files from being indexed.
- `remove` deletes only the SQLite index; it never deletes the repository.

State lives in `~/.refolith/refolith.sqlite3`. Set `REFOLITH_HOME` to use a
different state directory, for example:

```sh
REFOLITH_HOME=/tmp/refolith-demo refolith repos
```

Commands return `0` on success (including a completed index with file warnings),
`1` for an operational error, and `2` for invalid CLI arguments. Warnings and
errors go to stderr. Use `tree` to inspect persisted file failures.

## Code and data flow

```text
cli → indexer → repository → scanner → python_parser → database
cli → queries → SQLite

repositories → files → symbols
                    → imports
```

Read the core modules in this order:

| File in `src/refolith/` | Responsibility |
| --- | --- |
| `cli.py` | Parse arguments and print results/errors. |
| `repository.py` | Validate Git working trees and read their root and HEAD. |
| `scanner.py` | Discover `.py` paths; use directory descriptors for safe traversal. |
| `python_parser.py` | Extract definitions and imports from source text with `ast`. |
| `models.py` | Plain dataclasses shared between modules. |
| `database.py` | Visible SQLite schema, transactions, persistence, deletion. |
| `indexer.py` | Read/decode files and coordinate indexing and reindexing. |
| `queries.py` | Read stored data without depending on argparse. |
| `config.py`, `errors.py` | State location and expected application errors. |
| `__main__.py` | Entry point for `python -m refolith`. |

The database has `metadata`, `repositories`, `files`, `symbols`, and `imports`
tables with foreign keys and cascading deletion. Schema version 1 is checked on
open; v0.1 does not include schema migrations. Source text is not stored.

## Limits of v0.1

- Python only: classes, functions, async functions, methods, async methods, and
  imports. No call graph, type inference, dynamic definitions, or runtime analysis.
- The parser uses the syntax supported by the Python interpreter running Refolith.
  Definition line ranges start at `class`, `def`, or `async def`, not decorators.
- Module names come from paths: a leading `src/` is removed, and
  `package/__init__.py` becomes `package`. A root `__init__.py` keeps that name.
  Custom import roots and package configuration are not interpreted.
- The current working tree is read, including untracked files. HEAD is metadata;
  it is not a guarantee that indexed content matches that commit. Files changing
  during indexing may produce an inconsistent source snapshot; no watcher or
  incremental indexing is included.
- The scanner skips symlinks, special files, files larger than 1 MiB, and these
  directories: `.git`, `.venv`, `venv`, `__pycache__`, `build`, `dist`, `.refolith`.
  It does not interpret `.gitignore`. Discovery skips are reported as warnings;
  they are not stored as indexed file rows.
- Repository paths must be valid UTF-8. Files and directories with unsupported
  filename bytes are skipped with warnings so other files can still be indexed.
- Bare repositories are unsupported. Queries use the last stored index until
  `add` or `reindex` is run again. Large indexes are held in memory before saving.
  Recoverable parser memory errors are recorded per file, but there is no total
  memory quota or isolation from an operating-system out-of-memory termination.
- Git administrative metadata and the local state directory are not sandboxed.
  Git may follow its own configuration, ref, and worktree metadata indirections
  outside the source tree. Use trusted Git metadata and local state; the source
  scanner's no-follow protection does not extend to Git's internal file reads.
- Windows indexing is unsupported in v0.1 because the required Unix no-follow
  directory operations are unavailable. Linux is tested; macOS is not yet tested.
- Everything is local: no downloads, network services, telemetry, or MCP server.
  MCP support is a possible future milestone, not implemented functionality.

## Tests

After installing the `dev` extra in the virtual environment:

```sh
pytest
```

Tests use temporary repositories and SQLite databases. Any test commits use an
identity configured only in the temporary repository. The suite covers parsing,
scanner boundaries, persistence/rollback, end-to-end indexing, reindexing,
queries, and CLI success/error behavior.
