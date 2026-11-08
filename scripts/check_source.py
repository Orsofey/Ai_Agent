"""Check project imports and templates without installing or running the application."""
import ast
import json
import sys
from pathlib import Path


def check(root):
    root = Path(root)
    issues = []
    exports = {}

    def exists(module):
        path = root.joinpath(*module.split('.'))
        return path.with_suffix('.py').is_file() or (path / '__init__.py').is_file()

    def exported(module):
        if module not in exports:
            path = root.joinpath(*module.split('.')) / '__init__.py'
            names = set()
            if path.is_file():
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.add(node.name)
                    elif isinstance(node, (ast.Import, ast.ImportFrom)):
                        names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
                    elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                        names.add(node.id)
            exports[module] = names
        return exports[module]

    paths = [*root.glob('*.py'), *root.joinpath('src').rglob('*.py')]
    for path in sorted(paths):
        relative = path.relative_to(root)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError as exc:
            issues.append({'file': str(relative), 'line': exc.lineno, 'missing': str(exc)})
            continue
        package = list(relative.parts[:-1])
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level:
                    module = '.'.join(package[:len(package) - node.level + 1] + ([module] if module else []))
                modules = [module]
                package_path = root.joinpath(*module.split('.')) / '__init__.py'
                if package_path.is_file():
                    modules += [module + '.' + alias.name for alias in node.names
                                if alias.name != '*' and alias.name not in exported(module)]
            for module in modules:
                if module.startswith('src.') and not exists(module):
                    issues.append({'file': str(relative), 'line': node.lineno, 'missing': module})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                    node.func.id == 'render_template' and node.args and isinstance(node.args[0], ast.Constant):
                template = node.args[0].value
                if isinstance(template, str) and not (root / 'templates' / template).is_file():
                    issues.append({'file': str(relative), 'line': node.lineno, 'missing': 'templates/' + template})
    return issues


def main():
    issues = check(Path(__file__).resolve().parents[1])
    if '--json' in sys.argv:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        for issue in issues:
            print(f"{issue['file']}:{issue['line']}: missing {issue['missing']}")
        print(f'Source check: {len(issues)} unresolved references' if issues else 'Source check: OK')
    return bool(issues)


if __name__ == '__main__':
    sys.exit(main())
