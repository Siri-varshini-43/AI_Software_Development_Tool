from services.ollama_service import generate_response


def generate_auth(
    requirements,
    architecture,
    database
):

    prompt = f"""
You are a Flask authentication expert.

PROJECT REQUIREMENTS:
{requirements}

ARCHITECTURE:
{architecture}

DATABASE:
{database}

Generate authentication design.

Include:

- JWT
- Login
- Register
- Role Based Access Control

Return only backend authentication code.
"""

    return generate_response(prompt)