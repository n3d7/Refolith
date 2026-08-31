import os
from pathlib import Path

from refolith.errors import RefolithError


def database_path() -> Path:
    try:
        home = Path(os.environ.get("REFOLITH_HOME", "~/.refolith")).expanduser()
    except RuntimeError as error:
        raise RefolithError(f"Cannot resolve the state directory: {error}") from error
    return home / "refolith.sqlite3"
