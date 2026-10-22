import json
import logging
import os
import queue
import re
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from dotenv import load_dotenv, set_key
from flask import Response, stream_with_context

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file
)

load_dotenv()

from agents.project_generator import (
    GENERATED_PROJECTS_DIR,
    generate_project,
    migrate_legacy_project,
)
from agents.requirement_agent import analyze_requirements
from agents.architecture_agent import generate_architecture
from agents.database_agent import generate_database
from agents.backend_agent import generate_backend
from agents.frontend_agent import generate_frontend
from agents.project_manifest import validate_project_manifest
from agents.project_validator import validate_project
from services.deployment_service import deploy_project_pipeline

app = Flask(__name__)
GENERATED_PROJECT_PATH = os.path.join(GENERATED_PROJECTS_DIR, "project")
LEGACY_GENERATED_PROJECT_PATH = os.path.join(
    app.root_path,
    "generated_projects",
    "project"
)
PROJECT_HISTORY_FILENAME = ".project_history.json"

migrate_legacy_project(
    LEGACY_GENERATED_PROJECT_PATH,
    GENERATED_PROJECT_PATH
)


def create_project_directory():
    os.makedirs(GENERATED_PROJECTS_DIR, exist_ok=True)
    project_numbers = [
        int(match.group(1))
        for name in os.listdir(GENERATED_PROJECTS_DIR)
        if (match := re.fullmatch(r"project([1-9]\d*)", name))
        and os.path.isdir(os.path.join(GENERATED_PROJECTS_DIR, name))
    ]
    next_number = max(project_numbers, default=0) + 1

    while True:
        project_id = f"project{next_number}"
        project_path = os.path.join(GENERATED_PROJECTS_DIR, project_id)
        try:
            os.mkdir(project_path)
            return project_id, project_path
        except FileExistsError:
            next_number += 1


def get_project_path(project_id):
    if not isinstance(project_id, str) or not re.fullmatch(
        r"project[1-9]\d*",
        project_id,
    ):
        raise ValueError("A valid project_id is required.")

    project_path = os.path.abspath(
        os.path.join(GENERATED_PROJECTS_DIR, project_id)
    )
    if not os.path.isdir(project_path):
        raise FileNotFoundError("Project not found.")
    return project_path


def _history_timestamp():
    return datetime.now(timezone.utc).isoformat()


def _history_title(prompt, project_id):
    first_line = " ".join(str(prompt or "").strip().splitlines()).strip()
    return (first_line[:80].rstrip() or project_id)


def _history_path(project_path):
    return os.path.join(project_path, PROJECT_HISTORY_FILENAME)


def _write_project_history(project_path, **updates):
    """Persist all user-visible pipeline data for one generated project."""
    path = _history_path(project_path)
    record = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as history_file:
                record = json.load(history_file)
        except (OSError, json.JSONDecodeError):
            record = {}

    if (
        isinstance(record.get("deployment"), dict)
        and isinstance(updates.get("deployment"), dict)
    ):
        updates["deployment"] = {
            **record["deployment"],
            **updates["deployment"],
        }
    record.update(updates)
    record.setdefault("project_id", os.path.basename(project_path))
    record.setdefault("created_at", _history_timestamp())
    record["updated_at"] = _history_timestamp()
    record.setdefault("title", _history_title(record.get("prompt"), record["project_id"]))

    temporary_path = f"{path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as history_file:
        json.dump(record, history_file, ensure_ascii=False, indent=2, default=str)
    os.replace(temporary_path, path)
    return record


def _read_project_history(project_path):
    path = _history_path(project_path)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as history_file:
                return json.load(history_file)
        except (OSError, json.JSONDecodeError):
            pass

    # Keep older generated projects visible after upgrading the application.
    project_id = os.path.basename(project_path)
    manifest = {}
    manifest_path = os.path.join(project_path, "project_manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "project_id": project_id,
        "title": manifest.get("project_name") or project_id,
        "prompt": "",
        "requirements": "",
        "architecture": {},
        "database": {},
        "backend": {},
        "frontend": {},
        "project": {"project_id": project_id, "project_path": project_path},
        "deployment": {},
        "created_at": datetime.fromtimestamp(
            os.path.getctime(project_path), timezone.utc
        ).isoformat(),
        "updated_at": datetime.fromtimestamp(
            os.path.getmtime(project_path), timezone.utc
        ).isoformat(),
        "legacy": True,
    }


