from agents.backend_code_generator import generate_backend_code
from agents.frontend_code_generator import generate_frontend_code

def generate_project(
    requirements,
    architecture,
    database,
    backend,
    frontend
):

    backend_code = generate_backend_code(
        requirements,
        architecture,
        database
    )

    frontend_code = generate_frontend_code(
        requirements,
        architecture,
        database
    )

    return {

        "backend": backend_code,

        "frontend": frontend_code

    }