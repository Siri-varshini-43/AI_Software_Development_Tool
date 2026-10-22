import json
import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from app import app, create_project_zip
from test_project_validator import valid_project


class ProjectPackagingTests(unittest.TestCase):
    def _write_project(self, project_path, files):
        for relative_path, content in files.items():
            file_path = os.path.join(project_path, *relative_path.split("/"))
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)

    def test_only_validated_required_files_are_packaged(self):
        files = valid_project()
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_path = os.path.join(temporary_directory, "project")
            self._write_project(project_path, files)
            os.makedirs(os.path.join(project_path, "backend", "__pycache__"))
            with open(
                os.path.join(project_path, "backend", "__pycache__", "ignored.pyc"),
                "wb",
            ) as cache:
                cache.write(b"not source")

            with patch("app.GENERATED_PROJECTS_DIR", temporary_directory):
                zip_path = create_project_zip(project_path)

            with zipfile.ZipFile(zip_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    set(files),
                )

    def test_failed_validation_keeps_previous_archive_intact(self):
        files = valid_project()
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_path = os.path.join(temporary_directory, "project")
            self._write_project(project_path, files)

            with patch("app.GENERATED_PROJECTS_DIR", temporary_directory):
                zip_path = create_project_zip(project_path)
                with open(zip_path, "rb") as archive:
                    previous_archive = archive.read()

                broken_app = os.path.join(project_path, "backend", "app.py")
                with open(broken_app, "w", encoding="utf-8") as file:
                    file.write("def broken(:\n")

                with self.assertRaisesRegex(
                    ValueError,
                    "unvalidated project",
                ):
                    create_project_zip(project_path)

                with open(zip_path, "rb") as archive:
                    self.assertEqual(archive.read(), previous_archive)

    def test_download_contains_only_the_selected_partial_project_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            current_path = os.path.join(temporary_directory, "project1")
            other_path = os.path.join(temporary_directory, "project2")
            files = valid_project()
            partial_manifest = json.loads(files["project_manifest.json"])
            partial_manifest["generation_status"] = "partial"
            self._write_project(
                current_path,
                {
                    "project_manifest.json": json.dumps(partial_manifest),
                    "backend/app.py": "app = None\n",
                },
            )
            self._write_project(
                other_path,
                {
                    "backend/app.py": "other_project = True\n",
                    "other.txt": "belongs to project2",
                },
            )

            with patch("app.GENERATED_PROJECTS_DIR", temporary_directory):
                response = app.test_client().get(
                    "/api/download-project?project_id=project1"
                )
            archive_data = response.get_data()
            response.close()

            self.assertEqual(response.status_code, 200)
            self.assertIn("project1.zip", response.headers["Content-Disposition"])
            with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"project_manifest.json", "backend/app.py"},
                )
                self.assertEqual(
                    archive.read("backend/app.py").replace(b"\r\n", b"\n"),
                    b"app = None\n",
                )


if __name__ == "__main__":
    unittest.main()
