import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agents.project_manifest import (
    create_project_manifest,
    validate_project_manifest,
)
from agents.project_generator import (
    _parse_project_files,
    _generate_file_group,
    _generate_frontend_files,
    _repair_targets,
    run_smoke_tests,
    generate_project,
)
from agents.project_validator import validate_project
from agents.file_parser import parse_and_save_files as file_parser_save
from agents.code_parser import parse_and_save_files as code_parser_save
from app import create_project_zip
from test_project_validator import valid_project


class SDLCManifestPipelineTests(unittest.TestCase):
    """
    Test Step 1: Project manifest defines all expected files, database entities,
    API contracts, dependencies, and frontend pages in structured JSON.
    """

    def test_manifest_extracts_all_pages_and_contracts_from_requirements(self):
        requirements = "Healthcare platform for patients and doctors with appointments and medical records."
        architecture = {
            "rest_apis": [
                {"method": "POST", "url": "/api/patient/register", "description": "Register patient"},
                {"method": "GET", "url": "/api/patient/appointments", "description": "Get appointments"},
                {"method": "POST", "url": "/api/appointment/book", "description": "Book appointment"},
            ],
            "modules": ["patients", "doctors", "appointments", "records"],
            "technology_stack": {"Database": "PostgreSQL"},
        }
        database = {
            "tables": ["patients", "doctors", "appointments", "records"],
            "sql_schema": (
                "CREATE TABLE patients (id SERIAL PRIMARY KEY, name VARCHAR(100));\n"
                "CREATE TABLE doctors (id SERIAL PRIMARY KEY, name VARCHAR(100));\n"
                "CREATE TABLE appointments (id SERIAL PRIMARY KEY, patient_id INT, doctor_id INT);\n"
                "CREATE TABLE records (id SERIAL PRIMARY KEY, patient_id INT, notes TEXT);\n"
            ),
        }
        frontend = {
            "pages": "1. index.html\n2. login.html\n3. register.html\n4. dashboard.html\n5. appointments.html"
        }
        backend = {
            "structure": "Flask backend with auth and appointments modules."
        }

        manifest = create_project_manifest(
            requirements,
            architecture,
            database,
            backend,
            frontend,
        )

        validate_project_manifest(manifest)

        # 1. API contracts extracted from architecture rest_apis
        contract_endpoints = {(c["method"], c["path"]) for c in manifest["api_contracts"]}
        self.assertIn(("POST", "/api/patient/register"), contract_endpoints)
        self.assertIn(("GET", "/api/patient/appointments"), contract_endpoints)
        self.assertIn(("POST", "/api/appointment/book"), contract_endpoints)

        # 2. Database tables extracted
        self.assertIn("patients", manifest["database"]["tables"])
        self.assertIn("doctors", manifest["database"]["tables"])
        self.assertIn("appointments", manifest["database"]["tables"])
        self.assertIn("records", manifest["database"]["tables"])

        # 3. All frontend pages identified and included in files and pages list
        expected_pages = {"/", "/login", "/register", "/dashboard", "/appointments"}
        self.assertTrue(expected_pages.issubset(set(manifest["frontend"]["pages"])))

        expected_frontend_files = {
            "frontend/index.html",
            "frontend/login.html",
            "frontend/register.html",
            "frontend/dashboard.html",
            "frontend/appointments.html",
            "frontend/css/style.css",
            "frontend/js/script.js",
        }
        self.assertTrue(expected_frontend_files.issubset(set(manifest["frontend"]["files"])))

        # 4. Required files includes all frontend pages, backend files, schema, etc.
        self.assertTrue(expected_frontend_files.issubset(set(manifest["required_files"])))
        self.assertIn("database/schema.sql", manifest["required_files"])
        self.assertIn("backend/app.py", manifest["required_files"])

    def test_manifest_validation_normalizes_relative_paths(self):
        sample_manifest = {
            "manifest_version": 1,
            "project_name": "healthcare_platform",
            "backend": {
                "framework": "Flask",
                "application": "backend.app:app",
                "files": ["app.py", "config.py", "models.py", "routes.py", "requirements.txt"],
            },
            "frontend": {
                "files": ["index.html", "style.css", "script.js"],
                "pages": ["/"],
            },
            "database": {
                "tables": ["patients", "doctors", "appointments", "records"],
                "schema_file": "database/schema.sql",
            },
            "api_contracts": [
                {"method": "POST", "path": "/api/patient/register"},
            ],
            "dependencies": ["Flask", "Flask-SQLAlchemy", "gunicorn"],
            "required_files": [
                "backend/app.py",
                "backend/config.py",
                "backend/models.py",
                "backend/routes.py",
                "backend/requirements.txt",
                "frontend/index.html",
                "frontend/style.css",
                "frontend/script.js",
                "database/schema.sql",
            ],
        }

        # Must validate without error
        validate_project_manifest(sample_manifest)