def _project_history_entries(include_details=False):
    os.makedirs(GENERATED_PROJECTS_DIR, exist_ok=True)
    entries = []
    for name in os.listdir(GENERATED_PROJECTS_DIR):
        if not re.fullmatch(r"project[1-9]\d*", name):
            continue
        project_path = os.path.join(GENERATED_PROJECTS_DIR, name)
        if not os.path.isdir(project_path):
            continue
        record = _read_project_history(project_path)
        if include_details:
            entries.append(record)
        else:
            entries.append({
                key: record.get(key)
                for key in (
                    "project_id", "title", "prompt", "created_at", "updated_at",
                    "deployment", "legacy",
                )
            })
    return sorted(entries, key=lambda item: item.get("updated_at") or "", reverse=True)


# ==================================================
# HOME
# ==================================================

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/dashboard")
def dashboard():
    return render_template("index.html")


# ==================================================
# HEALTH CHECK
# ==================================================

@app.route("/health")
def health():
    return jsonify({
        "status": "running"
    })


# ==================================================
# GENERATED PROJECT HISTORY API
# ==================================================

@app.route("/api/history", methods=["GET"])
def api_history():
    project_id = request.args.get("project_id")
    try:
        if project_id:
            project_path = get_project_path(project_id)
            return jsonify({"success": True, "project": _read_project_history(project_path)})
        return jsonify({"success": True, "projects": _project_history_entries()})
    except ValueError as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except FileNotFoundError as error:
        return jsonify({"success": False, "message": str(error)}), 404
    except Exception as error:
        app.logger.exception("Could not read project history")
        return jsonify({"success": False, "message": str(error)}), 500


@app.route("/api/history/<project_id>", methods=["GET", "DELETE"])
def api_history_project(project_id):
    try:
        project_path = get_project_path(project_id)
        if request.method == "GET":
            return jsonify({"success": True, "project": _read_project_history(project_path)})

        shutil.rmtree(project_path)
        archive_path = os.path.join(GENERATED_PROJECTS_DIR, f"{project_id}.zip")
        if os.path.isfile(archive_path):
            os.remove(archive_path)
        return jsonify({"success": True, "project_id": project_id})
    except ValueError as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except FileNotFoundError as error:
        return jsonify({"success": False, "message": str(error)}), 404
    except Exception as error:
        app.logger.exception("Could not update project history")
        return jsonify({"success": False, "message": str(error)}), 500


# ==================================================
# REQUIREMENTS API
# ==================================================

