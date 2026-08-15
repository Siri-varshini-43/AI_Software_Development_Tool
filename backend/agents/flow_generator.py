from services.ollama_service import generate_response
import re


def generate_project_flow(requirements):

    prompt = f"""
You are an Expert Software Architect.

Software Requirements:

{requirements}

Generate ONLY a BUSINESS WORKFLOW.

The workflow should contain ONLY the MAIN STEPS.

Maximum 10 nodes.

Use EXACTLY this Mermaid syntax.

flowchart TD

Start([Start])

-->

Login[Login]

-->

Dashboard[Dashboard]

-->

MainProcess[Main Process]

-->

Database[(Database)]

-->

Notification[Notification]

-->

End([End])

Rules:

1. Return ONLY Mermaid.
2. First line MUST be:
flowchart TD
3. Do NOT explain.
4. Do NOT use markdown.
5. Do NOT create more than 10 nodes.
6. Keep node names short.
7. Show only the main workflow.
8. Every node must connect to the next node.
9. Never generate isolated nodes.
10. Never generate security, SQL Injection, Authentication, Authorization as separate flows unless they are essential business steps.
"""

    response = generate_response(prompt).strip()

    # Remove markdown if present
    response = re.sub(r"```mermaid", "", response, flags=re.IGNORECASE)
    response = re.sub(r"```", "", response)

    # Keep only Mermaid flowchart
    index = response.find("flowchart TD")

    if index != -1:
        response = response[index:]

    return response.strip()