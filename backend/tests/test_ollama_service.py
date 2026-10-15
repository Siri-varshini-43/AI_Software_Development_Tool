import json
import unittest
from unittest.mock import patch

from services.ollama_service import generate_response


class OllamaServiceTests(unittest.TestCase):
    def test_generate_response_emits_each_streamed_chunk(self):
        chunks = ["print(", "'ready')"]

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                assert decode_unicode
                yield json.dumps({"response": chunks[0]}).encode()
                yield json.dumps({"response": chunks[1]}).encode()
                yield json.dumps({"done": True}).encode()

        received = []
        response = FakeResponse()
        with patch("services.ollama_service.requests.post", return_value=response):
            result = generate_response("prompt", on_chunk=received.append)

        self.assertEqual(result, "".join(chunks))
        self.assertEqual(received, chunks)


if __name__ == "__main__":
    unittest.main()
