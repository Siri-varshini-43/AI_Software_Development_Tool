import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app, create_project_directory


class ProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory_patch = patch(
            "app.GENERATED_PROJECTS_DIR",
            self.temporary_directory.name,
        )
        self.directory_patch.start()
        self.client = app.test_client()

    def tearDown(self):
        self.directory_patch.stop()
        self.temporary_directory.cleanup()

    def test_each_project_gets_a_separate_numbered_directory(self):
        first_id, first_path = create_project_directory()
        second_id, second_path = create_project_directory()

        self.assertEqual(first_id, "project1")
        self.assertEqual(second_id, "project2")
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(os.path.isdir(first_path))
        self.assertTrue(os.path.isdir(second_path))

    @patch("app.generate_project")
    def test_project_generation_endpoint_uses_a_fresh_directory(
        self,
        generate_project,
    ):
        generate_project.side_effect = lambda *args, project_path, **kwargs: {
            "success": True,
            "project_path": project_path,
            "files": [],
        }
        request_data = {
            "requirements": "A sample project",
            "architecture": {},
            "database": {},
            "backend": {},
            "frontend": {},
        }

        first = self.client.post("/api/project", json=request_data).get_json()
        second = self.client.post("/api/project", json=request_data).get_json()

        self.assertEqual(first["project_id"], "project1")
        self.assertEqual(second["project_id"], "project2")
        self.assertNotEqual(first["project_path"], second["project_path"])
        self.assertEqual(generate_project.call_count, 2)

    def test_automated_generation_returns_its_project_id_and_directory(self):
        with (
            patch("app.analyze_requirements", return_value="sample requirements"),
            patch("app.generate_architecture", return_value={}),
            patch("app.generate_database", return_value={}),
            patch("app.generate_backend", return_value={}),
            patch("app.generate_frontend", return_value={}),
            patch("app.generate_project") as generate_project,
        ):
            generate_project.side_effect = (
                lambda *args, project_path, **kwargs: {
                    "success": True,
                    "project_path": project_path,
                    "files": [],
                }
            )

            first = self.client.post(
                "/api/generate",
                json={"requirements": "first project"},
            )
            first_events = [
                json_line
                for json_line in first.get_data(as_text=True).splitlines()
                if json_line.strip()
            ]
            second = self.client.post(
                "/api/generate",
                json={"requirements": "second project"},
            )
            second.get_data()

        self.assertEqual(first.headers["X-Project-Id"], "project1")
        self.assertEqual(second.headers["X-Project-Id"], "project2")
        self.assertTrue(
            any('"project_id": "project1"' in event for event in first_events)
        )
        generated_paths = [
            call.kwargs["project_path"]
            for call in generate_project.call_args_list
        ]
        self.assertNotEqual(generated_paths[0], generated_paths[1])
        self.assertTrue(all(os.path.isdir(path) for path in generated_paths))

    def test_partial_project_is_emitted_as_successful_completion(self):
        with (
            patch("app.analyze_requirements", return_value="sample requirements"),
            patch("app.generate_architecture", return_value={}),
            patch("app.generate_database", return_value={}),
            patch("app.generate_backend", return_value={}),
            patch("app.generate_frontend", return_value={}),
            patch("app.generate_project") as generate_project,
        ):
            generate_project.return_value = {
                "success": True,
                "partial": True,
                "message": "Stopped at the deadline; partial files are saved.",
                "project_path": "project1",
                "files": [{"path": "backend/app.py", "content": "app = None\n"}],
            }

            response = self.client.post(
                "/api/generate",
                json={"requirements": "partial project"},
            )
            events = [
                json.loads(line)
                for line in response.get_data(as_text=True).splitlines()
                if line.strip()
            ]

        completion = next(event for event in events if event["type"] == "complete")
        self.assertTrue(completion["success"])
        self.assertTrue(completion["project"]["partial"])
        self.assertEqual(completion["project"]["project_id"], "project1")
        self.assertFalse(any(event["type"] == "failure" for event in events))

    def test_project_file_list_and_content_are_scoped_to_project_id(self):
        first_id, first_path = create_project_directory()
        second_id, second_path = create_project_directory()
        with open(os.path.join(first_path, "first.py"), "w", encoding="utf-8") as file:
            file.write("first project")
        with open(os.path.join(second_path, "second.py"), "w", encoding="utf-8") as file:
            file.write("second project")

        response = self.client.get(
            "/api/project-files",
            query_string={"project_id": first_id},
        )

        self.assertEqual(response.status_code, 200)
        files = response.get_json()["files"]
        self.assertEqual([item["path"] for item in files], ["first.py"])
        self.assertEqual(files[0]["content"], "first project")

        content_response = self.client.get(
            "/api/project/file",
            query_string={"project_id": first_id, "path": "first.py"},
        )
        self.assertEqual(content_response.status_code, 200)
        self.assertEqual(content_response.get_json()["content"], "first project")

    def test_project_file_endpoints_reject_invalid_or_cross_project_paths(self):
        first_id, first_path = create_project_directory()
        second_id, second_path = create_project_directory()
        with open(os.path.join(second_path, "private.py"), "w", encoding="utf-8") as file:
            file.write("private")

        invalid_project = self.client.get(
            "/api/project-files",
            query_string={"project_id": "../project2"},
        )
        self.assertEqual(invalid_project.status_code, 400)

        cross_project_file = self.client.get(
            "/api/project/file",
            query_string={
                "project_id": first_id,
                "path": os.path.relpath(
                    os.path.join(second_path, "private.py"),
                    first_path,
                ),
            },
        )
        self.assertEqual(cross_project_file.status_code, 400)


if __name__ == "__main__":
    unittest.main()
