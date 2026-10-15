import ast
import builtins
import json
import os
import posixpath
import re
import shutil
import subprocess
import symtable
from html.parser import HTMLParser
from pathlib import PurePosixPath

from agents.project_manifest import validate_project_manifest


REQUIRED_FILES = {
    "backend/__init__.py",
    "backend/app.py",
    "backend/routes.py",
    "project_manifest.json",
    "backend/models.py",
    "backend/config.py",
    "backend/requirements.txt",
    "frontend/index.html",
    "frontend/css/style.css",
    "frontend/js/script.js",
    "tests/test_smoke.py",
    "database/schema.sql",
    ".env.example",
    "README.md",
}

PLACEHOLDER_PATTERN = re.compile(
    r"\b(?:TODO|FIXME|XXX)\b|\bpass\b|implement\s+this\s+later|"
    r"your\s+(?:code|implementation)\s+here|\bnotimplementederror\b|"
    r"\bplaceholder\s+(?:for|implementation|code|logic)\b|"
    r"\bnot\s+implemented\b",
    re.IGNORECASE
)


class _HTMLSyntaxChecker(HTMLParser):
    def error(self, message):
        raise ValueError(message)


def _resolved_frontend_reference(filename, target):
    if target.startswith("/static/"):
        joined = target[len("/static/"):]
    else:
        joined = posixpath.join(
            PurePosixPath(filename).parent.as_posix(),
            target,
        )
    normalized = posixpath.normpath(joined).lstrip("/")
    if normalized == ".." or normalized.startswith("../"):
        return None
    if normalized == "frontend" or normalized.startswith("frontend/"):
        return normalized
    return "frontend/" + normalized


def _python_module_names(files):
    modules = set()
    for filename in files:
        if not filename.endswith(".py"):
            continue
        module = PurePosixPath(filename).with_suffix("").as_posix().replace("/", ".")
        if module.endswith(".__init__"):
            module = module[:-len(".__init__")]
        modules.add(module)
        parts = module.split(".")
        modules.update(".".join(parts[:index]) for index in range(1, len(parts)))
    return modules


def _local_import_errors(files, modules):
    errors = []
    for filename, content in files.items():
        if not filename.endswith(".py"):
            continue
        source_module = PurePosixPath(filename).with_suffix("").as_posix().replace("/", ".")
        if source_module.endswith(".__init__"):
            source_module = source_module[:-len(".__init__")]
        package = source_module if filename.endswith("/__init__.py") else source_module.rpartition(".")[0]
        try:
            tree = ast.parse(content, filename=filename)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parent_parts = package.split(".") if package else []
                    keep = max(0, len(parent_parts) - node.level + 1)
                    base = ".".join(parent_parts[:keep])
                    imported = ".".join(part for part in (base, node.module or "") if part)
                else:
                    imported = node.module or ""
                names = [imported] if imported else []
            else:
                continue
            for name in names:
                if any(module == name or module.startswith(name + ".") for module in modules):
                    continue
                if any(name == module or name.startswith(module + ".") for module in modules):
                    continue
                if name.split(".", 1)[0] in {m.split(".", 1)[0] for m in modules}:
                    errors.append(f"{filename}: local import '{name}' does not resolve to a generated module")
    return errors


