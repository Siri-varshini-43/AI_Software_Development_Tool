import json
import re
from pathlib import PurePosixPath


REQUIRED_PROJECT_FILES = [
    "backend/__init__.py",
    "backend/app.py",
    "backend/config.py",
    "backend/models.py",
    "backend/requirements.txt",
    "backend/routes.py",
    "database/schema.sql",
    "frontend/index.html",
    "frontend/css/style.css",
    "frontend/js/script.js",
    "tests/test_smoke.py",
    ".env.example",
    "README.md",
    "project_manifest.json",
]

API_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _as_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _project_name(requirements):
    if isinstance(requirements, dict):
        source = next(
            (
                requirements[key]
                for key in ("project_name", "name", "title")
                if isinstance(requirements.get(key), str)
            ),
            "",
        )
    else:
        source = str(requirements or "").splitlines()[0] if str(requirements or "").strip() else ""
    slug = re.sub(r"[^a-z0-9]+", "_", source.casefold()).strip("_")
    return slug[:48].strip("_") or "generated_project"


def validate_project_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be a JSON object")
    if manifest.get("manifest_version") != 1:
        raise ValueError("unsupported or missing manifest_version")

    required_files = manifest.get("required_files")
    if (
        not isinstance(required_files, list)
        or not required_files
        or any(not isinstance(path, str) or not path for path in required_files)
    ):
        raise ValueError("required_files must be a non-empty list of paths")
    if len(set(required_files)) != len(required_files):
        raise ValueError("required_files contains duplicate paths")
    for path in required_files:
        normalized = path.replace("\\", "/")
        if (
            normalized.startswith("/")
            or ":" in normalized
            or "\x00" in normalized
            or ".." in PurePosixPath(normalized).parts
        ):
            raise ValueError(f"unsafe required file path: {path}")

    backend = manifest.get("backend")
    if (
        not isinstance(backend, dict)
        or not isinstance(backend.get("framework"), str)
        or not isinstance(backend.get("application"), str)
        or not isinstance(backend.get("files"), list)
        or any(not isinstance(path, str) for path in backend["files"])
    ):
        raise ValueError("backend must define its framework, application, and files")

    frontend = manifest.get("frontend")
    if not isinstance(frontend, dict):
        raise ValueError("frontend must be a JSON object")
    pages = frontend.get("pages")
    if not isinstance(pages, list) or any(
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or ":" in path
        or ".." in path.split("/")
        for path in pages
    ):
        raise ValueError("frontend.pages must be a list of safe absolute paths")
    if not isinstance(frontend.get("files"), list) or any(
        not isinstance(path, str)
        or not (path.startswith("frontend/") or not "/" in path)
        or ".." in PurePosixPath(path).parts
        for path in frontend["files"]
    ):
        raise ValueError("frontend.files must be a list of paths")

    database = manifest.get("database")
    if not isinstance(database, dict) or not isinstance(
        database.get("tables"), list
    ) or any(not isinstance(table, str) for table in database["tables"]):
        raise ValueError("database.tables must be a list of table names")
    schema_file = database.get("schema_file")
    if not isinstance(schema_file, str) or not schema_file:
        raise ValueError("database.schema_file must name the SQL schema file")

    declared_files = {p.replace("\\", "/") for p in required_files}
    normalized_backend = {
        p.replace("\\", "/") if p.replace("\\", "/").startswith("backend/") else f"backend/{p.replace('\\', '/')}"
        for p in backend["files"]
    }
    normalized_frontend = {
        p.replace("\\", "/") if p.replace("\\", "/").startswith("frontend/") else f"frontend/{p.replace('\\', '/')}"
        for p in frontend["files"]
    }
    referenced_files = (
        normalized_backend
        | normalized_frontend
        | {schema_file.replace("\\", "/")}
    )
    undeclared_files = sorted(referenced_files - declared_files)
    if undeclared_files:
        raise ValueError(
            "backend, frontend, and database file lists must be included in "
            "required_files: " + ", ".join(undeclared_files)
        )

    contracts = manifest.get("api_contracts")
    if not isinstance(contracts, list):
        raise ValueError("api_contracts must be a list")
    for contract in contracts:
        if (
            not isinstance(contract, dict)
            or contract.get("method") not in API_METHODS
            or not isinstance(contract.get("path"), str)
            or not contract["path"].startswith("/")
            or ".." in contract["path"].split("/")
        ):
            raise ValueError("api_contracts contains an invalid method/path pair")

    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list) or any(
        not isinstance(dependency, str) or not dependency
        for dependency in dependencies
    ):
        raise ValueError("dependencies must be a list of package names")


