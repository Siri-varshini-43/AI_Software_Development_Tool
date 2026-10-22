import os
import re
import json
import logging
import secrets
import shutil
import subprocess
import tempfile
import urllib.parse
import base64
import time
from datetime import datetime, timedelta, timezone
import requests

logger = logging.getLogger(__name__)

NEON_API_BASE = "https://console.neon.tech/api/v2"
RENDER_API_BASE = "https://api.render.com/v1"
GITHUB_API_BASE = "https://api.github.com"
RENDER_DEPLOY_POLL_INTERVAL_SECONDS = 5
RENDER_DEPLOY_TIMEOUT_SECONDS = 600
RENDER_DEPLOY_FAILURE_STATUSES = {
    "build_failed",
    "update_failed",
    "pre_deploy_failed",
    "canceled",
    "deactivated",
}


def _render_error(response, action: str) -> RuntimeError:
    return RuntimeError(
        f"{action} failed ({response.status_code}): {response.text}"
    )


def _fetch_render_logs(
    service_id: str, owner_id: str, headers: dict, log_type: str
) -> str:
    """Fetch recent Render build or application logs for a failed deployment."""
    params = {
        "ownerId": owner_id,
        "resource": service_id,
        "type": log_type,
        "startTime": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "endTime": datetime.now(timezone.utc).isoformat(),
        "direction": "backward",
        "limit": 100,
    }
    try:
        response = requests.get(
            f"{RENDER_API_BASE}/logs",
            headers=headers,
            params=params,
            timeout=20,
        )
        if not response.ok:
            logger.warning(
                "Could not retrieve Render %s logs (%s): %s",
                log_type,
                response.status_code,
                response.text,
            )
            return ""
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not retrieve Render %s logs: %s", log_type, exc)
        return ""

    entries = data if isinstance(data, list) else data.get("logs", [])
    messages = [
        entry.get("message", "")
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("message"), str)
    ]
    return "\n".join(message for message in reversed(messages[-20:]) if message)


def _wait_for_render_deploy(
    service_id: str, deploy_id: str, headers: dict, owner_id: str = "", emit=None
):
    """Wait until Render reports the requested deployment live or definitively failed."""
    def log(msg):
        if emit:
            emit({"type": "log", "message": msg})
        logger.info(msg)

    deadline = time.monotonic() + RENDER_DEPLOY_TIMEOUT_SECONDS
    last_status = None
    deploy_url = f"{RENDER_API_BASE}/services/{service_id}/deploys/{deploy_id}"

    while time.monotonic() < deadline:
        response = requests.get(deploy_url, headers=headers, timeout=20)
        if not response.ok:
            raise _render_error(response, "Failed to check Render deployment status")

        deploy = response.json()
        status = deploy.get("status")
        if status != last_status:
            log(f"Render deployment status: {status or 'unknown'}.")
            last_status = status

        if status == "live":
            return
        if status in RENDER_DEPLOY_FAILURE_STATUSES:
            log_sections = []
            if owner_id:
                for log_type in ("app", "build"):
                    output = _fetch_render_logs(
                        service_id, owner_id, headers, log_type
                    )
                    if output:
                        log_sections.append(
                            f"Recent Render {log_type} output:\n{output}"
                        )
            log_details = (
                "\n" + "\n".join(log_sections)
                if log_sections
                else "\nOpen the Render dashboard's Events and Logs tabs for the exact failure reason."
            )
            raise RuntimeError(
                f"Render deployment failed with status '{status}'. "
                f"View build logs in the Render dashboard: "
                f"https://dashboard.render.com/web/{service_id}{log_details}"
            )

        time.sleep(RENDER_DEPLOY_POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Render deployment did not become live within "
        f"{RENDER_DEPLOY_TIMEOUT_SECONDS // 60} minutes. Check its build logs in "
        f"https://dashboard.render.com/web/{service_id}"
    )


def normalize_postgres_url(url: str) -> str:
    """Normalize postgres URLs to standard postgresql:// format and ensure sslmode for Neon."""
    if not url:
        return ""
    clean_url = url.strip()
    if clean_url.startswith("postgres://"):
        clean_url = "postgresql://" + clean_url[len("postgres://"):]

    if "neon.tech" in clean_url and "sslmode=" not in clean_url:
        separator = "&" if "?" in clean_url else "?"
        clean_url = f"{clean_url}{separator}sslmode=require"

    return clean_url


