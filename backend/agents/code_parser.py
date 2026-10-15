import os
import re
from pathlib import PurePosixPath


def _clean_path(filename, expected_files=None):
    clean = filename.strip()
    clean = re.sub(
        r"^(?:#{1,6}\s*|\*\*|__)?(?:file\s*:\s*|\d+[\.)]\s*)?",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    clean = clean.strip("`'\"* ").rstrip(":").strip()
    clean = clean.replace("\\", "/")
    if clean.startswith("project/"):
        clean = clean[len("project/"):]
    clean = clean.lstrip("/")

    if expected_files:
        exp_set = set(expected_files)
        if clean in exp_set:
            return clean
        for prefix in ("frontend/", "backend/", "database/", "tests/"):
            if f"{prefix}{clean}" in exp_set:
                return f"{prefix}{clean}"
        base = PurePosixPath(clean).name.casefold()
        for exp in exp_set:
            if PurePosixPath(exp).name.casefold() == base:
                return exp
        norm_base = base.replace("-", "_")
        for exp in exp_set:
            if PurePosixPath(exp).name.casefold().replace("-", "_") == norm_base:
                return exp
    if clean.endswith(".py") and clean.startswith("frontend/"):
        clean = "backend/" + clean[len("frontend/"):]
    elif clean.startswith(("agents/", "services/", "rag/", "routes/", "models/")):
        clean = f"backend/{clean}"
    elif "/" not in clean:
        if clean in ("app.py", "config.py", "models.py", "routes.py", "__init__.py"):
            return f"backend/{clean}"
        elif clean.endswith((".html", ".css", ".js")):
            if clean == "style.css":
                return "frontend/css/style.css"
            elif clean == "script.js":
                return "frontend/js/script.js"
            return f"frontend/{clean}"
        elif clean == "schema.sql":
            return "database/schema.sql"
        elif clean == "requirements.txt":
            return "backend/requirements.txt"
        elif clean.endswith(".py"):
            if clean == "test_smoke.py" or clean.startswith("test_"):
                return f"tests/{clean}"
            return f"backend/{clean}"
    elif clean.startswith(("css/", "js/", "images/")):
        return f"frontend/{clean}"
    return clean


def parse_and_save_files(
    generated_text,
    output_folder,
    expected_files=None,
):
    os.makedirs(output_folder, exist_ok=True)

    pattern = re.compile(
        r"^(?:#{2,3}|File:|\*\*File:)\s*(.+?)\s*:?\s*\r?\n\s*```[^\r\n]*\r?\n(.*?)(?:\r?\n```|(?=\r?\n(?:#{2,3}|File:|\*\*File:)\s*.+?\s*:?\r?\n\s*```)|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    matches = pattern.findall(generated_text or "")

    if not matches:
        raise ValueError(
            "The model response contained no recognized file headings followed "
            "by fenced code blocks."
        )

    saved_files = []
    parsed_files = {}

    for raw_filename, content in matches:
        filename = _clean_path(raw_filename, expected_files)
        path = PurePosixPath(filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or ":" in filename
            or "\x00" in filename
            or any(part.endswith((" ", ".")) for part in path.parts)
        ):
            raise ValueError(f"Generated file path is not allowed: {raw_filename}")

        filename = path.as_posix()
        if not filename or filename == ".":
            raise ValueError("Generated file path is empty.")
        if PurePosixPath(filename).name.casefold() == "generated_output.txt":
            raise ValueError(
                "The model returned generated_output.txt instead of project files."
            )

        parsed_files[filename] = content.strip() + "\n"

    if expected_files is not None:
        expected = set(expected_files)
        missing = sorted(expected - parsed_files.keys())
        if missing:
            raise ValueError(f"missing expected files: {', '.join(missing)}")

    for filename, content in parsed_files.items():
        file_path = os.path.join(output_folder, *filename.split("/"))
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)

        saved_files.append({
            "name": os.path.basename(filename),
            "path": filename,
            "full_path": file_path,
            "content": content,
        })

    return saved_files