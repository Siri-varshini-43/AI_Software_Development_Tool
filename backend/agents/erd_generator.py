from services.ollama_service import generate_response
import re


def generate_erd(requirements, architecture):

    prompt = f"""
You are an expert Database Architect.

PROJECT REQUIREMENTS:
{requirements}

APPROVED SYSTEM ARCHITECTURE:
{architecture}

Generate ONLY a Mermaid ER Diagram.

IMPORTANT RULES:

1. The FIRST line MUST be:

erDiagram

2. Do NOT write:

erDiagram {{
}}

3. Do NOT use aliases such as:

Patient as P
Doctor as D

4. Entity names MUST be UPPERCASE.

Example:

PATIENT {{
    string id
    string firstName
    string lastName
}}

DOCTOR {{
    string id
    string name
}}

5. Relationships MUST use Mermaid ER syntax:

PATIENT ||--o{{ APPOINTMENT : books
DOCTOR ||--o{{ APPOINTMENT : handles

6. Include entity attributes.

7. Include primary foreign-key relationships.

8. Do NOT use markdown code fences.

9. Do NOT provide explanations.

10. Return ONLY Mermaid code.

Example Output:

erDiagram

    PATIENT {{
        string id
        string name
    }}

    DOCTOR {{
        string id
        string name
    }}

    APPOINTMENT {{
        int id
        string patientId
        string doctorId
    }}

    PATIENT ||--o{{ APPOINTMENT : books
    DOCTOR ||--o{{ APPOINTMENT : handles
"""

    response = generate_response(prompt)

    print("\n===== RAW ERD =====")
    print(response)
    print("===================\n")

    # Remove markdown fences
    response = re.sub(
        r"```mermaid",
        "",
        response,
        flags=re.IGNORECASE
    )

    response = re.sub(
        r"```",
        "",
        response
    )

    response = response.strip()

    # Extract from erDiagram onward
    match = re.search(
        r"erDiagram[\s\S]*",
        response
    )

    if not match:
        raise Exception(
            "AI did not return a valid Mermaid ER Diagram."
        )

    response = match.group(0).strip()

    # Prevent invalid syntax
    if "erDiagram {" in response:
        raise Exception(
            "Invalid Mermaid syntax generated. "
            "AI returned 'erDiagram {{ }}'."
        )

    print("\n===== CLEANED ERD =====")
    print(response)
    print("=======================\n")

    return response