def _python_import_errors(files):
    module_files = {}
    module_symbols = {}
    trees = {}
    namespaces = set()
    for filename, content in files.items():
        if not filename.endswith(".py"):
            continue
        module = PurePosixPath(filename).with_suffix("").as_posix().replace("/", ".")
        if module.endswith(".__init__"):
            module = module[:-len(".__init__")]
        module_files[module] = filename
        package = module if filename.endswith("/__init__.py") else module.rpartition(".")[0]
        parts = package.split(".") if package else []
        namespaces.update(
            ".".join(parts[:index]) for index in range(1, len(parts) + 1)
        )
        try:
            tree = ast.parse(content, filename=filename)
        except SyntaxError:
            continue
        trees[module] = tree

        symbols = set()
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        symbols.add(target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                symbols.update(
                    alias.asname or alias.name.split(".", 1)[0]
                    for alias in node.names
                    if alias.name != "*"
                )
        module_symbols[module] = symbols

    errors = []
    import_graph = {module: set() for module in trees}
    local_modules = set(module_files) | namespaces
    for source_module, tree in trees.items():
        filename = module_files[source_module]
        is_package = filename.endswith("/__init__.py")
        package = source_module if is_package else source_module.rpartition(".")[0]
        package_root = source_module.split(".", 1)[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
                for imported in imported_modules:
                    if imported in import_graph:
                        import_graph[source_module].add(imported)
                    elif (
                        "." not in imported
                        and f"{package_root}.{imported}" in module_files
                    ):
                        errors.append(
                            f"{filename}: local import '{imported}' should use "
                            f"'{package_root}.{imported}'"
                        )
                continue
            if not isinstance(node, ast.ImportFrom):
                continue

            if node.level:
                parent_parts = package.split(".") if package else []
                keep = max(0, len(parent_parts) - node.level + 1)
                base = ".".join(parent_parts[:keep])
                imported_module = ".".join(
                    part for part in (base, node.module or "") if part
                )
            else:
                imported_module = node.module or ""

            if (
                not node.level
                and imported_module
                and "." not in imported_module
                and f"{package_root}.{imported_module}" in module_files
            ):
                errors.append(
                    f"{filename}: local import '{imported_module}' should use "
                    f"'{package_root}.{imported_module}'"
                )
                continue

            if imported_module in module_files:
                import_graph[source_module].add(imported_module)
                available_symbols = module_symbols.get(imported_module, set())
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    child_module = f"{imported_module}.{alias.name}"
                    if (
                        alias.name not in available_symbols
                        and child_module not in local_modules
                    ):
                        errors.append(
                            f"{filename}: local import "
                            f"'{imported_module}.{alias.name}' does not resolve "
                            "to a module or exported symbol"
                        )
            elif imported_module in namespaces:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    child_module = f"{imported_module}.{alias.name}"
                    if child_module in import_graph:
                        import_graph[source_module].add(child_module)

    visited = set()
    active = []
    reported_cycles = set()

    def visit(module):
        if module not in import_graph:
            return
        if module in active:
            cycle = active[active.index(module):] + [module]
            cycle_key = tuple(sorted(set(cycle)))
            if cycle_key not in reported_cycles:
                reported_cycles.add(cycle_key)
                errors.append(
                    f"{module_files.get(module, module)}: circular local imports detected: "
                    + " -> ".join(cycle)
                )
            return
        if module in visited:
            return
        active.append(module)
        for imported in sorted(import_graph[module]):
            visit(imported)
        active.pop()
        visited.add(module)

    for module in sorted(import_graph):
        visit(module)

    allowed_runtime_names = {
        "__builtins__", "__cached__", "__doc__", "__file__", "__loader__",
        "__name__", "__package__", "__path__", "__spec__",
    }
    builtin_names = set(vars(builtins))
    for module, tree in trees.items():
        filename = module_files[module]
        source = files[filename]
        try:
            symbol_table = symtable.symtable(source, filename, "exec")
        except SyntaxError:
            continue
        module_bindings = {
            symbol.get_name()
            for symbol in symbol_table.get_symbols()
            if symbol.is_assigned() or symbol.is_imported()
        }
        has_star_import = any(
            isinstance(node, ast.ImportFrom)
            and any(alias.name == "*" for alias in node.names)
            for node in ast.walk(tree)
        )
        declared_globals = set()

        def collect_global_declarations(table):
            for symbol in table.get_symbols():
                if symbol.is_declared_global():
                    declared_globals.add(symbol.get_name())
            for child in table.get_children():
                collect_global_declarations(child)

        collect_global_declarations(symbol_table)
        if has_star_import:
            continue

        def find_undefined_globals(table):
            for symbol in table.get_symbols():
                name = symbol.get_name()
                if (
                    symbol.is_global()
                    and symbol.is_referenced()
                    and name not in module_bindings
                    and name not in builtin_names
                    and name not in allowed_runtime_names
                    and name not in declared_globals
                ):
                    errors.append(
                        f"{filename}: unresolved global name '{name}'"
                    )
            for child in table.get_children():
                find_undefined_globals(child)

        find_undefined_globals(symbol_table)
    return errors


def _html_references(files):
    references = []
    for filename, content in files.items():
        if not filename.lower().endswith((".html", ".htm")):
            continue
        parser = _HTMLSyntaxChecker()
        try:
            parser.feed(content)
            parser.close()
        except Exception as error:
            references.append(f"{filename}: invalid HTML: {error}")
        for match in re.finditer(r"\b(?:src|href)\s*=\s*(['\"])(.*?)\1", content, re.IGNORECASE):
            target = match.group(2).split("?", 1)[0].split("#", 1)[0]
            if target.startswith("/static/"):
                frontend_asset = _resolved_frontend_reference(filename, target)
                if frontend_asset is None:
                    references.append(
                        f"{filename}: static asset '{target}' escapes frontend/"
                    )
                    continue
                if frontend_asset not in files:
                    references.append(
                        f"{filename}: static asset '{target}' does not match "
                        f"generated file '{frontend_asset}'"
                    )
                continue
            if not target or target.startswith(("#", "/", "//")) or ":" in target:
                continue
            resolved = _resolved_frontend_reference(filename, target)
            if resolved is None:
                references.append(
                    f"{filename}: local file reference '{target}' escapes frontend/"
                )
                continue
            if resolved not in files:
                references.append(
                    f"{filename}: referenced local file '{target}' is missing; "
                    f"expected generated file '{resolved}'"
                )
    for filename, content in files.items():
        if filename.startswith("frontend/") and filename.lower().endswith(".css"):
            css_targets = [
                match.group(2)
                for match in re.finditer(
                r"url\(\s*(['\"]?)(.*?)\1\s*\)",
                content,
                re.IGNORECASE,
                )
            ]
            css_targets.extend(
                match.group(2)
                for match in re.finditer(
                    r"""@import\s+(['"])(.*?)\1""",
                    content,
                    re.IGNORECASE,
                )
            )
            for raw_target in css_targets:
                target = raw_target.strip().split("?", 1)[0].split("#", 1)[0]
                if not target or target.startswith(("#", "//")) or ":" in target:
                    continue
                resolved = _resolved_frontend_reference(filename, target)
                if resolved is None:
                    references.append(
                        f"{filename}: local file reference '{target}' escapes frontend/"
                    )
                elif resolved not in files:
                    references.append(
                        f"{filename}: referenced local file '{target}' is missing; "
                        f"expected generated file '{resolved}'"
                    )
        elif filename.startswith("frontend/") and filename.lower().endswith(".js"):
            for match in re.finditer(
                r"""(?:\bfrom\s*|\bimport\s+|\bimport\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]""",
                content,
            ):
                target = match.group(1).split("?", 1)[0].split("#", 1)[0]
                resolved = _resolved_frontend_reference(filename, target)
                if resolved is None:
                    references.append(
                        f"{filename}: local file reference '{target}' escapes frontend/"
                    )
                    continue
                candidates = [resolved]
                if not PurePosixPath(resolved).suffix:
                    candidates.extend((
                        resolved + ".js",
                        resolved + ".mjs",
                        resolved + ".json",
                        resolved + "/index.js",
                    ))
                if not any(candidate in files for candidate in candidates):
                    references.append(
                        f"{filename}: referenced local file '{target}' is missing; "
                        f"expected generated file '{resolved}'"
                    )
    return references


def _frontend_static_errors(files):
    source = files.get("backend/app.py", "")
    try:
        tree = ast.parse(source, filename="backend/app.py")
    except SyntaxError:
        return []

    configured = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        is_flask_constructor = (
            isinstance(function, ast.Name) and function.id == "Flask"
        ) or (
            isinstance(function, ast.Attribute) and function.attr == "Flask"
        )
        if not is_flask_constructor:
            continue
        settings = {}
        for keyword in node.keywords:
            if keyword.arg not in {"static_folder", "static_url_path"}:
                continue
            try:
                settings[keyword.arg] = ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                continue
        if (
            settings.get("static_folder") == "../frontend"
            and settings.get("static_url_path") == "/static"
        ):
            configured = True
            break
    if configured:
        return []
    return [
        "backend/app.py: Flask must serve frontend/ at the /static URL"
    ]


def _sql_identifiers(value):
    return value.strip().strip('`"[]').casefold()


def _parse_sql_tables(schema):
    tables = {}
    pattern = re.compile(
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.IGNORECASE
    )
    for match in pattern.finditer(schema):
        depth = 1
        quote = None
        escaped = False
        end = match.end()
        while end < len(schema) and depth:
            char = schema[end]
            if quote:
                if char == quote and not escaped:
                    quote = None
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False
            elif char in ("'", '"', "`"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            end += 1
        if depth:
            continue

        columns = set()
        statement = schema[match.end():end - 1]
        for definition in _split_sql_definitions(statement):
            column = re.match(
                r'\s*(`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)',
                definition
            )
            if not column:
                continue
            name = _sql_identifiers(column.group(1))
            if name not in {
                "primary", "foreign", "constraint", "unique", "check",
                "exclude",
            }:
                columns.add(name)
        tables[_sql_identifiers(match.group(1))] = columns
    return tables


def _split_sql_definitions(statement):
    definitions = []
    start = 0
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(statement):
        if quote:
            if char == quote and not escaped:
                quote = None
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            definitions.append(statement[start:index])
            start = index + 1
    definitions.append(statement[start:])
    return definitions


def _orm_schema_errors(files):
    model_source = files.get("backend/models.py", "")
    schema = files.get("database/schema.sql", "")
    if not model_source or not schema:
        return []
    try:
        tree = ast.parse(model_source, filename="backend/models.py")
    except SyntaxError:
        return []

    sql_tables = _parse_sql_tables(schema)
    if not sql_tables:
        return []

    errors = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        is_model = any(
            isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
            and base.value.id == "db"
            and base.attr == "Model"
            for base in node.bases
        )
        if not is_model:
            continue

        table_name = re.sub(r"(?<!^)(?=[A-Z])", "_", node.name).casefold()
        expected_columns = set()
        for member in node.body:
            if not isinstance(member, (ast.Assign, ast.AnnAssign)):
                continue
            value = member.value
            targets = member.targets if isinstance(member, ast.Assign) else [
                member.target
            ]
            if not isinstance(value, ast.Call):
                continue
            function = value.func
            if not (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "db"
                and function.attr == "Column"
            ):
                continue
            column_name = None
            if value.args and isinstance(value.args[0], ast.Constant):
                if isinstance(value.args[0].value, str):
                    column_name = value.args[0].value
            if column_name is None:
                target = next(
                    (target for target in targets if isinstance(target, ast.Name)),
                    None
                )
                if target:
                    column_name = target.id
            if column_name:
                expected_columns.add(_sql_identifiers(column_name))

        for member in node.body:
            if not isinstance(member, (ast.Assign, ast.AnnAssign)):
                continue
            targets = member.targets if isinstance(member, ast.Assign) else [
                member.target
            ]
            if not any(
                isinstance(target, ast.Name) and target.id == "__tablename__"
                for target in targets
            ):
                continue
            if isinstance(member.value, ast.Constant) and isinstance(
                member.value.value, str
            ):
                table_name = _sql_identifiers(member.value.value)
            break

        if table_name not in sql_tables:
            errors.append(
                f"database/schema.sql: table '{table_name}' for model "
                f"'{node.name}' is missing"
            )
            continue
        missing_columns = sorted(expected_columns - sql_tables[table_name])
        if missing_columns:
            errors.append(
                f"database/schema.sql: table '{table_name}' is missing model "
                "columns: " + ", ".join(missing_columns)
            )
    return errors


def _route_errors(files, manifest=None):
    errors = []
    routes = set()
    route_handlers = {}
    blueprint_prefixes = {}
    registered_prefixes = {}
    registered_blueprints = set()
    blueprint_names = set()
    trees = {}
    for filename, content in files.items():
        if not filename.endswith(".py"):
            continue
        try:
            trees[filename] = ast.parse(content, filename=filename)
        except SyntaxError:
            continue
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name) and node.value.func.id == "Blueprint":
                    prefix = ""
                    for keyword in node.value.keywords:
                        if keyword.arg == "url_prefix":
                            try:
                                prefix = ast.literal_eval(keyword.value)
                            except (ValueError, TypeError):
                                pass
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            blueprint_prefixes[target.id] = prefix or ""
                            blueprint_names.add(target.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "register_blueprint" and node.args and isinstance(node.args[0], ast.Name):
                    registered_blueprints.add(node.args[0].id)
                    prefix = None
                    for keyword in node.keywords:
                        if keyword.arg == "url_prefix":
                            try:
                                prefix = ast.literal_eval(keyword.value)
                            except (ValueError, TypeError):
                                pass
                    if prefix is not None:
                        registered_prefixes[node.args[0].id] = prefix

    app_tree = trees.get("backend/app.py")
    top_level_registrations = {}
    if app_tree:
        for node in app_tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "register_blueprint"
                and node.value.args
                and isinstance(node.value.args[0], ast.Name)
            ):
                blueprint = node.value.args[0].id
                top_level_registrations[blueprint] = (
                    top_level_registrations.get(blueprint, 0) + 1
                )
    for blueprint in sorted(blueprint_names):
        registrations = top_level_registrations.get(blueprint, 0)
        if registrations != 1:
            errors_message = (
                "must be registered exactly once at module scope"
            )
            errors.append(
                f"backend/app.py: blueprint '{blueprint}' {errors_message}"
            )

    blueprint_prefixes.update(registered_prefixes)
    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if decorator.func.attr not in {"route", "get", "post", "put", "patch", "delete", "options", "head"} or not decorator.args:
                    continue
                try:
                    path = ast.literal_eval(decorator.args[0])
                except (ValueError, TypeError):
                    continue
                receiver = decorator.func.value
                if (
                    isinstance(receiver, ast.Name)
                    and receiver.id in blueprint_names
                    and receiver.id not in registered_blueprints
                ):
                    continue
                prefix = blueprint_prefixes.get(receiver.id, "") if isinstance(receiver, ast.Name) else ""
                path = prefix.rstrip("/") + "/" + path.lstrip("/") if prefix else path
                methods = {decorator.func.attr.upper()} if decorator.func.attr != "route" else {"GET"}
                for keyword in decorator.keywords:
                    if keyword.arg == "methods":
                        try:
                            methods = {method.upper() for method in ast.literal_eval(keyword.value)}
                        except (ValueError, TypeError):
                            pass
                for method in methods:
                    routes.add((method, path))
                    route_handlers[(method, path)] = node

    app_source = files.get("backend/app.py", "")
    try:
        app_tree = ast.parse(app_source, filename="backend/app.py")
    except SyntaxError:
        app_tree = None
    app_exported = app_tree is not None and any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "app"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
        for node in app_tree.body
    )
    if not app_exported:
        errors.append("backend/app.py: WSGI application variable 'app' is missing")
    if not re.search(
        r"\bapp\.config\.from_object\(\s*Config\s*\)",
        app_source,
    ):
        errors.append(
            "backend/app.py: Flask application must load backend.config.Config"
        )

    if ("GET", "/health") not in routes:
        errors.append("backend/routes.py: required GET /health route is missing")
    ready_handler = route_handlers.get(("GET", "/ready"))
    if ready_handler is None:
        errors.append("backend/routes.py: required GET /ready route is missing")
    else:
        checks_database = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and any(
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and argument.value.strip().upper() == "SELECT 1"
                for argument in ast.walk(node)
            )
            for node in ast.walk(ready_handler)
        )
        if not checks_database:
            errors.append(
                "backend/routes.py: GET /ready must execute SELECT 1 to check "
                "database connectivity"
            )

    if manifest:
        for page in manifest.get("frontend", {}).get("pages", []):
            if ("GET", page) not in routes:
                page_error = (
                    f"frontend/index.html: GET {page} has no matching Flask route"
                )
                if page_error not in errors:
                    errors.append(page_error)
        for contract in manifest.get("api_contracts", []):
            method = contract.get("method")
            path = contract.get("path")
            if (method, path) not in routes:
                errors.append(
                    f"backend/routes.py: manifest API contract {method} {path} "
                    "has no matching "
                    "Flask route"
                )

    for filename in sorted(files):
        if (
            not filename.startswith("frontend/")
            or not filename.lower().endswith((".html", ".htm"))
            or filename.casefold() == "frontend/index.html"
        ):
            continue
        relative_path = filename[len("frontend/"):]
        page_routes = {"/" + relative_path}
        page_path = PurePosixPath(relative_path)
        if page_path.suffix.lower() in {".html", ".htm"}:
            page_routes.add("/" + page_path.with_suffix("").as_posix())
        for page in sorted(page_routes):
            if ("GET", page) not in routes:
                errors.append(
                    f"{filename}: GET {page} has no matching Flask route"
                )

    for filename, content in files.items():
        if not filename.lower().endswith((".js", ".html")):
            continue
        if filename.lower().endswith(".html"):
            for match in re.finditer(
                r"\bhref\s*=\s*(['\"])(.*?)\1", content, re.IGNORECASE
            ):
                path = match.group(2).split("?", 1)[0].split("#", 1)[0]
                if (
                    not path.startswith("/")
                    or path.startswith(("/static/", "//"))
                    or ":" in path
                ):
                    continue
                if ("GET", path) not in routes:
                    errors.append(
                        f"{filename}: GET {path} has no matching Flask route"
                    )
        for match in re.finditer(r"fetch\(\s*(['\"])(.*?)\1\s*(?:,\s*\{(.*?)\})?\s*\)", content, re.DOTALL):
            path = match.group(2)
            if not path.startswith("/") or not path.startswith("/api/"):
                continue
            options = match.group(3) or ""
            method_match = re.search(r"\bmethod\s*:\s*(['\"])(.*?)\1", options, re.IGNORECASE)
            method = method_match.group(2).upper() if method_match else "GET"
            if (method, path) not in routes:
                errors.append(f"{filename}: {method} {path} has no matching Flask route")
    return list(dict.fromkeys(errors))