def parse_schema_sql(schema_sql: str) -> list:
    """Parse schema.sql into clean individual executable SQL statements."""
    if not schema_sql:
        return []

    # Strip multi-line comments /* ... */
    cleaned = re.sub(r"/\*.*?\*/", "", schema_sql, flags=re.DOTALL)

    # Strip single-line comments -- ...
    cleaned = re.sub(r"--[^\r\n]*", "", cleaned)

    statements = []
    current = []
    in_single_quote = False
    in_double_quote = False
    in_dollar_quote = False
    dollar_tag = ""
    i = 0
    n = len(cleaned)

    while i < n:
        char = cleaned[i]

        if not in_single_quote and not in_double_quote:
            # Check for dollar quoting $$ or $tag$
            if char == "$":
                match = re.match(r"\$[A-Za-z0-9_]*\$", cleaned[i:])
                if match:
                    tag = match.group(0)
                    if in_dollar_quote and tag == dollar_tag:
                        in_dollar_quote = False
                        dollar_tag = ""
                    elif not in_dollar_quote:
                        in_dollar_quote = True
                        dollar_tag = tag
                    current.append(tag)
                    i += len(tag)
                    continue

        if not in_dollar_quote:
            if char == "'" and not in_double_quote:
                # Handle escaped single quote ''
                if in_single_quote and i + 1 < n and cleaned[i + 1] == "'":
                    current.append("''")
                    i += 2
                    continue
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif char == ";" and not in_single_quote and not in_double_quote:
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                i += 1
                continue

        current.append(char)
        i += 1

    last_stmt = "".join(current).strip()
    if last_stmt:
        statements.append(last_stmt)

    return statements


def execute_schema_on_postgres(connection_url: str, schema_sql: str) -> dict:
    """Execute SQL statements from schema.sql on a PostgreSQL database."""
    normalized_url = normalize_postgres_url(connection_url)
    statements = parse_schema_sql(schema_sql)

    if not statements:
        return {
            "success": True,
            "message": "No SQL statements found in schema.",
            "tables": [],
            "table_count": 0,
        }

    # Try psycopg2 first
    try:
        import psycopg2

        conn = psycopg2.connect(normalized_url)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)

                # Query existing tables in public schema
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name;"
                )
                rows = cur.fetchall()
                tables = [r[0] for r in rows]
        finally:
            conn.close()

        return {
            "success": True,
            "tables": tables,
            "table_count": len(tables),
            "message": f"Successfully applied schema. Created {len(tables)} tables.",
        }
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("psycopg2 execution failed, attempting pg8000: %s", exc)

    # Fallback to pg8000
    try:
        import pg8000.native

        parsed = urllib.parse.urlparse(normalized_url)
        port = parsed.port or 5432
        ssl_context = True if "sslmode=require" in normalized_url or "neon.tech" in (parsed.hostname or "") else False

        conn = pg8000.native.Connection(
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=port,
            database=parsed.path.lstrip("/"),
            ssl_context=ssl_context,
        )
        try:
            for stmt in statements:
                conn.run(stmt)

            rows = conn.run(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name;"
            )
            tables = [r[0] for r in rows]
        finally:
            conn.close()

        return {
            "success": True,
            "tables": tables,
            "table_count": len(tables),
            "message": f"Successfully applied schema. Created {len(tables)} tables.",
        }
    except Exception as exc:
        raise RuntimeError(f"Failed to execute schema.sql on PostgreSQL: {exc}") from exc


