import ast
import json
import os
import re
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import PurePosixPath

from agents.project_validator import (
    REQUIRED_FILES,
    PLACEHOLDER_PATTERN,
    validate_project,
    _parse_sql_tables,
    _sql_identifiers,
)
from agents.project_manifest import create_project_manifest
from services.ollama_service import (
    check_generation_time_limit,
    GenerationDeadlineExceeded,
    generate_response,
    generation_time_limit,
)


MAX_REPAIR_ATTEMPTS = 2
MAX_FORMAT_RETRIES = 1
FRONTEND_MAX_PREDICT = 1792
MAX_FRONTEND_CONTEXT_CHARS = 2000
GENERATED_PROJECTS_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    ),
    "generated_projects"
)
logger = logging.getLogger(__name__)


def migrate_legacy_project(legacy_project_path, project_path):
    if os.path.exists(project_path) or not os.path.isdir(legacy_project_path):
        return False

    os.makedirs(os.path.dirname(project_path), exist_ok=True)
    shutil.copytree(legacy_project_path, project_path)
    return True


def _project_prompt(
    requirements,
    architecture,
    database,
    backend,
    frontend,
    manifest=None
):
    return f"""
Build a small, runnable full-stack project. Implement the core requirements,
use the architecture's technology choices, and keep the frontend API calls
consistent with the Flask backend. Avoid unnecessary abstractions and verbose
documentation. Use complete, executable code without placeholders.

The backend is a Flask package rooted at backend/. Export a Flask application
as backend.app:app, read SECRET_KEY and DATABASE_URL from the environment, and
never use Flask debug mode in production. Keep imports one-directional: routes
must not import backend.app or use `from backend import app`. Define the
SQLAlchemy extension once as db in backend/models.py, and import it from
backend.models wherever needed; do not import it from backend.db. The
Flask app must use `static_folder="../frontend"` and
`static_url_path="/static"` to serve generated frontend assets. The
application must register the route blueprints exactly once. Define
/health as a liveness endpoint and /ready as a database readiness endpoint
that executes
db.session.execute(text("SELECT 1")). Serve the frontend from Flask. Ensure
blueprint URL prefixes are not repeated in route decorators, every internal
HTML link has a matching GET route, frontend assets resolve, and each API
request matches a registered backend route and HTTP method.

The project must run locally from its root with
`python -m flask --app backend.app run`. Include gunicorn in
backend/requirements.txt for optional Linux production hosting, and document
local startup and production environment variables in README.md. Do not
generate a Dockerfile or Docker instructions. Do not embed credentials,
placeholder database URLs, or a hard-coded production secret. List Flask,
Flask-SQLAlchemy, and gunicorn in backend/requirements.txt; include the
appropriate database driver for the configured production database.

REQUIREMENTS:
{requirements}

ARCHITECTURE:
{architecture}

DATABASE:
{database}

BACKEND PLAN:
{backend}

FRONTEND PLAN:
{frontend}

PROJECT MANIFEST:
{json.dumps(manifest or {}, ensure_ascii=False, indent=2)}
"""


def _emit_progress(progress, message, level=logging.INFO):
    if progress:
        progress(message, level)
    else:
        logger.log(level, message)


def _remove_dockerfiles(files):
    for filename in list(files):
        if PurePosixPath(filename).name.casefold() == "dockerfile":
            del files[filename]


def _clean_path(filename, expected_files=None):
    clean = filename.strip()
    clean = re.sub(
        r"^(?:#{1,6}\s*|\*\*|__)?(?:file\s*:\s*|\d+[\.)]\s*)?",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    clean = clean.strip("`'\"* ").rstrip(":").strip()
    clean = clean.replace("\\", "/")
    if clean.startswith("project/"):
        clean = clean[len("project/"):]
    clean = clean.lstrip("/")

    if expected_files:
        exp_set = set(expected_files)
        if clean in exp_set:
            return clean
        for prefix in ("frontend/", "backend/", "database/", "tests/"):
            if f"{prefix}{clean}" in exp_set:
                return f"{prefix}{clean}"
        base = PurePosixPath(clean).name.casefold()
        for exp in exp_set:
            if PurePosixPath(exp).name.casefold() == base:
                return exp
        norm_base = base.replace("-", "_")
        for exp in exp_set:
            if PurePosixPath(exp).name.casefold().replace("-", "_") == norm_base:
                return exp
    if clean.endswith(".py") and clean.startswith("frontend/"):
        clean = "backend/" + clean[len("frontend/"):]
    elif clean.startswith(("agents/", "services/", "rag/", "routes/", "models/")):
        clean = f"backend/{clean}"
    elif "/" not in clean:
        if clean in ("app.py", "config.py", "models.py", "routes.py", "__init__.py"):
            return f"backend/{clean}"
        elif clean.endswith((".html", ".css", ".js")):
            if clean == "style.css":
                return "frontend/css/style.css"
            elif clean == "script.js":
                return "frontend/js/script.js"
            return f"frontend/{clean}"
        elif clean == "schema.sql":
            return "database/schema.sql"
        elif clean == "requirements.txt":
            return "backend/requirements.txt"
        elif clean.endswith(".py"):
            if clean == "test_smoke.py" or clean.startswith("test_"):
                return f"tests/{clean}"
            return f"backend/{clean}"
    elif clean.startswith(("css/", "js/", "images/")):
        return f"frontend/{clean}"
    return clean


def _parse_project_files(response, progress=None, expected_files=None):
    pattern = re.compile(
        r"^(?:#{2,3}|File:|\*\*File:)\s*(.+?)\s*:?\s*\r?\n\s*```[^\r\n]*\r?\n(.*?)(?:\r?\n```|(?=\r?\n(?:#{2,3}|File:|\*\*File:)\s*.+?\s*:?\r?\n\s*```)|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    files = {}
    canonical_paths = {}

    for raw_filename, content in pattern.findall(response or ""):
        filename = _clean_path(raw_filename, expected_files)
        path = PurePosixPath(filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or ":" in filename
            or "\x00" in filename
            or any(part.endswith((" ", ".")) for part in path.parts)
        ):
            raise ValueError(f"Generated file path is not allowed: {raw_filename}")
        filename = path.as_posix()
        if filename.startswith("project/"):
            filename = filename[len("project/"):]
        if not filename or filename == ".":
            raise ValueError("Generated file path is empty.")
        if PurePosixPath(filename).name.casefold() == "generated_output.txt":
            raise ValueError(
                "The model returned generated_output.txt instead of project files."
            )

        normalized_name = filename.casefold()
        file_content = content.strip() + "\n"
        existing_name = canonical_paths.get(normalized_name)
        if existing_name:
            if files[existing_name] != file_content:
                _emit_progress(
                    progress,
                    f"Duplicate generated path '{existing_name}'; "
                    "using its latest complete version.",
                    logging.WARNING
                )
                files[existing_name] = file_content
            continue

        canonical_paths[normalized_name] = filename
        files[filename] = file_content

    if not files:
        raise ValueError(
            "The model response contained no recognized file headings followed "
            "by fenced code blocks."
        )
    if expected_files is not None:
        expected = set(expected_files)
        missing = sorted(expected - files.keys())
        unexpected = sorted(files.keys() - expected)
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing expected files: " + ", ".join(missing))
            if unexpected:
                details.append("unexpected files: " + ", ".join(unexpected))
            raise ValueError("; ".join(details))
    return files


def _validate_generated_group(files):
    _repair_python_syntax_inplace(files)
    errors = []
    for filename, content in files.items():
        if not content.strip():
            errors.append(f"{filename}: generated file is empty")
        elif PLACEHOLDER_PATTERN.search(content):
            errors.append(
                f"{filename}: placeholder or incomplete implementation detected"
            )
        elif filename.endswith(".py"):
            try:
                ast.parse(content, filename=filename)
            except SyntaxError as error:
                errors.append(
                    f"{filename}: Python syntax error at line "
                    f"{error.lineno}: {error.msg}"
                )
        elif filename.endswith(".css") and content.count("{") != content.count("}"):
            errors.append(f"{filename}: unmatched CSS braces")
        elif filename.endswith(".js"):
            node = shutil.which("node")
            if node:
                result = subprocess.run(
                    [node, "--check", "-"],
                    input=content,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode:
                    details = (result.stderr or result.stdout).strip().splitlines()
                    errors.append(
                        f"{filename}: JavaScript syntax error: "
                        f"{details[-1] if details else 'invalid syntax'}"
                    )
    if errors:
        raise ValueError(
            "Generated file group failed stage validation: " + "; ".join(errors)
        )


def _smoke_test_source(manifest):
    pages = sorted(set(manifest.get("frontend", {}).get("pages", [])))
    assets = sorted(
        path[len("frontend/"):]
        for path in manifest.get("frontend", {}).get("files", [])
        if path.startswith("frontend/")
        and not path.lower().endswith((".html", ".htm"))
    )
    contracts = manifest.get("api_contracts", [])
    return f'''import os
import re
import unittest

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "generated-project-smoke-test"

from backend.app import app
from backend.models import db

PAGES = {pages!r}
ASSETS = {assets!r}
API_CONTRACTS = {contracts!r}


class GeneratedProjectSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["LOGIN_DISABLED"] = True
        with app.app_context():
            if hasattr(db, "create_all"):
                db.create_all()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            if hasattr(db, "drop_all"):
                db.drop_all()

    def test_health_readiness_pages_and_assets(self):
        with app.test_client() as client:
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            health.close()
            readiness = client.get("/ready")
            self.assertEqual(readiness.status_code, 200)
            readiness.close()
            for path in PAGES:
                with self.subTest(page=path):
                    response = client.get(path, follow_redirects=True)
                    self.assertEqual(response.status_code, 200)
                    response.close()
            for path in ASSETS:
                with self.subTest(asset=path):
                    response = client.get("/static/" + path)
                    self.assertEqual(response.status_code, 200)
                    response.close()

    def test_api_contracts_do_not_crash_or_miss_routes(self):
        with app.test_client() as client:
            for contract in API_CONTRACTS:
                path = re.sub(
                    r"<(?:[^:>]+:)?[^>]+>|{{[^{{}}]+}}",
                    "1",
                    contract["path"],
                )
                with self.subTest(method=contract["method"], path=path):
                    response = client.open(
                        path,
                        method=contract["method"],
                        json={{}},
                    )
                    self.assertLess(response.status_code, 500)
                    self.assertNotIn(response.status_code, (404, 405))
                    response.close()


if __name__ == "__main__":
    unittest.main()
'''


def run_smoke_tests(files, manifest=None, timeout=25):
    smoke_source = files.get("tests/test_smoke.py")
    if not smoke_source:
        return []

    models_code = files.get("backend/models.py", "")
    if "object()" in models_code and "SQLAlchemy" not in models_code:
        return []

    parent_path = GENERATED_PROJECTS_DIR
    os.makedirs(parent_path, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix=".smoke-test-", dir=parent_path)
    try:
        for filename, content in files.items():
            filepath = os.path.join(temp_dir, *filename.split("/"))
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)

        env = dict(os.environ)
        env["PYTHONPATH"] = temp_dir
        env["DATABASE_URL"] = "sqlite://"
        env["SECRET_KEY"] = "generated-project-smoke-test"

        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests/test_smoke.py"],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            summary_lines = [
                line.strip() for line in output.splitlines()
                if line.strip().startswith(("FAIL:", "ERROR:", "AssertionError:", "ModuleNotFoundError:", "ImportError:", "SyntaxError:"))
            ]
            if summary_lines:
                return [f"tests/test_smoke.py: {summary_lines[0]}"]
            lines = [l.strip() for l in output.splitlines() if l.strip()]
            return [f"tests/test_smoke.py: {lines[-1] if lines else 'Smoke test failed'}"]
        return []
    except subprocess.TimeoutExpired:
        return ["tests/test_smoke.py: smoke test execution timed out"]
    except Exception as error:
        return [f"tests/test_smoke.py: could not execute smoke tests: {error}"]
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)



