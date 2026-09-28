from agents.frontend_structure_generator import (
    generate_frontend_structure
)

from services.ollama_service import (
    generate_response
)


def generate_frontend(
    requirements,
    architecture,
    database,
    backend
):

    # =====================================
    # FRONTEND TECH STACK
    # =====================================

    tech_stack_prompt = f"""
Project Requirements:
{requirements}

Generate only Frontend Technology Stack.

Use:
- HTML
- CSS
- JavaScript

Return clean text only.
"""

    frontend_tech_stack = generate_response(
        tech_stack_prompt
    )

    # =====================================
    # FRONTEND STRUCTURE
    # =====================================

    frontend_structure = (
        generate_frontend_structure(
            requirements,
            architecture,
            database,
            backend
        )
    )

    # =====================================
    # FRONTEND PAGES
    # =====================================

    pages_prompt = f"""
Project Requirements:
{requirements}

Architecture:
{architecture}

Generate:

Frontend Pages List

Return only page names with short description.

Example:

1. login.html
2. register.html
3. dashboard.html

Return clean text only.
"""

    frontend_pages = generate_response(
        pages_prompt
    )

    # =====================================
    # RETURN
    # =====================================

    return {

        "tech_stack":
            frontend_tech_stack,

        "structure":
            frontend_structure,

        "pages":
            frontend_pages

    }