def provision_neon_project(api_key: str, project_name: str) -> dict:
    """Create a new project/database on Neon via their REST API."""
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", project_name).strip("-")[:40] or "ai-project"

    payload = {
        "project": {
            "name": clean_name
        }
    }

    response = requests.post(
        f"{NEON_API_BASE}/projects",
        headers=headers,
        json=payload,
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"Neon API project creation failed ({response.status_code}): {response.text}"
        )

    data = response.json()
    project = data.get("project", {})
    project_id = project.get("id")

    connection_uri = ""
    # Neon returns connection_uris in the project creation response
    connection_uris = project.get("connection_uris") or []
    if connection_uris:
        connection_uri = connection_uris[0].get("connection_uri", "")

    # If connection_uri was not in the initial response, fetch it
    if not connection_uri and project_id:
        uri_res = requests.get(
            f"{NEON_API_BASE}/projects/{project_id}/connection_uri",
            headers=headers,
            params={"database_name": "neondb", "role_name": "neondb_owner"},
            timeout=20,
        )
        if uri_res.ok:
            connection_uri = uri_res.json().get("uri", "")

    if not connection_uri:
        # Fallback to inspecting endpoints/databases
        endpoints = data.get("endpoints") or []
        roles = data.get("roles") or []
        databases = data.get("databases") or []
        if endpoints and roles:
            host = endpoints[0].get("host", "")
            user = roles[0].get("name", "neondb_owner")
            pwd = roles[0].get("password", "")
            db = databases[0].get("name", "neondb") if databases else "neondb"
            connection_uri = f"postgresql://{user}:{pwd}@{host}/{db}?sslmode=require"

    if not connection_uri:
        raise RuntimeError("Neon project was created, but unable to retrieve connection URI.")

    connection_uri = normalize_postgres_url(connection_uri)

    return {
        "project_id": project_id,
        "name": clean_name,
        "connection_uri": connection_uri,
        "console_url": f"https://console.neon.tech/app/projects/{project_id}",
    }


