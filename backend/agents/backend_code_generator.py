from services.ollama_service import generate_response


def generate_backend_code(
    requirements,
    architecture,
    database
):

    prompt = f"""
You are a Principal Flask Backend Architect.

Generate a COMPLETE production-ready Flask backend.

==================================================
PROJECT REQUIREMENTS
==================================================

{requirements}

==================================================
SYSTEM ARCHITECTURE
==================================================

{architecture}

==================================================
DATABASE DESIGN
==================================================

{database}

==================================================
MANDATORY FILES
==================================================

Generate ALL backend files.

### app.py
### routes.py
### models.py
### config.py
### requirements.txt

==================================================
RULES
==================================================

1. Generate COMPLETE code.
2. No placeholders.
3. No TODO comments.
4. No pass statements.
5. No explanations.
6. No markdown descriptions.
7. No text before or after files.
8. Every API must have working implementation.
9. Include SQLAlchemy models.
10. Include Flask configuration.
11. Include database connection.
12. Include CRUD operations.
13. Include validation.
14. Include error handling.
15. Include imports.
16. Code must be executable.

==================================================
OUTPUT FORMAT
==================================================

### app.py
<full code>

### routes.py
<full code>

### models.py
<full code>

### config.py
<full code>

### requirements.txt
<full content>

Return ALL files.
"""

    return generate_response(prompt)