from agents.backend_structure_generator import generate_backend_structure


def generate_backend(
    requirements,
    architecture,
    database
):

    backend_structure = generate_backend_structure(
        requirements,
        architecture,
        database
    )

    return {
        "structure": backend_structure
    }