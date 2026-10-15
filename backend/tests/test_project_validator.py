import json
import shutil
import unittest

from agents.project_validator import (
    _orm_schema_errors,
    _python_import_errors,
    validate_project,
)


def valid_project():
    return {
        "backend/__init__.py": '"""Backend package."""\n',
        "backend/app.py": (
            "from flask import Flask\n"
            "from sqlalchemy import text\n"
            "from backend.config import Config\n"
            "from backend.models import db\n"
            "app = Flask(__name__, static_folder='../frontend', "
            "static_url_path='/static')\n"
            "app.config.from_object(Config)\n"
            "@app.get('/')\n"
            "def home():\n"
            "    return {'status': 'ok'}\n"
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
        "project_manifest.json": json.dumps({
            "manifest_version": 1,
            "required_files": [
                "backend/__init__.py",
                "backend/app.py",
                "backend/config.py",
                "backend/models.py",
                "backend/requirements.txt",
                "backend/routes.py",
                "frontend/index.html",
                "frontend/css/style.css",
                "frontend/js/script.js",
                "tests/test_smoke.py",
                "database/schema.sql",
                ".env.example",
                "README.md",
                "project_manifest.json",
            ],
            "backend": {
                "framework": "Flask",
                "application": "backend/app.py",
                "files": [
                    "backend/__init__.py",
                    "backend/app.py",
                    "backend/config.py",
                    "backend/models.py",
                    "backend/requirements.txt",
                    "backend/routes.py",
                ],
            },
            "frontend": {
                "pages": ["/"],
                "files": [
                    "frontend/index.html",
                    "frontend/css/style.css",
                    "frontend/js/script.js",
                ],
            },
            "database": {
                "tables": [],
                "schema_file": "database/schema.sql",
            },
            "api_contracts": [],
            "dependencies": [],
        }),
        "frontend/index.html": (
            '<link rel="stylesheet" href="css/style.css">'
            '<script src="js/script.js"></script>'
        ),
        "frontend/css/style.css": "body { color: black; }\n",
        "frontend/js/script.js": "console.log('ready');\n",
        "tests/test_smoke.py": (
            "import unittest\n"
            "class SmokeTests(unittest.TestCase):\n"
            "    def test_smoke(self):\n"
            "        self.assertTrue(True)\n"
        ),
        "database/schema.sql": "CREATE TABLE patients (id INTEGER);\n",
        ".env.example": "DATABASE_URL=sqlite:///app.db\nSECRET_KEY=replace-me\n",
        "README.md": "# Hospital system\n",
    }


class ProjectValidatorTests(unittest.TestCase):
    def test_accepts_complete_deployable_project(self):
        self.assertEqual(validate_project(valid_project()), [])

    def test_detects_missing_local_symbol_and_import_cycle(self):
        files = {
            "backend/app.py": "from backend.routes import app_routes\n",
            "backend/routes.py": "from backend.app import app\n",
        }

        errors = _python_import_errors(files)

        self.assertTrue(any("app_routes" in error for error in errors))
        self.assertTrue(any("circular local imports" in error for error in errors))

    def test_detects_unresolved_globals_and_unqualified_package_imports(self):
        files = {
            "backend/__init__.py": "",
            "backend/app.py": (
                "from flask import Flask\n"
                "from config import Config\n"
                "app = Flask(__name__)\n"
            ),
            "backend/config.py": "class Config:\n    pass\n",
            "backend/routes.py": (
                "def broken():\n"
                "    app.app.register_blueprint(routes)\n"
                "    return db.session.execute(text('SELECT 1'))\n"
            ),
        }

        errors = _python_import_errors(files)

        self.assertTrue(
            any("local import 'config' should use 'backend.config'" in error
                for error in errors)
        )
        self.assertTrue(
            any("unresolved global name 'app'" in error for error in errors)
        )
        self.assertTrue(
            any("unresolved global name 'text'" in error for error in errors)
        )

    def test_detects_missing_absolute_frontend_assets(self):
        files = valid_project()
        files["frontend/index.html"] = (
            '<link rel="stylesheet" href="/static/style.css">'
            '<script src="/static/script.js"></script>'
        )

        errors = validate_project(files)

        self.assertTrue(
            any("static asset '/static/style.css'" in error for error in errors)
        )
        self.assertTrue(
            any("static asset '/static/script.js'" in error for error in errors)
        )

    def test_requires_flask_to_serve_generated_frontend_assets(self):
        files = valid_project()
        files["backend/app.py"] = (
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
        )

        errors = validate_project(files)

        self.assertTrue(
            any("must serve frontend/ at the /static URL" in error
                for error in errors)
        )

    def test_detects_model_and_sql_schema_mismatch(self):
        files = {
            "backend/models.py": (
                "class Patient(db.Model):\n"
                "    id = db.Column(db.Integer, primary_key=True)\n"
                "    first_name = db.Column(db.String(100), nullable=False)\n"
            ),
            "database/schema.sql": (
                "CREATE TABLE Patients (\n"
                "    PatientID SERIAL PRIMARY KEY,\n"
                "    FirstName VARCHAR(100) NOT NULL\n"
                ");\n"
            ),
        }

        errors = _orm_schema_errors(files)

        self.assertTrue(
            any("table 'patient' for model 'Patient' is missing" in error
                for error in errors)
        )

    def test_accepts_matching_explicit_model_table_and_columns(self):
        files = {
            "backend/models.py": (
                "class Patient(db.Model):\n"
                "    __tablename__ = 'patients'\n"
                "    id = db.Column(db.Integer, primary_key=True)\n"
                "    first_name = db.Column(db.String(100), nullable=False)\n"
            ),
            "database/schema.sql": (
                "CREATE TABLE patients (\n"
                "    id SERIAL PRIMARY KEY,\n"
                "    first_name VARCHAR(100) NOT NULL\n"
                ");\n"
            ),
        }

        self.assertEqual(_orm_schema_errors(files), [])

    def test_detects_python_and_javascript_syntax_errors(self):
        files = valid_project()
        files["backend/app.py"] = "def broken(:\n"
        files["frontend/js/script.js"] = "const = ;\n"

        errors = validate_project(files)

        self.assertTrue(any("Python syntax error" in error for error in errors))
        if shutil.which("node"):
            self.assertTrue(any("JavaScript syntax error" in error for error in errors))
        else:
            self.assertTrue(
                any("Node.js is unavailable" in error for error in errors)
            )

    def test_detects_frontend_api_route_mismatch(self):
        files = valid_project()
        files["frontend/js/script.js"] = (
            "fetch('/api/patient/register', {method: 'POST'});\n"
        )

        errors = validate_project(files)

        self.assertTrue(
            any("POST /api/patient/register has no matching Flask route" in error
                for error in errors)
        )

    def test_manifest_api_contracts_must_have_matching_backend_routes(self):
        files = valid_project()
        manifest = json.loads(files["project_manifest.json"])
        manifest["api_contracts"] = [
            {"method": "POST", "path": "/api/patients"}
        ]

        errors = validate_project(files, manifest)

        self.assertTrue(
            any(
                "manifest API contract POST /api/patients" in error
                for error in errors
            )
        )

    def test_ignores_routes_from_unregistered_blueprints(self):
        files = valid_project()
        files["backend/routes.py"] = (
            "from flask import Blueprint\n"
            "patient_routes = Blueprint('patient_routes', __name__)\n"
            "@patient_routes.post('/api/patient/register')\n"
            "def register_patient():\n"
            "    return {'status': 'ok'}\n"
        )
        files["frontend/js/script.js"] = (
            "fetch('/api/patient/register', {method: 'POST'});\n"
        )

        errors = validate_project(files)

        self.assertTrue(
            any("POST /api/patient/register has no matching Flask route" in error
                for error in errors)
        )
        self.assertTrue(
            any("must be registered exactly once at module scope" in error
                for error in errors)
        )

    def test_detects_broken_internal_navigation_and_wsgi_target(self):
        files = valid_project()
        files["frontend/index.html"] = '<a href="/patient/register">Register</a>\n'
        files["backend/app.py"] = "from flask import Flask\nFlask(__name__)\n"

        errors = validate_project(files)

        self.assertTrue(
            any("GET /patient/register has no matching Flask route" in error
                for error in errors)
        )
        self.assertTrue(any("WSGI application variable 'app' is missing" in error
                            for error in errors))

    def test_requires_routes_for_generated_html_pages(self):
        files = valid_project()
        files["frontend/login.html"] = "<main>Login</main>\n"

        errors = validate_project(files)

        self.assertTrue(
            any(
                "frontend/login.html: GET /login has no matching Flask route"
                in error
                for error in errors
            )
        )
        self.assertTrue(
            any(
                "frontend/login.html: GET /login.html has no matching Flask route"
                in error
                for error in errors
            )
        )

    def test_checks_css_and_javascript_local_import_paths(self):
        files = valid_project()
        files["frontend/css/style.css"] = (
            "body { background: url('../images/bg.svg'); }\n"
            "@import '../css/theme.css';\n"
        )
        files["frontend/js/script.js"] = (
            "import './modules/app.js';\n"
            "import('./modules/lazy.js');\n"
        )

        errors = validate_project(files)
        missing_paths = {
            "frontend/images/bg.svg",
            "frontend/css/theme.css",
            "frontend/js/modules/app.js",
            "frontend/js/modules/lazy.js",
        }

        self.assertEqual(
            {
                error.partition("expected generated file '")[2].split("'", 1)[0]
                for error in errors
                if "expected generated file '" in error
            },
            missing_paths,
        )

    def test_requires_database_check_on_readiness_route(self):
        files = valid_project()
        files["backend/app.py"] = (
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "@app.get('/health')\n"
            "def health():\n"
            "    return {'status': 'ok'}\n"
            "@app.get('/ready')\n"
            "def ready():\n"
            "    return {'status': 'ready'}\n"
        )

        errors = validate_project(files)

        self.assertTrue(any("must execute SELECT 1" in error for error in errors))

    def test_rejects_placeholder_implementations(self):
        files = valid_project()
        files["backend/routes.py"] = "# Placeholder for authentication logic\n"

        errors = validate_project(files)

        self.assertTrue(any("placeholder or incomplete" in error for error in errors))

    def test_does_not_require_dockerfile_for_a_complete_project(self):
        files = valid_project()

        self.assertNotIn("Dockerfile", files)
        self.assertNotIn("Dockerfile", "\n".join(validate_project(files)))

    def test_requires_runtime_and_connectivity_configuration(self):
        files = valid_project()
        files["backend/requirements.txt"] = "Flask\n"
        files[".env.example"] = "DATABASE_URL=postgresql://[username]:[password]@[host]/db\n"
        files["backend/app.py"] = "from flask import Flask\napp = Flask(__name__)\n"
        files["backend/routes.py"] = '"""No health routes."""\n'

        errors = validate_project(files)

        self.assertTrue(any("gunicorn is required" in error for error in errors))
        self.assertTrue(any("flask-sqlalchemy is required" in error for error in errors))
        self.assertTrue(any("SECRET_KEY" in error for error in errors))
        self.assertTrue(any("placeholder PostgreSQL" in error for error in errors))
        self.assertTrue(any("GET /health route is missing" in error for error in errors))
        self.assertTrue(any("GET /ready route is missing" in error for error in errors))

    def test_requires_secret_and_database_configuration_from_environment(self):
        files = valid_project()
        files["backend/config.py"] = (
            "class Config:\n"
            "    SECRET_KEY = 'embedded-secret'\n"
            "    SQLALCHEMY_DATABASE_URI = 'postgresql://localhost/app'\n"
        )

        errors = validate_project(files)

        self.assertTrue(
            any("SECRET_KEY must be read from the environment" in error
                for error in errors)
        )
        self.assertTrue(
            any("SQLALCHEMY_DATABASE_URI must be read from the environment"
                in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
