from services.ollama_service import generate_response


def generate_models(
    requirements,
    architecture,
    database
):

    prompt = f"""
You are a Flask SQLAlchemy expert.

PROJECT REQUIREMENTS:
{requirements}

ARCHITECTURE:
{architecture}

DATABASE:
{database}

Generate SQLAlchemy model definitions.

Include:

- table names
- columns
- primary keys
- foreign keys

Return only model code.
"""

    return generate_response(prompt)