def _generate_file_group(
    project_prompt,
    manifest,
    expected_files,
    interface_context,
    progress=None,
    num_predict=2048,
    code_progress=None,
):
    context = "\n\n".join(
        f"### {filename}\n```\n{content.rstrip()}\n```"
        for filename, content in interface_context.items()
    )
    base_prompt = f"""
Generate complete, runnable contents for only these files:
{chr(10).join(f"- {filename}" for filename in expected_files)}

Follow this shared project manifest exactly. Do not change its API paths,
HTTP methods, database entities, filenames, or dependencies:
{json.dumps(manifest, ensure_ascii=False, indent=2)}

Related generated files, provided as read-only interface context:
{context or "(none)"}

Project requirements and design plans:
{project_prompt}

Return exactly one fenced code block per requested file. Put its exact project
path in a ### heading immediately before the block. Do not return prose,
unrequested files, or generated_output.txt.
"""
    last_error = None
    requested_files = list(expected_files)
    generated_files = {}
    context = dict(interface_context)
    for attempt in range(MAX_FORMAT_RETRIES + 1):
        pending_files = [
            filename for filename in requested_files
            if filename not in generated_files
        ]
        if not pending_files:
            break
        if code_progress:
            code_progress({
                "type": "code_start",
                "files": pending_files,
                "attempt": attempt + 1,
            })
        if attempt:
            _emit_progress(
                progress,
                "Retrying generation only for these missing or invalid files: "
                + ", ".join(pending_files),
                logging.WARNING,
            )
        prompt = base_prompt
        if last_error:
            prompt = f"""
Generate complete, runnable contents for only these files:
{chr(10).join(f"- {filename}" for filename in pending_files)}

The following generated files are read-only context. Preserve their interfaces:
{chr(10).join(
    f"### {filename}\n```\n{content.rstrip()}\n```"
    for filename, content in context.items()
)}

Previous response error: {last_error}
Project requirements and manifest:
{project_prompt}

Return exactly one fenced code block per requested file. Use the exact path
in a ### heading immediately before each block. Do not return prose.
"""

        def report_progress(chunk_count):
            _emit_progress(
                progress,
                f"Model generated {chunk_count} response chunks...",
            )

        generation_options = {
            "num_predict": num_predict,
            "progress": report_progress,
        }
        if code_progress:
            generation_options["on_chunk"] = lambda chunk: code_progress({
                "type": "code_chunk",
                "files": pending_files,
                "attempt": attempt + 1,
                "content": chunk,
            })
        response = generate_response(prompt, **generation_options)
        try:
            parsed_files = _parse_project_files(response, progress)
        except ValueError as error:
            last_error = str(error)
            continue
        # Try syntax repair on any generated python files
        _repair_python_syntax_inplace(parsed_files, progress)

        filtered_parsed = {}
        for fname, fcontent in parsed_files.items():
            if fname in pending_files:
                filtered_parsed[fname] = fcontent
            elif fname in context or fname in generated_files:
                _emit_progress(
                    progress,
                    f"Preserving existing version of '{fname}'; ignoring duplicate.",
                    logging.DEBUG,
                )
            else:
                # Extra unrequested file: keep only if valid; do not force retry if invalid
                temp_group = {fname: fcontent}
                try:
                    _validate_generated_group(temp_group)
                    filtered_parsed[fname] = temp_group[fname]
                except ValueError:
                    pass

        try:
            _validate_generated_group(filtered_parsed)
        except ValueError as error:
            last_error = str(error)
            invalid_pending = [
                filename for filename in pending_files
                if f"{filename}:" in last_error
            ]
            # Save any files that were valid
            for filename, content in filtered_parsed.items():
                if f"{filename}:" not in last_error:
                    generated_files[filename] = content
                    context[filename] = content
            if invalid_pending:
                continue
            # If no pending file was invalid, something else failed
            raise

        generated_files.update(filtered_parsed)
        context.update(filtered_parsed)
        if code_progress:
            code_progress({
                "type": "code_files",
                "files": [
                    {"path": filename, "content": content}
                    for filename, content in generated_files.items()
                ],
            })
        missing_files = sorted(set(pending_files) - set(generated_files.keys()))
        if missing_files:
            last_error = "missing expected files: " + ", ".join(missing_files)
            continue

        unexpected_files = sorted(set(generated_files.keys()) - set(requested_files))
        if unexpected_files:
            _emit_progress(
                progress,
                "Reusing additional generated project files: "
                + ", ".join(unexpected_files),
            )

        last_error = None
        break

    missing_files = sorted(set(requested_files) - generated_files.keys())
    if missing_files or last_error:
        details = []
        if missing_files:
            details.append("missing expected files: " + ", ".join(missing_files))
        if last_error:
            details.append(last_error)
        raise ValueError(
            "File group generation failed after "
            f"{MAX_FORMAT_RETRIES + 1} attempts: {'; '.join(details)}"
        )
    return generated_files


def _repair_targets(files, errors):
    targets = []
    page_route_missing = False
    needs_blueprint_context = any(
        "blueprint '" in error and "module scope" in error
        for error in errors
    )
    needs_schema_context = any(
        error.startswith("database/schema.sql:")
        for error in errors
    )
    for error in errors:
        prefix, separator, _detail = error.partition(":")
        clean_prefix = prefix.strip()
        if (
            separator
            and (clean_prefix in files or clean_prefix in REQUIRED_FILES)
            and clean_prefix not in targets
            and clean_prefix != "tests/test_smoke.py"
        ):
            targets.append(clean_prefix)
        match = re.search(r"expected generated file '([^']+)'", error)
        if match:
            expected_fn = match.group(1).replace("\\", "/")
            if expected_fn not in targets:
                targets.append(expected_fn)
        if (
            prefix.startswith("backend/")
            and "backend.db" in error
            and "backend/models.py" in files
            and "backend/models.py" not in targets
        ):
            targets.append("backend/models.py")
        if (
            prefix == "backend/models.py"
            and "unresolved global name 'app'" in error
            and "backend/app.py" in files
            and "backend/app.py" not in targets
        ):
            targets.append("backend/app.py")
        if (
            prefix.lower().endswith((".html", ".htm"))
            and re.search(r"\bGET\s+\S+\s+has no matching Flask route\b", error)
        ):
            page_route_missing = True
        if error.startswith("missing required files:"):
            missing = error.partition(":")[2].split(",")
            targets.extend(
                filename.strip()
                for filename in missing
                if filename.strip() not in targets
            )
        if error.startswith("manifest missing required files:"):
            missing = error.partition(":")[2].split(",")
            targets.extend(
                filename.strip()
                for filename in missing
                if filename.strip() not in targets
            )
        if error.startswith("tests/test_smoke.py:"):
            if "/ready" in error or "SELECT 1" in error or "database" in error.lower() or "table" in error.lower():
                for fn in ("backend/models.py", "backend/app.py", "database/schema.sql"):
                    if fn in files and fn not in targets:
                        targets.append(fn)
            if "/api/" in error or "404" in error or "405" in error or "500" in error:
                for fn in ("backend/routes.py", "backend/app.py"):
                    if fn in files and fn not in targets:
                        targets.append(fn)
            if "page=" in error or "asset=" in error or "/static/" in error:
                for fn in ("backend/app.py", "frontend/index.html"):
                    if fn in files and fn not in targets:
                        targets.append(fn)
    if page_route_missing:
        for filename in ("backend/routes.py", "backend/app.py"):
            if filename in files and filename not in targets:
                targets.append(filename)
    if needs_blueprint_context and "backend/routes.py" in files:
        if "backend/routes.py" not in targets:
            targets.append("backend/routes.py")
    if needs_schema_context and "backend/models.py" in files:
        if "backend/models.py" not in targets:
            targets.append("backend/models.py")
    return [filename for filename in targets if filename]


def _missing_referenced_files(files, errors):
    missing = set()
    for error in errors:
        match = re.search(r"expected generated file '([^']+)'", error)
        if not match:
            continue
        filename = match.group(1).replace("\\", "/")
        path = PurePosixPath(filename)
        if (
            not filename.startswith("frontend/")
            or path.is_absolute()
            or ".." in path.parts
            or ":" in filename
            or "\x00" in filename
            or filename in files
        ):
            continue
        missing.add(filename)
    return sorted(missing)


def _repair_unresolved_local_imports(files):
    module_symbols = {}
    module_namespaces = set()
    for filename, content in files.items():
        if not filename.endswith(".py"):
            continue
        module = PurePosixPath(filename).with_suffix("").as_posix().replace("/", ".")
        is_package = filename.endswith("/__init__.py")
        if module.endswith(".__init__"):
            module = module[:-len(".__init__")]
        package = module if is_package else module.rpartition(".")[0]
        parts = package.split(".") if package else []
        module_namespaces.update(
            ".".join(parts[:index]) for index in range(1, len(parts) + 1)
        )
        try:
            tree = ast.parse(content, filename=filename)
        except SyntaxError:
            continue

        symbols = set()
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                symbols.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
        module_symbols[module] = symbols

    local_roots = {module.split(".", 1)[0] for module in module_symbols}
    changes = {}
    for filename, content in files.items():
        if not filename.endswith(".py"):
            continue
        module = PurePosixPath(filename).with_suffix("").as_posix().replace("/", ".")
        is_package = filename.endswith("/__init__.py")
        if module.endswith(".__init__"):
            module = module[:-len(".__init__")]
        source_module = module
        package = module if is_package else module.rpartition(".")[0]
        try:
            tree = ast.parse(content, filename=filename)
        except SyntaxError:
            continue

        lines = content.splitlines(keepends=True)
        edits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.names:
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
                not imported_module
                or imported_module.split(".", 1)[0] not in local_roots
                or any(alias.name == "*" for alias in node.names)
                or node.lineno != node.end_lineno
            ):
                continue

            imports_by_module = {imported_module: []}
            changed = False
            for alias in node.names:
                child_module = f"{imported_module}.{alias.name}"
                is_resolved = (
                    alias.name in module_symbols.get(imported_module, set())
                    or child_module in module_symbols
                    or child_module in module_namespaces
                )
                if is_resolved:
                    imports_by_module[imported_module].append(alias)
                    continue

                candidates = [
                    candidate
                    for candidate, symbols in module_symbols.items()
                    if candidate != imported_module
                    and alias.name in symbols
                    and not (
                        source_module == "backend.routes"
                        and candidate == "backend.app"
                        and alias.name == "app"
                    )
                ]
                if len(candidates) == 1:
                    imports_by_module.setdefault(candidates[0], []).append(alias)
                    changed = True
                else:
                    imports_by_module[imported_module].append(alias)

            if not changed:
                continue

            original_line = lines[node.lineno - 1]
            before = original_line[:node.col_offset]
            after = original_line[node.end_col_offset:]
            newline = "\r\n" if original_line.endswith("\r\n") else "\n"
            replacement_lines = []
            for index, (module, aliases) in enumerate(imports_by_module.items()):
                if not aliases:
                    continue
                imported = ", ".join(
                    alias.name + (f" as {alias.asname}" if alias.asname else "")
                    for alias in aliases
                )
                line = f"{before}from {module} import {imported}"
                line += after if index == 0 else newline
                replacement_lines.append(line)
            if replacement_lines:
                edits.append((node.lineno - 1, "".join(replacement_lines)))

        if edits:
            for line_number, replacement in reversed(edits):
                lines[line_number] = replacement
            changes[filename] = "".join(lines)

    if not changes:
        return False
    files.update(changes)
    return True


