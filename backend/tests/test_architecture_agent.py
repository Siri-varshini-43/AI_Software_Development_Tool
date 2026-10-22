import unittest
from unittest.mock import patch

from agents.architecture_agent import generate_architecture


class ArchitectureAgentTests(unittest.TestCase):
    @patch("agents.architecture_agent.generate_architecture_diagram")
    def test_generates_only_the_architecture_diagram(self, generate_diagram):
        generate_diagram.return_value = "graph LR\nFrontend --> Backend"

        architecture = generate_architecture("A sample project")

        self.assertEqual(
            architecture,
            {"architecture_diagram": "graph LR\nFrontend --> Backend"},
        )
        generate_diagram.assert_called_once_with("A sample project")


if __name__ == "__main__":
    unittest.main()
