from services.ollama_service import generate_response


def generate_modules(requirements):

    prompt = f"""
You are a Software Architect.

Requirements:

{requirements}

List ONLY the software modules.

Rules:

1. Return JSON array.

Example:

[
"Authentication Module",
"Patient Module",
"Doctor Module",
"Appointment Module",
"Billing Module"
]

No explanation.
"""

    return generate_response(prompt).strip()