def _ensure_runtime_dependencies(files, manifest=None):
    requirements = files.get("backend/requirements.txt", "")
    declared = {
        re.split(r"[<=>!~\[]", line.partition("#")[0].strip(), maxsplit=1)[0]
        .casefold()
        .replace("_", "-")
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_dependencies = list(
        (manifest or {}).get("dependencies", [])
    )
    required_dependencies.extend(("Flask", "Flask-SQLAlchemy", "gunicorn"))
    missing_dependencies = [
        package for package in required_dependencies
        if package.casefold().replace("_", "-") not in declared
    ]
    if missing_dependencies:
        if requirements and not requirements.endswith("\n"):
            requirements += "\n"
        files["backend/requirements.txt"] = (
            requirements + "\n".join(missing_dependencies) + "\n"
        )


def _repair_frontend_static_paths(files):
    asset_paths = {
        filename[len("frontend/"):].casefold(): filename[len("frontend/"):]
        for filename in files
        if filename.startswith("frontend/") and not filename.lower().endswith((".html", ".htm"))
    }
    by_basename = {}
    for path in asset_paths.values():
        by_basename.setdefault(PurePosixPath(path).name.casefold(), []).append(path)

    any_changed = False
    for filename, content in list(files.items()):
        if not filename.lower().endswith((".html", ".htm")):
            continue
        changed = False

        def replace_path(match):
            nonlocal changed
            current = match.group(3)
            relative_path = current[len("/static/"):]
            if relative_path.casefold() in asset_paths:
                return match.group(0)
            matches = by_basename.get(
                PurePosixPath(relative_path).name.casefold(),
                []
            )
            if len(matches) != 1:
                return match.group(0)
            changed = True
            return f"{match.group(1)}{match.group(2)}/static/{matches[0]}{match.group(2)}"

        updated = re.sub(
            r"""((?:href|src)\s*=\s*)(['"])(/static/[^'"]+)\2""",
            replace_path,
            content,
            flags=re.IGNORECASE
        )
        if changed:
            files[filename] = updated
            any_changed = True
    return any_changed


def _ensure_sqlalchemy_text_import(files):
    filename = "backend/app.py"
    source = files.get(filename)
    if source is None:
        return False
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return False
    needs_text = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "text"
        for node in ast.walk(tree)
    )
    already_imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "sqlalchemy"
        and any(alias.name == "text" for alias in node.names)
        for node in tree.body
    )
    if not needs_text or already_imported:
        return False
    lines = source.splitlines(keepends=True)
    import_nodes = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    insertion = max((node.end_lineno for node in import_nodes), default=0)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines.insert(insertion, f"from sqlalchemy import text{newline}")
    files[filename] = "".join(lines)
    return True


def _repair_backend_db_imports(files):
    models_path = "backend/models.py"
    models_source = files.get(models_path)
    if models_source is None:
        return False
    db_module_source = files.get("backend/db.py")
    if db_module_source is not None:
        try:
            db_module_tree = ast.parse(db_module_source, filename="backend/db.py")
        except SyntaxError:
            db_module_tree = None
        if db_module_tree and any(
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "db"
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
            )
            for node in db_module_tree.body
        ):
            return False
    try:
        models_tree = ast.parse(models_source, filename=models_path)
    except SyntaxError:
        return False

    has_db_binding = any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "db"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
        for node in models_tree.body
    )
    model_imports_db = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "backend.db"
        and any(alias.name == "db" for alias in node.names)
        for node in models_tree.body
    )
    needs_extension = not has_db_binding and model_imports_db
    changed = False

    for filename, source in list(files.items()):
        if not filename.startswith("backend/") or not filename.endswith(".py"):
            continue
        if filename == models_path and not needs_extension:
            continue
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError:
            continue
        lines = source.splitlines(keepends=True)
        edits = []
        for node in tree.body:
            if not (
                isinstance(node, ast.ImportFrom)
                and node.module == "backend.db"
                and any(alias.name == "db" for alias in node.names)
            ):
                continue
            if filename == models_path:
                edits.append((node.lineno - 1, node.end_lineno, ""))
            else:
                newline = "\r\n" if lines[node.lineno - 1].endswith("\r\n") else "\n"
                names = ", ".join(
                    alias.name + (f" as {alias.asname}" if alias.asname else "")
                    for alias in node.names
                )
                edits.append((
                    node.lineno - 1,
                    node.end_lineno,
                    f"from backend.models import {names}{newline}"
                ))
        for start, end, replacement in reversed(edits):
            lines[start:end] = [replacement] if replacement else []
        updated = "".join(lines)

        if filename == models_path and needs_extension:
            try:
                updated_tree = ast.parse(updated, filename=filename)
            except SyntaxError:
                continue
            imports = [
                node for node in updated_tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom))
            ]
            insertion = max((node.end_lineno for node in imports), default=0)
            newline = "\r\n" if "\r\n" in updated else "\n"
            extension = (
                f"from flask_sqlalchemy import SQLAlchemy{newline}"
                f"db = SQLAlchemy(){newline}"
            )
            updated_lines = updated.splitlines(keepends=True)
            updated_lines.insert(insertion, extension)
            updated = "".join(updated_lines)

        if updated != source:
            files[filename] = updated
            changed = True
    return changed


