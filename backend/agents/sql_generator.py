from services.ollama_service import generate_response


def generate_sql(requirements, architecture):

    prompt = f"""
You are a PostgreSQL Database Engineer.

PROJECT REQUIREMENTS:
{requirements}

APPROVED SYSTEM ARCHITECTURE:
{architecture}

Generate the complete PostgreSQL database schema
required by the approved architecture.

The SQL must match the database tables and relationships
required by the project.

Rules:

1. Use PostgreSQL syntax.
2. Use CREATE TABLE statements.
3. Every table must have a PRIMARY KEY.
4. Use FOREIGN KEY constraints where required.
5. Use appropriate PostgreSQL data types.
6. Maintain consistent table and column names.
7. Do not create unrelated tables.
8. Do not include explanations.
9. Return SQL only.
10. Do not use markdown code fences.

Generate the complete schema.
"""

    return generate_response(prompt).strip()