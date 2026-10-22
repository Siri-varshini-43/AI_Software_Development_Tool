from agents.diagram_generator import generate_architecture_diagram


def generate_architecture(requirements):
    return {
        "architecture_diagram": generate_architecture_diagram(requirements)
    }