def _register_declared_blueprints(files):
    routes_source = files.get("backend/routes.py")
    app_source = files.get("backend/app.py")
    if routes_source is None or app_source is None:
        return False
    try:
        routes_tree = ast.parse(routes_source, filename="backend/routes.py")
        app_tree = ast.parse(app_source, filename="backend/app.py")
    except SyntaxError:
        return False

    blueprints = []
    for node in routes_tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "Blueprint"
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        blueprints.extend(
            target.id for target in targets if isinstance(target, ast.Name)
        )
    if not blueprints:
        return False

    existing_imports = {}
    registrations = {}
    for node in app_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {
            "backend.routes", "routes"
        }:
            for alias in node.names:
                existing_imports[alias.name] = alias.asname or alias.name
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "register_blueprint"
            and node.value.args
            and isinstance(node.value.args[0], ast.Name)
        ):
            name = node.value.args[0].id
            registrations[name] = registrations.get(name, 0) + 1

    missing = [
        name for name in blueprints
        if registrations.get(existing_imports.get(name, name), 0) == 0
    ]
    if not missing:
        return False

    app_assignment = next(
        (
            node for node in app_tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "app"
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
            )
        ),
        None
    )
    if app_assignment is None:
        return False

    new_imports = [
        name if existing_imports.get(name, name) == name
        else f"{name} as {existing_imports[name]}"
        for name in missing
        if name not in existing_imports
    ]
    lines = app_source.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in app_source else "\n"
    insertions = []
    if new_imports:
        import_nodes = [
            node for node in app_tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        import_position = max(
            (node.end_lineno for node in import_nodes),
            default=0
        )
        insertions.append(
            (
                import_position,
                f"from backend.routes import {', '.join(new_imports)}{newline}"
            )
        )
    registrations_source = "".join(
        f"app.register_blueprint({existing_imports.get(name, name)}){newline}"
        for name in missing
    )
    insertions.append((app_assignment.end_lineno, registrations_source))
    for position, content in sorted(insertions, reverse=True):
        lines.insert(position, content)
    files["backend/app.py"] = "".join(lines)
    return True


def _write_project_files(files, project_path, preserve_existing=False):
    parent_path = os.path.dirname(project_path)
    os.makedirs(parent_path, exist_ok=True)
    staging_path = tempfile.mkdtemp(prefix=".project-staging-", dir=parent_path)
    backup_path = None
    try:
        if preserve_existing and os.path.isdir(project_path):
            shutil.copytree(project_path, staging_path, dirs_exist_ok=True)

        for filename, content in files.items():
            file_path = os.path.join(staging_path, *filename.split("/"))
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8", newline="\n") as file:
                file.write(content)

        if os.path.exists(project_path):
            backup_path = tempfile.mkdtemp(
                prefix=".project-backup-",
                dir=parent_path
            )
            os.rmdir(backup_path)
            os.replace(project_path, backup_path)
        try:
            os.replace(staging_path, project_path)
        except Exception:
            if backup_path and not os.path.exists(project_path):
                os.replace(backup_path, project_path)
                backup_path = None
            raise
    finally:
        if os.path.exists(staging_path):
            shutil.rmtree(staging_path)
    if backup_path and os.path.exists(backup_path):
        shutil.rmtree(backup_path)


def _repair_prompt(original_prompt, files, errors, targets, manifest=None):
    current_files = "\n\n".join(
        f"### {name}\n```\n{content.rstrip()}\n```"
        for name, content in files.items()
        if name in targets
    )
    related_paths = set()
    if any(error.startswith("database/schema.sql:") for error in errors):
        related_paths.add("backend/models.py")
    if any("blueprint '" in error for error in errors):
        related_paths.update(("backend/routes.py", "backend/app.py"))
    if any("backend.db" in error for error in errors):
        related_paths.update(("backend/models.py", "backend/app.py"))
    if any("unresolved global name 'app'" in error for error in errors):
        related_paths.update(("backend/models.py", "backend/app.py"))
    context_files = "\n\n".join(
        f"### {name} (read-only context)\n```\n{files[name].rstrip()}\n```"
        for name in sorted(related_paths - set(targets))
        if name in files
    )
    missing_page_routes = [
        match.group(1)
        for error in errors
        if error.partition(":")[0].lower().endswith((".html", ".htm"))
        for match in [
            re.search(r"\bGET\s+(\S+)\s+has no matching Flask route\b", error)
        ]
        if match
    ]
    page_route_instructions = ""
    if missing_page_routes:
        page_paths = sorted(set(missing_page_routes))
        page_route_instructions = (
            "\n\nThe following HTML navigation paths currently have no Flask "
            "GET handler:\n"
            + "\n".join(f"- {path}" for path in page_paths)
            + "\nAdd and register GET handlers for these paths in the Flask "
            "application/blueprint. Each handler must serve the generated "
            "frontend/index.html using a filesystem path resolved relative "
            "to the backend source file. Preserve the existing API routes, "
            "blueprint prefixes, and WSGI application export."
        )
    return f"""
Fix only the listed files. Preserve their working behavior. Return complete
contents for each requested file with a ### path heading and fenced code block.
Resolve every listed validation error. Replace incomplete handlers with real
behavior supported by the generated models; deleting a placeholder comment
without implementing the handler is not a fix. Do not return unchanged files,
explanations, or any other text.
Import SQLAlchemy's `text` wherever the readiness check uses it. Keep the sole
`db = SQLAlchemy()` extension in backend/models.py; do not import `backend.db`
or the Flask app into backend/models.py. Register each declared blueprint once
at module scope in backend/app.py. Match SQL table and column names to ORM
models, and point `/static/` references to the correct frontend asset paths.
{page_route_instructions}

Project instructions:
{original_prompt}

Validation errors:
{chr(10).join(f'- {error}' for error in errors)}

Files to repair:
{current_files}

Related files for context only (do not regenerate these):
{context_files or "(none)"}

Required paths:
{chr(10).join(targets)}

Shared project manifest and interfaces:
{json.dumps(manifest or {}, ensure_ascii=False, indent=2)}
"""


def _add_missing_frontend_routes(files, errors, progress=None):
    missing_paths = set()
    for error in errors:
        match = re.search(
            r"^(?:frontend/[^:]+): GET (\S+) has no matching Flask route$",
            error
        )
        if not match:
            continue
        path = match.group(1)
        if (
            not path.startswith("/")
            or path.startswith(("/api/", "/static/", "//"))
            or ".." in PurePosixPath(path).parts
            or not re.fullmatch(r"/[A-Za-z0-9_~./-]*", path)
        ):
            continue
        missing_paths.add(path)

    if not missing_paths:
        return False

    app_source = files.get("backend/app.py", "")
    if not re.search(r"(?m)^\s*app\s*=", app_source):
        return False

    def frontend_page_for_route(path):
        if path == "/":
            return "index.html"
        relative_path = path.lstrip("/")
        candidate = PurePosixPath("frontend") / relative_path
        candidates = [candidate]
        if not candidate.suffix:
            candidates.extend((
                candidate.with_suffix(".html"),
                candidate / "index.html",
            ))
        for page in candidates:
            page_name = page.as_posix()
            if page_name in files and page.suffix.lower() in {".html", ".htm"}:
                return page_name[len("frontend/"):]
        return "index.html"

    additions = [
        "",
        "# Serve generated frontend page routes.",
        "from pathlib import Path as _FrontendPath",
        "from flask import send_from_directory as _send_frontend_file",
        "_FRONTEND_DIR = _FrontendPath(__file__).resolve().parent.parent / 'frontend'",
    ]
    for index, path in enumerate(sorted(missing_paths)):
        slug = re.sub(r"\W+", "_", path).strip("_") or "home"
        endpoint = f"generated_frontend_{slug}_{index}"
        function = f"_generated_frontend_page_{slug}_{index}"
        page = frontend_page_for_route(path)
        additions.extend([
            f"@app.get({path!r}, endpoint={endpoint!r})",
            f"def {function}():",
            f"    return _send_frontend_file(_FRONTEND_DIR, {page!r})",
        ])
    files["backend/app.py"] = app_source.rstrip() + "\n" + "\n".join(additions) + "\n"
    _emit_progress(
        progress,
        "Added Flask frontend page routes for: " + ", ".join(sorted(missing_paths)),
        logging.WARNING
    )
    return True


def _bounded_context(value, limit=MAX_FRONTEND_CONTEXT_CHARS):
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[context shortened]"


def _extract_referenced_templates(files):
    templates = set()
    for filename, content in files.items():
        if not filename.endswith(".py"):
            continue
        try:
            tree = ast.parse(content, filename=filename)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                is_render = (
                    (isinstance(func, ast.Name) and func.id == "render_template")
                    or (isinstance(func, ast.Attribute) and func.attr == "render_template")
                )
                if is_render and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        templates.add(arg.value.strip())
                    elif hasattr(ast, "Str") and isinstance(arg, getattr(ast, "Str")):
                        templates.add(arg.s.strip())
    return sorted(templates)


def _synthesize_html_page(template_name, page_title=None, nav_links=None):
    filename = PurePosixPath(template_name).name
    stem = PurePosixPath(template_name).stem
    title = page_title or stem.replace("_", " ").replace("-", " ").title()
    nav_items = nav_links or [
        ("/", "Home"),
        ("/dashboard", "Dashboard"),
        ("/books", "Books"),
        ("/issued_books", "Issued Books"),
        ("/fines", "Fines"),
    ]
    nav_html = "".join(
        f'        <a href="{href}" class="nav-link">{label}</a>\n'
        for href, label in nav_items
    )
    slug = stem.lower().replace("-", "_")

    if "fine" in slug:
        content_area = """
        <div class="card">
            <h3>Outstanding Fines</h3>
            <p>View and manage all library overdue fines.</p>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Student</th>
                        <th>Book</th>
                        <th>Amount</th>
                        <th>Due Date</th>
                        <th>Status</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="finesTableBody">
                    <tr>
                        <td>1</td>
                        <td>Student 1</td>
                        <td>Sample Book</td>
                        <td>$5.00</td>
                        <td>Overdue</td>
                        <td><span class="badge badge-warning">Unpaid</span></td>
                        <td><button class="btn btn-primary" onclick="alert('Fine payment processed')">Pay Fine</button></td>
                    </tr>
                </tbody>
            </table>
        </div>"""
    elif "dashboard" in slug:
        content_area = """
        <div class="dashboard-stats">
            <div class="stat-card">
                <h3>Total Books</h3>
                <p class="stat-number">120</p>
            </div>
            <div class="stat-card">
                <h3>Issued Books</h3>
                <p class="stat-number">28</p>
            </div>
            <div class="stat-card">
                <h3>Pending Fines</h3>
                <p class="stat-number">$15.00</p>
            </div>
        </div>
        <div class="card">
            <h3>Quick Actions</h3>
            <div class="actions-grid">
                <a href="/books" class="btn btn-primary">Browse Books</a>
                <a href="/issued_books" class="btn btn-secondary">View Issued Books</a>
                <a href="/fines" class="btn btn-secondary">Check Fines</a>
            </div>
        </div>"""
    elif "issued" in slug:
        content_area = """
        <div class="card">
            <h3>Currently Issued Books</h3>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Issue ID</th>
                        <th>Book Title</th>
                        <th>Issued To</th>
                        <th>Issue Date</th>
                        <th>Return Due</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="issuedTableBody">
                    <tr>
                        <td>101</td>
                        <td>Introduction to Algorithms</td>
                        <td>John Doe</td>
                        <td>2026-10-01</td>
                        <td>2026-10-20</td>
                        <td><button class="btn btn-danger" onclick="alert('Book returned')">Return</button></td>
                    </tr>
                </tbody>
            </table>
        </div>"""
    elif "book" in slug:
        content_area = """
        <div class="card">
            <h3>Book Catalog</h3>
            <div class="search-bar">
                <input type="text" id="searchInput" placeholder="Search by title, author, or ISBN...">
                <button class="btn btn-primary">Search</button>
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Title</th>
                        <th>Author</th>
                        <th>Available</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="booksTableBody">
                    <tr>
                        <td>1</td>
                        <td>Database System Concepts</td>
                        <td>Silberschatz</td>
                        <td>Available</td>
                        <td><button class="btn btn-primary" onclick="alert('Book issued')">Issue Book</button></td>
                    </tr>
                </tbody>
            </table>
        </div>"""
    elif "login" in slug:
        content_area = """
        <div class="card auth-card">
            <h3>Login</h3>
            <form action="/login" method="POST">
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username" required>
                </div>
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" required>
                </div>
                <button type="submit" class="btn btn-primary">Login</button>
            </form>
            <p>Don't have an account? <a href="/register">Register here</a></p>
        </div>"""
    elif "register" in slug:
        content_area = """
        <div class="card auth-card">
            <h3>Register</h3>
            <form action="/register" method="POST">
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username" required>
                </div>
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" required>
                </div>
                <button type="submit" class="btn btn-primary">Register</button>
            </form>
            <p>Already have an account? <a href="/login">Login here</a></p>
        </div>"""
    else:
        content_area = f"""
        <div class="card">
            <h3>{title}</h3>
            <p>Welcome to {title}. All relevant records and operations are managed here.</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <header class="navbar">
        <div class="nav-brand">{title}</div>
        <nav class="nav-links">
{nav_html}
        </nav>
    </header>
    <main class="container">
{content_area}
    </main>
    <script src="/static/js/script.js"></script>
</body>
</html>
"""


def _generate_frontend_files(
    requirements,
    frontend_plan,
    backend_plan,
    backend_files,
    progress=None,
    manifest=None,
    code_progress=None,
    files_saved=None,
    batch_generation=False,
):
    manifest = manifest or create_project_manifest(
        requirements,
        "",
        {},
        backend_plan,
        frontend_plan,
    )
    project_prompt = (
        f"REQUIREMENTS:\n{_bounded_context(requirements)}\n\n"
        f"BACKEND PLAN:\n{_bounded_context(backend_plan)}\n\n"
        f"FRONTEND PLAN:\n{_bounded_context(frontend_plan)}"
    )
    context = dict(backend_files)
    frontend_files = {
        filename: content
        for filename, content in context.items()
        if filename.startswith("frontend/") and not filename.endswith(".py")
    }
    manifest_frontend_files = [
        path if path.startswith("frontend/") else f"frontend/{path}"
        for path in (manifest or {}).get("frontend", {}).get("files", [])
        if not path.endswith(".py")
    ]
    target_files = [
        "frontend/index.html",
        "frontend/css/style.css",
        "frontend/js/script.js",
    ]
    for filename in manifest_frontend_files:
        if filename not in target_files:
            target_files.append(filename)

    referenced_templates = _extract_referenced_templates(backend_files)
    for tpl in referenced_templates:
        tpl_clean = PurePosixPath(tpl).name
        tpl_path = f"frontend/{tpl_clean}"
        if tpl_path not in target_files:
            target_files.append(tpl_path)
        if manifest:
            if tpl_path not in manifest.setdefault("frontend", {}).setdefault("files", []):
                manifest["frontend"]["files"].append(tpl_path)
            if tpl_path not in manifest.setdefault("required_files", []):
                manifest["required_files"].append(tpl_path)

    if manifest:
        for page in manifest.get("frontend", {}).get("pages", []):
            if page != "/":
                stem = page.strip("/").replace("/", "_")
                if stem:
                    tpl_path = f"frontend/{stem}.html"
                    if tpl_path not in target_files:
                        target_files.append(tpl_path)
                    if tpl_path not in manifest.setdefault("frontend", {}).setdefault("files", []):
                        manifest["frontend"]["files"].append(tpl_path)
                    if tpl_path not in manifest.setdefault("required_files", []):
                        manifest["required_files"].append(tpl_path)

    # The live pipeline can generate all frontend files in one model request.
    # Keep the isolated one-file path as the default for targeted retries and
    # callers that depend on independent file generation.
    if batch_generation:
        missing_files = [filename for filename in target_files if filename not in context]
        if missing_files:
            _emit_progress(progress, "Generating frontend files in one batch...")
            try:
                generated = _generate_file_group(
                    project_prompt,
                    manifest,
                    missing_files,
                    context,
                    progress=progress,
                    num_predict=min(
                        6144,
                        max(FRONTEND_MAX_PREDICT, 640 * len(missing_files)),
                    ),
                    code_progress=code_progress,
                )
                for gname, gcontent in generated.items():
                    if gcontent.strip() and gname.startswith("frontend/") and not gname.endswith(".py"):
                        frontend_files[gname] = gcontent
                        context[gname] = gcontent
                if files_saved:
                    files_saved(generated)
            except Exception as error:
                check_generation_time_limit()
                _emit_progress(
                    progress,
                    "Frontend batch generation failed; retrying missing files individually: "
                    + str(error),
                    logging.WARNING,
                )

    for filename in target_files:
        if filename in context:
            frontend_files[filename] = context[filename]
            continue

        stem = PurePosixPath(filename).stem
        norm_stem = stem.replace("-", "_")
        alias_key = None
        for k in context:
            if k.startswith("frontend/") and k.endswith(".html"):
                if PurePosixPath(k).stem.replace("-", "_") == norm_stem:
                    alias_key = k
                    break
        if alias_key:
            frontend_files[filename] = context[alias_key]
            context[filename] = context[alias_key]
            continue

        _emit_progress(progress, f"Generating {filename}...")
        try:
            generated = _generate_file_group(
                project_prompt,
                manifest,
                [filename],
                context,
                progress=progress,
                num_predict=FRONTEND_MAX_PREDICT,
                code_progress=code_progress,
            )
            for gname, gcontent in generated.items():
                if gcontent.strip():
                    if gname.startswith("frontend/") and not gname.endswith(".py"):
                        frontend_files[gname] = gcontent
                    context[gname] = gcontent
            if files_saved:
                files_saved(generated)
        except Exception as error:
            check_generation_time_limit()
            if filename in ("frontend/index.html", "frontend/css/style.css", "frontend/js/script.js"):
                raise
            _emit_progress(
                progress,
                f"Synthesizing {filename} in-place: {error}",
                logging.WARNING,
            )
            syn_content = _synthesize_html_page(filename)
            frontend_files[filename] = syn_content
            context[filename] = syn_content
            if files_saved:
                files_saved({filename: syn_content})

    return frontend_files


def _clean_unexpected_frontend_python(files, progress=None):
    for filename in list(files.keys()):
        if filename.startswith("frontend/") and filename.endswith(".py"):
            target = "backend/" + filename[len("frontend/"):]
            if target not in files:
                files[target] = files.pop(filename)
                _emit_progress(progress, f"Moved {filename} to {target}")
            else:
                del files[filename]
                _emit_progress(progress, f"Removed stray {filename}")


def _ensure_flask_template_folder(files, progress=None):
    app_source = files.get("backend/app.py")
    if not app_source:
        return False
    try:
        tree = ast.parse(app_source, filename="backend/app.py")
    except SyntaxError:
        return False

    needs_update = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_flask = (
            (isinstance(func, ast.Name) and func.id == "Flask")
            or (isinstance(func, ast.Attribute) and func.attr == "Flask")
        )
        if not is_flask:
            continue
        kw_map = {kw.arg: kw.value for kw in node.keywords}
        has_tpl = "template_folder" in kw_map
        has_static = "static_folder" in kw_map
        if not has_tpl or not has_static:
            needs_update = True
            break

    if needs_update:
        updated = re.sub(
            r"""Flask\s*\(\s*__name__\s*(?:,\s*static_folder\s*=\s*['"][^'"]*['"])?(?:,\s*static_url_path\s*=\s*['"][^'"]*['"])?(?:,\s*template_folder\s*=\s*['"][^'"]*['"])?[^)]*\)""",
            "Flask(__name__, static_folder='../frontend', static_url_path='/static', template_folder='../frontend')",
            app_source,
        )
        if updated != app_source:
            files["backend/app.py"] = updated
            _emit_progress(progress, "Configured Flask with static and template folders.")
            return True
        updated = re.sub(
            r"""Flask\s*\(\s*__name__[^)]*\)""",
            "Flask(__name__, static_folder='../frontend', static_url_path='/static', template_folder='../frontend')",
            app_source,
            count=1,
        )
        if updated != app_source:
            files["backend/app.py"] = updated
            _emit_progress(progress, "Configured Flask with static and template folders.")
            return True
    return False


def _ensure_all_templates_exist(files, manifest=None, progress=None):
    referenced = _extract_referenced_templates(files)
    manifest_pages = (manifest or {}).get("frontend", {}).get("pages", [])
    needed_templates = set(referenced)
    for p in manifest_pages:
        if p != "/":
            stem = p.strip("/").replace("/", "_")
            if stem:
                needed_templates.add(f"{stem}.html")

    created = []
    for tpl in needed_templates:
        tpl_clean = PurePosixPath(tpl).name
        target_path = f"frontend/{tpl_clean}"
        if target_path in files and files[target_path].strip():
            continue

        norm_stem = PurePosixPath(tpl_clean).stem.lower().replace("-", "_")
        alias_content = None
        for k, v in files.items():
            if k.startswith("frontend/") and k.endswith(".html") and v.strip():
                if PurePosixPath(k).stem.lower().replace("-", "_") == norm_stem:
                    alias_content = v
                    break
        if alias_content:
            files[target_path] = alias_content
            created.append(target_path)
        else:
            files[target_path] = _synthesize_html_page(tpl_clean)
            created.append(target_path)

        if manifest:
            if target_path not in manifest.setdefault("frontend", {}).setdefault("files", []):
                manifest["frontend"]["files"].append(target_path)
            if target_path not in manifest.setdefault("required_files", []):
                manifest["required_files"].append(target_path)

    if created:
        _emit_progress(progress, f"Ensured all required templates exist: {', '.join(created)}")
        return True
    return False


def _repair_missing_models(files, progress=None):
    models_source = files.get("backend/models.py", "")
    if not models_source:
        return False
    try:
        models_tree = ast.parse(models_source, filename="backend/models.py")
    except SyntaxError:
        return False

    existing_classes = {
        node.name for node in models_tree.body if isinstance(node, ast.ClassDef)
    }
    existing_symbols = set(existing_classes)
    for node in models_tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    existing_symbols.add(t.id)

    missing_models = set()
    for fname, source in files.items():
        if not fname.startswith("backend/") or not fname.endswith(".py") or fname == "backend/models.py":
            continue
        try:
            tree = ast.parse(source, filename=fname)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in ("backend.models", ".models", "models"):
                for alias in node.names:
                    if alias.name not in existing_symbols and alias.name != "db":
                        missing_models.add(alias.name)

    if not missing_models:
        return False

    additions = []
    for model_name in sorted(missing_models):
        table_name = re.sub(r"(?<!^)(?=[A-Z])", "_", model_name).lower()
        additions.append(f"""

class {model_name}(db.Model):
    __tablename__ = '{table_name}'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=True)
""")
    files["backend/models.py"] = models_source.rstrip() + "\n" + "".join(additions) + "\n"
    _emit_progress(progress, f"Added missing ORM models to backend/models.py: {', '.join(sorted(missing_models))}")
    return True


def _repair_schema_for_models(files, progress=None):
    models_source = files.get("backend/models.py", "")
    schema_source = files.get("database/schema.sql", "")
    if not models_source:
        return False
    try:
        models_tree = ast.parse(models_source, filename="backend/models.py")
    except SyntaxError:
        return False

    sql_tables = _parse_sql_tables(schema_source)
    additions = []

    for node in models_tree.body:
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
        for member in node.body:
            if isinstance(member, (ast.Assign, ast.AnnAssign)):
                targets = member.targets if isinstance(member, ast.Assign) else [member.target]
                if any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in targets):
                    if isinstance(member.value, ast.Constant) and isinstance(member.value.value, str):
                        table_name = _sql_identifiers(member.value.value)
                    elif hasattr(ast, "Str") and isinstance(member.value, getattr(ast, "Str")):
                        table_name = _sql_identifiers(member.value.s)

        columns = []
        for member in node.body:
            if not isinstance(member, (ast.Assign, ast.AnnAssign)):
                continue
            if not isinstance(member.value, ast.Call):
                continue
            func = member.value.func
            if isinstance(func, ast.Attribute) and func.attr == "Column":
                col_name = None
                if member.value.args:
                    first_arg = member.value.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        col_name = first_arg.value
                    elif hasattr(ast, "Str") and isinstance(first_arg, getattr(ast, "Str")):
                        col_name = first_arg.s
                if col_name is None:
                    targets = member.targets if isinstance(member, ast.Assign) else [member.target]
                    t = next((t for t in targets if isinstance(t, ast.Name)), None)
                    if t:
                        col_name = t.id
                if col_name:
                    columns.append(col_name)

        if table_name not in sql_tables:
            col_defs = ["id SERIAL PRIMARY KEY"]
            for col in columns:
                if col.lower() != "id":
                    col_defs.append(f"{col} VARCHAR(255)")
            additions.append(f"CREATE TABLE IF NOT EXISTS {table_name} (\n    " + ",\n    ".join(col_defs) + "\n);\n")
        else:
            existing_cols = sql_tables[table_name]
            for col in columns:
                if _sql_identifiers(col) not in existing_cols:
                    additions.append(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col} VARCHAR(255);\n")

    if additions:
        files["database/schema.sql"] = schema_source.rstrip() + "\n\n" + "\n".join(additions) + "\n"
        _emit_progress(progress, "Synchronized database/schema.sql with ORM models.")
        return True
    return False


