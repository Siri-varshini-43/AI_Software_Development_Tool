import os


def create_file(path, content):

    os.makedirs(
        os.path.dirname(path),
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(content)


def build_project(
    project_name,
    backend_code,
    frontend_code,
    database_sql
):

    base_path = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        ),
        "generated_projects",
        project_name
    )

    # =========================
    # BACKEND
    # =========================

    create_file(
        os.path.join(
            base_path,
            "backend",
            "app.py"
        ),
        backend_code.get(
            "app.py",
            ""
        )
    )

    create_file(
        os.path.join(
            base_path,
            "backend",
            "config.py"
        ),
        backend_code.get(
            "config.py",
            ""
        )
    )

    create_file(
        os.path.join(
            base_path,
            "backend",
            "requirements.txt"
        ),
        backend_code.get(
            "requirements.txt",
            ""
        )
    )

    # =========================
    # FRONTEND
    # =========================

    create_file(
        os.path.join(
            base_path,
            "frontend",
            "index.html"
        ),
        frontend_code.get(
            "index.html",
            ""
        )
    )

    create_file(
        os.path.join(
            base_path,
            "frontend",
            "css",
            "style.css"
        ),
        frontend_code.get(
            "style.css",
            ""
        )
    )

    create_file(
        os.path.join(
            base_path,
            "frontend",
            "js",
            "app.js"
        ),
        frontend_code.get(
            "app.js",
            ""
        )
    )

    # =========================
    # DATABASE
    # =========================

    create_file(
        os.path.join(
            base_path,
            "database",
            "schema.sql"
        ),
        database_sql
    )

    return base_path