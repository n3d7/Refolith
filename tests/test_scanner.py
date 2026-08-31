import os
import errno
from pathlib import Path

from refolith import scanner


def test_scanner_ignores_non_python_and_excluded_directories(tmp_path):
    for directory in (".git", ".venv", "venv", "__pycache__", "build", "dist"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "hidden.py").write_text("pass\n")
    (tmp_path / "package").mkdir()
    (tmp_path / "package" / "yes.py").write_text("pass\n")
    (tmp_path / "no.txt").write_text("ignored")
    result = scanner.scan_python_files(tmp_path)
    assert [path.relative_to(tmp_path).as_posix() for path in result.paths] == [
        "package/yes.py"
    ]


def test_scanner_skips_symlinks_large_files_and_special_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("pass\n")
    (root / "linked.py").symlink_to(outside / "secret.py")
    (root / "linked_dir").symlink_to(outside, target_is_directory=True)
    (root / "cycle").symlink_to(root, target_is_directory=True)
    (root / "big.py").write_bytes(b" " * 21)
    os.mkfifo(root / "pipe.py")
    (root / "ok.py").write_text("pass\n")
    result = scanner.scan_python_files(root, max_file_size=20)
    assert [path.name for path in result.paths] == ["ok.py"]
    assert any(issue.path == "big.py" for issue in result.issues)
    assert any(issue.path == "pipe.py" for issue in result.issues)


def test_scanner_reports_unreadable_directory(tmp_path, monkeypatch):
    directory = tmp_path / "locked"
    directory.mkdir()
    original = os.open

    def denied(path, *args, **kwargs):
        if os.fspath(path) == "locked":
            raise PermissionError(errno.EACCES, "denied", "locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", denied)
    result = scanner.scan_python_files(tmp_path)
    assert result.paths == []
    assert any(issue.path == "locked" for issue in result.issues)


def test_scanner_does_not_traverse_swapped_directory(tmp_path, monkeypatch):
    root = tmp_path / "root"
    package = root / "package"
    package.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external.py").write_text("pass\n")
    original_iterdir = Path.iterdir
    original_os_open = os.open
    swapped = False

    def swap():
        nonlocal swapped
        if not swapped:
            swapped = True
            package.rename(root / "old_package")
            package.symlink_to(outside, target_is_directory=True)

    def iterdir(path):
        if path == package:
            swap()
        return original_iterdir(path)

    def descriptor_open(path, *args, **kwargs):
        if os.fspath(path) == "package":
            swap()
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    monkeypatch.setattr(os, "open", descriptor_open)
    assert scanner.scan_python_files(root).paths == []
    assert swapped
