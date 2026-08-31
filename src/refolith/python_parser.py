import ast
import warnings

from refolith.models import Import, ParsedFile, Symbol


def parse_python(source: str, path: str, module: str) -> ParsedFile:
    parsed = ParsedFile(path=path, module=module)

    def visit(node: ast.AST, scope: tuple[str, ...], parent_kind: str) -> None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node, ast.ClassDef):
                kind = "class"
            else:
                if parent_kind == "class":
                    kind = "method"
                else:
                    kind = "function"
                if isinstance(node, ast.AsyncFunctionDef):
                    kind = "async_" + kind
            scope = (*scope, node.name)
            parsed.symbols.append(Symbol(
                name=node.name, qualified_name=".".join(scope), kind=kind,
                start_line=node.lineno, end_line=node.end_lineno,
            ))
            parent_kind = kind
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if isinstance(node, ast.ImportFrom):
                    imported_module = node.module
                    imported_name = alias.name
                    level = node.level
                else:
                    imported_module = alias.name
                    imported_name = None
                    level = 0
                parsed.imports.append(Import(
                    module=imported_module, name=imported_name,
                    alias=alias.asname, level=level,
                    start_line=node.lineno, end_line=node.end_lineno,
                ))
        for child in ast.iter_child_nodes(node):
            visit(child, scope, parent_kind)

    try:
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            tree = ast.parse(source, filename=path)
        visit(tree, (module,) if module else (), "module")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        if isinstance(error, MemoryError):
            message = "not enough memory to parse this file"
        elif isinstance(error, SyntaxError):
            message = f"{error.msg} (line {error.lineno})"
        else:
            message = str(error)
        return ParsedFile(path=path, module=module, status="parse_error", error=message)
    return parsed
