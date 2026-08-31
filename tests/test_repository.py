import os
import subprocess

import pytest

from refolith import errors, repository


def test_repository_root_and_head(git_repo):
    child = git_repo / "package"
    child.mkdir()
    info = repository.inspect_repository(child)
    assert info.path == git_repo
    assert info.name == "sample"
    assert info.head is None

    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "--quiet", "--allow-empty", "-m", "test"],
        check=True,
    )
    expected = subprocess.check_output(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"], text=True
    ).strip()
    assert repository.inspect_repository(child).head == expected


def test_invalid_repository(tmp_path):
    with pytest.raises(errors.RepositoryError, match="Git repository"):
        repository.inspect_repository(tmp_path)
    with pytest.raises(errors.RepositoryError):
        repository.inspect_repository(tmp_path / "missing")


def test_git_environment_cannot_redirect_repository(git_repo, tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_DIR", str(git_repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(git_repo))
    with pytest.raises(errors.RepositoryError):
        repository.inspect_repository(plain)


def test_repository_root_preserves_newline_characters(git_repo):
    renamed = git_repo.with_name("sample\n")
    git_repo.rename(renamed)
    assert repository.inspect_repository(renamed).path == renamed


def test_non_utf8_repository_path_is_rejected_clearly(git_repo):
    renamed = git_repo.with_name(os.fsdecode(b"repo\xff"))
    git_repo.rename(renamed)
    with pytest.raises(errors.RepositoryError, match="UTF-8"):
        repository.inspect_repository(renamed)


def test_git_config_cannot_redirect_to_another_working_tree(git_repo, tmp_path):
    outside = tmp_path / "outside"
    subprocess.run(["git", "init", "--quiet", str(outside)], check=True)
    subprocess.run(
        ["git", "-C", str(git_repo), "config", "core.worktree", str(outside)], check=True
    )
    with pytest.raises(errors.RepositoryError, match="root"):
        repository.inspect_repository(git_repo)