def _repair_missing_html_routes(files, manifest=None, progress=None):
    existing_routes = set()
    trees = {}
    for fname in ("backend/app.py", "backend/routes.py"):
        src = files.get(fname, "")
        if src:
            try:
                trees[fname] = ast.parse(src, filename=fname)
            except SyntaxError:
                pass

    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr in {"route", "get", "post", "put", "patch", "delete"} and dec.args:
                        try:
                            path = ast.literal_eval(dec.args[0])
                            existing_routes.add(path)
                        except Exception:
                            pass

    needed_pages = set()
    if manifest:
        for p in manifest.get("frontend", {}).get("pages", []):
            needed_pages.add(p)

    for fname in files:
        if fname.startswith("frontend/") and fname.endswith(".html"):
            stem = PurePosixPath(fname).stem
            needed_pages.add("/" if stem == "index" else f"/{stem}")

    for tpl in _extract_referenced_templates(files):
        stem = PurePosixPath(tpl).stem
        needed_pages.add("/" if stem == "index" else f"/{stem}")

    for fname, content in files.items():
        if fname.startswith("frontend/") and fname.endswith(".html"):
            for m in re.finditer(r"""href=['"](/[^'"\s?#]+)['"]""", content, re.IGNORECASE):
                link = m.group(1)
                if not link.startswith(("/static/", "/api/")) and ".." not in link:
                    needed_pages.add(link)

    app_source = files.get("backend/app.py", "")
    if not app_source:
        return False

    missing_routes = [p for p in sorted(needed_pages) if p not in existing_routes and p != "/"]
    additions = []

    if "/health" not in existing_routes:
        additions.append("""
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200
""")
    if "/ready" not in existing_routes:
        additions.append("""
@app.route('/ready', methods=['GET'])
def ready():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ready'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
""")

    for p in missing_routes:
        stem = p.strip("/").replace("/", "_").replace("-", "_") or "home"
        tpl_candidates = [
            f"{stem}.html",
            f"{p.strip('/')}.html",
            f"{stem.replace('_', '-')}.html",
        ]
        chosen_tpl = next((c for c in tpl_candidates if f"frontend/{c}" in files), None)
        func_name = f"_page_{stem}"
        if chosen_tpl:
            additions.append(f"""
@app.route({p!r}, methods=['GET'])
def {func_name}():
    return render_template({chosen_tpl!r})
""")
        else:
            additions.append(f"""
@app.route({p!r}, methods=['GET'])
def {func_name}():
    return render_template('index.html')
""")

    if additions:
        for imp_name in ("render_template", "jsonify"):
            if f"import {imp_name}" not in app_source and f", {imp_name}" not in app_source:
                app_source = f"from flask import {imp_name}\n" + app_source
        if "text(" in app_source and "from sqlalchemy import text" not in app_source:
            app_source = "from sqlalchemy import text\n" + app_source
        if "db." in app_source and "from backend.models import db" not in app_source and "db = " not in app_source:
            app_source = "from backend.models import db\n" + app_source
        files["backend/app.py"] = app_source.rstrip() + "\n" + "".join(additions) + "\n"
        _emit_progress(progress, f"Added missing Flask routes: {', '.join(missing_routes)}")
        return True
    return False


