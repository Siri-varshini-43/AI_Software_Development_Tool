import requests

OLLAMA_URL = "http://localhost:11434/api/generate"

def generate_response(prompt):

    payload = {
        "model": "qwen2.5:3b",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 800
        }
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=180)

    response.raise_for_status()

    data = response.json()

    return data["response"].strip()