from services.ollama_service import generate_response


def generate_architecture_diagram(requirements):

    prompt = f"""
You are an expert Software Architect.

Requirements:

{requirements}

Generate ONLY Mermaid code.

Rules:

1. Output ONLY Mermaid.
2. First line MUST be exactly:

graph LR

3. Do NOT use markdown.
4. Do NOT explain.
5. Every connection must use -->

Example:

graph LR

Patient --> Frontend

Doctor --> Frontend

Admin --> Frontend

Frontend --> Authentication

Authentication --> PatientModule

Authentication --> AppointmentModule

PatientModule --> PostgreSQL

AppointmentModule --> PostgreSQL
"""

    return generate_response(prompt).strip()