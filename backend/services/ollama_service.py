import requests


OLLAMA_URL = (
    "http://localhost:11434/api/generate"
)


def generate_response(
    prompt
):

    payload = {

        "model": "qwen2.5:3b",

        "prompt": prompt,

        "stream": False,

        "options": {

            "temperature": 0.1,

            "num_predict": 4096,

            "top_p": 0.9

        }

    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=None
    )

    response.raise_for_status()

    data = response.json()

    return data.get(
        "response",
        ""
    ).strip()