def deploy_neon_database(
    project_path: str,
    neon_api_key: str = None,
    neon_database_url: str = None,
    project_name: str = None,
    emit=None,
) -> dict:
    """Deploy database to Neon using schema.sql."""
    def log(msg, level="info"):
        if emit:
            emit({"type": "log", "message": msg, "level": level})
        logger.info(msg)

    # 1. Locate schema.sql
    schema_paths = [
        os.path.join(project_path, "database", "schema.sql"),
        os.path.join(project_path, "schema.sql"),
    ]
    schema_file = next((p for p in schema_paths if os.path.isfile(p)), None)

    if not schema_file:
        raise FileNotFoundError(
            f"Could not find schema.sql in {project_path}. Expected at database/schema.sql."
        )

    with open(schema_file, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    log(f"Found schema.sql ({len(schema_sql)} bytes).")

    # 2. Get connection URI
    active_connection_uri = ""
    neon_project_id = ""
    console_url = ""

    if neon_database_url and neon_database_url.strip():
        active_connection_uri = normalize_postgres_url(neon_database_url.strip())
        log("Using provided Neon Database URL.")
    elif neon_api_key and neon_api_key.strip():
        log("Provisioning serverless PostgreSQL database on Neon via API...")
        neon_proj = provision_neon_project(neon_api_key.strip(), project_name or "ai-project")
        active_connection_uri = neon_proj["connection_uri"]
        neon_project_id = neon_proj["project_id"]
        console_url = neon_proj["console_url"]
        log(f"Neon database provisioned! Project ID: {neon_project_id}")
    else:
        raise ValueError(
            "Neither NEON_API_KEY nor NEON_DATABASE_URL was provided. "
            "Please provide a Neon API key or database URL to deploy the database."
        )

    # 3. Apply schema.sql
    log("Applying schema.sql to Neon PostgreSQL database...")
    result = execute_schema_on_postgres(active_connection_uri, schema_sql)
    tables = result.get("tables", [])
    log(f"Database schema deployed successfully to Neon! Created tables: {', '.join(tables) or 'None'}")

    return {
        "success": True,
        "connection_uri": active_connection_uri,
        "project_id": neon_project_id,
        "console_url": console_url or "https://console.neon.tech",
        "tables": tables,
        "table_count": len(tables),
    }


def create_and_push_github_repo(
    project_path: str,
    github_token: str,
    repo_name: str = None,
    is_private: bool = False,
    emit=None,
) -> dict:
    """Create a GitHub repository and push project files using git CLI."""
    def log(msg, level="info"):
        if emit:
            emit({"type": "log", "message": msg, "level": level})
        logger.info(msg)

    clean_token = github_token.strip()
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-Software-Engineering-Platform",
    }

    # 1. Verify user identity
    log("Verifying GitHub credentials...")
    user_res = requests.get(f"{GITHUB_API_BASE}/user", headers=headers, timeout=20)
    if not user_res.ok:
        raise RuntimeError(
            f"GitHub authentication failed ({user_res.status_code}): {user_res.text}"
        )
    user_data = user_res.json()
    github_username = user_data.get("login")
    log(f"Authenticated as GitHub user: @{github_username}")

    # 2. Determine repository name
    target_repo_name = (
        repo_name or f"ai-project-{os.path.basename(os.path.abspath(project_path))}"
    )
    target_repo_name = re.sub(r"[^a-zA-Z0-9._-]", "-", target_repo_name).strip("-")

    # 3. Create repository if not already existing
    repository_exists = False
    log(f"Creating GitHub repository '{target_repo_name}'...")
    repo_res = requests.post(
        f"{GITHUB_API_BASE}/user/repos",
        headers=headers,
        json={
            "name": target_repo_name,
            "description": "Auto-generated project deployed from AI Software Engineering Platform",
            "private": is_private,
            "auto_init": False,
        },
        timeout=20,
    )

    if repo_res.status_code == 422:
        log(f"Repository '{target_repo_name}' already exists. Will update its main branch.")
        check_repo = requests.get(
            f"{GITHUB_API_BASE}/repos/{github_username}/{target_repo_name}",
            headers=headers,
            timeout=20,
        )
        if not check_repo.ok:
            raise RuntimeError(f"Repository exists but cannot be accessed: {check_repo.text}")
        repo_data = check_repo.json()
        repository_exists = True
    elif not repo_res.ok:
        raise RuntimeError(
            f"Failed to create GitHub repository ({repo_res.status_code}): {repo_res.text}"
        )
    else:
        repo_data = repo_res.json()

    repo_html_url = repo_data.get("html_url")
    log(f"GitHub repository ready: {repo_html_url}")

    # 4. Prepare local files in a temporary deploy staging directory
    temp_git_dir = tempfile.mkdtemp(prefix="git-deploy-")
    try:
        auth_header = base64.b64encode(
            f"x-access-token:{clean_token}".encode("utf-8")
        ).decode("ascii")
        git_env = os.environ.copy()
        git_env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth_header}",
        })

        def run_git(args):
            res = subprocess.run(
                ["git"] + args,
                cwd=temp_git_dir,
                env=git_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode != 0:
                if "non-fast-forward" in res.stderr.lower() or "fetch first" in res.stderr.lower():
                    raise RuntimeError(
                        f"Could not safely update GitHub repository '{target_repo_name}': "
                        "the remote branch has commits that are not in the local history. "
                        "No remote commits were overwritten."
                    )
                raise RuntimeError(f"Git command 'git {' '.join(args)}' failed: {res.stderr}")
            return res.stdout

        remote_url = f"https://github.com/{github_username}/{target_repo_name}.git"
        default_branch = repo_data.get("default_branch") if repository_exists else None
        cloned_existing_repository = repository_exists and bool(default_branch)
        if cloned_existing_repository:
            log(f"Cloning existing repository branch '{default_branch}' for a safe update...")
            run_git(["clone", "--branch", default_branch, "--single-branch", remote_url, "."])
            if default_branch != "main":
                run_git(["branch", "-M", "main"])
        else:
            run_git(["init", "-b", "main"])

        log("Staging generated project files...")
        ignored_files = {".git", ".env", "__pycache__", ".pytest_cache", "venv"}
        for item in os.listdir(project_path):
            if item in ignored_files:
                continue
            src = os.path.join(project_path, item)
            dst = os.path.join(temp_git_dir, item)
            if os.path.isdir(src):
                shutil.copytree(
                    src,
                    dst,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
                        ".git", ".env", "__pycache__", "*.pyc", ".pytest_cache", "venv"
                    ),
                )
            else:
                shutil.copy2(src, dst)

        gitignore_path = os.path.join(temp_git_dir, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write("__pycache__/\n*.pyc\nvenv/\n.env\n.pytest_cache/\n")

        procfile_path = os.path.join(temp_git_dir, "Procfile")
        if not os.path.exists(procfile_path):
            with open(procfile_path, "w", encoding="utf-8") as f:
                f.write("web: gunicorn --bind 0.0.0.0:$PORT backend.app:app\n")

        backend_requirements = os.path.join(temp_git_dir, "backend", "requirements.txt")
        if os.path.isfile(backend_requirements):
            with open(backend_requirements, "r", encoding="utf-8") as f:
                requirements = f.read()
            if not re.search(r"(?im)^\s*gunicorn(?:\s|[<>=!~;]|$)", requirements):
                with open(backend_requirements, "a", encoding="utf-8") as f:
                    f.write("\ngunicorn\n")

        run_git(["config", "user.name", "AI Platform Deployer"])
        run_git(["config", "user.email", "deployer@ai-platform.local"])
        if cloned_existing_repository:
            run_git(["branch", "--set-upstream-to", f"origin/{default_branch}", "main"])

        if run_git(["status", "--porcelain"]):
            run_git(["add", "-A"])
            run_git(["commit", "-m", "Deploy generated project"])
            if not cloned_existing_repository:
                run_git(["remote", "add", "origin", remote_url])
            log("Pushing project files to GitHub (main branch)...")
            run_git(["push", "-u", "origin", "main"])
            log("Successfully pushed project to GitHub!")
        else:
            log("GitHub repository already contains the current project files; no update is needed.")

    finally:
        shutil.rmtree(temp_git_dir, ignore_errors=True)

    return {
        "repo_name": target_repo_name,
        "repo_url": repo_html_url,
        "clone_url": f"https://github.com/{github_username}/{target_repo_name}.git",
        "owner": github_username,
    }


def deploy_to_render(
    repo_url: str,
    service_name: str,
    neon_database_url: str,
    render_api_key: str,
    render_owner_id: str = None,
    emit=None,
) -> dict:
    """Create or trigger deployment of a free Web Service on Render."""
    def log(msg, level="info"):
        if emit:
            emit({"type": "log", "message": msg, "level": level})
        logger.info(msg)

    clean_key = render_api_key.strip()
    headers = {
        "Authorization": f"Bearer {clean_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # 1. Resolve Owner ID if not given
    owner_id = render_owner_id
    if not owner_id:
        log("Fetching Render owner account details...")
        owners_res = requests.get(f"{RENDER_API_BASE}/owners", headers=headers, timeout=20)
        if not owners_res.ok:
            raise RuntimeError(
                f"Failed to fetch Render owners ({owners_res.status_code}): {owners_res.text}"
            )
        owners_list = owners_res.json()
        if not owners_list:
            raise RuntimeError("No Render owners found for the provided API key.")
        owner_id = owners_list[0].get("owner", {}).get("id") or owners_list[0].get("id")
        log(f"Using Render owner ID: {owner_id}")

    # 2. Check if service already exists
    clean_service_name = re.sub(r"[^a-zA-Z0-9-]", "-", service_name.lower()).strip("-")[:32]
    log(f"Checking for existing Render service '{clean_service_name}'...")

    check_res = requests.get(
        f"{RENDER_API_BASE}/services",
        headers=headers,
        params={"name": clean_service_name, "limit": 5},
        timeout=20,
    )

    service_id = ""
    service_url = ""

    if not check_res.ok:
        raise _render_error(check_res, "Failed to check existing Render services")

    existing_services = check_res.json()
    for item in existing_services:
        srv = item.get("service") or item
        if srv.get("name") == clean_service_name:
            service_id = srv.get("id")
            service_url = srv.get("serviceDetails", {}).get("url") or srv.get("url") or ""
            log(f"Found existing Render service ID: {service_id}")
            break

    secret_key = secrets.token_hex(24)
    deploy_id = ""

    # 3. Create service if not found
    if not service_id:
        log(f"Creating Render Web Service '{clean_service_name}'...")
        payload = {
            "type": "web_service",
            "name": clean_service_name,
            "ownerId": owner_id,
            "repo": repo_url,
            "branch": "main",
            "autoDeployTrigger": "off",
            "serviceDetails": {
                "runtime": "python",
                "envSpecificDetails": {
                    "buildCommand": "pip install -r backend/requirements.txt",
                    "startCommand": "gunicorn --bind 0.0.0.0:$PORT backend.app:app",
                },
                "plan": "free",
            },
            "envVars": [
                {
                    "key": "DATABASE_URL",
                    "value": normalize_postgres_url(neon_database_url),
                },
                {
                    "key": "SECRET_KEY",
                    "value": secret_key,
                },
                {
                    "key": "PYTHON_VERSION",
                    "value": "3.11.9",
                },
            ],
        }

        create_res = requests.post(
            f"{RENDER_API_BASE}/services",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if not create_res.ok:
            if create_res.status_code == 402:
                raise RuntimeError(
                    "Render rejected creation of the free web service because "
                    "the account requires payment information or billing "
                    f"verification: {create_res.text}"
                )
            raise RuntimeError(
                f"Failed to create Render service ({create_res.status_code}): {create_res.text}"
            )

        data = create_res.json()
        srv = data.get("service") or data
        service_id = srv.get("id")
        service_url = srv.get("serviceDetails", {}).get("url") or f"https://{clean_service_name}.onrender.com"
        deploy_id = (
            data.get("deployId")
            or (data.get("deploy") or {}).get("id", "")
        )
        log(f"Render Web Service created! Service ID: {service_id}")
    else:
        service_res = requests.get(
            f"{RENDER_API_BASE}/services/{service_id}",
            headers=headers,
            timeout=20,
        )
        if not service_res.ok:
            raise _render_error(service_res, "Failed to inspect existing Render service")

        service_data = service_res.json()
        service = service_data.get("service") or service_data
        existing_repo = (service.get("repo") or "").rstrip("/").removesuffix(".git").lower()
        expected_repo = repo_url.rstrip("/").removesuffix(".git").lower()
        if existing_repo != expected_repo:
            raise RuntimeError(
                f"Render service '{clean_service_name}' is connected to a different "
                "GitHub repository. Choose another service name or reconnect the "
                "service to the repository shown in this deployment."
            )

        update_res = requests.patch(
            f"{RENDER_API_BASE}/services/{service_id}",
            headers=headers,
            json={
                "serviceDetails": {
                    "runtime": "python",
                    "plan": "free",
                    "envSpecificDetails": {
                        "buildCommand": "pip install -r backend/requirements.txt",
                        "startCommand": "gunicorn --bind 0.0.0.0:$PORT backend.app:app",
                    },
                },
                "autoDeployTrigger": "off",
            },
            timeout=20,
        )
        if not update_res.ok:
            raise _render_error(update_res, "Failed to update existing Render service")

        database_res = requests.put(
            f"{RENDER_API_BASE}/services/{service_id}/env-vars/DATABASE_URL",
            headers=headers,
            json={"value": normalize_postgres_url(neon_database_url)},
            timeout=20,
        )
        if not database_res.ok:
            raise _render_error(database_res, "Failed to update Render DATABASE_URL")

    # 4. Trigger Deploy
    if not deploy_id:
        log("Triggering deployment on Render...")
        deploy_res = requests.post(
            f"{RENDER_API_BASE}/services/{service_id}/deploys",
            headers=headers,
            json={"clearCache": "do_not_clear"},
            timeout=20,
        )
        if not deploy_res.ok:
            raise _render_error(deploy_res, "Failed to trigger Render deployment")

        deploy_data = deploy_res.json()
        deploy_id = deploy_data.get("id") or deploy_data.get("deploy", {}).get("id")

    if not deploy_id:
        raise RuntimeError("Render accepted the service request but returned no deployment ID.")
    log(f"Render deployment queued. Deploy ID: {deploy_id}")
    _wait_for_render_deploy(
        service_id, deploy_id, headers, owner_id=owner_id, emit=emit
    )

    final_url = service_url or f"https://{clean_service_name}.onrender.com"
    dashboard_url = f"https://dashboard.render.com/web/{service_id}"

    log(f"Render deployment is live! URL: {final_url}")

    return {
        "success": True,
        "service_id": service_id,
        "deploy_id": deploy_id,
        "service_name": clean_service_name,
        "url": final_url,
        "dashboard_url": dashboard_url,
    }


def simulate_deployment(project_id: str, emit=None) -> dict:
    """Run a simulated/demo deployment when user requests testing or test mode."""
    import time

    def log(msg):
        if emit:
            emit({"type": "log", "message": msg})
        logger.info("[Simulate] %s", msg)

    if emit:
        emit({"type": "step", "step": "neon", "status": "running", "message": "Provisioning Neon DB..."})
    log("[Simulation] Reading database/schema.sql...")
    time.sleep(0.5)

    log("[Simulation] Provisioning serverless PostgreSQL database on Neon...")
    time.sleep(0.5)
    log("[Simulation] Executing schema.sql on Neon database (Created 6 tables)...")
    if emit:
        emit({"type": "step", "step": "neon", "status": "completed", "message": "Neon database provisioned!"})

    if emit:
        emit({"type": "step", "step": "github", "status": "running", "message": "Pushing to GitHub..."})
    log(f"[Simulation] Creating GitHub repository 'ai-{project_id}'...")
    time.sleep(0.5)
    log("[Simulation] Pushed project files to GitHub repository.")
    if emit:
        emit({"type": "step", "step": "github", "status": "completed", "message": "Pushed to GitHub!"})

    if emit:
        emit({"type": "step", "step": "render", "status": "running", "message": "Deploying on Render..."})
    log(f"[Simulation] Creating Render Web Service '{project_id}-web'...")
    time.sleep(0.5)
    log("[Simulation] Connected Neon DATABASE_URL and triggered build...")
    if emit:
        emit({"type": "step", "step": "render", "status": "completed", "message": "Render deployment live!"})

    url = f"https://{project_id}-web.onrender.com"
    return {
        "success": True,
        "url": url,
        "simulated": True,
        "neon": {
            "tables": ["users", "records", "sessions"],
            "connection_uri": "postgresql://neondb_owner:***@ep-demo.us-east-2.aws.neon.tech/neondb",
            "console_url": "https://console.neon.tech",
        },
        "github": {
            "repo_url": f"https://github.com/demo/{project_id}",
        },
        "render": {
            "url": url,
            "dashboard_url": f"https://dashboard.render.com",
        },
    }


def deploy_project_pipeline(project_id: str, project_path: str, config: dict, emit=None) -> dict:
    """End-to-end deployment orchestrator for Neon DB + GitHub + Render."""
    def log(msg, level="info"):
        if emit:
            emit({"type": "log", "message": msg, "level": level})
        logger.info(msg)

    # Check for dry run / simulate mode
    if config.get("simulate"):
        return simulate_deployment(project_id, emit=emit)

    neon_api_key = config.get("neon_api_key") or os.environ.get("NEON_API_KEY", "")
    neon_db_url = config.get("neon_database_url") or os.environ.get("NEON_DATABASE_URL", "")
    github_token = config.get("github_token") or os.environ.get("GITHUB_TOKEN", "")
    render_api_key = config.get("render_api_key") or os.environ.get("RENDER_API_KEY", "")
    render_owner_id = config.get("render_owner_id") or os.environ.get("RENDER_OWNER_ID", "")

    # Validate required credentials
    missing = []
    if not neon_api_key and not neon_db_url:
        missing.append("Neon API Key or Neon Database URL")
    if not github_token:
        missing.append("GitHub Personal Access Token (GITHUB_TOKEN)")
    if not render_api_key:
        missing.append("Render API Key (RENDER_API_KEY)")

    if missing:
        raise ValueError(
            f"Missing required deployment credentials: {', '.join(missing)}. "
            "Please provide them in the deployment dialog or configure them in backend/.env."
        )

    # 1. Step 1: Deploy Neon DB
    if emit:
        emit({"type": "step", "step": "neon", "status": "running", "message": "Deploying database to Neon DB..."})
    log("=== Stage 1: Neon Database Deployment ===")
    neon_result = deploy_neon_database(
        project_path=project_path,
        neon_api_key=neon_api_key,
        neon_database_url=neon_db_url,
        project_name=f"ai-{project_id}",
        emit=emit,
    )
    if emit:
        emit({"type": "step", "step": "neon", "status": "completed", "message": "Database deployed to Neon DB!"})

    # 2. Step 2: Push to GitHub
    if emit:
        emit({"type": "step", "step": "github", "status": "running", "message": "Pushing project code to GitHub..."})
    log("=== Stage 2: GitHub Repository Push ===")
    repo_name = config.get("repo_name") or f"ai-{project_id}"
    github_result = create_and_push_github_repo(
        project_path=project_path,
        github_token=github_token,
        repo_name=repo_name,
        is_private=bool(config.get("is_private", False)),
        emit=emit,
    )
    if emit:
        emit({"type": "step", "step": "github", "status": "completed", "message": "Project code pushed to GitHub!"})

    # 3. Step 3: Deploy to Render
    if emit:
        emit({"type": "step", "step": "render", "status": "running", "message": "Provisioning Web Service on Render..."})
    log("=== Stage 3: Render Web Service Deployment ===")
    service_name = config.get("service_name") or f"ai-{project_id}"
    render_result = deploy_to_render(
        repo_url=github_result["repo_url"],
        service_name=service_name,
        neon_database_url=neon_result["connection_uri"],
        render_api_key=render_api_key,
        render_owner_id=render_owner_id,
        emit=emit,
    )
    if emit:
        emit({"type": "step", "step": "render", "status": "completed", "message": "Deployed to Render!"})

    final_url = render_result["url"]
    log(f"=== Deployment Completed Successfully! Live Application URL: {final_url} ===")

    return {
        "success": True,
        "url": final_url,
        "neon": neon_result,
        "github": github_result,
        "render": render_result,
    }
