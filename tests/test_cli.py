import os
import subprocess
import sys

import pytest

from refolith import cli


def test_cli_commands_and_errors(git_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REFOLITH_HOME", str(tmp_path / "state"))
    source = git_repo / "work.py"
    source.write_text("from pathlib import Path as P\nclass Worker:\n    def run(self): pass\n")
    commands = [
        (["add", str(git_repo)], "Indexed"),
        (["repos"], "sample"),
        (["tree", "sample"], "work.py"),
        (["find", "Worker"], "work.Worker"),
        (["find", "run", "--repo", "sample"], "work.Worker.run"),
        (["show", "sample", "Worker"], "class"),
        (["imports", "sample", "work.py"], "from pathlib import Path as P"),
        (["reindex", "sample"], "Indexed"),
        (["remove", "sample"], "Removed"),
    ]
    for arguments, expected in commands:
        assert cli.main(arguments) == 0
        output = capsys.readouterr()
        assert expected in output.out
        assert output.err == ""
    assert source.exists()
    assert cli.main(["show", "sample", "Worker"]) == 1
    assert "error:" in capsys.readouterr().err
    assert cli.main(["add", str(tmp_path / "missing")]) == 1
    assert "error:" in capsys.readouterr().err


def test_module_help_and_argparse_error_do_not_create_state(tmp_path):
    state = tmp_path / "state"
    environment = dict(os.environ, REFOLITH_HOME=str(state))
    for arguments, expected_code in ((["--help"], 0), ([], 2), (["unknown"], 2)):
        result = subprocess.run(
            [sys.executable, "-m", "refolith", *arguments],
            capture_output=True, text=True, env=environment,
        )
        assert result.returncode == expected_code
        assert "usage:" in result.stdout + result.stderr
    assert not state.exists()


def test_terminal_controls_from_repository_paths_are_escaped(git_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REFOLITH_HOME", str(tmp_path / "state"))
    (git_repo / "unsafe\x1b[31m.py").write_text("def visible(): pass\n")
    assert cli.main(["add", str(git_repo)]) == 0
    assert cli.main(["tree", "sample"]) == 0
    assert cli.main(["find", "visible"]) == 0
    output = capsys.readouterr()
    assert "\x1b" not in output.out + output.err
    assert "visible" in output.out


def test_cli_reports_parse_failure_but_keeps_good_files(git_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REFOLITH_HOME", str(tmp_path / "state"))
    (git_repo / "good.py").write_text("def good(): pass\n")
    (git_repo / "broken.py").write_text("def broken(:\n")
    assert cli.main(["add", str(git_repo)]) == 0
    output = capsys.readouterr()
    assert "broken.py" in output.err
    assert cli.main(["imports", "sample", "broken.py"]) == 1
    assert "not parsed" in capsys.readouterr().err
    assert cli.main(["find", "good"]) == 0
    assert "good.good" in capsys.readouterr().out


@pytest.mark.parametrize("bad_home", [False, True])
def test_unknown_home_directory_is_a_clear_cli_error(tmp_path, bad_home):
    unknown = "~refolith_nonexistent_user_94622"
    environment = dict(os.environ, REFOLITH_HOME=unknown if bad_home else str(tmp_path / "state"))
    arguments = ["repos"] if bad_home else ["tree", unknown]
    result = subprocess.run(
        [sys.executable, "-m", "refolith", *arguments],
        capture_output=True, text=True, env=environment,
    )
    assert result.returncode == 1
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("arguments, stream", [
    (["repos"], "stdout"),
    (["--help"], "stdout"),
    (["unknown"], "stderr"),
    (["tree", "missing"], "stderr"),
])
def test_closed_output_pipe_exits_without_a_shutdown_traceback(tmp_path, arguments, stream):
    environment = dict(os.environ, REFOLITH_HOME=str(tmp_path / "state"))
    reader, writer = os.pipe()
    os.close(reader)
    streams = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, stream: writer}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "refolith", *arguments],
            **streams, text=True, env=environment,
        )
    finally:
        os.close(writer)
    assert result.returncode == 1
    assert result.stdout in (None, "")
    assert result.stderr in (None, "")
