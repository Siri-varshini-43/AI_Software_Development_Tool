from agents.diagram_generator import generate_architecture_diagram
from agents.flow_generator import generate_project_flow
from agents.module_generator import generate_modules
from agents.api_generator import generate_rest_apis
from agents.actor_generator import generate_actors

import json
import re


def parse_json_response(response):
    """
    Cleans and converts JSON array returned by Ollama into Python list.
    """

    response = response.strip()

    # Remove markdown if present
    response = re.sub(r"```json", "", response, flags=re.IGNORECASE)
    response = re.sub(r"```", "", response)

    start = response.find("[")
    end = response.rfind("]")

    if start == -1 or end == -1:
        return []

    response = response[start:end + 1]

    try:
        return json.loads(response)

    except Exception:
        return []


def generate_architecture(requirements):

    architecture = {}

    # ==========================================
    # Generate Architecture Diagram
    # ==========================================

    architecture["architecture_diagram"] = \
        generate_architecture_diagram(requirements)

    # ==========================================
    # Generate Project Flow
    # ==========================================

    architecture["project_flow"] = \
        generate_project_flow(requirements)

    # ==========================================
    # Generate Actors
    # ==========================================

    actors = generate_actors(requirements)

    architecture["actors"] = parse_json_response(actors)

    # ==========================================
    # Generate Modules
    # ==========================================

    modules = generate_modules(requirements)

    architecture["modules"] = parse_json_response(modules)

    # ==========================================
    # Generate REST APIs
    # ==========================================

    apis = generate_rest_apis(requirements)

    architecture["rest_apis"] = parse_json_response(apis)

    # ==========================================
    # Fixed Technology Stack
    # ==========================================

    architecture["technology_stack"] = {

        "Frontend": "HTML, CSS, JavaScript",

        "Backend": "Flask",

        "Database": "PostgreSQL",

        "Local LLM": "Ollama",

        "Model": "Qwen2.5",

        "Embeddings": "BAAI/bge-small-en-v1.5",

        "Vector Database": "ChromaDB",

        "Deployment": "GitHub + Render + Neon"

    }

    # ==========================================
    # Fixed Folder Structure
    # ==========================================

    architecture["folder_structure"] = [

        "backend/",
        "backend/agents/",
        "backend/routes/",
        "backend/services/",
        "backend/rag/",
        "backend/templates/",
        "backend/static/",
        "backend/generated_projects/",
        "database/"

    ]

    return architecture