@app.route("/api/requirements", methods=["POST"])
def api_requirements():

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "success": False,
                "message": "Request data is missing."
            }), 400

        prompt = data.get(
            "prompt",
            ""
        ).strip()

        if not prompt:
            return jsonify({
                "success": False,
                "message": "Project description cannot be empty."
            }), 400

        app.logger.info("Requirements generation started")
        requirements = analyze_requirements(
            prompt
        )
        app.logger.info("Requirements generation completed")

        return jsonify({
            "success": True,
            "requirements": requirements
        })

    except Exception as e:

        print(
            "Requirement Generation Error:",
            str(e)
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ==================================================
# ARCHITECTURE API
# ==================================================

@app.route("/api/architecture", methods=["POST"])
def api_architecture():

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "success": False,
                "message": "Request data is missing."
            }), 400

        requirements = data.get(
            "requirements",
            ""
        ).strip()

        if not requirements:
            return jsonify({
                "success": False,
                "message": "Requirements cannot be empty."
            }), 400

        architecture = generate_architecture(
            requirements
        )

        return jsonify({
            "success": True,
            "architecture": architecture
        })

    except Exception as e:

        print(
            "Architecture Generation Error:",
            str(e)
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ==================================================
# DATABASE API
# ==================================================

@app.route("/api/database", methods=["POST"])
def api_database():

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "success": False,
                "message": "Request data is missing."
            }), 400

        requirements = data.get(
            "requirements",
            ""
        ).strip()

        architecture = data.get(
            "architecture",
            {}
        )

        if not requirements:
            return jsonify({
                "success": False,
                "message": "Requirements cannot be empty."
            }), 400

        if not architecture:
            return jsonify({
                "success": False,
                "message": "Architecture is required."
            }), 400

        database = generate_database(
            requirements,
            architecture
        )

        return jsonify({
            "success": True,
            "database": database
        })

    except Exception as e:

        print(
            "Database Generation Error:",
            str(e)
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ==================================================
# BACKEND API
# ==================================================

@app.route("/api/backend", methods=["POST"])
def api_backend():

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "success": False,
                "message": "Request data is missing."
            }), 400

        requirements = data.get(
            "requirements",
            ""
        ).strip()

        architecture = data.get(
            "architecture",
            {}
        )

        database = data.get(
            "database",
            {}
        )

        if not requirements:
            return jsonify({
                "success": False,
                "message": "Requirements cannot be empty."
            }), 400

        if not architecture:
            return jsonify({
                "success": False,
                "message": "Architecture is required."
            }), 400

        if not database:
            return jsonify({
                "success": False,
                "message": "Database design is required."
            }), 400

        backend = generate_backend(
            requirements,
            architecture,
            database
        )

        return jsonify({
            "success": True,
            "backend": backend
        })

    except Exception as e:

        print(
            "Backend Generation Error:",
            str(e)
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ==================================================
# FRONTEND API
# ==================================================

@app.route("/api/frontend", methods=["POST"])
def api_frontend():

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "success": False,
                "message": "Request data is missing."
            }), 400

        requirements = data.get(
            "requirements",
            ""
        ).strip()

        architecture = data.get(
            "architecture",
            {}
        )

        database = data.get(
            "database",
            {}
        )

        backend = data.get(
            "backend",
            {}
        )

        if not requirements:
            return jsonify({
                "success": False,
                "message": "Requirements cannot be empty."
            }), 400

        if not architecture:
            return jsonify({
                "success": False,
                "message": "Architecture is required."
            }), 400

        if not database:
            return jsonify({
                "success": False,
                "message": "Database design is required."
            }), 400

        if not backend:
            return jsonify({
                "success": False,
                "message": "Backend design is required."
            }), 400

        frontend = generate_frontend(
            requirements,
            architecture,
            database,
            backend
        )

        return jsonify({
            "success": True,
            "frontend": frontend
        })

    except Exception as e:

        print(
            "Frontend Generation Error:",
            str(e)
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ==================================================
# AUTOMATIC PROJECT GENERATION API
# ==================================================

@app.route("/api/generate", methods=["POST"])
def api_generate():

    data = request.get_json()
    prompt = ((data or {}).get("prompt") or "").strip()
    requirements = ((data or {}).get("requirements") or "").strip()
    if not prompt and not requirements:
        return jsonify({
            "success": False,
            "message": "Project description or generated requirements are required."
        }), 400

    try:
        project_id, project_path = create_project_directory()
        _write_project_history(
            project_path,
            project_id=project_id,
            title=_history_title(prompt or requirements, project_id),
            prompt=prompt,
            requirements=requirements,
            architecture={},
            database={},
            backend={},
            frontend={},
            project={},
            deployment={},
            status="generating",
        )
    except OSError as error:
        app.logger.exception("Unable to create a project directory")
        return jsonify({
            "success": False,
            "message": str(error)
        }), 500

    events = queue.Queue()

    def run_pipeline():
        current_stage = "Project generation"
        active_requirements = requirements

        def emit(message, level=logging.INFO):
            app.logger.log(level, message)
            events.put({"type": "log", "message": message})

        def emit_code(event):
            events.put(event)

        try:
            if requirements:
                emit("Using saved requirements.")
            else:
                current_stage = "Requirements generation"
                emit("Requirements generation started...")
                generated_requirements = analyze_requirements(prompt)
                emit("Requirements generated successfully.")
                events.put({
                    "type": "requirements",
                    "requirements": generated_requirements
                })
                active_requirements = generated_requirements
            _write_project_history(
                project_path,
                requirements=active_requirements,
                status="generating",
            )

            current_stage = "Architecture generation"
            emit("Architecture generation started...")
            architecture = generate_architecture(active_requirements)
            _write_project_history(project_path, architecture=architecture)
            emit("Architecture generated successfully.")
            events.put({"type": "architecture", "architecture": architecture})

            current_stage = "Database schema generation"
            emit("Database schema generation started...")
            database = generate_database(active_requirements, architecture)
            _write_project_history(project_path, database=database)
            emit("Database schema generated successfully.")
            events.put({"type": "database", "database": database})

            current_stage = "Project generation"
            emit("Project generation started...")
            emit("Generating project structure...")
            backend = generate_backend(
                active_requirements,
                architecture,
                database
            )
            _write_project_history(project_path, backend=backend)
            emit("Project structure generated successfully.")

            emit("Preparing frontend implementation plan...")
            frontend = generate_frontend(
                active_requirements,
                architecture,
                database,
                backend
            )
            _write_project_history(project_path, frontend=frontend)
            emit("Frontend implementation plan generated successfully.")

            emit("Project code generation timeout is 15 minutes.")
            project = generate_project(
                active_requirements,
                architecture,
                database,
                backend,
                frontend,
                progress=emit,
                code_progress=emit_code,
                project_path=project_path,
            )
            project["project_id"] = project_id
            _write_project_history(
                project_path,
                project=project,
                status="partial" if project.get("partial") else "completed",
            )
            if project.get("partial"):
                emit(project["message"], logging.WARNING)
            else:
                emit("Project generation completed successfully.")
            events.put({
                "type": "complete",
                "success": True,
                "project": project
            })
        except Exception as error:
            message = f"{current_stage} failed: {error}"
            _write_project_history(
                project_path,
                status="failed",
                error=message,
            )
            emit(message, logging.ERROR)
            events.put({
                "type": "failure",
                "success": False,
                "message": message
            })
        finally:
            events.put(None)

    threading.Thread(target=run_pipeline, daemon=True).start()

    def stream_events():
        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return Response(
        stream_with_context(stream_events()),
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Project-Id": project_id,
        }
    )

