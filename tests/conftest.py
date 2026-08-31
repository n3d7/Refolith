import os
import subprocess

import pytest


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    for key in os.environ:
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    root = tmp_path / "sample"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Refolith Tests"], check=True
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "tests@example.invalid"],
        check=True,
    )
    return root


@pytest.fixture
def database(tmp_path):
    from refolith.database import connect_database

    connection = connect_database(tmp_path / "state" / "refolith.sqlite3")
    yield connection
    connection.close()
