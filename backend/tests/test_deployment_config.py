import os
import unittest
from unittest.mock import patch

from app import app, run_local_server


class DeploymentConfigTests(unittest.TestCase):
    def test_local_server_uses_environment_and_keeps_debug_disabled(self):
        with patch.dict(os.environ, {"HOST": "127.0.0.2", "PORT": "5100"}):
            with patch.object(app, "run") as run:
                run_local_server()

        run.assert_called_once_with(
            host="127.0.0.2",
            port=5100,
            debug=False
        )

    def test_local_server_defaults_to_loopback(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(app, "run") as run:
                run_local_server()

        run.assert_called_once_with(
            host="127.0.0.1",
            port=5000,
            debug=False
        )


if __name__ == "__main__":
    unittest.main()
