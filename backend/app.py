from flask import Flask, render_template, request, jsonify

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

        prompt = data.get("prompt", "").strip()

        if not prompt:
            return jsonify({
                "success": False,
                "message": "Project description cannot be empty."
            }), 400

        requirements = analyze_requirements(prompt)

        return jsonify({
            "success": True,
            "requirements": requirements
        })

    except Exception as e:

        print("Requirement Generation Error:", str(e))

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
# MAIN
# ==================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )