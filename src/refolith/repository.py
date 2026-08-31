import os
from pathlib import Path
import subprocess

from refolith.errors import RepositoryError
from refolith.models import RepositoryInfo


def _git(path: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
    })
    try:
        return subprocess.run(
            ["git", "--no-pager", "--no-replace-objects", "-C", str(path),
             "-c", "core.fsmonitor=false", *arguments],
            capture_output=True, env=environment,
            timeout=10, check=False,
        )
    except FileNotFoundError as error:
        raise RepositoryError("Git is not installed or is not on PATH.") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RepositoryError(f"Cannot inspect Git repository: {error}") from error


def inspect_repository(path: str | Path) -> RepositoryInfo:
    try:
        selected = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RepositoryError(f"Cannot access Git repository: {path}") from error
    try:
        str(selected).encode("utf-8")
    except UnicodeError as error:
        raise RepositoryError("Repository paths must be valid UTF-8 for SQLite storage.") from error
    if not selected.is_dir():
        raise RepositoryError(f"Not a Git repository directory: {selected}")

    expected_root = None
    for directory in (selected, *selected.parents):
        marker = directory / ".git"
        if marker.is_symlink():
            raise RepositoryError("The repository's .git marker must not be a symlink.")
        if marker.exists():
            expected_root = directory
            break
    if expected_root is None:
        raise RepositoryError(f"Not a Git repository: {selected}")

    result = _git(selected, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise RepositoryError(f"Not a usable Git repository: {selected}. {detail}")
    root = Path(os.fsdecode(result.stdout.removesuffix(b"\n"))).resolve()
    if root != expected_root:
        raise RepositoryError("Git repository root was redirected outside the selected working tree.")
    head_result = _git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    if head_result.returncode == 0:
        head = head_result.stdout.decode("ascii").strip()
    elif _git(root, "symbolic-ref", "--quiet", "HEAD").returncode == 0:
        head = None
    else:
        raise RepositoryError(f"Cannot determine HEAD for Git repository: {root}")
    return RepositoryInfo(path=root, name=root.name, head=head)