def create_project_manifest(
    requirements,
    architecture,
    database,
    backend,
    frontend,
):
    database = database if isinstance(database, dict) else {}
    schema = str(database.get("sql_schema", "") or "")
    planning_text = "\n".join(
        _as_text(value)
        for value in (requirements, architecture, backend, frontend)
    )

    contracts = {}

    # 1. Structured REST APIs from architecture
    if isinstance(architecture, dict):
        rest_apis = architecture.get("rest_apis")
        if isinstance(rest_apis, list):
            for item in rest_apis:
                if isinstance(item, dict):
                    method = str(item.get("method", "")).upper()
                    path = str(item.get("url") or item.get("path") or item.get("endpoint") or "").strip()
                    path = path.rstrip(".,;)")
                    if method in API_METHODS and path.startswith("/") and not path.startswith("//") and ".." not in path.split("/"):
                        contracts[(method, path)] = {"method": method, "path": path}
                elif isinstance(item, str):
                    m = re.match(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/(?:api/)?[A-Za-z0-9_{}<>./:-]*)", item, re.IGNORECASE)
                    if m:
                        method = m.group(1).upper()
                        path = m.group(2).rstrip(".,;)")
                        if not path.startswith("//") and ".." not in path.split("/"):
                            contracts[(method, path)] = {"method": method, "path": path}

    # 2. JSON route fragments in planning text
    json_contract_pattern = re.compile(
        r"""["']method["']\s*:\s*["'](GET|POST|PUT|PATCH|DELETE)["']\s*,\s*["'](?:url|path|endpoint)["']\s*:\s*["'](/[^"'\s]+)["']""",
        re.IGNORECASE,
    )
    for match in json_contract_pattern.finditer(planning_text):
        method = match.group(1).upper()
        path = match.group(2).rstrip(".,;)")
        if not path.startswith("//") and ".." not in path.split("/"):
            contracts[(method, path)] = {"method": method, "path": path}

    # 3. Standard method and path pattern in planning text
    route_pattern = re.compile(
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+"
        r"(/(?:api/)?[A-Za-z0-9_{}<>./:-]*)",
        re.IGNORECASE,
    )
    for match in route_pattern.finditer(planning_text):
        method = match.group(1).upper()
        path = match.group(2).rstrip(".,;)")
        if path.startswith("//") or ".." in path.split("/"):
            continue
        contracts[(method, path)] = {"method": method, "path": path}

    # 4. Table markdown rows in planning text
    table_row_pattern = re.compile(
        r"""\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*(/(?:api/)?[A-Za-z0-9_{}<>./:-]*)\s*\|""",
        re.IGNORECASE,
    )
    for match in table_row_pattern.finditer(planning_text):
        method = match.group(1).upper()
        path = match.group(2).rstrip(".,;)")
        if not path.startswith("//") and ".." not in path.split("/"):
            contracts[(method, path)] = {"method": method, "path": path}

    # 5. Extract pages and HTML files
    pages = {"/"}
    html_files = {"frontend/index.html"}

    frontend_pages_input = []
    if isinstance(frontend, dict):
        raw_pages = frontend.get("pages")
        if isinstance(raw_pages, str):
            frontend_pages_input.append(raw_pages)
        elif isinstance(raw_pages, list):
            frontend_pages_input.extend(str(p) for p in raw_pages)

    for text_block in frontend_pages_input:
        for match in re.finditer(r"\b([A-Za-z0-9_-]+\.html)\b", text_block, re.IGNORECASE):
            fname = match.group(1).casefold()
            stem = PurePosixPath(fname).stem
            route = "/" if stem == "index" else f"/{stem}"
            pages.add(route)
            html_files.add(f"frontend/{fname}")
        for match in re.finditer(r"(?:\b(?:page|screen|frontend\s+route|view)\b\s*[:=-]?\s*)?(/(?:[A-Za-z0-9_-]+))", text_block, re.IGNORECASE):
            route = match.group(1)
            if not route.startswith(("/api/", "/static/")) and ".." not in route.split("/"):
                pages.add(route)
                stem = route.strip("/")
                if stem:
                    html_files.add(f"frontend/{stem}.html")

    page_pattern = re.compile(
        r"\b(?:page|screen|frontend\s+route)\s*[:=-]?\s*"
        r"(/(?:[A-Za-z0-9_./-]*))",
        re.IGNORECASE,
    )
    for match in page_pattern.finditer(planning_text):
        path = match.group(1).rstrip(".,;)")
        if not path.startswith(("/api/", "/static/")) and ".." not in path.split("/"):
            pages.add(path)
            stem = path.strip("/")
            if stem:
                if not stem.endswith(".html"):
                    html_files.add(f"frontend/{stem}.html")
                else:
                    html_files.add(f"frontend/{stem}")

    for match in re.finditer(r"""href=['"](/?[A-Za-z0-9_-]+\.html)['"]""", planning_text, re.IGNORECASE):
        fname = match.group(1).lstrip("/").casefold()
        stem = PurePosixPath(fname).stem
        route = "/" if stem == "index" else f"/{stem}"
        pages.add(route)
        html_files.add(f"frontend/{fname}")

    # Ensure all route pages map to html_files
    for route in list(pages):
        if route != "/":
            stem = route.strip("/")
            if stem:
                if not stem.endswith(".html"):
                    html_files.add(f"frontend/{stem}.html")
                else:
                    html_files.add(f"frontend/{stem}")

    frontend_files = sorted(
        set(["frontend/index.html", "frontend/css/style.css", "frontend/js/script.js"])
        | html_files
    )

    # 6. Extract database tables
    tables = {
        match.group(1).strip('"`[]').casefold()
        for match in re.finditer(
            r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
            r"([A-Za-z_][A-Za-z0-9_]*)",
            schema,
            re.IGNORECASE,
        )
    }
    planned_tables = database.get("tables", [])
    if isinstance(planned_tables, dict):
        planned_tables = list(planned_tables.values())
    if isinstance(planned_tables, list):
        for table in planned_tables:
            if isinstance(table, str):
                name = table
            elif isinstance(table, dict):
                name = next(
                    (
                        table[key]
                        for key in ("table_name", "name", "table")
                        if isinstance(table.get(key), str)
                    ),
                    None,
                )
            else:
                name = None
            if name:
                tables.add(name.strip().strip('"`[]').casefold())

    database_context = "\n".join((_as_text(architecture), schema)).casefold()
    dependencies = ["Flask", "Flask-SQLAlchemy", "gunicorn"]
    if "postgres" in database_context or re.search(r"\bserial\b", schema, re.IGNORECASE):
        dependencies.append("psycopg2-binary")
    elif "mysql" in database_context:
        dependencies.append("PyMySQL")

    backend_files = set([
        "backend/app.py",
        "backend/config.py",
        "backend/models.py",
        "backend/routes.py",
        "backend/requirements.txt",
    ])
    if isinstance(backend, dict):
        for f in backend.get("files", []):
            if isinstance(f, str) and f.strip():
                clean_f = f.replace("\\", "/").strip().lstrip("/")
                if not clean_f.startswith("backend/"):
                    clean_f = f"backend/{clean_f}"
                backend_files.add(clean_f)
    if isinstance(architecture, dict):
        for f in architecture.get("files", []):
            if isinstance(f, str) and f.strip():
                clean_f = f.replace("\\", "/").strip().lstrip("/")
                if not clean_f.startswith("backend/"):
                    clean_f = f"backend/{clean_f}"
                backend_files.add(clean_f)
        for mod in architecture.get("modules", []):
            if isinstance(mod, str) and mod.endswith(".py"):
                clean_m = mod.replace("\\", "/").strip().lstrip("/")
                if not clean_m.startswith("backend/"):
                    clean_m = f"backend/{clean_m}"
                backend_files.add(clean_m)
            elif isinstance(mod, dict):
                path = mod.get("path") or mod.get("file")
                if isinstance(path, str) and path.endswith(".py"):
                    clean_m = path.replace("\\", "/").strip().lstrip("/")
                    if not clean_m.startswith("backend/"):
                        clean_m = f"backend/{clean_m}"
                    backend_files.add(clean_m)

    for match in re.finditer(r"\b(backend/[A-Za-z0-9_./-]+\.py)\b", planning_text, re.IGNORECASE):
        candidate = match.group(1).replace("\\", "/")
        if ".." not in PurePosixPath(candidate).parts:
            backend_files.add(candidate)

    for match in re.finditer(r"\b((?:agents|services|rag|routes|models)/[A-Za-z0-9_./-]+\.py)\b", planning_text, re.IGNORECASE):
        candidate = "backend/" + match.group(1).replace("\\", "/")
        if ".." not in PurePosixPath(candidate).parts:
            backend_files.add(candidate)

    backend_files_list = sorted(backend_files)

    base_required = set(REQUIRED_PROJECT_FILES)
    required_files = sorted(
        base_required
        | set(backend_files_list)
        | set(frontend_files)
        | {database.get("schema_file", "database/schema.sql")}
    )

    return {
        "manifest_version": 1,
        "project_name": _project_name(requirements),
        "backend": {
            "framework": "Flask",
            "application": "backend.app:app",
            "files": backend_files_list,
        },
        "frontend": {
            "files": frontend_files,
            "pages": sorted(pages),
        },
        "database": {
            "schema_file": database.get("schema_file", "database/schema.sql"),
            "tables": sorted(tables),
        },
        "api_contracts": [
            contracts[key] for key in sorted(contracts)
        ],
        "dependencies": dependencies,
        "required_files": required_files,
    }