class SDLCParserSecurityTests(unittest.TestCase):
    """
    Test Step 3: Parse file paths and fenced code blocks, reject unsafe paths,
    detect missing expected files, and never treat fallback generated_output.txt
    as successful generation.
    """

    def test_parser_rejects_generated_output_txt_fallback(self):
        with self.assertRaisesRegex(ValueError, "generated_output.txt"):
            _parse_project_files("### generated_output.txt\n```text\nfallback\n```")

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "generated_output.txt"):
                file_parser_save("### generated_output.txt\n```text\nfallback\n```", temp_dir)

            with self.assertRaisesRegex(ValueError, "generated_output.txt"):
                code_parser_save("### generated_output.txt\n```text\nfallback\n```", temp_dir)

    def test_parser_rejects_unsafe_paths(self):
        unsafe_payloads = [
            "### ../etc/passwd\n```text\nevil\n```",
            "### C:/Windows/System32/evil.dll\n```text\nevil\n```",
            "### backend/../evil.py\n```python\nevil\n```",
        ]
        for payload in unsafe_payloads:
            with self.assertRaises(ValueError):
                _parse_project_files(payload)

            with tempfile.TemporaryDirectory() as temp_dir:
                with self.assertRaises(ValueError):
                    file_parser_save(payload, temp_dir)

    def test_parser_detects_missing_expected_files(self):
        content = "### backend/app.py\n```python\napp = None\n```\n"
        with self.assertRaisesRegex(ValueError, "missing expected files"):
            _parse_project_files(content, expected_files=["backend/app.py", "backend/models.py"])

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "missing expected files"):
                file_parser_save(content, temp_dir, expected_files=["backend/app.py", "backend/models.py"])


