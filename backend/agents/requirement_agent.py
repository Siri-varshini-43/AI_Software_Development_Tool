from services.ollama_service import generate_response

def analyze_requirements(project_description):

    prompt = f"""
You are a Senior Software Requirements Engineer.

Your job is to convert a user's project idea into a Software Requirement Specification (SRS).

Project Description:
{project_description}

Generate ONLY the following sections:

## Functional Requirements
- List the main features.

## Non-Functional Requirements
- Performance
- Security
- Usability

## Actors
- List all users of the system.

## Modules
- Break the project into modules.

Do not generate source code.
Do not generate HTML.
Do not generate CSS.
Do not generate JavaScript.
Do not generate Python.

Return the answer in clean Markdown.

Important Instructions:

- Keep the response below 300 words.
- Use concise bullet points.
- Do not explain.
- Do not generate markdown code blocks.
"""

    return generate_response(prompt)