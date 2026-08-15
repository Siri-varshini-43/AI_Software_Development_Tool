from services.ollama_service import generate_response


def generate_frontend_structure(
    requirements,
    architecture,
    database,
    backend
):

    prompt = f"""
You are a Senior Frontend Architect.

Requirements:
{requirements}

Architecture:
{architecture}

Database:
{database}

Backend:
{backend}

Generate ONLY:

1. Frontend Technology Stack
2. Frontend Folder Structure
3. Frontend Pages

Return in clean text format.
"""

    return generate_response(prompt)