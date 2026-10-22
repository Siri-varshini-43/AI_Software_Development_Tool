import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

from app import app


class DeploymentRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_get_deploy_config(self):
        response = self.client.get("/api/deploy/config")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("configured", data)
        self.assertIn("has_neon_api_key", data["configured"])
        self.assertIn("has_github_token", data["configured"])
        self.assertIn("has_render_api_key", data["configured"])

    def test_post_deploy_config(self):
        payload = {
            "neon_api_key": "test-neon-key",
            "github_token": "test-gh-token",
            "render_api_key": "test-rnd-key",
            "save_to_env": False,
        }
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post(
                "/api/deploy/config",
                data=json.dumps(payload),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])

    def test_deploy_config_persists_quoted_credentials_when_requested(self):
        secret = "neon-key-with-'quotes' # preserved"
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(app, "root_path", temp_dir), patch.dict(
                os.environ, {}, clear=True
            ):
                response = self.client.post(
                    "/api/deploy/config",
                    data=json.dumps({
                        "neon_api_key": secret,
                        "save_to_env": True,
                    }),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    dotenv_values(Path(temp_dir) / ".env")["NEON_API_KEY"],
                    secret,
                )
                self.assertEqual(os.environ["NEON_API_KEY"], secret)

    def test_deploy_config_reports_persistence_failure(self):
        with patch("app._update_env_file", side_effect=OSError("disk is read-only")):
            response = self.client.post(
                "/api/deploy/config",
                data=json.dumps({
                    "github_token": "test-token",
                    "save_to_env": True,
                }),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["success"])

    def test_deploy_endpoint_requires_project_id(self):
        response = self.client.post(
            "/api/deploy",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("project_id is required", data["message"])

    def test_deploy_endpoint_rejects_nonexistent_project(self):
        response = self.client.post(
            "/api/deploy",
            data=json.dumps({"project_id": "project99999"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_deploy_endpoint_simulation_stream(self):
        # Using project5 which exists in generated_projects
        response = self.client.post(
            "/api/deploy",
            data=json.dumps({
                "project_id": "project5",
                "simulate": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/x-ndjson")

        lines = response.get_data(as_text=True).strip().split("\n")
        self.assertTrue(len(lines) > 0)

        events = [json.loads(line) for line in lines if line.strip()]
        complete_event = next((e for e in events if e.get("type") == "complete"), None)
        self.assertIsNotNone(complete_event)
        self.assertTrue(complete_event["success"])
        self.assertTrue(complete_event["simulated"])
        self.assertIn("No cloud resources were created", complete_event["message"])
        self.assertIn("https://project5-web.onrender.com", complete_event["url"])


if __name__ == "__main__":
    unittest.main()
