import os
import zipfile
from flask import send_file, jsonify

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file
)
from agents.project_generator import generate_project
from agents.requirement_agent import analyze_requirements
from agents.architecture_agent import generate_architecture
from agents.database_agent import generate_database
from agents.backend_agent import generate_backend
from agents.frontend_agent import generate_frontend

app = Flask(__name__)


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

        requirements = analyze_requirements(
            prompt
        )

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

        project_path = os.path.join(
            "generated_projects",
            "project"
        )

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
                )

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

        project_root = os.path.join(
            "generated_projects",
            "project"
        )

        full_path = os.path.join(
            project_root,
            file_path
        )

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

        project_path = os.path.join(
            "generated_projects",
            "project"
        )

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
                )

                try:

                    with open(
                        file_path,
                        "r",
                        encoding="utf-8"
                    ) as f:

                        content = f.read()

                except Exception:

                    content = "Unable to read file."

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

    zip_path = os.path.join(
        "generated_projects",
        "project.zip"
    )

    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(
        zip_path,
        "w",
        zipfile.ZIP_DEFLATED
    ) as zipf:

        for root, dirs, files in os.walk(project_path):

            for file in files:

                file_path = os.path.join(
                    root,
                    file
                )

                arcname = os.path.relpath(
                    file_path,
                    project_path
                )

                zipf.write(
                    file_path,
                    arcname
                )

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

        project_path = os.path.join(
            "generated_projects",
            "project"
        )

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

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )