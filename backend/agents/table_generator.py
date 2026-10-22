from services.ollama_service import generate_response


def generate_tables(requirements, architecture):

    prompt = f"""
You are a Database Architect.

PROJECT REQUIREMENTS:
{requirements}

APPROVED SYSTEM ARCHITECTURE:
{architecture}

Design the PostgreSQL database based strictly on the
approved architecture and requirements.

Use the requirements as the source of truth for entities and relationships.
The architecture diagram is context only.

For each foreign-key column, set "foreign_key" to the referenced
"table.column" (for example, "patients.id"). Use an empty string for
columns that are not foreign keys.

Return ONLY valid JSON.

Required format:

[
    {{
        "table_name": "patients",
        "columns": [
            {{
                "name": "id",
                "type": "SERIAL",
                "primary_key": true,
                "foreign_key": ""
            }},
            {{
                "name": "name",
                "type": "VARCHAR(100)",
                "primary_key": false,
                "foreign_key": ""
            }}
        ]
    }}
]

Rules:

1. Use PostgreSQL data types.
2. Every table must have a primary key.
3. Use foreign keys for relationships.
4. Do not create unrelated tables.
5. Tables must support the approved modules.
6. Use consistent table and column names.
7. Do not include explanations.
8. Return ONLY JSON.
"""

    return generate_response(prompt)