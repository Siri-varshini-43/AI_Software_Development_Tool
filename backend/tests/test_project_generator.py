import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agents.project_generator import (
    GENERATED_PROJECTS_DIR,
    _generate_file_group,
    _generate_frontend_files,
    _missing_referenced_files,
    _parse_project_files,
    _remove_dockerfiles,
    _add_missing_frontend_routes,
    _ensure_runtime_dependencies,
    _repair_prompt,
    _repair_backend_db_imports,
    _repair_frontend_static_paths,
    _repair_targets,
    _repair_unresolved_local_imports,
    _ensure_sqlalchemy_text_import,
    _register_declared_blueprints,
    _write_project_files,
    generate_project,
    migrate_legacy_project,
)
from agents.project_manifest import create_project_manifest
from agents.project_validator import _route_errors
from agents.project_validator import validate_project


class ParseProjectFilesTests(unittest.TestCase):
    def test_manifest_captures_files_entities_contracts_pages_and_dependencies(self):
        manifest = create_project_manifest(
            "Build a patient portal.",
            "Use PostgreSQL.",
            {
                "sql_schema": (
                    "CREATE TABLE patients (id INTEGER); "
                    "CREATE TABLE appointments (id INTEGER);"
                )
            },
            "POST /api/patients/register",
            "Page /login",
        )

        self.assertEqual(manifest["project_name"], "build_a_patient_portal")
        self.assertIn("backend/app.py", manifest["backend"]["files"])
        self.assertEqual(
            manifest["database"]["tables"],
            ["appointments", "patients"],
        )
        self.assertEqual(
            manifest["api_contracts"],
            [{"method": "POST", "path": "/api/patients/register"}],
        )
        self.assertEqual(manifest["frontend"]["pages"], ["/", "/login"])
        self.assertIn("psycopg2-binary", manifest["dependencies"])

    def test_parser_rejects_fallback_output_and_enforces_expected_paths(self):
        with self.assertRaisesRegex(ValueError, "generated_output.txt"):
            _parse_project_files(
                "### generated_output.txt\n```text\nnot a project\n```"
            )

        with self.assertRaisesRegex(ValueError, "missing expected files"):
            _parse_project_files(
                "### backend/app.py\n```python\napp = None\n```",
                expected_files={"backend/app.py", "backend/routes.py"},
            )

    def test_parser_rejects_unrequested_files_in_a_generation_group(self):
        with self.assertRaisesRegex(ValueError, "unexpected files"):
            _parse_project_files(
                "### backend/app.py\n```python\napp = None\n```\n"
                "### README.md\n```markdown\nother\n```",
                expected_files={"backend/app.py"},
            )

    @patch("agents.project_generator.generate_response")
    def test_file_group_keeps_requested_files_from_full_project_response(
        self,
        generate_response
    ):
        generate_response.return_value = (
            "### backend/models.py\n```python\n"
            "db = object()\n"
            "```\n"
            "### backend/app.py\n```python\n"
            "app = object()\n"
            "```\n"
            "### README.md\n```markdown\n"
            "# Extra response content\n"
            "```\n"
        )
        progress = []

        files = _generate_file_group(
            "Build a project.",
            {},
            ["backend/models.py"],
            {},
            progress=lambda message, level: progress.append(message),
        )

        self.assertEqual(
            files,
            {
                "backend/models.py": "db = object()\n",
                "backend/app.py": "app = object()\n",
                "README.md": "# Extra response content\n",
            },
        )
        self.assertEqual(generate_response.call_count, 1)
        self.assertTrue(any("reusing additional generated project files" in message.casefold()
                            for message in progress))

    @patch("agents.project_generator.generate_response")
    def test_file_group_retries_if_a_requested_file_is_missing(
        self,
        generate_response
    ):
        generate_response.side_effect = [
            "### backend/app.py\n```python\napp = None\n```\n",
            "### backend/models.py\n```python\ndb = object()\n```\n",
        ]

        files = _generate_file_group(
            "Build a project.",
            {},
            ["backend/models.py"],
            {},
        )

        self.assertEqual(
            files,
            {
                "backend/app.py": "app = None\n",
                "backend/models.py": "db = object()\n",
            },
        )
        self.assertEqual(generate_response.call_count, 2)

    @patch("agents.project_generator.generate_response")
    def test_frontend_group_reuses_files_already_returned_by_backend(
        self,
        generate_response
    ):
        existing = {
            "frontend/index.html": "<main>Ready</main>\n",
            "frontend/css/style.css": "main { color: navy; }\n",
            "frontend/js/script.js": "console.log('ready');\n",
        }

        generated = _generate_frontend_files(
            "Build a project.",
            "A simple frontend.",
            "A Flask API.",
            existing,
            manifest={},
        )

        self.assertEqual(generated, existing)
        generate_response.assert_not_called()

    @patch("agents.project_generator.generate_response")
    def test_frontend_group_preserves_additional_pages_and_assets(
        self,
        generate_response
    ):
        existing = {
            "frontend/index.html": "<a href='login.html'>Login</a>\n",
            "frontend/login.html": "<main>Login</main>\n",
            "frontend/register.html": "<main>Register</main>\n",
            "frontend/css/style.css": "main { color: navy; }\n",
            "frontend/js/script.js": "console.log('ready');\n",
        }

        generated = _generate_frontend_files(
            "Build a project.",
            "A frontend with login and registration pages.",
            "A Flask API.",
            existing,
            manifest={},
        )

        self.assertEqual(generated, existing)
        generate_response.assert_not_called()

    def test_missing_local_asset_error_resolves_to_safe_generated_path(self):
        errors = [
            "frontend/index.html: referenced local file 'images/logo.svg' "
            "is missing; expected generated file 'frontend/images/logo.svg'",
            "frontend/index.html: referenced local file '../secrets.txt' "
            "is missing; expected generated file '../secrets.txt'",
        ]

        self.assertEqual(
            _missing_referenced_files({}, errors),
            ["frontend/images/logo.svg"],
        )

    @patch("agents.project_generator.generate_response")
    def test_file_group_streams_chunks_and_publishes_validated_file(
        self,
        generate_response
    ):
        source = "### backend/models.py\n```python\ndb = object()\n```\n"

        def stream_response(_prompt, on_chunk=None, **_options):
            on_chunk(source[:28])
            on_chunk(source[28:])
            return source

        generate_response.side_effect = stream_response
        events = []

        files = _generate_file_group(
            "Build a project.",
            {},
            ["backend/models.py"],
            {},
            code_progress=events.append,
        )

        self.assertEqual(files, {"backend/models.py": "db = object()\n"})
        self.assertEqual(events[0]["type"], "code_start")
        self.assertEqual(
            "".join(
                event["content"]
                for event in events
                if event["type"] == "code_chunk"
            ),
            source,
        )
        self.assertEqual(events[-1]["type"], "code_files")
        self.assertEqual(
            events[-1]["files"],
            [{"path": "backend/models.py", "content": "db = object()\n"}],
        )

    def test_generated_projects_directory_is_at_repository_root(self):
        repository_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        self.assertEqual(
            os.path.abspath(GENERATED_PROJECTS_DIR),
            os.path.join(repository_root, "generated_projects")
        )

    def test_legacy_project_migrates_without_overwriting_existing_project(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            legacy_path = os.path.join(temporary_directory, "legacy", "project")
            project_path = os.path.join(temporary_directory, "generated", "project")
            os.makedirs(legacy_path)
            with open(
                os.path.join(legacy_path, "README.md"),
                "w",
                encoding="utf-8"
            ) as legacy_file:
                legacy_file.write("existing project")

            self.assertTrue(migrate_legacy_project(legacy_path, project_path))
            self.assertFalse(migrate_legacy_project(legacy_path, project_path))

            with open(
                os.path.join(project_path, "README.md"),
                encoding="utf-8"
            ) as migrated_file:
                self.assertEqual(migrated_file.read(), "existing project")

    def test_repairs_unresolved_local_import_from_existing_module(self):
        files = {
            "backend/__init__.py": "",
            "backend/models.py": (
                "db = object()\n"
                "class Patient:\n"
                "    id = 1\n"
            ),
            "backend/routes.py": (
                "from backend import db, Patient\n"
                "from backend.db import db as database\n"
                "routes = object()\n"
            ),
        }

        changed = _repair_unresolved_local_imports(files)

        self.assertTrue(changed)
        self.assertIn(
            "from backend.models import db, Patient",
            files["backend/routes.py"]
        )
        self.assertIn(
            "from backend.models import db as database",
            files["backend/routes.py"]
        )
        self.assertFalse(
            any("backend.db" in error for error in validate_project(files))
        )

    def test_repairs_mixed_imports_without_creating_an_app_routes_cycle(self):
        files = {
            "backend/__init__.py": "",
            "backend/models.py": "db = object()\nclass Patient:\n    pass\n",
            "backend/app.py": "app = object()\n",
            "backend/routes.py": "from backend import app, db, Patient\n",
        }

        changed = _repair_unresolved_local_imports(files)

        self.assertTrue(changed)
        self.assertIn(
            "from backend import app\nfrom backend.models import db, Patient",
            files["backend/routes.py"]
        )
        self.assertFalse(
            any("circular local imports" in error
                for error in validate_project(files))
        )

    def test_runtime_dependencies_are_added_without_creating_dockerfile(self):
        files = {"backend/requirements.txt": "Flask\n"}

        _ensure_runtime_dependencies(files)

        self.assertIn("Flask-SQLAlchemy", files["backend/requirements.txt"])
        self.assertIn("gunicorn", files["backend/requirements.txt"])
        self.assertNotIn("Dockerfile", files)

    def test_repairs_backend_db_imports_to_the_models_extension(self):
        files = {
            "backend/models.py": (
                "from backend.db import db\n"
                "class Patient(db.Model):\n"
                "    id = db.Column(db.Integer, primary_key=True)\n"
            ),
            "backend/app.py": "from backend.db import db\n",
            "backend/routes.py": "from backend.db import db\n",
        }

        changed = _repair_backend_db_imports(files)

        self.assertTrue(changed)
        self.assertIn("db = SQLAlchemy()", files["backend/models.py"])
        self.assertNotIn("from backend.db import db", files["backend/models.py"])
        self.assertIn(
            "from backend.models import db",
            files["backend/app.py"]
        )
        self.assertIn(
            "from backend.models import db",
            files["backend/routes.py"]
        )
        self.assertFalse(
            any("backend.db" in error for error in validate_project(files))
        )

    def test_keeps_a_resolvable_backend_db_module_unchanged(self):
        files = {
            "backend/db.py": "db = object()\n",
            "backend/models.py": "from backend.db import db\n",
            "backend/app.py": "from backend.db import db\n",
        }

        self.assertFalse(_repair_backend_db_imports(files))
        self.assertEqual(files["backend/models.py"], "from backend.db import db\n")

    def test_adds_sqlalchemy_text_import_for_readiness_query(self):
        files = {
            "backend/app.py": (
                "from flask import Flask\n"
                "app = Flask(__name__)\n"
                "def ready():\n"
                "    return db.session.execute(text('SELECT 1'))\n"
            )
        }

        self.assertTrue(_ensure_sqlalchemy_text_import(files))
        self.assertIn("from sqlalchemy import text", files["backend/app.py"])

    def test_repairs_frontend_static_url_when_file_has_unique_nested_path(self):
        files = {
            "frontend/index.html": (
                '<link rel="stylesheet" href="/static/style.css">'
                '<script src="/static/script.js"></script>'
            ),
            "frontend/css/style.css": "body {}\n",
            "frontend/js/script.js": "console.log('ok');\n",
        }

        self.assertTrue(_repair_frontend_static_paths(files))
        self.assertIn(
            'href="/static/css/style.css"',
            files["frontend/index.html"]
        )
        self.assertIn(
            'src="/static/js/script.js"',
            files["frontend/index.html"]
        )
        self.assertFalse(
            any("static asset" in error for error in validate_project(files))
        )

    def test_registers_route_blueprints_once_in_application_module(self):
        files = {
            "backend/app.py": (
                "from flask import Flask\n"
                "app = Flask(__name__)\n"
            ),
            "backend/routes.py": (
                "from flask import Blueprint\n"
                "patients = Blueprint('patients', __name__)\n"
                "appointments = Blueprint('appointments', __name__)\n"
            ),
        }

        self.assertTrue(_register_declared_blueprints(files))
        errors = validate_project({
            **files,
            "backend/__init__.py": "",
            "backend/config.py": "class Config:\n    pass\n",
            "backend/models.py": "db = object()\n",
            "backend/requirements.txt": (
                "Flask\nFlask-SQLAlchemy\ngunicorn\n"
            ),
            "frontend/index.html": "<main>App</main>\n",
            "frontend/css/style.css": "body {}\n",
            "frontend/js/script.js": "console.log('ok');\n",
            "database/schema.sql": "CREATE TABLE patients (id INTEGER);\n",
            ".env.example": (
                "DATABASE_URL=sqlite:///app.db\nSECRET_KEY=replace-me\n"
            ),
            "README.md": "# App\n",
        })
        self.assertFalse(
            any("must be registered exactly once" in error for error in errors)
        )

    def test_model_authored_dockerfile_is_removed_case_insensitively(self):
        files = {
            "backend/app.py": "app = None\n",
            "dockerfile": "FROM python:3.12-slim\n",
        }

        _remove_dockerfiles(files)

        self.assertEqual(files, {"backend/app.py": "app = None\n"})

    def test_project_files_publish_complete_frontend_atomically(self):
        with tempfile.TemporaryDirectory() as output_dir:
            project_path = os.path.join(output_dir, "project")
            os.makedirs(os.path.join(project_path, "frontend", "css"))
            with open(
                os.path.join(project_path, "old.txt"),
                "w",
                encoding="utf-8"
            ) as previous:
                previous.write("old project")

            _write_project_files(
                {
                    "frontend/index.html": "<main>Ready</main>\n",
                    "frontend/css/style.css": "main { color: navy; }\n",
                    "frontend/js/script.js": "console.log('ready');\n",
                },
                project_path
            )

            self.assertTrue(
                os.path.isfile(
                    os.path.join(project_path, "frontend", "css", "style.css")
                )
            )
            self.assertFalse(os.path.exists(os.path.join(project_path, "old.txt")))
            self.assertEqual(set(os.listdir(output_dir)), {"project"})

    def test_project_file_checkpoint_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as output_dir:
            project_path = os.path.join(output_dir, "project")
            os.makedirs(project_path)
            with open(
                os.path.join(project_path, "README.md"),
                "w",
                encoding="utf-8",
            ) as previous:
                previous.write("previous contents")

            _write_project_files(
                {"backend/app.py": "app = None\n"},
                project_path,
                preserve_existing=True,
            )

            with open(
                os.path.join(project_path, "README.md"),
                encoding="utf-8",
            ) as previous:
                self.assertEqual(previous.read(), "previous contents")
            with open(
                os.path.join(project_path, "backend", "app.py"),
                encoding="utf-8",
            ) as generated:
                self.assertEqual(generated.read(), "app = None\n")

    def test_failed_project_publish_restores_last_successful_project(self):
        with tempfile.TemporaryDirectory() as output_dir:
            project_path = os.path.join(output_dir, "project")
            os.makedirs(project_path)
            previous_file = os.path.join(project_path, "README.md")
            with open(previous_file, "w", encoding="utf-8") as file:
                file.write("previous successful project")

            real_replace = os.replace
            replacement_count = 0

            def fail_staging_publish(source, destination):
                nonlocal replacement_count
                replacement_count += 1
                if replacement_count == 2:
                    raise OSError("simulated publish failure")
                real_replace(source, destination)

            with patch(
                "agents.project_generator.os.replace",
                side_effect=fail_staging_publish,
            ):
                with self.assertRaisesRegex(OSError, "simulated publish failure"):
                    _write_project_files(
                        {"README.md": "new project"},
                        project_path,
                    )

            with open(previous_file, encoding="utf-8") as file:
                self.assertEqual(file.read(), "previous successful project")
            self.assertEqual(os.listdir(output_dir), ["project"])

    @patch("agents.project_generator.generate_response")
    def test_generation_uses_manifest_and_small_stages_before_publish(
        self,
        generate_response
    ):
        core_response = (
            "### backend/models.py\n```python\n"
            "from flask_sqlalchemy import SQLAlchemy\n"
            "db = SQLAlchemy()\n"
            "class Patient(db.Model):\n"
            "    __tablename__ = 'patients'\n"
            "    id = db.Column(db.Integer, primary_key=True)\n"
            "```\n"
            "### backend/config.py\n```python\n"
            "import os\n"
            "class Config:\n"
            "    SECRET_KEY = os.environ.get('SECRET_KEY')\n"
            "    SQLALCHEMY_DATABASE_URI = os.environ.get("
            "'DATABASE_URL', 'sqlite:///app.db')\n"
            "```\n"
            "### backend/requirements.txt\n```text\n"
            "Flask\nFlask-SQLAlchemy\ngunicorn\n"
            "```\n"
        )
        routes_response = (
            "### backend/routes.py\n```python\n"
            "from flask import Blueprint\n"
            "from sqlalchemy import text\n"
            "from backend.models import db\n"
            "routes = Blueprint('routes', __name__)\n"
            "@routes.get('/health')\n"
            "def health():\n"
            "    return {'status': 'ok'}\n"
            "@routes.get('/ready')\n"
            "def ready():\n"
            "    db.session.execute(text('SELECT 1'))\n"
            "    return {'status': 'ready'}\n"
            "```\n"
        )
        app_response = (
            "### backend/app.py\n```python\n"
            "from flask import Flask, send_from_directory\n"
            "from backend.config import Config\n"
            "from backend.models import db\n"
            "from backend.routes import routes\n"
            "app = Flask(__name__, static_folder='../frontend', "
            "static_url_path='/static')\n"
            "app.config.from_object(Config)\n"
            "db.init_app(app)\n"
            "app.register_blueprint(routes)\n"
            "@app.get('/')\n"
            "def home():\n"
            "    return send_from_directory(app.static_folder, 'index.html')\n"
            "```\n"
        )
        generate_response.side_effect = [
            core_response,
            routes_response,
            app_response,
            (
                "### frontend/index.html\n```html\n"
                "<html><head><link rel=\"stylesheet\" href=\"css/style.css\">"
                "</head><body><main>Ready</main>"
                "<script src=\"js/script.js\"></script></body></html>\n"
                "```\n"
            ),
            "### frontend/css/style.css\n```css\nmain { color: navy; }\n```\n",
            "### frontend/js/script.js\n```javascript\nconsole.log('ready');\n```\n",
        ]

        with tempfile.TemporaryDirectory() as output_dir:
            with patch(
                "agents.project_generator.GENERATED_PROJECTS_DIR",
                output_dir
            ):
                result = generate_project(
                    "Build a small hospital application.",
                    {},
                    {"sql_schema": "CREATE TABLE patients (id INTEGER);"},
                    {},
                    {}
                )

            css_path = os.path.join(
                output_dir, "project", "frontend", "css", "style.css"
            )
            self.assertTrue(os.path.isfile(css_path))
            self.assertEqual(generate_response.call_count, 6)
            self.assertFalse(
                any(file["path"] == "Dockerfile" for file in result["files"])
            )
            self.assertTrue(
                any(file["path"] == "project_manifest.json" for file in result["files"])
            )
            self.assertTrue(all(
                "PROJECT MANIFEST" in call.args[0]
                or "shared project manifest" in call.args[0]
                for call in generate_response.call_args_list
            ))
            css_payload = next(
                file for file in result["files"]
                if file["path"] == "frontend/css/style.css"
            )
            self.assertEqual(css_payload["content"], "main { color: navy; }\n")

    @patch("agents.project_generator.generate_response")
    def test_full_project_response_is_saved_without_regenerating_each_group(
        self,
        generate_response
    ):
        from test_project_validator import valid_project

        project_files = valid_project()
        project_files.pop("backend/requirements.txt")
        project_response = "".join(
            f"### {filename}\n```text\n{content.rstrip()}\n```\n"
            for filename, content in project_files.items()
        )
        progress_events = []
        saved_manifest = []

        with tempfile.TemporaryDirectory() as output_dir:
            def generate_project_response(*_args, **_kwargs):
                manifest_path = os.path.join(
                    output_dir,
                    "project",
                    "project_manifest.json",
                )
                self.assertTrue(os.path.isfile(manifest_path))
                with open(manifest_path, encoding="utf-8") as manifest_file:
                    manifest = json.load(manifest_file)
                    self.assertEqual(manifest["manifest_version"], 1)
                    saved_manifest.append(manifest)
                return project_response

            generate_response.side_effect = generate_project_response
            with patch(
                "agents.project_generator.GENERATED_PROJECTS_DIR",
                output_dir
            ):
                result = generate_project(
                    "Build a small hospital application.",
                    {},
                    {"sql_schema": project_files["database/schema.sql"]},
                    {},
                    {},
                    code_progress=progress_events.append,
                )

            saved_app = os.path.join(
                output_dir, "project", "backend", "app.py"
            )
            saved_login = os.path.join(
                output_dir, "project", "frontend", "index.html"
            )
            self.assertTrue(os.path.isfile(saved_app))
            self.assertTrue(os.path.isfile(saved_login))
            self.assertTrue(os.path.isfile(os.path.join(
                output_dir, "project", "backend", "requirements.txt"
            )))
            self.assertEqual(generate_response.call_count, 1)
            self.assertEqual(
                {file["path"] for file in result["files"]},
                set(project_files) | {"backend/requirements.txt"},
            )
            first_file_event = next(
                event
                for event in progress_events
                if event["type"] == "code_files"
            )
            self.assertEqual(
                {file["path"] for file in first_file_event["files"]},
                {"database/schema.sql", "project_manifest.json"},
            )
            returned_manifest = next(
                file["content"]
                for file in result["files"]
                if file["path"] == "project_manifest.json"
            )
            self.assertEqual(json.loads(returned_manifest), saved_manifest[0])

    @patch("agents.project_generator.generate_response")
    def test_missing_referenced_asset_is_generated_and_saved(
        self,
        generate_response
    ):
        from test_project_validator import valid_project

        project_files = valid_project()
        project_files["frontend/index.html"] += (
            '<img src="images/logo.svg" alt="Logo">'
        )
        full_project_response = "".join(
            f"### {filename}\n```text\n{content.rstrip()}\n```\n"
            for filename, content in project_files.items()
        )
        logo_response = (
            "### frontend/images/logo.svg\n```svg\n"
            "<svg xmlns=\"http://www.w3.org/2000/svg\" "
            "viewBox=\"0 0 10 10\"><circle cx=\"5\" cy=\"5\" r=\"4\"/>"
            "</svg>\n```\n"
        )
        generate_response.side_effect = [full_project_response, logo_response]

        with tempfile.TemporaryDirectory() as output_dir:
            with patch(
                "agents.project_generator.GENERATED_PROJECTS_DIR",
                output_dir
            ):
                result = generate_project(
                    "Build a small hospital application.",
                    {},
                    {"sql_schema": project_files["database/schema.sql"]},
                    {},
                    {},
                )

            saved_logo = os.path.join(
                output_dir, "project", "frontend", "images", "logo.svg"
            )
            self.assertTrue(os.path.isfile(saved_logo))
            self.assertEqual(generate_response.call_count, 2)
            self.assertIn(
                "frontend/images/logo.svg",
                {file["path"] for file in result["files"]},
            )

    def test_does_not_guess_when_local_symbol_source_is_ambiguous(self):
        files = {
            "backend/__init__.py": "",
            "backend/first.py": "db = object()\n",
            "backend/second.py": "db = object()\n",
            "backend/routes.py": "from backend import db\n",
        }

        self.assertFalse(_repair_unresolved_local_imports(files))
        self.assertIn("from backend import db", files["backend/routes.py"])

    def test_duplicate_paths_keep_latest_complete_contents(self):
        warnings = []
        response = (
            "### backend/app.py\n"
            "```python\n"
            "print('first')\n"
            "```\n"
            "### backend\\APP.py\n"
            "```python\n"
            "print('latest')\n"
            "```\n"
        )

        files = _parse_project_files(
            response,
            lambda message, level: warnings.append((message, level))
        )

        self.assertEqual(files, {"backend/app.py": "print('latest')\n"})
        self.assertEqual(len(warnings), 1)
        self.assertIn("using its latest complete version", warnings[0][0])

    def test_project_prefix_and_path_separators_are_normalized(self):
        response = (
            "### project\\backend\\app.py\n"
            "```python\n"
            "print('ok')\n"
            "```\n"
        )

        self.assertEqual(
            _parse_project_files(response),
            {"backend/app.py": "print('ok')\n"}
        )

    def test_parent_directory_paths_are_rejected(self):
        response = (
            "### ../outside.py\n"
            "```python\n"
            "print('no')\n"
            "```\n"
        )

        with self.assertRaisesRegex(ValueError, "path is not allowed"):
            _parse_project_files(response)

    def test_missing_html_routes_target_the_flask_route_sources(self):
        files = {
            "frontend/index.html": '<a href="/">Home</a><a href="/login">Login</a>',
            "backend/app.py": "app = Flask(__name__)\n",
            "backend/routes.py": "app_routes = Blueprint('app_routes', __name__)\n",
        }
        errors = [
            "frontend/index.html: GET / has no matching Flask route",
            "frontend/index.html: GET /login has no matching Flask route",
        ]

        targets = _repair_targets(files, errors)

        self.assertEqual(
            targets,
            [
                "frontend/index.html",
                "backend/routes.py",
                "backend/app.py",
            ]
        )

    def test_blueprint_registration_validation_targets_application_and_routes(self):
        files = {
            "backend/app.py": "app = Flask(__name__)\n",
            "backend/routes.py": (
                "patient_routes = Blueprint('patients', __name__)\n"
            ),
        }

        targets = _repair_targets(
            files,
            [
                "backend/app.py: blueprint 'patient_routes' must be registered "
                "exactly once at module scope"
            ]
        )

        self.assertEqual(targets, ["backend/app.py", "backend/routes.py"])

    def test_schema_validation_targets_schema_and_orm_models(self):
        files = {
            "database/schema.sql": "CREATE TABLE patient (id INTEGER);\n",
            "backend/models.py": "class Patient:\n    pass\n",
        }

        targets = _repair_targets(
            files,
            ["database/schema.sql: table 'patient' for model 'Patient' is missing"]
        )

        self.assertEqual(targets, ["database/schema.sql", "backend/models.py"])

    def test_repair_prompt_requests_html_page_routes(self):
        files = {
            "frontend/index.html": '<a href="/register">Register</a>\n',
            "backend/app.py": "app = Flask(__name__)\n",
            "backend/routes.py": "app_routes = Blueprint('app_routes', __name__)\n",
        }
        errors = [
            "frontend/index.html: GET /register has no matching Flask route"
        ]
        targets = _repair_targets(files, errors)

        prompt = _repair_prompt("Build a hospital app.", files, errors, targets)

        self.assertIn("Add and register GET handlers", prompt)
        self.assertIn("frontend/index.html", prompt)
        self.assertIn("backend/routes.py", prompt)
        self.assertIn("/register", prompt)

    def test_repair_prompt_requires_implementations_not_comment_removal(self):
        files = {
            "backend/routes.py": (
                "# Placeholder for authentication logic\n"
                "def login():\n"
                "    return {'message': 'logged in'}\n"
            )
        }
        errors = [
            "backend/routes.py: placeholder or incomplete implementation detected"
        ]

        prompt = _repair_prompt(
            "Build a hospital system.",
            files,
            errors,
            ["backend/routes.py"]
        )

        self.assertIn("Replace incomplete handlers with real", prompt)
        self.assertIn("deleting a placeholder comment", prompt)

    def test_missing_frontend_page_routes_are_added_to_flask_app(self):
        files = {
            "backend/app.py": "from flask import Flask\napp = Flask(__name__)\n",
            "frontend/index.html": (
                '<a href="/">Home</a><a href="/login">Login</a>'
            ),
        }
        errors = [
            "frontend/index.html: GET / has no matching Flask route",
            "frontend/index.html: GET /login has no matching Flask route",
        ]

        changed = _add_missing_frontend_routes(files, errors)

        self.assertTrue(changed)
        self.assertIn("_FrontendPath(__file__).resolve().parent.parent", files["backend/app.py"])
        self.assertIn("@app.get('/', endpoint='generated_frontend_home_0')", files["backend/app.py"])
        self.assertIn("@app.get('/login', endpoint='generated_frontend_login_1')", files["backend/app.py"])
        self.assertFalse(
            any("has no matching Flask route" in error for error in _route_errors(files))
        )

    def test_generated_html_pages_get_extensionless_and_file_routes(self):
        files = {
            "backend/app.py": "from flask import Flask\napp = Flask(__name__)\n",
            "frontend/index.html": '<a href="/login">Log in</a>\n',
            "frontend/login.html": "<main>Login page</main>\n",
        }

        errors = _route_errors(files)
        self.assertTrue(any("GET /login has no matching Flask route" in error
                            for error in errors))
        self.assertTrue(any("GET /login.html has no matching Flask route" in error
                            for error in errors))
        self.assertTrue(_add_missing_frontend_routes(files, errors))

        route_errors = _route_errors(files)
        self.assertFalse(any("has no matching Flask route" in error
                             for error in route_errors))
        self.assertIn(
            "return _send_frontend_file(_FRONTEND_DIR, 'login.html')",
            files["backend/app.py"],
        )

    def test_frontend_page_route_repair_clears_project_validation_errors(self):
        files = {
            "backend/__init__.py": '"""Backend package."""\n',
            "backend/app.py": (
                "from flask import Flask\n"
                "from sqlalchemy import text\n"
                "from backend.config import Config\n"
                "from backend.models import db\n"
                "app = Flask(__name__, static_folder='../frontend', "
                "static_url_path='/static')\n"
                "app.config.from_object(Config)\n"
                "@app.get('/health')\n"
                "def health():\n"
                "    return {'status': 'ok'}\n"
                "@app.get('/ready')\n"
                "def ready():\n"
                "    db.session.execute(text('SELECT 1'))\n"
                "    return {'status': 'ready'}\n"
            ),
            "backend/config.py": (
                "import os\n"
                "class Config:\n"
                "    SECRET_KEY = os.environ.get('SECRET_KEY')\n"
                "    SQLALCHEMY_DATABASE_URI = os.environ.get("
                "'DATABASE_URL', 'sqlite:///app.db')\n"
            ),
            "backend/models.py": "db = object()\n",
            "backend/requirements.txt": "Flask\nFlask-SQLAlchemy\ngunicorn\n",
            "backend/routes.py": '"""API routes."""\n',
            "frontend/index.html": (
                '<a href="/">Home</a><a href="/login">Login</a>'
                '<a href="/register">Register</a>'
                '<link rel="stylesheet" href="css/style.css">'
                '<script src="js/script.js"></script>'
            ),
            "frontend/css/style.css": "body { color: navy; }\n",
            "frontend/js/script.js": "console.log('ready');\n",
            "tests/test_smoke.py": (
                "import unittest\n"
                "class SmokeTests(unittest.TestCase):\n"
                "    def test_smoke(self):\n"
                "        self.assertTrue(True)\n"
            ),
            "database/schema.sql": "CREATE TABLE patients (id INTEGER);\n",
            "project_manifest.json": json.dumps(
                create_project_manifest(
                    "A hospital app.",
                    {},
                    {"sql_schema": "CREATE TABLE patients (id INTEGER);"},
                    {},
                    {},
                )
            ),
            ".env.example": "DATABASE_URL=sqlite:///app.db\nSECRET_KEY=replace-me\n",
            "README.md": "# Hospital system\n",
        }

        errors = validate_project(files)
        self.assertEqual(
            sum("has no matching Flask route" in error for error in errors),
            3
        )

        self.assertTrue(_add_missing_frontend_routes(files, errors))

        self.assertEqual(validate_project(files), [])

    def test_missing_api_and_asset_urls_are_not_added_as_page_routes(self):
        files = {"backend/app.py": "app = Flask(__name__)\n"}
        errors = [
            "frontend/index.html: GET /api/patients has no matching Flask route",
            "frontend/index.html: GET /static/logo.svg has no matching Flask route",
        ]

        changed = _add_missing_frontend_routes(files, errors)

        self.assertFalse(changed)
        self.assertEqual(files["backend/app.py"], "app = Flask(__name__)\n")

    @patch("agents.project_generator.generate_response")
    def test_frontend_generation_retries_invalid_format(self, generate_response):
        generate_response.side_effect = [
            "I will create the frontend now.",
            (
                "### `frontend/index.html`\n```html\n"
                "<main>Hospital</main>\n"
                "<link rel=\"stylesheet\" href=\"css/style.css\">\n"
                "<script src=\"js/script.js\"></script>\n"
                "```\n"
            ),
            "### frontend/css/style.css\n```css\nmain { color: navy; }\n```\n",
            "### frontend/js/script.js\n```javascript\nconsole.log('ready');\n```\n",
        ]
        progress = []
        backend_files = {"backend/routes.py": "routes\n"}

        files = _generate_frontend_files(
            "Build a hospital management frontend.",
            "Render patient registration and appointment booking.",
            "POST /api/patients and GET /api/doctors",
            backend_files,
            lambda message, level: progress.append(message)
        )

        self.assertEqual(
            set(files),
            {
                "frontend/index.html",
                "frontend/css/style.css",
                "frontend/js/script.js",
            }
        )
        self.assertEqual(generate_response.call_count, 4)
        self.assertTrue(any("retrying" in message.casefold() for message in progress))
        self.assertNotIn(
            "I will create the frontend now.",
            generate_response.call_args_list[1].args[0]
        )
        self.assertLess(len(generate_response.call_args_list[1].args[0]), 10000)
        self.assertEqual(generate_response.call_args.kwargs["num_predict"], 1792)

    @patch("agents.project_generator.generate_response")
    def test_frontend_generation_retries_when_required_file_is_missing(
        self,
        generate_response
    ):
        generate_response.side_effect = [
            (
                "### frontend/README.md\n```text\nwrong file\n```\n"
            ),
            "### frontend/index.html\n```html\n<main>Hospital</main>\n```\n",
            "### frontend/css/style.css\n```css\nmain { color: navy; }\n```\n",
            "### frontend/js/script.js\n```javascript\nconsole.log('ready');\n```\n",
        ]

        files = _generate_frontend_files(
            "Build a hospital management frontend.",
            "Render patient registration.",
            "POST /api/patients",
            {"backend/routes.py": "routes\n"}
        )

        self.assertIn("frontend/css/style.css", files)
        self.assertEqual(generate_response.call_count, 4)

    @patch("agents.project_generator.generate_response")
    def test_frontend_generation_reports_exhausted_format_retries(
        self,
        generate_response
    ):
        generate_response.return_value = "No files were provided."

        with self.assertRaisesRegex(
            ValueError,
            "File group generation failed after 2 attempts"
        ):
            _generate_frontend_files(
                "Build a hospital management frontend.",
                "Render patient registration.",
                "POST /api/patients",
                {"backend/routes.py": "routes\n"}
            )

        self.assertEqual(generate_response.call_count, 2)

    @patch("agents.project_generator.generate_response")
    def test_frontend_generation_does_not_send_unbounded_context(
        self,
        generate_response
    ):
        generate_response.side_effect = [
            "### frontend/index.html\n```html\n<main>Hospital</main>\n```\n",
            "### frontend/css/style.css\n```css\nmain { color: navy; }\n```\n",
            "### frontend/js/script.js\n```javascript\nconsole.log('ready');\n```\n",
        ]

        _generate_frontend_files(
            "R" * 12000,
            "F" * 12000,
            "B" * 12000,
            {"backend/routes.py": "routes\n"}
        )

        prompt = generate_response.call_args_list[0].args[0]
        self.assertLess(len(prompt), 10000)
        self.assertIn("[context shortened]", prompt)


if __name__ == "__main__":
    unittest.main()
