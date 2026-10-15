import json
import logging
import os
import time

import requests


OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate"
)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 180
MAX_GENERATION_SECONDS = 1200
PROGRESS_INTERVAL_CHUNKS = 25
logger = logging.getLogger(__name__)


def generate_response(
    prompt,
    num_predict=4096,
    progress=None,
    on_chunk=None,
):

    payload = {

        "model": OLLAMA_MODEL,

        "prompt": prompt,

        "stream": True,

        "options": {

            "temperature": 0.1,

            "num_predict": num_predict,

            "top_p": 0.9

        }

    }

    started_at = time.monotonic()
    response_chunks = []
    chunk_count = 0
    reported_chunks = 0
    completed = False

    try:
        with requests.post(
            OLLAMA_URL,
            json=payload,
            stream=True,
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if time.monotonic() - started_at > MAX_GENERATION_SECONDS:
                    raise TimeoutError(
                        "Ollama generation exceeded the 20-minute limit."
                    )
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        "Ollama returned an invalid streaming response."
                    ) from error

                if data.get("error"):
                    raise RuntimeError(f"Ollama error: {data['error']}")

                chunk = data.get("response", "")
                if chunk:
                    response_chunks.append(chunk)
                    chunk_count += 1
                    if on_chunk:
                        on_chunk(chunk)

                    if chunk_count - reported_chunks >= PROGRESS_INTERVAL_CHUNKS:
                        logger.info(
                            "Ollama generated %s response chunks",
                            chunk_count
                        )
                        if progress:
                            progress(chunk_count)
                        reported_chunks = chunk_count

                if data.get("done"):
                    completed = True
                    break
    except requests.Timeout as error:
        raise TimeoutError(
            "Ollama stopped responding for 180 seconds. Verify the local "
            "Ollama service and model are available."
        ) from error

    if not completed:
        raise RuntimeError("Ollama ended the response before generation completed.")

    generated_text = "".join(response_chunks).strip()
    if not generated_text:
        raise RuntimeError("Ollama completed generation with an empty response.")

    if progress and chunk_count != reported_chunks:
        progress(chunk_count)

    logger.info(
        "Ollama generation completed with %s response chunks",
        chunk_count
    )
    return generated_text