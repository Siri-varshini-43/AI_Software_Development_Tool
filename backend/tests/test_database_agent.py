import unittest
from unittest.mock import patch

from agents.database_agent import generate_database


class DatabaseAgentTests(unittest.TestCase):
    @patch("agents.database_agent.generate_tables")
    def test_derives_sql_and_erd_without_extra_model_requests(self, generate_tables):
        generate_tables.return_value = """[
            {
                "table_name": "patients",
                "columns": [
                    {"name": "id", "type": "SERIAL", "primary_key": true, "foreign_key": ""},
                    {"name": "name", "type": "VARCHAR(100)", "primary_key": false, "foreign_key": ""}
                ]
            },
            {
                "table_name": "appointments",
                "columns": [
                    {"name": "id", "type": "SERIAL", "primary_key": true, "foreign_key": ""},
                    {"name": "patient_id", "type": "INTEGER", "primary_key": false, "foreign_key": "patients.id"}
                ]
            }
        ]"""

        database = generate_database("Requirements", {"architecture_diagram": "graph LR"})

        self.assertEqual(generate_tables.call_count, 1)
        self.assertIn(
            'ALTER TABLE "appointments" ADD FOREIGN KEY ("patient_id") '
            'REFERENCES "patients" ("id")',
            database["sql_schema"],
        )
        self.assertIn(
            "PATIENTS ||--o{ APPOINTMENTS : patient_id",
            database["erd"],
        )
        self.assertIn("int id PK", database["erd"])

    @patch("agents.database_agent.generate_tables")
    def test_rejects_invalid_table_identifiers(self, generate_tables):
        generate_tables.return_value = (
            '[{"table_name":"patients; DROP TABLE users","columns":'
            '[{"name":"id","type":"SERIAL","primary_key":true}]}]'
        )

        with self.assertRaisesRegex(ValueError, "Invalid database table name"):
            generate_database("Requirements", {"architecture_diagram": "graph LR"})


if __name__ == "__main__":
    unittest.main()
