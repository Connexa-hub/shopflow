"""
Minimal, dependency-free replica of ruff's F401 (unused import) check.
Used only because ruff itself can't be installed in this offline sandbox —
this is NOT a replacement for running real ruff in CI, just a local sanity
check so we don't ship the same class of bug twice in a row.
"""
import ast
import sys
from pathlib import Path


def find_unused_imports(path: Path) -> list[str]:
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))

    imported_names: dict[str, int] = {}  # name -> lineno
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue  # compiler directives, never flagged by ruff/pyflakes
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                imported_names[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                name = alias.asname or alias.name
                imported_names[name] = node.lineno

    # Respect inline `# noqa` / `# noqa: F401` suppression comments, same as ruff.
    imported_names = {
        name: lineno
        for name, lineno in imported_names.items()
        if "noqa" not in lines[lineno - 1].lower()
    }

    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            # covers `module.attr` usage where `module` is the Name node anyway,
            # but walk already visits the Name inside Attribute.value separately.
            pass

    # __all__ exports count as "used"
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant):
                                used_names.add(elt.value)

    unused = [
        f"{path}:{lineno}: '{name}' imported but never used"
        for name, lineno in imported_names.items()
        if name not in used_names and name != "*"
    ]
    return unused


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    all_issues: list[str] = []
    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            all_issues.extend(find_unused_imports(py_file))
        except SyntaxError as e:
            print(f"SYNTAX ERROR in {py_file}: {e}")
            return 1

    if all_issues:
        print(f"Found {len(all_issues)} potential unused import(s) (noqa-tagged lines may be false positives):")
        for issue in all_issues:
            print(f"  {issue}")
        return 1

    print("No unused imports found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
