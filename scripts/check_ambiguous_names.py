"""
Minimal, dependency-free replica of ruff's E741 (ambiguous variable name)
check — same reasoning as check_unused_imports.py: ruff itself can't be
installed in this offline sandbox, so this catches the same class of bug
before it costs another CI round-trip. Flags `l`, `O`, `I` as binding
targets: assignments, for-loop targets (including tuple unpacking),
function/lambda parameters, comprehension targets, `with ... as`, and
`except ... as`.
"""
import ast
import sys
from pathlib import Path

AMBIGUOUS = {"l", "O", "I"}


def _names_in_target(target: ast.expr) -> list[str]:
    """Handles simple names and tuple/list unpacking targets."""
    names = []
    if isinstance(target, ast.Name):
        names.append(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            names.extend(_names_in_target(elt))
    elif isinstance(target, ast.Starred):
        names.extend(_names_in_target(target.value))
    return names


def find_ambiguous_names(path: Path) -> list[str]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    issues = []

    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        lineno = getattr(node, "lineno", 0)

        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.For):
            targets = [node.target]
        elif isinstance(node, ast.comprehension):
            targets = [node.target]
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None:
                targets = [node.optional_vars]
        elif isinstance(node, ast.ExceptHandler):
            if node.name and node.name in AMBIGUOUS:
                issues.append(f"{path}:{node.lineno}: ambiguous except-as name '{node.name}'")
            continue
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            for arg in (
                args.posonlyargs + args.args + args.kwonlyargs
                + ([args.vararg] if args.vararg else [])
                + ([args.kwarg] if args.kwarg else [])
            ):
                if arg.arg in AMBIGUOUS:
                    issues.append(f"{path}:{arg.lineno}: ambiguous parameter name '{arg.arg}'")
            continue
        elif isinstance(node, ast.NamedExpr):  # walrus :=
            targets = [node.target]

        for t in targets:
            for name in _names_in_target(t):
                if name in AMBIGUOUS:
                    issues.append(f"{path}:{lineno}: ambiguous variable name '{name}'")

    return issues


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    all_issues: list[str] = []
    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            all_issues.extend(find_ambiguous_names(py_file))
        except SyntaxError as e:
            print(f"SYNTAX ERROR in {py_file}: {e}")
            return 1

    if all_issues:
        print(f"Found {len(all_issues)} ambiguous name(s):")
        for issue in all_issues:
            print(f"  {issue}")
        return 1

    print("No ambiguous variable names (l, O, I) found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
