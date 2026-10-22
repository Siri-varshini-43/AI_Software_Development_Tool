import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app


class ProjectHistoryTests(unittest.TestCase):
    def test_home_page_places_history_behind_navbar_toggle(self):
        response = app.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="historyToggleBtn"', response.data)
        self.assertIn(b'id="projectHistorySection"', response.data)
        self.assertIn(b'aria-expanded="false"', response.data)
        self.assertIn(b'aria-label="Project history" hidden', response.data)
        self.assertIn(b'id="projectHistoryDetails"', response.data)

    def test_history_list_includes_original_prompt_and_deployment_links(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = os.path.join(temp_dir, "project1")
            os.makedirs(project_path)
            app._write_project_history(
                project_path,
                prompt="Build a task tracker",
                requirements="Users can create and update tasks.",
                deployment={
                    "status": "deployed",
                    "url": "https://tasks.onrender.com",
                    "github": {"repo_url": "https://github.com/example/tasks"},
                    "render": {"dashboard_url": "https://dashboard.render.com/web/tasks"},
                },
            )

            with patch.object(app, "GENERATED_PROJECTS_DIR", temp_dir):
                response = app.app.test_client().get("/api/history")

        self.assertEqual(response.status_code, 200)
        project = response.get_json()["projects"][0]
        self.assertEqual(project["prompt"], "Build a task tracker")
        self.assertEqual(project["deployment"]["url"], "https://tasks.onrender.com")
        self.assertEqual(
            project["deployment"]["github"]["repo_url"],
            "https://github.com/example/tasks",
        )

    def test_failed_deployment_update_preserves_saved_live_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app._write_project_history(
                temp_dir,
                deployment={
                    "status": "deployed",
                    "url": "https://example.onrender.com",
                },
            )

            record = app._write_project_history(
                temp_dir,
                deployment={
                    "status": "failed",
                    "message": "A later deployment failed.",
                },
            )

        self.assertEqual(record["deployment"]["status"], "failed")
        self.assertEqual(
            record["deployment"]["url"],
            "https://example.onrender.com",
        )

    def test_simulated_deployment_does_not_replace_live_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = os.path.join(temp_dir, "project1")
            os.makedirs(project_path)
            app._write_project_history(
                project_path,
                deployment={
                    "status": "deployed",
                    "url": "https://example.onrender.com",
                },
            )
            simulated_result = {
                "simulated": True,
                "url": "https://project1-web.onrender.com",
            }

            with (
                patch.object(app, "GENERATED_PROJECTS_DIR", temp_dir),
                patch.object(app, "_apply_deployment_config"),
                patch.object(
                    app,
                    "deploy_project_pipeline",
                    return_value=simulated_result,
                ),
            ):
                response = app.app.test_client().post(
                    "/api/deploy",
                    json={"project_id": "project1", "simulate": True},
                )
                self.assertEqual(response.status_code, 200)
                response.get_data(as_text=True)

            with open(
                os.path.join(project_path, app.PROJECT_HISTORY_FILENAME),
                encoding="utf-8",
            ) as history_file:
                record = json.load(history_file)

        self.assertEqual(record["deployment"]["status"], "simulated")
        self.assertEqual(
            record["deployment"]["url"],
            "https://example.onrender.com",
        )


if __name__ == "__main__":
    unittest.main()
