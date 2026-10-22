import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar

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
_generation_deadline = ContextVar("generation_deadline", default=None)


class GenerationDeadlineExceeded(TimeoutError):
    pass


@contextmanager
def generation_time_limit(seconds):
    token = _generation_deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _generation_deadline.reset(token)


def check_generation_time_limit():
    deadline = _generation_deadline.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise GenerationDeadlineExceeded(
            "Project code generation exceeded its 15-minute time limit."
        )


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
    deadline = _generation_deadline.get()
    if deadline is None:
        deadline = started_at + MAX_GENERATION_SECONDS
    check_generation_time_limit()
    read_timeout_seconds = min(
        READ_TIMEOUT_SECONDS,
        max(1, deadline - time.monotonic()),
    )
    response_chunks = []
    chunk_count = 0
    reported_chunks = 0
    completed = False

    try:
        with requests.post(
            OLLAMA_URL,
            json=payload,
            stream=True,
            timeout=(CONNECT_TIMEOUT_SECONDS, read_timeout_seconds)
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if time.monotonic() >= deadline:
                    if _generation_deadline.get() is not None:
                        check_generation_time_limit()
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
        check_generation_time_limit()
        raise TimeoutError(
            f"Ollama stopped responding for {read_timeout_seconds:g} seconds. Verify the local "
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