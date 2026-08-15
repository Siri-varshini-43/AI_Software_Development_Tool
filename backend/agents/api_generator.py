from services.ollama_service import generate_response


def generate_rest_apis(requirements):

    prompt = f"""
You are a Backend Architect.

Requirements:

{requirements}

Generate REST APIs.

Return ONLY JSON.

Example:

[
{{

"method":"POST",

"url":"/api/register",

"description":"Register Patient"

}},

{{

"method":"POST",

"url":"/api/login",

"description":"Login User"

}}

]

No explanation.
"""

    return generate_response(prompt).strip()