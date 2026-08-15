from services.ollama_service import generate_response


def generate_routes(
    requirements,
    architecture,
    database
):

    prompt = f"""
You are a Flask REST API architect.

PROJECT REQUIREMENTS:
{requirements}

ARCHITECTURE:
{architecture}

DATABASE:
{database}

Generate Flask REST API routes.

Include:

GET
POST
PUT
DELETE

Return route code only.
"""

    return generate_response(prompt)