# ==================================================
# PROJECT GENERATION API
# ==================================================

@app.route("/api/project", methods=["POST"])
def api_project():

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "success": False,
                "message": "Request data is missing."
            }), 400

        requirements = data.get(
            "requirements",
            ""
        )

        architecture = data.get(
            "architecture",
            {}
        )

        database = data.get(
            "database",
            {}
        )

        backend = data.get(
            "backend",
            {}
        )

        frontend = data.get(
            "frontend",
            {}
        )

        project_id, project_path = create_project_directory()
        project = generate_project(
            requirements,
            architecture,
            database,
            backend,
            frontend,
            project_path=project_path,
        )
        project["project_id"] = project_id
        _write_project_history(
            project_path,
            project_id=project_id,
            title=_history_title(requirements, project_id),
            prompt=data.get("prompt", ""),
            requirements=requirements,
            architecture=architecture,
            database=database,
            backend=backend,
            frontend=frontend,
            project=project,
            deployment={},
            status="partial" if project.get("partial") else "completed",
        )

        return jsonify(project)

    except Exception as e:

        print(
            "Project Generation Error:",
            str(e)
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500



# ==================================================
# PROJECT FILE LIST API
# ==================================================

@app.route("/api/project/files")
def get_project_files():

    try:

        project_path = get_project_path(request.args.get("project_id"))

        files = []

        if not os.path.exists(
            project_path
        ):

            return jsonify({

                "success": False,

                "message":
                "Project folder not found."

            }), 404

        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [
                directory for directory in dirs
                if directory not in {
                    "__pycache__",
                    ".pytest_cache",
                    ".git",
                    "venv",
                }
            ]

            for file in filenames:
                if file.endswith((".pyc", ".pyo", ".pyd")):
                    continue

                full_path = os.path.join(
                    root,
                    file
                )

                relative_path = os.path.relpath(
                    full_path,
                    project_path
                ).replace("\\", "/")

                files.append(
                    relative_path
                )

        return jsonify({

            "success": True,

            "files": files

        })

    except ValueError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    except FileNotFoundError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 404

    except Exception as e:

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500


# ==================================================
# PROJECT FILE CONTENT API
# ==================================================

@app.route("/api/project/file")
def get_project_file():

    try:

        file_path = request.args.get(
            "path"
        )

        if not file_path:

            return jsonify({

                "success": False,

                "message":
                "File path missing."

            }), 400

        project_root = get_project_path(request.args.get("project_id"))
        full_path = os.path.abspath(os.path.join(project_root, file_path))
        try:
            is_project_file = (
                os.path.commonpath((project_root, full_path)) == project_root
            )
        except ValueError:
            is_project_file = False
        if not is_project_file:
            return jsonify({
                "success": False,
                "message": "Invalid file path."
            }), 400

        if not os.path.exists(
            full_path
        ):

            return jsonify({

                "success": False,

                "message":
                "File not found."

            }), 404

        with open(
            full_path,
            "r",
            encoding="utf-8"
        ) as file:

            content = file.read()

        return jsonify({

            "success": True,

            "content": content

        })

    except ValueError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    except FileNotFoundError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 404

    except Exception as e:

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500

# ==================================================
# PROJECT FILES API
# ==================================================

@app.route("/api/project-files", methods=["GET"])
def api_project_files():

    try:

        project_path = get_project_path(request.args.get("project_id"))

        files_data = []

        for root, dirs, files in os.walk(project_path):
            dirs[:] = [
                directory for directory in dirs
                if directory not in {
                    "__pycache__",
                    ".pytest_cache",
                    ".git",
                    "venv",
                }
            ]

            for file in files:
                if file.endswith((".pyc", ".pyo", ".pyd")):
                    continue

                file_path = os.path.join(
                    root,
                    file
                )

                relative_path = os.path.relpath(
                    file_path,
                    project_path
                ).replace("\\", "/")

                with open(
                    file_path,
                    "r",
                    encoding="utf-8",
                    errors="replace"
                ) as f:

                    content = f.read()

                files_data.append({

                    "name": file,

                    "path": relative_path,

                    "content": content

                })

        return jsonify({

            "success": True,

            "files": files_data

        })

    except ValueError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    except FileNotFoundError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 404

    except Exception as e:

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500
    




# ============================================================
# CREATE ZIP
# ============================================================

def create_project_zip(project_path, validate=True):
    os.makedirs(GENERATED_PROJECTS_DIR, exist_ok=True)
    project_id = os.path.basename(os.path.abspath(project_path))
    zip_path = os.path.join(GENERATED_PROJECTS_DIR, f"{project_id}.zip")
    try:
        with open(
            os.path.join(project_path, "project_manifest.json"),
            encoding="utf-8",
        ) as manifest_file:
            manifest = json.load(manifest_file)
        validate_project_manifest(manifest)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            "Cannot package project: a valid project_manifest.json is required."
        ) from error

    project_files = {}
    is_partial = manifest.get("generation_status") == "partial"
    required_files = manifest.get("required_files")
    if not isinstance(required_files, list):
        raise ValueError(
            "Cannot package project: manifest required_files must be a list."
        )
    for relative_path in required_files:
        if (
            not isinstance(relative_path, str)
            or os.path.isabs(relative_path)
            or ".." in relative_path.replace("\\", "/").split("/")
        ):
            raise ValueError(
                "Cannot package project: manifest contains an unsafe file path."
            )
        file_path = os.path.join(project_path, *relative_path.replace("\\", "/").split("/"))
        try:
            with open(file_path, encoding="utf-8") as file:
                project_files[relative_path.replace("\\", "/")] = file.read()
        except OSError as error:
            if is_partial:
                continue
            raise ValueError(
                f"Cannot package project: required file '{relative_path}' is unavailable."
            ) from error

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
            if rel_path not in project_files:
                try:
                    with open(full_path, encoding="utf-8") as file:
                        project_files[rel_path] = file.read()
                except (OSError, UnicodeDecodeError):
                    pass

    if is_partial:
        if "project_manifest.json" not in project_files:
            with open(
                os.path.join(project_path, "project_manifest.json"),
                encoding="utf-8",
            ) as manifest_file:
                project_files["project_manifest.json"] = manifest_file.read()
    elif validate:
        validation_errors = validate_project(project_files, manifest)
        if validation_errors:
            raise ValueError(
                "Cannot package an unvalidated project: "
                + "; ".join(validation_errors)
            )

    descriptor, temporary_zip = tempfile.mkstemp(
        prefix=".project-",
        suffix=".zip",
        dir=GENERATED_PROJECTS_DIR,
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary_zip,
            "w",
            zipfile.ZIP_DEFLATED
        ) as zipf:
            for relative_path in sorted(project_files):
                file_path = os.path.join(
                    project_path,
                    *relative_path.split("/"),
                )
                zipf.write(file_path, relative_path)
        os.replace(temporary_zip, zip_path)
    finally:
        if os.path.exists(temporary_zip):
            os.remove(temporary_zip)

    return zip_path


