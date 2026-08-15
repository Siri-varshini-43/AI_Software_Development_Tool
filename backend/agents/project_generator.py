from services.project_builder import build_project


def generate_project(

    project_name,

    backend_code,

    frontend_code,

    database_sql

):

    project_path = build_project(

        project_name,

        backend_code,

        frontend_code,

        database_sql

    )

    return {

        "success": True,

        "project_path": project_path

    }