import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from services.deployment_service import (
    parse_schema_sql,
    normalize_postgres_url,
    deploy_neon_database,
    provision_neon_project,
    create_and_push_github_repo,
    deploy_to_render,
    simulate_deployment,
    deploy_project_pipeline,
)


class DeploymentServiceTests(unittest.TestCase):
    def test_normalize_postgres_url(self):
        # postgres:// prefix normalized to postgresql://
        url = "postgres://user:pass@ep-xyz.us-east-2.aws.neon.tech/neondb"
        normalized = normalize_postgres_url(url)
        self.assertTrue(normalized.startswith("postgresql://"))
        self.assertIn("sslmode=require", normalized)

        # non-neon url preserved
        local_url = "postgresql://user:pass@localhost:5432/test"
        self.assertEqual(normalize_postgres_url(local_url), local_url)

    def test_parse_schema_sql_clean_statements(self):
        sql = """
        -- Create users table
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) NOT NULL
        );

        /* Block comment
           with semicolon; */
        CREATE TABLE posts (
            id SERIAL PRIMARY KEY,
            title VARCHAR(100),
            content TEXT
        );
        """
        statements = parse_schema_sql(sql)
        self.assertEqual(len(statements), 2)
        self.assertTrue(statements[0].startswith("CREATE TABLE users"))
        self.assertTrue(statements[1].startswith("CREATE TABLE posts"))

    def test_parse_schema_sql_with_semicolons_in_quotes(self):
        sql = "INSERT INTO logs (message) VALUES ('Hello; World;');"
        statements = parse_schema_sql(sql)
        self.assertEqual(len(statements), 1)
        self.assertIn("'Hello; World;'", statements[0])

    @patch("services.deployment_service.requests.post")
    def test_provision_neon_project_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "project": {
                "id": "neon-proj-123",
                "connection_uris": [
                    {"connection_uri": "postgresql://neondb_owner:secret@ep-xyz.neon.tech/neondb?sslmode=require"}
                ]
            }
        }
        mock_post.return_value = mock_resp

        result = provision_neon_project("test_api_key", "test-project")
        self.assertEqual(result["project_id"], "neon-proj-123")
        self.assertIn("postgresql://", result["connection_uri"])
        self.assertIn("ep-xyz.neon.tech", result["connection_uri"])

    @patch("services.deployment_service.execute_schema_on_postgres")
    def test_deploy_neon_database_with_url(self, mock_exec):
        mock_exec.return_value = {
            "success": True,
            "tables": ["users", "tasks"],
            "table_count": 2
        }

        # Use an existing project path from generated_projects
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_path = os.path.join(os.path.dirname(backend_dir), "generated_projects", "project5")

        if os.path.exists(project_path):
            result = deploy_neon_database(
                project_path=project_path,
                neon_database_url="postgresql://user:pass@ep-xyz.neon.tech/neondb",
            )
            self.assertTrue(result["success"])
            self.assertEqual(result["tables"], ["users", "tasks"])

    @patch("services.deployment_service.requests.get")
    @patch("services.deployment_service.requests.post")
    def test_deploy_to_render_success(self, mock_post, mock_get):
        # Mock owners
        mock_owners = MagicMock()
        mock_owners.ok = True
        mock_owners.json.return_value = [{"owner": {"id": "usr-12345"}}]

        # Mock check services
        mock_services = MagicMock()
        mock_services.ok = True
        mock_services.json.return_value = []

        mock_get.side_effect = [mock_owners, mock_services]

        # Mock service creation
        mock_create = MagicMock()
        mock_create.ok = True
        mock_create.json.return_value = {
            "service": {
                "id": "srv-99999",
                "name": "ai-project1",
                "serviceDetails": {
                    "url": "https://ai-project1.onrender.com"
                }
            },
            "deployId": "dep-11111",
        }

        mock_status = MagicMock()
        mock_status.ok = True
        mock_status.json.return_value = {"id": "dep-11111", "status": "live"}

        mock_post.return_value = mock_create
        mock_get.side_effect = [mock_owners, mock_services, mock_status]

        result = deploy_to_render(
            repo_url="https://github.com/testuser/ai-project1",
            service_name="ai-project1",
            neon_database_url="postgresql://neondb_owner:secret@ep-xyz.neon.tech/neondb",
            render_api_key="rnd_secret_key",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["service_id"], "srv-99999")
        self.assertEqual(result["url"], "https://ai-project1.onrender.com")
        create_payload = mock_post.call_args_list[0].kwargs["json"]
        self.assertEqual(create_payload["serviceDetails"]["runtime"], "python")
        self.assertEqual(create_payload["serviceDetails"]["plan"], "free")
        self.assertEqual(create_payload["autoDeployTrigger"], "off")
        self.assertEqual(
            create_payload["serviceDetails"]["envSpecificDetails"]["buildCommand"],
            "pip install -r backend/requirements.txt",
        )
        self.assertEqual(
            create_payload["serviceDetails"]["envSpecificDetails"]["startCommand"],
            "gunicorn --bind 0.0.0.0:$PORT backend.app:app",
        )
        self.assertEqual(
            {item["key"] for item in create_payload["envVars"]},
            {"DATABASE_URL", "SECRET_KEY", "PYTHON_VERSION"},
        )
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(
            mock_get.call_args_list[-1].args[0],
            "https://api.render.com/v1/services/srv-99999/deploys/dep-11111",
        )

    @patch("services.deployment_service.requests.get")
    @patch("services.deployment_service.requests.post")
    def test_render_payment_requirement_does_not_retry_with_paid_plan(
        self, mock_post, mock_get
    ):
        mock_owners = MagicMock()
        mock_owners.ok = True
        mock_owners.json.return_value = [{"owner": {"id": "usr-12345"}}]

        mock_services = MagicMock()
        mock_services.ok = True
        mock_services.json.return_value = []
        mock_get.side_effect = [mock_owners, mock_services]

        payment_required = MagicMock()
        payment_required.ok = False
        payment_required.status_code = 402
        payment_required.text = '{"message":"Payment information is required"}'
        mock_post.return_value = payment_required

        with self.assertRaisesRegex(RuntimeError, "free web service.*billing verification"):
            deploy_to_render(
                repo_url="https://github.com/testuser/ai-project1",
                service_name="ai-project1",
                neon_database_url="postgresql://user:pass@db.neon.tech/neondb",
                render_api_key="rnd_secret_key",
            )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["serviceDetails"]["plan"], "free")

    @patch("services.deployment_service.requests.put")
    @patch("services.deployment_service.requests.patch")
    @patch("services.deployment_service.requests.get")
    @patch("services.deployment_service.requests.post")
    def test_existing_render_service_uses_single_manual_deploy(
        self, mock_post, mock_get, mock_patch, mock_put
    ):
        repo_url = "https://github.com/testuser/ai-project1"
        owner_response = MagicMock(ok=True)
        owner_response.json.return_value = [{"owner": {"id": "owner-123"}}]
        services_response = MagicMock(ok=True)
        services_response.json.return_value = [
            {
                "service": {
                    "id": "srv-123",
                    "name": "ai-project1",
                    "serviceDetails": {
                        "url": "https://ai-project1.onrender.com",
                    },
                }
            }
        ]
        service_response = MagicMock(ok=True)
        service_response.json.return_value = {"service": {"repo": repo_url}}
        status_response = MagicMock(ok=True)
        status_response.json.return_value = {"id": "dep-123", "status": "live"}
        mock_get.side_effect = [
            owner_response,
            services_response,
            service_response,
            status_response,
        ]
        deploy_response = MagicMock(ok=True)
        deploy_response.json.return_value = {"id": "dep-123"}
        mock_post.return_value = deploy_response
        mock_patch.return_value = MagicMock(ok=True)
        mock_put.return_value = MagicMock(ok=True)

        result = deploy_to_render(
            repo_url=repo_url,
            service_name="ai-project1",
            neon_database_url="postgresql://user:password@db.example/library",
            render_api_key="rnd_secret_key",
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            mock_patch.call_args.kwargs["json"]["autoDeployTrigger"],
            "off",
        )
        self.assertEqual(mock_post.call_count, 1)
        self.assertTrue(
            mock_post.call_args.args[0].endswith("/services/srv-123/deploys")
        )

    @patch("services.deployment_service.subprocess.run")
    @patch("services.deployment_service.requests.get")
    @patch("services.deployment_service.requests.post")
    def test_existing_github_repo_is_cloned_before_update(
        self, mock_post, mock_get, mock_run
    ):
        user_response = MagicMock()
        user_response.ok = True
        user_response.json.return_value = {"login": "testuser"}

        repository_response = MagicMock()
        repository_response.ok = True
        repository_response.json.return_value = {
            "html_url": "https://github.com/testuser/ai-project6",
            "default_branch": "main",
        }
        mock_get.side_effect = [user_response, repository_response]

        repo_exists_response = MagicMock()
        repo_exists_response.status_code = 422
        mock_post.return_value = repo_exists_response

        def git_result(command, **_kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = " M README.md" if command[-1] == "--porcelain" else ""
            result.stderr = ""
            return result

        mock_run.side_effect = git_result

        with tempfile.TemporaryDirectory() as project_path:
            with open(os.path.join(project_path, "README.md"), "w", encoding="utf-8") as readme:
                readme.write("# Project 6\n")
            result = create_and_push_github_repo(
                project_path=project_path,
                github_token="test-token",
                repo_name="ai-project6",
            )

        self.assertEqual(result["repo_name"], "ai-project6")
        commands = [call.args[0][1:] for call in mock_run.call_args_list]
        self.assertIn(
            [
                "clone",
                "--branch",
                "main",
                "--single-branch",
                "https://github.com/testuser/ai-project6.git",
                ".",
            ],
            commands,
        )
        self.assertNotIn(["init", "-b", "main"], commands)
        self.assertIn(["push", "-u", "origin", "main"], commands)

    @patch("services.deployment_service.time.sleep")
    @patch("services.deployment_service.requests.get")
    def test_render_deploy_failure_does_not_report_success(self, mock_get, _mock_sleep):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {"id": "dep-failed", "status": "build_failed"}
        mock_get.return_value = response

        with self.assertRaisesRegex(RuntimeError, "build_failed"):
            from services.deployment_service import _wait_for_render_deploy
            _wait_for_render_deploy(
                "srv-123",
                "dep-failed",
                {"Authorization": "Bearer test"},
            )

    @patch("services.deployment_service.requests.get")
    def test_failed_deploy_includes_render_build_output(self, mock_get):
        status = MagicMock()
        status.ok = True
        status.json.return_value = {"id": "dep-failed", "status": "update_failed"}
        app_logs = MagicMock()
        app_logs.ok = True
        app_logs.json.return_value = {
            "logs": [{"message": "Application failed: missing DATABASE_URL"}]
        }
        build_logs = MagicMock()
        build_logs.ok = True
        build_logs.json.return_value = {
            "logs": [{"message": "Build completed successfully"}]
        }
        mock_get.side_effect = [status, app_logs, build_logs]

        from services.deployment_service import _wait_for_render_deploy

        with self.assertRaisesRegex(RuntimeError, "Application failed: missing DATABASE_URL"):
            _wait_for_render_deploy(
                "srv-123",
                "dep-failed",
                {},
                owner_id="owner-123",
            )

        self.assertEqual(mock_get.call_count, 3)

    @patch("services.deployment_service.requests.get")
    def test_fetch_render_build_logs_returns_recent_messages(self, mock_get):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {
            "logs": [
                {"message": "Newest build message"},
                {"message": "Earlier build message"},
            ]
        }
        mock_get.return_value = response

        from services.deployment_service import _fetch_render_logs

        result = _fetch_render_logs("srv-123", "owner-123", {}, "build")

        self.assertEqual(result, "Earlier build message\nNewest build message")
        self.assertEqual(
            mock_get.call_args.kwargs["params"]["resource"],
            "srv-123",
        )
        self.assertEqual(mock_get.call_args.kwargs["params"]["type"], "build")

    def test_simulate_deployment(self):
        events = []
        result = simulate_deployment("project1", emit=lambda ev: events.append(ev))
        self.assertTrue(result["success"])
        self.assertTrue(result["simulated"])
        self.assertIn("https://project1-web.onrender.com", result["url"])
        self.assertTrue(len(events) > 0)

    def test_deploy_project_pipeline_requires_credentials(self):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_path = os.path.join(os.path.dirname(backend_dir), "generated_projects", "project5")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                deploy_project_pipeline(
                    project_id="project5",
                    project_path=project_path,
                    config={},
                )
            self.assertIn("Missing required deployment credentials", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