# ============================================================
# DOWNLOAD PROJECT
# ============================================================

@app.route(
    "/api/download-project",
    methods=["GET"]
)
def download_project():

    try:

        project_id = request.args.get("project_id")
        project_path = get_project_path(project_id)

        zip_path = create_project_zip(
            project_path,
            validate=False,
        )

        return send_file(

            zip_path,

            as_attachment=True,

            download_name=f"{project_id}.zip"

        )

    except ValueError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    except FileNotFoundError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 404

    except Exception as e:

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500


# ============================================================
# CLOUD DEPLOYMENT API (NEON DB + RENDER)
# ============================================================

def _update_env_file(key_values: dict):
    env_path = os.path.join(app.root_path, ".env")
    for key, value in key_values.items():
        success, _, _ = set_key(env_path, key, value, quote_mode="always")
        if not success:
            raise OSError(f"Could not save {key} to the deployment environment file.")


def _apply_deployment_config(data: dict, save_to_env: bool = False):
    fields = {
        "neon_api_key": "NEON_API_KEY",
        "neon_database_url": "NEON_DATABASE_URL",
        "github_token": "GITHUB_TOKEN",
        "render_api_key": "RENDER_API_KEY",
        "render_owner_id": "RENDER_OWNER_ID",
    }
    updates = {}
    for field, env_key in fields.items():
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            updates[env_key] = value.strip()

    if save_to_env and updates:
        _update_env_file(updates)

    os.environ.update(updates)
    return updates