def validate_project(files, manifest=None, project_path=None):
    errors = []

    search_dirs = []
    if project_path and os.path.isdir(project_path):
        search_dirs.append(project_path)

    # Check actual filesystem for missing required files
    for req_file in list(REQUIRED_FILES):
        if req_file not in files:
            for sdir in search_dirs:
                disk_file = os.path.join(sdir, *req_file.split("/"))
                if os.path.isfile(disk_file):
                    try:
                        with open(disk_file, "r", encoding="utf-8") as f:
                            disk_content = f.read()
                        if disk_content.strip() or req_file == "backend/__init__.py":
                            files[req_file] = disk_content
                            break
                    except (OSError, UnicodeDecodeError):
                        pass

    missing = sorted(REQUIRED_FILES - files.keys())
    if missing:
        errors.append("missing required files: " + ", ".join(missing))

    if manifest is None and files.get("project_manifest.json"):
        try:
            manifest = json.loads(files["project_manifest.json"])
        except json.JSONDecodeError:
            manifest = None

    if manifest:
        manifest_files = set(manifest.get("required_files", []))
        # Verify filesystem for manifest required files as well
        for mf in list(manifest_files):
            if mf not in files:
                for sdir in search_dirs:
                    disk_file = os.path.join(sdir, *mf.split("/"))
                    if os.path.isfile(disk_file):
                        try:
                            with open(disk_file, "r", encoding="utf-8") as f:
                                disk_content = f.read()
                            if disk_content.strip() or mf == "backend/__init__.py":
                                files[mf] = disk_content
                                break
                        except (OSError, UnicodeDecodeError):
                            pass

        # Sync files into manifest so every generated file is registered
        m_req = manifest.setdefault("required_files", [])
        m_backend = manifest.setdefault("backend", {}).setdefault("files", [])
        m_frontend = manifest.setdefault("frontend", {}).setdefault("files", [])
        for f in files:
            if f == "project_manifest.json":
                continue
            if f not in m_req:
                m_req.append(f)
            if f.startswith("backend/") and f != "backend/__init__.py" and f not in m_backend:
                m_backend.append(f)
            if f.startswith("frontend/") and f not in m_frontend:
                m_frontend.append(f)
        manifest["required_files"] = sorted(set(m_req))
        manifest["backend"]["files"] = sorted(set(m_backend))
        manifest["frontend"]["files"] = sorted(set(m_frontend))
        files["project_manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

        try:
            validate_project_manifest(manifest)
        except ValueError as error:
            errors.append(f"project_manifest.json: {error}")
            manifest = None
        if manifest:
            manifest_files = set(manifest["required_files"])
            missing_from_manifest = sorted(manifest_files - files.keys())
            if missing_from_manifest:
                errors.append(
                    "manifest missing required files: "
                    + ", ".join(missing_from_manifest)
                )

    for filename, content in files.items():
        if not content.strip():
            errors.append(f"{filename}: file is empty")
            continue
        if PLACEHOLDER_PATTERN.search(content):
            errors.append(f"{filename}: placeholder or incomplete implementation detected")
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix == ".py":
            try:
                ast.parse(content, filename=filename)
            except SyntaxError as error:
                errors.append(f"{filename}: Python syntax error at line {error.lineno}: {error.msg}")
        elif suffix == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError as error:
                errors.append(f"{filename}: invalid JSON at line {error.lineno}: {error.msg}")
        elif suffix in (".html", ".htm"):
            checker = _HTMLSyntaxChecker()
            try:
                checker.feed(content)
                checker.close()
            except Exception as error:
                errors.append(f"{filename}: invalid HTML: {error}")
        elif suffix == ".css":
            if content.count("{") != content.count("}"):
                errors.append(f"{filename}: unmatched CSS braces")
        elif suffix == ".sql":
            if content.count("(") != content.count(")"):
                errors.append(f"{filename}: unmatched SQL parentheses")

    modules = _python_module_names(files)
    errors.extend(_local_import_errors(files, modules))
    errors.extend(_python_import_errors(files))
    errors.extend(_html_references(files))
    errors.extend(_frontend_static_errors(files))
    errors.extend(_route_errors(files, manifest))
    errors.extend(_orm_schema_errors(files))

    requirements = files.get("backend/requirements.txt", "")
    declared_dependencies = {
        re.split(r"[<=>!~\[]", line.partition("#")[0].strip(), maxsplit=1)[0]
        .casefold()
        .replace("_", "-")
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_dependencies = list(manifest.get("dependencies", [])) if manifest else []
    for dependency, purpose in (
        ("flask", "Flask application framework"),
        ("flask-sqlalchemy", "SQLAlchemy database integration"),
        ("gunicorn", "production WSGI server"),
    ):
        required_dependencies.append(dependency)
    for dependency in sorted(set(required_dependencies), key=str.casefold):
        purpose = "project manifest dependency"
        dependency = dependency.casefold().replace("_", "-")
        if dependency not in declared_dependencies:
            errors.append(
                f"backend/requirements.txt: {dependency} is required for {purpose}"
            )

    config_source = files.get("backend/config.py", "")
    for setting, description in (
        ("SECRET_KEY", "application secret"),
        ("SQLALCHEMY_DATABASE_URI", "database connection"),
    ):
        if not re.search(
            rf"(?m)^\s*{setting}\s*=[^\n]*"
            r"(?:os\.getenv|os\.environ(?:\.get|\[))",
            config_source,
        ):
            errors.append(
                f"backend/config.py: {setting} must be read from the "
                f"environment for {description}"
            )

    if manifest:
        sql_tables = _parse_sql_tables(files.get("database/schema.sql", ""))
        for table in manifest.get("database", {}).get("tables", []):
            if _sql_identifiers(table) not in sql_tables:
                errors.append(
                    f"database/schema.sql: manifest database table '{table}' "
                    "is missing"
                )
    env_example = files.get(".env.example", "")
    for variable in ("DATABASE_URL", "SECRET_KEY"):
        if not re.search(rf"(?m)^\s*{variable}\s*=", env_example):
            errors.append(f".env.example: missing {variable} configuration")

    for filename, content in files.items():
        if re.search(r"postgres(?:ql)?://\[[^\]]+\]", content, re.IGNORECASE):
            errors.append(
                f"{filename}: contains a placeholder PostgreSQL connection URL"
            )

    javascript = [name for name in files if name.endswith(".js")]
    node = shutil.which("node")
    if javascript and not node:
        errors.append("JavaScript files cannot be validated because Node.js is unavailable")
    elif node:
        for filename in javascript:
            result = subprocess.run(
                [node, "--check", "-"],
                input=files[filename],
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
                check=False
            )
            if result.returncode:
                detail = (result.stderr or result.stdout).strip().splitlines()
                errors.append(f"{filename}: JavaScript syntax error: {detail[-1] if detail else 'invalid syntax'}")

    return errors