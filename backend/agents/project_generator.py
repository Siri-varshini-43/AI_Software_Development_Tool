import os

from agents.backend_code_generator import (
    generate_backend_code
)

from agents.frontend_code_generator import (
    generate_frontend_code
)

from agents.file_parser import (
    parse_and_save_files
)


def generate_project(
    requirements,
    architecture,
    database,
    backend,
    frontend
):

    project_path = os.path.join(
        "generated_projects",
        "project"
    )

    backend_path = os.path.join(
        project_path,
        "backend"
    )

    frontend_path = os.path.join(
        project_path,
        "frontend"
    )

    os.makedirs(
        backend_path,
        exist_ok=True
    )

    os.makedirs(
        frontend_path,
        exist_ok=True
    )

    print("\n========== BACKEND ==========")

    backend_code = generate_backend_code(
        requirements,
        architecture,
        database
    )

    print(backend_code)

    backend_files = parse_and_save_files(
        backend_code,
        backend_path
    )

    print(
        f"Backend Files Saved: {len(backend_files)}"
    )

    print("\n========== FRONTEND ==========")

    frontend_code = generate_frontend_code(
        requirements,
        architecture,
        backend
    )

    print(frontend_code)

    frontend_files = parse_and_save_files(
        frontend_code,
        frontend_path
    )

    print(
        f"Frontend Files Saved: {len(frontend_files)}"
    )

    all_files = (
        backend_files +
        frontend_files
    )

    return {

        "success": True,

        "project_path": project_path,

        "backend_generated":
            len(backend_files) > 0,

        "frontend_generated":
            len(frontend_files) > 0,

        "files": all_files

    }