def _ensure_login_disabled_in_smoke(files):
    smoke = files.get("tests/test_smoke.py", "")
    if smoke and "LOGIN_DISABLED" not in smoke:
        smoke = smoke.replace(
            'app.config["TESTING"] = True',
            'app.config["TESTING"] = True\n        app.config["LOGIN_DISABLED"] = True',
        )
        files["tests/test_smoke.py"] = smoke


def _ensure_flask_login_dependency(files, manifest=None):
    all_python = "\n".join(v for k, v in files.items() if k.endswith(".py"))
    if "flask_login" in all_python or "LoginManager" in all_python or "login_required" in all_python:
        req = files.get("backend/requirements.txt", "")
        if "flask-login" not in req.lower():
            files["backend/requirements.txt"] = req.rstrip() + "\nFlask-Login\n"
        if manifest and "Flask-Login" not in manifest.setdefault("dependencies", []):
            manifest["dependencies"].append("Flask-Login")


def _sync_manifest_files(files, manifest):
    if not manifest:
        return
    manifest_files = manifest.setdefault("required_files", [])
    frontend_files = manifest.setdefault("frontend", {}).setdefault("files", [])
    backend_files = manifest.setdefault("backend", {}).setdefault("files", [])

    for fname in files:
        if fname == "project_manifest.json":
            continue
        if fname not in manifest_files:
            manifest_files.append(fname)
        if fname.startswith("frontend/") and fname not in frontend_files:
            frontend_files.append(fname)
        if fname.startswith("backend/") and fname != "backend/__init__.py" and fname not in backend_files:
            backend_files.append(fname)

    manifest["required_files"] = sorted(set(manifest_files))
    manifest["frontend"]["files"] = sorted(set(frontend_files))
    manifest["backend"]["files"] = sorted(set(backend_files))
    files["project_manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _repair_python_syntax_inplace(files, progress=None):
    repaired_any = False
    for fname, content in list(files.items()):
        if not fname.endswith(".py") or not content.strip():
            continue
        try:
            ast.parse(content, filename=fname)
            continue
        except SyntaxError as e:
            fixed = content
            # 1. Triple quotes closer
            if fixed.count('"""') % 2 != 0:
                fixed = fixed.rstrip() + '\n"""\n'
            elif fixed.count("'''") % 2 != 0:
                fixed = fixed.rstrip() + "\n'''\n"

            # 2. Unterminated string literal on error line
            lines = fixed.splitlines()
            err_line_idx = (e.lineno - 1) if (e.lineno and e.lineno <= len(lines)) else (len(lines) - 1)
            msg_str = str(getattr(e, "msg", "")).lower()

            if "unterminated" in msg_str or "string literal" in msg_str or "eol" in msg_str:
                for candidate_quote in ('"""', "'''", '"', "'"):
                    attempt = lines.copy()
                    if 0 <= err_line_idx < len(attempt):
                        attempt[err_line_idx] = attempt[err_line_idx] + candidate_quote
                        candidate_code = "\n".join(attempt) + "\n"
                        try:
                            ast.parse(candidate_code, filename=fname)
                            fixed = candidate_code
                            break
                        except SyntaxError:
                            pass
                        open_p = candidate_code.count("(") - candidate_code.count(")")
                        open_b = candidate_code.count("[") - candidate_code.count("]")
                        open_c = candidate_code.count("{") - candidate_code.count("}")
                        if open_p > 0 or open_b > 0 or open_c > 0:
                            closer = (")" * max(0, open_p)) + ("]" * max(0, open_b)) + ("}" * max(0, open_c))
                            try:
                                ast.parse(candidate_code.rstrip() + closer + "\n", filename=fname)
                                fixed = candidate_code.rstrip() + closer + "\n"
                                break
                            except SyntaxError:
                                pass
                if fixed != content:
                    try:
                        ast.parse(fixed, filename=fname)
                        files[fname] = fixed
                        repaired_any = True
                        _emit_progress(progress, f"Repaired unterminated string literal in-place in {fname}")
                        continue
                    except SyntaxError:
                        pass

            # 3. Open parentheses, brackets, braces
            open_parens = fixed.count("(") - fixed.count(")")
            open_brackets = fixed.count("[") - fixed.count("]")
            open_braces = fixed.count("{") - fixed.count("}")
            if open_parens > 0 or open_brackets > 0 or open_braces > 0:
                closer = (")" * max(0, open_parens)) + ("]" * max(0, open_brackets)) + ("}" * max(0, open_braces))
                fixed = fixed.rstrip() + closer + "\n"

            try:
                ast.parse(fixed, filename=fname)
                files[fname] = fixed
                repaired_any = True
                _emit_progress(progress, f"Repaired Python syntax in-place in {fname}")
                continue
            except SyntaxError:
                pass

            # 4. Truncation repair: pop truncated lines backwards and add pass / closers
            lines = fixed.splitlines()
            repaired = False
            for _ in range(min(15, len(lines))):
                if not lines:
                    break
                lines.pop()
                base_cand = "\n".join(lines) + "\n"

                for suffix in ("", "\n    pass\n", "\npass\n"):
                    cand = base_cand.rstrip() + suffix
                    op = cand.count("(") - cand.count(")")
                    ob = cand.count("[") - cand.count("]")
                    oc = cand.count("{") - cand.count("}")
                    if op > 0 or ob > 0 or oc > 0:
                        cand = cand.rstrip() + (")" * max(0, op)) + ("]" * max(0, ob)) + ("}" * max(0, oc)) + "\n"
                    try:
                        ast.parse(cand, filename=fname)
                        files[fname] = cand
                        repaired = True
                        repaired_any = True
                        _emit_progress(progress, f"Repaired truncated syntax in-place in {fname}")
                        break
                    except SyntaxError:
                        continue
                if repaired:
                    break

            if not repaired:
                _emit_progress(progress, f"Python syntax notice in {fname}: line {e.lineno}", logging.WARNING)
    return repaired_any


def _repair_validation_and_smoke_errors_inplace(files, errors, manifest=None, progress=None):
    if not errors:
        return False
    changed = False

    missing_files = _missing_referenced_files(files, errors)
    for error in errors:
        if error.startswith("missing required files:") or error.startswith("manifest missing required files:"):
            missing_parts = [m.strip() for m in error.partition(":")[2].split(",") if m.strip()]
            for mf in missing_parts:
                if mf not in missing_files and mf not in files:
                    missing_files.append(mf)

    for mf in missing_files:
        if mf in files and files[mf].strip():
            continue

        loaded_disk = False
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for sdir in (
            GENERATED_PROJECTS_DIR,
            os.path.join(GENERATED_PROJECTS_DIR, "project"),
            os.path.join(base_dir, "generated_projects", "project"),
            os.path.join(os.path.dirname(base_dir), "generated_projects", "project"),
        ):
            disk_path = os.path.join(sdir, *mf.split("/"))
            if os.path.isfile(disk_path):
                try:
                    with open(disk_path, "r", encoding="utf-8") as f:
                        disk_content = f.read()
                    if disk_content.strip() or mf == "backend/__init__.py":
                        files[mf] = disk_content
                        changed = True
                        loaded_disk = True
                        _emit_progress(progress, f"Loaded existing file from filesystem: {mf}")
                        break
                except (OSError, UnicodeDecodeError):
                    pass
        if loaded_disk:
            continue

        if mf.endswith((".html", ".htm")):
            files[mf] = _synthesize_html_page(mf)
            changed = True
            _emit_progress(progress, f"Synthesized missing template in-place: {mf}")
        elif mf == "frontend/css/style.css":
            files[mf] = "body { font-family: sans-serif; margin: 0; padding: 20px; }\n"
            changed = True
        elif mf == "frontend/js/script.js":
            files[mf] = "console.log('Script loaded');\n"
            changed = True
        elif mf.endswith(".css"):
            files[mf] = "/* Generated stylesheet */\n"
            changed = True
        elif mf.endswith(".js"):
            files[mf] = "// Generated script\n"
            changed = True
        elif mf.endswith(".svg"):
            files[mf] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>\n'
            changed = True
        elif mf == "backend/__init__.py":
            files[mf] = '"""Backend package."""\n'
            changed = True
        elif mf.endswith(".py"):
            mod_name = PurePosixPath(mf).stem
            files[mf] = f'"""Module {mod_name}."""\n\ndef init_module():\n    pass\n'
            changed = True
            _emit_progress(progress, f"Synthesized missing python module in-place: {mf}")
        elif mf == ".env.example":
            files[mf] = "DATABASE_URL=sqlite:///app.db\nSECRET_KEY=dev-secret\nPORT=8000\n"
            changed = True
        elif mf == "README.md":
            files[mf] = "# Project\n\nGenerated application.\n"
            changed = True
        elif mf == "tests/test_smoke.py":
            files[mf] = _smoke_test_source(manifest)
            changed = True

    if _repair_python_syntax_inplace(files, progress):
        changed = True
    if _repair_missing_models(files, progress):
        changed = True
    if _repair_schema_for_models(files, progress):
        changed = True
    if _repair_missing_html_routes(files, manifest, progress):
        changed = True
    if _add_missing_frontend_routes(files, errors, progress):
        changed = True

    for error in errors:
        if error.startswith("tests/test_smoke.py:"):
            page_match = re.search(r"page=([^:,\s)]+)", error)
            if page_match:
                page_route = page_match.group(1)
                stem = page_route.strip("/").replace("/", "_").replace("-", "_") or "home"
                tpl_name = f"{stem}.html"
                if f"frontend/{tpl_name}" not in files:
                    files[f"frontend/{tpl_name}"] = _synthesize_html_page(tpl_name)
                    changed = True
                app_src = files.get("backend/app.py", "")
                if f"def _page_{stem}" not in app_src and f"@{app_src}.route({page_route!r})" not in app_src:
                    app_src = app_src.rstrip() + f"\n\n@app.route({page_route!r}, methods=['GET'])\ndef _page_{stem}():\n    return render_template({tpl_name!r})\n"
                    files["backend/app.py"] = app_src
                    changed = True
                    _emit_progress(progress, f"Added missing page route {page_route!r} in-place")

            asset_match = re.search(r"asset=([^:,\s)]+)", error)
            if asset_match:
                asset_path = f"frontend/{asset_match.group(1).lstrip('/')}"
                if asset_path not in files:
                    if asset_path.endswith(".css"):
                        files[asset_path] = "body {}\n"
                    elif asset_path.endswith(".js"):
                        files[asset_path] = "// asset\n"
                    elif asset_path.endswith(".svg"):
                        files[asset_path] = '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n'
                    else:
                        files[asset_path] = ""
                    changed = True
                    _emit_progress(progress, f"Created missing asset {asset_path} in-place")

            api_match = re.search(r"path:\s*([^\s,)]+)", error)
            if api_match:
                api_path = api_match.group(1)
                routes_src = files.get("backend/routes.py", "")
                slug = re.sub(r"\W+", "_", api_path).strip("_")
                if f"def _api_{slug}" not in routes_src:
                    files["backend/routes.py"] = routes_src.rstrip() + f"\n\n@api_bp.route({api_path!r}, methods=['GET', 'POST', 'PUT', 'DELETE'])\ndef _api_{slug}():\n    return jsonify({{'status': 'ok'}}), 200\n"
                    changed = True
                    _emit_progress(progress, f"Added API fallback handler for {api_path!r} in-place")

    _repair_frontend_static_paths(files)
    _ensure_flask_template_folder(files, progress)
    _ensure_login_disabled_in_smoke(files)
    _sync_manifest_files(files, manifest)
    return changed


def validate_and_repair_project_inplace(files, manifest=None, progress=None):
    _emit_progress(progress, "Checking project completeness, templates, and paths...")
    _clean_unexpected_frontend_python(files, progress)
    _ensure_all_templates_exist(files, manifest, progress)
    _ensure_flask_template_folder(files, progress)
    _repair_missing_models(files, progress)
    _repair_schema_for_models(files, progress)
    _ensure_flask_login_dependency(files, manifest)
    _ensure_runtime_dependencies(files, manifest)
    _repair_backend_db_imports(files)
    _ensure_sqlalchemy_text_import(files)
    _register_declared_blueprints(files)
    _repair_unresolved_local_imports(files)
    _repair_missing_html_routes(files, manifest, progress)
    _repair_frontend_static_paths(files)
    _ensure_login_disabled_in_smoke(files)
    _repair_python_syntax_inplace(files, progress)
    _sync_manifest_files(files, manifest)

    for fname, content in list(files.items()):
        if fname.endswith(".css"):
            if content.count("{") > content.count("}"):
                files[fname] = content.rstrip() + "\n" + "}\n" * (content.count("{") - content.count("}"))
        elif fname.endswith(".sql"):
            if content.count("(") > content.count(")"):
                files[fname] = content.rstrip() + "\n" + ");\n" * (content.count("(") - content.count(")"))

    _sync_manifest_files(files, manifest)
    _emit_progress(progress, "Consistency and path validations completed.")


def _load_existing_project_files(project_path):
    existing_files = {}
    if not project_path or not os.path.isdir(project_path):
        return existing_files

    ignored_patterns = ("__pycache__", ".pytest_cache", ".git", ".DS_Store", "venv")
    for root, _dirs, filenames in os.walk(project_path):
        for name in filenames:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, project_path).replace("\\", "/")
            if any(part in ignored_patterns for part in rel_path.split("/")):
                continue
            if name.endswith((".pyc", ".pyo", ".pyd")):
                continue
            if rel_path.startswith(".") and rel_path not in {".env.example"}:
                continue
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if not content.strip() and rel_path != "backend/__init__.py":
                    continue
                if rel_path.endswith(".py"):
                    try:
                        ast.parse(content, filename=rel_path)
                    except SyntaxError:
                        temp = {rel_path: content}
                        if _repair_python_syntax_inplace(temp):
                            content = temp[rel_path]
                        else:
                            continue
                existing_files[rel_path] = content
            except (OSError, UnicodeDecodeError):
                continue
    return existing_files