class SDLCUnitsAndValidationTests(unittest.TestCase):
    """
    Test Step 2, 4 & 5: Smaller units generation for all manifest files,
    smoke testing, and repairing only failing files.
    """

    @patch("agents.project_generator.generate_response")
    def test_frontend_generator_generates_all_pages_in_manifest(self, generate_response):
        manifest = {
            "manifest_version": 1,
            "required_files": [
                "frontend/index.html",
                "frontend/login.html",
                "frontend/dashboard.html",
                "frontend/css/style.css",
                "frontend/js/script.js",
            ],
            "frontend": {
                "files": [
                    "frontend/index.html",
                    "frontend/css/style.css",
                    "frontend/js/script.js",
                    "frontend/login.html",
                    "frontend/dashboard.html",
                ],
                "pages": ["/", "/login", "/dashboard"],
            },
        }

        generate_response.side_effect = [
            "### frontend/index.html\n```html\n<main>Index</main>\n```\n",
            "### frontend/css/style.css\n```css\nbody { color: blue; }\n```\n",
            "### frontend/js/script.js\n```javascript\nconsole.log('ready');\n```\n",
            "### frontend/login.html\n```html\n<main>Login</main>\n```\n",
            "### frontend/dashboard.html\n```html\n<main>Dashboard</main>\n```\n",
        ]

        files = _generate_frontend_files(
            "Healthcare portal",
            "Login and dashboard pages",
            "Flask API",
            {"backend/routes.py": "routes\n"},
            manifest=manifest,
        )

        self.assertIn("frontend/index.html", files)
        self.assertIn("frontend/login.html", files)
        self.assertIn("frontend/dashboard.html", files)
        self.assertIn("frontend/css/style.css", files)
        self.assertIn("frontend/js/script.js", files)
        self.assertEqual(generate_response.call_count, 5)

    def test_smoke_tests_execution_on_valid_project(self):
        # Build complete working Flask + SQLite project
        files = {
            "backend/__init__.py": '"""Backend"""\n',
            "backend/models.py": (
                "from flask_sqlalchemy import SQLAlchemy\n"
                "db = SQLAlchemy()\n"
                "class Patient(db.Model):\n"
                "    __tablename__ = 'patients'\n"
                "    id = db.Column(db.Integer, primary_key=True)\n"
                "    name = db.Column(db.String(100), nullable=False)\n"
            ),
            "backend/config.py": (
                "import os\n"
                "class Config:\n"
                "    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret')\n"
                "    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite://')\n"
            ),
            "backend/routes.py": (
                "from flask import Blueprint, jsonify, request\n"
                "from sqlalchemy import text\n"
                "from backend.models import db, Patient\n"
                "api_bp = Blueprint('api', __name__, url_prefix='/api')\n"
                "@api_bp.get('/patients')\n"
                "def get_patients():\n"
                "    patients = Patient.query.all()\n"
                "    return jsonify([{'id': p.id, 'name': p.name} for p in patients])\n"
                "@api_bp.post('/patient/register')\n"
                "def register_patient():\n"
                "    data = request.get_json() or {}\n"
                "    p = Patient(name=data.get('name', 'Anonymous'))\n"
                "    db.session.add(p)\n"
                "    db.session.commit()\n"
                "    return jsonify({'id': p.id, 'name': p.name}), 201\n"
            ),
            "backend/app.py": (
                "from flask import Flask, jsonify\n"
                "from sqlalchemy import text\n"
                "from backend.config import Config\n"
                "from backend.models import db\n"
                "from backend.routes import api_bp\n"
                "app = Flask(__name__, static_folder='../frontend', static_url_path='/static')\n"
                "app.config.from_object(Config)\n"
                "db.init_app(app)\n"
                "app.register_blueprint(api_bp)\n"
                "@app.get('/health')\n"
                "def health():\n"
                "    return jsonify({'status': 'ok'}), 200\n"
                "@app.get('/ready')\n"
                "def ready():\n"
                "    db.session.execute(text('SELECT 1'))\n"
                "    return jsonify({'status': 'ready'}), 200\n"
                "@app.get('/')\n"
                "def home():\n"
                "    return 'Home', 200\n"
            ),
            "backend/requirements.txt": "Flask\nFlask-SQLAlchemy\ngunicorn\n",
            "frontend/index.html": "<main>Home</main>",
            "frontend/css/style.css": "body { color: black; }",
            "frontend/js/script.js": "console.log('ready');",
            "database/schema.sql": "CREATE TABLE patients (id INTEGER PRIMARY KEY, name TEXT);",
            ".env.example": "DATABASE_URL=sqlite://\nSECRET_KEY=secret\n",
            "README.md": "# Healthcare Project",
            "project_manifest.json": json.dumps({
                "manifest_version": 1,
                "project_name": "healthcare_platform",
                "backend": {
                    "framework": "Flask",
                    "application": "backend.app:app",
                    "files": ["backend/app.py", "backend/config.py", "backend/models.py", "backend/routes.py", "backend/requirements.txt"],
                },
                "frontend": {
                    "files": ["frontend/index.html", "frontend/css/style.css", "frontend/js/script.js"],
                    "pages": ["/"],
                },
                "database": {
                    "tables": ["patients"],
                    "schema_file": "database/schema.sql",
                },
                "api_contracts": [
                    {"method": "GET", "path": "/api/patients"},
                    {"method": "POST", "path": "/api/patient/register"},
                ],
                "dependencies": ["Flask", "Flask-SQLAlchemy", "gunicorn"],
                "required_files": [
                    "backend/__init__.py",
                    "backend/app.py",
                    "backend/config.py",
                    "backend/models.py",
                    "backend/routes.py",
                    "backend/requirements.txt",
                    "frontend/index.html",
                    "frontend/css/style.css",
                    "frontend/js/script.js",
                    "tests/test_smoke.py",
                    "database/schema.sql",
                    ".env.example",
                    "README.md",
                    "project_manifest.json",
                ],
            }),
        }

        manifest = json.loads(files["project_manifest.json"])
        from agents.project_generator import _smoke_test_source
        files["tests/test_smoke.py"] = _smoke_test_source(manifest)

        # 1. Static validation passes
        static_errors = validate_project(files, manifest)
        self.assertEqual(static_errors, [])

        # 2. Smoke tests run against live in-memory SQLite and pass!
        smoke_errors = run_smoke_tests(files, manifest)
        self.assertEqual(smoke_errors, [])

    def test_repair_targets_identifies_failing_files_for_smoke_and_syntax_errors(self):
        files = {
            "backend/models.py": "db = None\n",
            "backend/routes.py": "routes = None\n",
            "backend/app.py": "app = None\n",
        }
        errors = [
            "backend/models.py: Python syntax error at line 5: invalid syntax",
            "tests/test_smoke.py: FAIL: test_api_contracts (path: /api/patients 404 Not Found)",
        ]

        targets = _repair_targets(files, errors)
        self.assertIn("backend/models.py", targets)
        self.assertIn("backend/routes.py", targets)
        self.assertIn("backend/app.py", targets)


class SDLCPackagingTests(unittest.TestCase):
    """
    Test Step 6: Package only validated projects, atomic ZIP creation,
    and keeping previous valid archive intact on failure.
    """

    def test_packaging_includes_all_validated_files_and_preserves_archive(self):
        files = valid_project()
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = os.path.join(temp_dir, "project")
            for rel_path, content in files.items():
                dest = os.path.join(project_path, *rel_path.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(content)

            with patch("app.GENERATED_PROJECTS_DIR", temp_dir):
                zip_path = create_project_zip(project_path)
                self.assertTrue(os.path.isfile(zip_path))

                with open(zip_path, "rb") as zf:
                    good_archive = zf.read()

                # Break syntax
                broken_file = os.path.join(project_path, "backend", "app.py")
                with open(broken_file, "w", encoding="utf-8") as f:
                    f.write("def broken(:\n")

                with self.assertRaisesRegex(ValueError, "unvalidated project"):
                    create_project_zip(project_path)

                # Ensure good archive remains intact
                with open(zip_path, "rb") as zf:
                    self.assertEqual(zf.read(), good_archive)


if __name__ == "__main__":
    unittest.main()
