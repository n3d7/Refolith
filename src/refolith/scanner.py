from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import stat

from refolith.errors import IndexingError
from refolith.models import ScanIssue, ScanResult


IGNORED_DIRECTORIES = {
    ".git", ".venv", "venv", "__pycache__", "build", "dist", ".refolith",
}
MAX_FILE_SIZE = 1024 * 1024


@contextmanager
def open_directory(path: Path) -> Iterator[int]:
    """Pin a directory without following links in any path component."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "fwalk"):
        raise IndexingError("Indexing requires Unix directory-descriptor support (Linux/macOS).")
    if not path.is_absolute() or ".." in path.parts:
        raise IndexingError("Expected an absolute directory path without '..'.")
    access = getattr(os, "O_PATH", getattr(os, "O_SEARCH", os.O_RDONLY))
    flags = access | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def scan_python_files(root: Path, max_file_size: int = MAX_FILE_SIZE) -> ScanResult:
    result = ScanResult()

    def on_error(error: OSError) -> None:
        result.issues.append(ScanIssue(str(error.filename or root), str(error)))

    try:
        with open_directory(root) as root_descriptor:
            for directory, subdirectories, filenames, descriptor in os.fwalk(
                ".", dir_fd=root_descriptor, follow_symlinks=False, onerror=on_error
            ):
                subdirectories[:] = sorted(
                    name for name in subdirectories if name not in IGNORED_DIRECTORIES
                )
                file_names = set(filenames)
                for name in subdirectories.copy() + sorted(filenames):
                    if name in IGNORED_DIRECTORIES:
                        continue
                    relative = Path(directory) / name
                    try:
                        name.encode("utf-8")
                    except UnicodeError:
                        result.issues.append(ScanIssue(relative.as_posix(), "path is not valid UTF-8"))
                        if name in subdirectories:
                            subdirectories.remove(name)
                        continue
                    try:
                        information = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                        if stat.S_ISLNK(information.st_mode):
                            result.issues.append(ScanIssue(relative.as_posix(), "skipped symlink"))
                            if name in subdirectories:
                                subdirectories.remove(name)
                        elif relative.suffix == ".py" and name in file_names:
                            if not stat.S_ISREG(information.st_mode):
                                result.issues.append(ScanIssue(relative.as_posix(), "not a regular file"))
                            elif information.st_size > max_file_size:
                                result.issues.append(ScanIssue(relative.as_posix(), "source file is too large"))
                            else:
                                result.paths.append(root / relative)
                    except OSError as error:
                        result.issues.append(ScanIssue(relative.as_posix(), str(error)))
    except OSError as error:
        raise IndexingError(f"Cannot scan repository: {root}: {error}") from error
    result.paths.sort()
    result.issues.sort(key=lambda issue: issue.path)
    return result