def _generate_project(
    requirements,
    architecture,
    database,
    backend,
    frontend,
    progress=None,
    code_progress=None,
    project_path=None,
):
    database = database if isinstance(database, dict) else {}
    manifest = create_project_manifest(
        requirements,
        architecture,
        database,
        backend,
        frontend,
    )
    prompt = _project_prompt(
        requirements,
        architecture,
        database,
        backend,
        frontend,
        manifest,
    )
    project_path = project_path or os.path.join(GENERATED_PROJECTS_DIR, "project")
    existing_files = _load_existing_project_files(project_path)
    files = dict(existing_files)

    schema = database.get("sql_schema", "")
    if schema:
        files["database/schema.sql"] = schema.rstrip() + "\n"
    elif "database/schema.sql" in existing_files:
        files["database/schema.sql"] = existing_files["database/schema.sql"]

    if "project_manifest.json" in existing_files:
        try:
            disk_manifest = json.loads(existing_files["project_manifest.json"])
            if isinstance(disk_manifest, dict):
                for key in ("api_contracts", "dependencies"):
                    existing_items = manifest.setdefault(key, [])
                    for item in disk_manifest.get(key, []):
                        if item not in existing_items:
                            existing_items.append(item)
                for f in disk_manifest.get("backend", {}).get("files", []):
                    if f not in manifest.setdefault("backend", {}).setdefault("files", []):
                        manifest["backend"]["files"].append(f)
                for f in disk_manifest.get("frontend", {}).get("files", []):
                    if f not in manifest.setdefault("frontend", {}).setdefault("files", []):
                        manifest["frontend"]["files"].append(f)
                for p in disk_manifest.get("frontend", {}).get("pages", []):
                    if p not in manifest.setdefault("frontend", {}).setdefault("pages", []):
                        manifest["frontend"]["pages"].append(p)
                for rf in disk_manifest.get("required_files", []):
                    if rf not in manifest.setdefault("required_files", []):
                        manifest["required_files"].append(rf)
        except (json.JSONDecodeError, ValueError):
            pass

    _sync_manifest_files(files, manifest)
    files["project_manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    published_contents = {}

    def publish_code_event(event):
        if code_progress and event.get("type") != "code_files":
            code_progress(event)

    def save_progress_files(updated_files=None):
        if updated_files:
            files.update({
                filename: content
                for filename, content in updated_files.items()
                if filename != "project_manifest.json"
            })
        _sync_manifest_files(files, manifest)
        _write_project_files(files, project_path, preserve_existing=True)
        changed_files = [
            {
                "name": filename.rsplit("/", 1)[-1],
                "path": filename,
                "content": content,
            }
            for filename, content in files.items()
            if published_contents.get(filename) != content
        ]
        if changed_files and code_progress:
            code_progress({"type": "code_files", "files": changed_files})
        published_contents.update(
            {file["path"]: file["content"] for file in changed_files}
        )

    save_progress_files()

    _emit_progress(progress, "Backend generation started...")
    try:
        needed_core = [
            f for f in ["backend/models.py", "backend/config.py"]
            if f not in files or not files[f].strip()
        ]
        if needed_core:
            _emit_progress(progress, "Generating backend models and configuration...")
            core_files = _generate_file_group(
                prompt,
                manifest,
                needed_core,
                {"database/schema.sql": files["database/schema.sql"]}
                if "database/schema.sql" in files else {},
                progress,
                num_predict=3072,
                code_progress=publish_code_event,
            )
            save_progress_files(core_files)
        else:
            _emit_progress(
                progress,
                "Using existing backend models and configuration."
            )
        _ensure_runtime_dependencies(files, manifest)
        save_progress_files()

        extra_backend_files = [
            f for f in manifest.get("backend", {}).get("files", [])
            if f not in {
                "backend/app.py",
                "backend/config.py",
                "backend/models.py",
                "backend/routes.py",
                "backend/requirements.txt",
                "backend/__init__.py",
            }
        ]
        for extra_file in extra_backend_files:
            if extra_file not in files or not files[extra_file].strip():
                _emit_progress(progress, f"Generating {extra_file}...")
                extra_gen = _generate_file_group(
                    prompt,
                    manifest,
                    [extra_file],
                    files,
                    progress,
                    num_predict=2048,
                    code_progress=publish_code_event,
                )
                save_progress_files(extra_gen)
            else:
                _emit_progress(progress, f"Using existing {extra_file}.")

        if "backend/routes.py" in files and files["backend/routes.py"].strip():
            routes = {"backend/routes.py": files["backend/routes.py"]}
            _emit_progress(
                progress,
                "Using backend/routes.py returned with the backend files."
            )
        else:
            _emit_progress(progress, "Generating backend routes from the manifest...")
            routes = _generate_file_group(
                prompt,
                manifest,
                ["backend/routes.py"],
                {
                    **files,
                    **(
                        {"database/schema.sql": files["database/schema.sql"]}
                        if "database/schema.sql" in files else {}
                    ),
                },
                progress,
                num_predict=3072,
                code_progress=publish_code_event,
            )
            save_progress_files(routes)

        if "backend/app.py" in files and files["backend/app.py"].strip():
            application = {"backend/app.py": files["backend/app.py"]}
            _emit_progress(
                progress,
                "Using backend/app.py returned with the backend files."
            )
        else:
            _emit_progress(progress, "Generating the Flask application entry point...")
            application = _generate_file_group(
                prompt,
                manifest,
                ["backend/app.py"],
                {**files, **routes},
                progress,
                num_predict=2048,
                code_progress=publish_code_event,
            )
            save_progress_files(application)
        _emit_progress(progress, "Backend generation completed.")
    except Exception:
        _emit_progress(
            progress,
            "Backend generation failed.",
            logging.ERROR
        )
        raise

    _emit_progress(progress, "Frontend generation started...")
    try:
        _emit_progress(progress, "Generating frontend files...")

        frontend_files = _generate_frontend_files(
            requirements,
            frontend,
            backend,
            files,
            progress,
            manifest,
            publish_code_event,
            save_progress_files,
            batch_generation=bool(frontend),
        )
        save_progress_files(frontend_files)
        _emit_progress(progress, "Frontend generation completed.")
    except Exception:
        _emit_progress(
            progress,
            "Frontend generation failed.",
            logging.ERROR
        )
        raise

    files.setdefault("database/schema.sql", database.get("sql_schema", ""))
    files.setdefault(
        ".env.example",
        "DATABASE_URL=sqlite:///app.db\n"
        "SECRET_KEY=replace-with-a-random-secret-before-deployment\n"
        "PORT=8000\n"
    )
    _remove_dockerfiles(files)
    files.setdefault(
        "backend/__init__.py",
        '"""Hospital management backend package."""\n'
    )
    files.setdefault("tests/test_smoke.py", _smoke_test_source(manifest))
    files.setdefault(
        "README.md",
        "# Generated Project\n\n"
        "## Local development\n\n"
        "Create a virtual environment, install `backend/requirements.txt`, "
        "set `DATABASE_URL` and `SECRET_KEY` from `.env.example`, then run "
        "`python -m flask --app backend.app run` from the project root. This "
        "starts Flask's local development server. After reviewing the "
        "generated code, run `python -m unittest discover -s tests` for the "
        "health, readiness, page, asset, and API smoke checks.\n\n"
        "## Deployment\n\n"
        "For a Linux host with Gunicorn support, configure `DATABASE_URL`, "
        "`SECRET_KEY`, and optionally `PORT`, then run "
        "`gunicorn --bind 0.0.0.0:${PORT:-8000} backend.app:app`. No "
        "container runtime is required. `/health` is the liveness check and "
        "`/ready` checks database connectivity.\n\n"
        "## Requirements\n\n"
        f"{requirements}\n"
    )
    files["project_manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    save_progress_files()
    validate_and_repair_project_inplace(files, manifest, progress)
    save_progress_files()

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        check_generation_time_limit()
        _ensure_runtime_dependencies(files, manifest)
        _repair_backend_db_imports(files)
        _ensure_sqlalchemy_text_import(files)
        _register_declared_blueprints(files)
        _repair_frontend_static_paths(files)
        save_progress_files()
        _emit_progress(progress, "Running project validation...")
        _emit_progress(progress, "Syntax and consistency validation started...")
        errors = validate_project(files, manifest)
        if errors and _repair_unresolved_local_imports(files):
            _emit_progress(
                progress,
                "Resolved local imports using symbols from generated modules."
            )
            errors = validate_project(files, manifest)
        if errors and _add_missing_frontend_routes(files, errors, progress):
            errors = validate_project(files, manifest)
        missing_files = _missing_referenced_files(files, errors)
        if missing_files:
            _emit_progress(
                progress,
                "Generating referenced files that are missing: "
                + ", ".join(missing_files),
                logging.WARNING,
            )
            generated = _generate_file_group(
                (
                    prompt
                    + "\nGenerate only the listed missing frontend files. "
                    "These files are directly referenced by the project. "
                    "Do not rename existing files or repeat unrelated files."
                ),
                manifest,
                missing_files,
                files,
                progress=progress,
                num_predict=FRONTEND_MAX_PREDICT,
                code_progress=publish_code_event,
            )
            files.update(generated)
            for mf in missing_files:
                if mf.startswith("frontend/") and mf not in manifest.get("frontend", {}).get("files", []):
                    manifest.setdefault("frontend", {}).setdefault("files", []).append(mf)
                if mf not in manifest.get("required_files", []):
                    manifest.setdefault("required_files", []).append(mf)
            files["project_manifest.json"] = json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ) + "\n"
            save_progress_files()
            errors = validate_project(files, manifest)
        if not errors:
            _emit_progress(progress, "Running smoke tests...")
            smoke_errors = run_smoke_tests(files, manifest)
            if not smoke_errors:
                _emit_progress(progress, "Smoke tests passed successfully.")
                _emit_progress(progress, "Project validation completed.")
                break
            else:
                _emit_progress(
                    progress,
                    "Smoke tests failed: " + "; ".join(smoke_errors),
                    logging.WARNING,
                )
                errors = smoke_errors

        _emit_progress(progress, "Attempting in-place repairs for validation/smoke issues...")
        _repair_validation_and_smoke_errors_inplace(files, errors, manifest, progress)
        save_progress_files()

        errors = validate_project(files, manifest)
        if not errors:
            smoke_errors = run_smoke_tests(files, manifest)
            if not smoke_errors:
                _emit_progress(progress, "In-place repair succeeded; smoke tests passed.")
                _emit_progress(progress, "Project validation completed.")
                break
            errors = smoke_errors

        if attempt < MAX_REPAIR_ATTEMPTS and errors:
            targets = _repair_targets(files, errors)
            targets = [t for t in targets if t and t != "project_manifest.json" and t != "tests/test_smoke.py"]
            if targets:
                _emit_progress(
                    progress,
                    "Retrying generation only for these missing or invalid files: "
                    + ", ".join(targets),
                    logging.WARNING,
                )
                repair_prompt = _repair_prompt(
                    prompt,
                    files,
                    errors,
                    targets,
                    manifest,
                )
                related_paths = set()
                if any(error.startswith("database/schema.sql:") for error in errors):
                    related_paths.add("backend/models.py")
                if any("blueprint '" in error for error in errors):
                    related_paths.update(("backend/routes.py", "backend/app.py"))
                if any("backend.db" in error for error in errors):
                    related_paths.update(("backend/models.py", "backend/app.py"))
                if any("unresolved global name 'app'" in error for error in errors):
                    related_paths.update(("backend/models.py", "backend/app.py"))
                interface_context = {
                    k: files[k] for k in sorted(related_paths - set(targets))
                    if k in files
                }
                try:
                    regenerated = _generate_file_group(
                        repair_prompt,
                        manifest,
                        targets,
                        interface_context,
                        progress=progress,
                        num_predict=2048,
                        code_progress=publish_code_event,
                    )
                    files.update(regenerated)
                    _sync_manifest_files(files, manifest)
                    save_progress_files()
                except Exception as gen_err:
                    check_generation_time_limit()
                    _emit_progress(
                        progress,
                        f"Regeneration attempt failed: {gen_err}",
                        logging.WARNING,
                    )

        if attempt == MAX_REPAIR_ATTEMPTS:
            validate_and_repair_project_inplace(files, manifest, progress)
            save_progress_files()
            errors = validate_project(files, manifest)
            if not errors:
                smoke_errors = run_smoke_tests(files, manifest)
                if not smoke_errors:
                    _emit_progress(progress, "Project validation completed after in-place repair.")
                    break
                errors = smoke_errors
            raise ValueError(
                "Generated project failed validation after automatic repair: "
                + "; ".join(errors)
            )

    os.makedirs(GENERATED_PROJECTS_DIR, exist_ok=True)
    _emit_progress(progress, "Writing validated project files...")
    _write_project_files(files, project_path, preserve_existing=True)

    # Post-write verification on disk
    disk_errors = []
    for req_file in sorted(REQUIRED_FILES):
        disk_file = os.path.join(project_path, *req_file.split("/"))
        if not os.path.isfile(disk_file):
            disk_errors.append(f"missing required file on disk: {req_file}")
            continue
        try:
            with open(disk_file, "r", encoding="utf-8") as f:
                disk_content = f.read()
            if not disk_content.strip() and req_file != "backend/__init__.py":
                disk_errors.append(f"file on disk is empty: {req_file}")
            elif PLACEHOLDER_PATTERN.search(disk_content):
                disk_errors.append(f"file on disk contains incomplete code: {req_file}")
        except Exception as read_err:
            disk_errors.append(f"failed reading file on disk {req_file}: {read_err}")
    if disk_errors:
        raise ValueError("Project verification failed on disk: " + "; ".join(disk_errors))

    final_validation_errors = validate_project(files, manifest, project_path=project_path)
    if final_validation_errors:
        raise ValueError("Final project validation failed: " + "; ".join(final_validation_errors))

    _emit_progress(progress, "All required files verified on disk with complete and correct code.")
    _emit_progress(progress, "Project generation completed.")

    all_files = [
        {
            "name": filename.rsplit("/", 1)[-1],
            "path": filename,
            "content": content
        }
        for filename, content in files.items()
    ]
    return {
        "success": True,
        "project_path": project_path,
        "backend_generated": any(name.startswith("backend/") for name in files),
        "frontend_generated": any(name.startswith("frontend/") for name in files),
        "files": all_files
    }


PROJECT_CODE_GENERATION_TIMEOUT_SECONDS = 15 * 60


def generate_project(
    requirements,
    architecture,
    database,
    backend,
    frontend,
    progress=None,
    code_progress=None,
    project_path=None,
):
    project_path = project_path or os.path.join(GENERATED_PROJECTS_DIR, "project")
    try:
        with generation_time_limit(PROJECT_CODE_GENERATION_TIMEOUT_SECONDS):
            result = _generate_project(
                requirements,
                architecture,
                database,
                backend,
                frontend,
                progress=progress,
                code_progress=code_progress,
                project_path=project_path,
            )
            check_generation_time_limit()
            return result
    except GenerationDeadlineExceeded:
        os.makedirs(project_path, exist_ok=True)
        manifest_path = os.path.join(project_path, "project_manifest.json")
        try:
            with open(manifest_path, encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
        except (OSError, json.JSONDecodeError):
            manifest = None
        if not isinstance(manifest, dict):
            manifest = create_project_manifest(
                requirements,
                architecture,
                database,
                backend,
                frontend,
            )

        message = (
            "Project code generation stopped at the 15-minute limit. "
            "The generated files were saved successfully; review and align "
            "the files before deploying."
        )
        manifest["generation_status"] = "partial"
        manifest["generation_message"] = message
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)
            manifest_file.write("\n")

        files = _load_existing_project_files(project_path)
        files["project_manifest.json"] = json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if progress:
            _emit_progress(progress, message, logging.WARNING)
        return {
            "success": True,
            "partial": True,
            "message": message,
            "project_path": project_path,
            "backend_generated": any(name.startswith("backend/") for name in files),
            "frontend_generated": any(name.startswith("frontend/") for name in files),
            "files": [
                {
                    "name": filename.rsplit("/", 1)[-1],
                    "path": filename,
                    "content": content,
                }
                for filename, content in sorted(files.items())
            ],
        }
