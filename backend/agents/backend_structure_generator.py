from services.ollama_service import generate_response

def generate_backend_structure(
    requirements,
    architecture,
    database
):

    prompt = f"""
You are a Senior Software Architect.

Requirements:
{requirements}

Architecture:
{architecture}

Database:
{database}

Generate ONLY:

1. Backend Technology Stack
2. Backend Folder Structure
3. Backend Modules

Do NOT generate source code.
Do NOT generate models.
Do NOT generate API routes.
Do NOT generate authentication code.

Return clean structured text.
"""

    return generate_response(prompt)