class RefolithError(Exception):
    """An expected error that the CLI can present without a traceback."""


class RepositoryError(RefolithError):
    pass


class IndexingError(RefolithError):
    pass


class DatabaseError(RefolithError):
    pass


class QueryError(RefolithError):
    pass