@app.route("/api/deploy/config", methods=["GET", "POST"])
def api_deploy_config():
    if request.method == "POST":
        data = request.get_json() or {}
        try:
            _apply_deployment_config(data, save_to_env=data.get("save_to_env") is True)
        except OSError as error:
            app.logger.exception("Failed to save deployment credentials")
            return jsonify({
                "success": False,
                "message": f"Could not save deployment credentials: {error}",
            }), 500

        return jsonify({
            "success": True,
            "message": "Deployment configuration updated."
        })

    return jsonify({
        "success": True,
        "configured": {
            "has_neon_api_key": bool(os.environ.get("NEON_API_KEY")),
            "has_neon_database_url": bool(os.environ.get("NEON_DATABASE_URL")),
            "has_github_token": bool(os.environ.get("GITHUB_TOKEN")),
            "has_render_api_key": bool(os.environ.get("RENDER_API_KEY")),
            "render_owner_id": os.environ.get("RENDER_OWNER_ID", ""),
        }
    })


@app.route("/api/deploy", methods=["POST"])
def api_deploy():
    data = request.get_json() or {}
    project_id = (data.get("project_id") or "").strip()

    if not project_id:
        return jsonify({
            "success": False,
            "message": "project_id is required for deployment."
        }), 400

    try:
        project_path = get_project_path(project_id)
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 404

    try:
        _apply_deployment_config(data, save_to_env=data.get("save_to_env") is True)
    except OSError as error:
        app.logger.exception("Failed to save deployment credentials")
        return jsonify({
            "success": False,
            "message": f"Could not save deployment credentials: {error}",
        }), 500

    events = queue.Queue()

    def run_deploy():
        def emit(event):
            events.put(event)

        try:
            emit({"type": "log", "message": f"Starting automated cloud deployment for {project_id}..."})
            result = deploy_project_pipeline(
                project_id=project_id,
                project_path=project_path,
                config=data,
                emit=emit,
            )
            simulated = bool(result.get("simulated"))
            deployment = {
                "status": "simulated" if simulated else "deployed",
                "neon": result.get("neon", {}),
                "github": result.get("github", {}),
                "render": result.get("render", {}),
                "summary": {
                    "title": "This was a deployment simulation" if simulated else "Your Application is Live on Render!",
                    "description": (
                        "No database, GitHub repository, or Render service was created."
                        if simulated
                        else "The database schema was applied to Neon, code pushed to GitHub, and Render confirmed the web service is live."
                    ),
                },
                "message": (
                    "Simulation completed. No cloud resources were created."
                    if simulated
                    else f"Deployment is live at {result.get('url')}"
                ),
                "updated_at": _history_timestamp(),
            }
            if not simulated and result.get("url"):
                deployment["url"] = result["url"]
            _write_project_history(
                project_path,
                deployment=deployment,
            )
            emit({
                "type": "complete",
                "success": True,
                "simulated": simulated,
                "url": result.get("url", ""),
                "neon": result.get("neon", {}),
                "github": result.get("github", {}),
                "render": result.get("render", {}),
                "message": (
                    "Simulation completed. No cloud resources were created."
                    if simulated
                    else f"Deployment is live at {result.get('url')}"
                )
            })
        except Exception as error:
            app.logger.exception("Deployment failed")
            _write_project_history(
                project_path,
                deployment={
                    "status": "failed",
                    "message": str(error),
                    "updated_at": _history_timestamp(),
                },
            )
            emit({
                "type": "failure",
                "success": False,
                "message": str(error)
            })
        finally:
            events.put(None)

    threading.Thread(target=run_deploy, daemon=True).start()

    def stream_events():
        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return Response(
        stream_with_context(stream_events()),
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ==================================================
# MAIN
# ==================================================

def run_local_server():
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=False
    )


if __name__ == "__main__":
    run_local_server()
