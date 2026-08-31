from refolith import python_parser


def test_symbols_keep_lexical_scope_and_line_ranges():
    source = (
        "class Worker:\n"
        "    def run(self):\n"
        "        def nested():\n"
        "            pass\n"
        "    async def fetch(self):\n"
        "        pass\n"
        "def ordinary():\n"
        "    pass\n"
        "async def background():\n"
        "    pass\n"
    )
    parsed = python_parser.parse_python(source, "package/work.py", "package.work")
    assert parsed.status == "ok"
    assert [(s.qualified_name, s.kind, s.start_line, s.end_line) for s in parsed.symbols] == [
        ("package.work.Worker", "class", 1, 6),
        ("package.work.Worker.run", "method", 2, 4),
        ("package.work.Worker.run.nested", "function", 3, 4),
        ("package.work.Worker.fetch", "async_method", 5, 6),
        ("package.work.ordinary", "function", 7, 8),
        ("package.work.background", "async_function", 9, 10),
    ]


def test_imports_aliases_and_relative_levels():
    parsed = python_parser.parse_python(
        "import os, pathlib as p\nfrom ..helpers import Thing as T\n"
        "from . import sibling\nfrom math import *\n",
        "package/mod.py", "package.mod",
    )
    assert [(i.module, i.name, i.alias, i.level, i.start_line) for i in parsed.imports] == [
        ("os", None, None, 0, 1),
        ("pathlib", None, "p", 0, 1),
        ("helpers", "Thing", "T", 2, 2),
        (None, "sibling", None, 1, 3),
        ("math", "*", None, 0, 4),
    ]


def test_syntax_error_is_returned_as_a_file_failure():
    parsed = python_parser.parse_python("def broken(:\n", "bad.py", "bad")
    assert parsed.status == "parse_error"
    assert parsed.error
    assert parsed.symbols == []
    assert parsed.imports == []


def test_parser_does_not_execute_source(tmp_path):
    marker = tmp_path / "executed"
    source = f"open({str(marker)!r}, 'w').write('bad')\ndef safe(): pass\n"
    parsed = python_parser.parse_python(source, "unsafe.py", "unsafe")
    assert parsed.symbols[0].name == "safe"
    assert not marker.exists()


def test_parser_does_not_emit_raw_warnings(recwarn):
    parsed = python_parser.parse_python('text = "\\q"\n', "unsafe\x1b[31m.py", "unsafe")
    assert parsed.status == "ok"
    assert list(recwarn) == []
