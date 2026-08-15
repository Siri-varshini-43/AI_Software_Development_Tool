from services.ollama_service import generate_response


def generate_actors(requirements):

    prompt = f"""
You are a Software Architect.

Requirements:

{requirements}

Extract ONLY the actors involved in the software system.

Rules:

1. Return ONLY a JSON array.
2. Do NOT explain anything.
3. Do NOT use markdown.
4. Do NOT use ```json.
5. Each actor should be a string.
6. Do not include duplicates.

Example:

[
    "Patient",
    "Doctor",
    "Administrator"
]

If the project contains additional actors, include them.

Return JSON only.
"""

    return generate_response(prompt).strip()