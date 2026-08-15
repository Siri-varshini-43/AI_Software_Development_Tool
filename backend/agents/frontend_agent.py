from agents.frontend_structure_generator import generate_frontend_structure


def generate_frontend(
    requirements,
    architecture,
    database,
    backend
):

    frontend_structure = generate_frontend_structure(
        requirements,
        architecture,
        database,
        backend
    )

    return {
        "structure": frontend_structure
    }