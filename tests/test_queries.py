import pytest

from refolith import database as persistence
from refolith import errors, models, python_parser, queries


def test_search_is_literal_and_can_be_scoped(database, tmp_path):
    for name in ("one", "two"):
        persistence.save_index(database, models.RepositoryInfo(tmp_path / name, name, None), [
            python_parser.parse_python("def needle(): pass\n", "work.py", "work")
        ])
    assert len(queries.find_symbols(database, "NEEDLE")) == 2
    repo = queries.resolve_repository(database, "one")
    matches = queries.find_symbols(database, "work.needle", repo.id)
    assert [match.repository_name for match in matches] == ["one"]
    assert queries.find_symbols(database, "' OR 1=1 --") == []
    assert queries.find_symbols(database, "%") == []
    assert queries.find_symbols(database, "_") == []
    assert queries.resolve_repository(database, str(repo.id)) == repo
    assert queries.resolve_repository(database, str(tmp_path / "one")) == repo
    assert queries.show_symbols(database, repo.id, "needle") == matches
    with pytest.raises(errors.QueryError):
        queries.find_symbols(database, "  ")


def test_ambiguous_names_and_missing_entries_have_clear_errors(database, tmp_path):
    for path in (tmp_path / "one" / "same", tmp_path / "two" / "same"):
        persistence.save_index(database, models.RepositoryInfo(path, "same", None), [])
    with pytest.raises(errors.QueryError, match="[Aa]mbiguous"):
        queries.resolve_repository(database, "same")
    with pytest.raises(errors.QueryError, match="[Nn]o repository"):
        queries.resolve_repository(database, "missing")
    repo_id = queries.list_repositories(database)[0].id
    with pytest.raises(errors.QueryError):
        queries.show_symbols(database, repo_id, "missing")
    with pytest.raises(errors.QueryError):
        queries.list_imports(database, repo_id, "../outside.py")
