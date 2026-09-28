from services.ollama_service import generate_response


def generate_frontend_code(
    requirements,
    architecture,
    backend
):

    prompt = f"""
You are a Senior Frontend Architect.

Generate a COMPLETE production-ready frontend.

==================================================
PROJECT REQUIREMENTS
==================================================

{requirements}

==================================================
SYSTEM ARCHITECTURE
==================================================

{architecture}

==================================================
BACKEND DESIGN
==================================================

{backend}

==================================================
MANDATORY FILES
==================================================

### index.html
### style.css
### script.js

==================================================
RULES
==================================================

1. Generate COMPLETE code.
2. No TODO comments.
3. No placeholders.
4. No explanations.
5. No markdown text.
6. No text outside file sections.
7. Responsive UI.
8. Modern CSS design.
9. Forms and validation.
10. API integration using fetch().
11. Event handlers.
12. Navigation.
13. User-friendly interface.
14. Executable code.

==================================================
OUTPUT FORMAT
==================================================

### index.html
<full code>

### style.css
<full code>

### script.js
<full code>

Return ALL files.
"""

    return generate_response(prompt)