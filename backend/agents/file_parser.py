import os
import re


def parse_and_save_files(
    generated_code,
    output_dir
):

    saved_files = []

    patterns = [

        r"###\s+([^\n]+)\n```(?:\w+)?\n(.*?)```",

        r"File:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```",

    ]

    matches = []

    for pattern in patterns:

        matches.extend(

            re.findall(
                pattern,
                generated_code,
                re.DOTALL
            )

        )

    if not matches:

        print(
            "\n❌ No files detected."
        )

        fallback_file = os.path.join(
            output_dir,
            "generated_output.txt"
        )

        with open(
            fallback_file,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                generated_code
            )

        return [
            {
                "name": "generated_output.txt",
                "path": fallback_file
            }
        ]

    for (
        filename,
        content
    ) in matches:

        filename = filename.strip()

        content = content.strip()

        filepath = os.path.join(
            output_dir,
            filename
        )

        os.makedirs(
            os.path.dirname(filepath),
            exist_ok=True
        )

        with open(
            filepath,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                content
            )

        saved_files.append(
            {
                "name": os.path.basename(
                    filename
                ),
                "path": filepath
            }
        )

        print(
            f"✅ Saved: {filepath}"
        )

    return saved_files