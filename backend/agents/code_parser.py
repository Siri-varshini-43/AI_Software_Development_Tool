import os
import re


def parse_and_save_files(
    generated_text,
    output_folder
):

    os.makedirs(
        output_folder,
        exist_ok=True
    )

    pattern = r"###\s+([^\n]+)\n```[a-zA-Z]*\n(.*?)```"

    matches = re.findall(
        pattern,
        generated_text,
        re.DOTALL
    )

    saved_files = []

    for filename, content in matches:

        filename = filename.strip()

        file_path = os.path.join(
            output_folder,
            filename
        )

        with open(
            file_path,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                content.strip()
            )

        saved_files.append({
            "name": filename,
            "path": file_path
        })

    return saved_files