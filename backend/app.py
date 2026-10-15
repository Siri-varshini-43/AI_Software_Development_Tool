import json
import logging
import os
import queue
import tempfile
import threading
import zipfile
from dotenv import load_dotenv
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

app = Flask(__name__)
GENERATED_PROJECT_PATH = os.path.join(GENERATED_PROJECTS_DIR, "project")
LEGACY_GENERATED_PROJECT_PATH = os.path.join(
    app.root_path,
    "generated_projects",
    "project"
)

migrate_legacy_project(
    LEGACY_GENERATED_PROJECT_PATH,
    GENERATED_PROJECT_PATH
)


# ==================================================
# HOME
# ==================================================

@app.route("/")
def home():
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

            current_stage = "Architecture generation"
            emit("Architecture generation started...")
            architecture = generate_architecture(active_requirements)
            emit("Architecture generated successfully.")
            events.put({"type": "architecture", "architecture": architecture})

            current_stage = "Database schema generation"
            emit("Database schema generation started...")
            database = generate_database(active_requirements, architecture)
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
            emit("Project structure generated successfully.")

            emit("Preparing frontend implementation plan...")
            frontend = generate_frontend(
                active_requirements,
                architecture,
                database,
                backend
            )
            emit("Frontend implementation plan generated successfully.")

            project = generate_project(
                active_requirements,
                architecture,
                database,
                backend,
                frontend,
                progress=emit,
                code_progress=emit_code,
            )
            emit("Project generation completed successfully.")
            events.put({
                "type": "complete",
                "success": True,
                "project": project
            })
        except Exception as error:
            message = f"{current_stage} failed: {error}"
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
            "X-Accel-Buffering": "no"
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

        project = generate_project(
            requirements,
            architecture,
            database,
            backend,
            frontend
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

        project_path = GENERATED_PROJECT_PATH

        files = []

        if not os.path.exists(
            project_path
        ):

            return jsonify({

                "success": False,

                "message":
                "Project folder not found."

            }), 404

        for root, dirs, filenames in os.walk(
            project_path
        ):

            for file in filenames:

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

        project_root = GENERATED_PROJECT_PATH
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

        project_path = GENERATED_PROJECT_PATH

        files_data = []

        for root, dirs, files in os.walk(project_path):

            for file in files:

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

    except Exception as e:

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500
    




# ============================================================
# CREATE ZIP
# ============================================================

def create_project_zip(project_path):
    os.makedirs(GENERATED_PROJECTS_DIR, exist_ok=True)
    zip_path = os.path.join(GENERATED_PROJECTS_DIR, "project.zip")
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

        project_path = GENERATED_PROJECT_PATH

        if not os.path.exists(project_path):

            return jsonify({

                "success": False,

                "message":
                    "Project not found."

            }), 404

        zip_path = create_project_zip(
            project_path
        )

        return send_file(

            zip_path,

            as_attachment=True,

            download_name="project.zip"

        )

    except Exception as e:

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500

    
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