from agents.table_generator import generate_tables

import json
import re


def _sql_identifier(value, description):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*",
        value,
    ):
        raise ValueError(f"Invalid database {description}: {value!r}")
    return f'"{value}"'


def _column_type(value):
    allowed_types = (
        r"(?:SMALLINT|INT|INTEGER|BIGINT|SERIAL|BIGSERIAL|SMALLSERIAL|"
        r"REAL|DOUBLE\s+PRECISION|BOOLEAN|BOOL|TEXT|DATE|TIME"
        r"(?:\s+WITH(?:OUT)?\s+TIME\s+ZONE)?|TIMESTAMP"
        r"(?:\s+WITH(?:OUT)?\s+TIME\s+ZONE)?|JSON|JSONB|UUID|BYTEA|"
        r"CHAR(?:ACTER)?(?:\s+VARYING)?|VARCHAR|NUMERIC|DECIMAL)"
        r"(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?(?:\[\])?"
    )
    if not isinstance(value, str) or not re.fullmatch(
        allowed_types,
        value.strip(),
        re.IGNORECASE,
    ):
        raise ValueError(f"Invalid PostgreSQL column type: {value!r}")
    return value.strip().upper()


def _foreign_key_target(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid foreign key target: {value!r}")

    match = re.fullmatch(
        r"(?:REFERENCES\s+)?([A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*\.\s*|\s*\(\s*)"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\)?",
        value.strip(),
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Foreign key targets must use 'table.column' format; "
            f"received {value!r}"
        )
    return match.group(1), match.group(2)


def _build_sql_schema(tables):
    statements = []
    foreign_keys = []
    table_columns = {}
    for table in tables:
        table_name = _sql_identifier(table.get("table_name"), "table name")
        normalized_table_name = table["table_name"].casefold()
        if normalized_table_name in table_columns:
            raise ValueError(f"Duplicate database table: {table['table_name']!r}")
        columns = table.get("columns")
        if not isinstance(columns, list) or not columns:
            raise ValueError(f"Table {table.get('table_name')!r} has no columns.")

        definitions = []
        primary_keys = []
        seen_columns = set()
        for column in columns:
            if not isinstance(column, dict):
                raise ValueError(f"Invalid column definition in {table_name}.")
            column_name = _sql_identifier(column.get("name"), "column name")
            normalized_column_name = column["name"].casefold()
            if normalized_column_name in seen_columns:
                raise ValueError(
                    f"Duplicate column in {table_name}: {column['name']!r}"
                )
            seen_columns.add(normalized_column_name)
            column_type = _column_type(column.get("type"))
            definitions.append(f"    {column_name} {column_type}")
            if column.get("primary_key"):
                primary_keys.append(column_name)
            target = _foreign_key_target(column.get("foreign_key"))
            if target:
                foreign_keys.append(
                    (
                        table_name,
                        column_name,
                        target[0],
                        target[1],
                    )
                )

        if not primary_keys:
            raise ValueError(f"Table {table_name} must define a primary key.")
        definitions.append(
            "    PRIMARY KEY (" + ", ".join(primary_keys) + ")"
        )
        table_columns[normalized_table_name] = seen_columns
        statements.append(
            f"CREATE TABLE {table_name} (\n"
            + ",\n".join(definitions)
            + "\n);"
        )

    for table_name, column_name, target_table, target_column in foreign_keys:
        target_columns = table_columns.get(target_table.casefold())
        if target_columns is None or target_column.casefold() not in target_columns:
            raise ValueError(
                f"Foreign key from {table_name} references unknown "
                f"column {target_table}.{target_column}."
            )
        statements.append(
            f"ALTER TABLE {table_name} ADD FOREIGN KEY ({column_name}) "
            f"REFERENCES {_sql_identifier(target_table, 'foreign key table')} "
            f"({_sql_identifier(target_column, 'foreign key column')});"
        )

    return "\n\n".join(statements)


def _erd_type(column_type):
    normalized = _column_type(column_type).casefold()
    if any(value in normalized for value in ("char", "text", "uuid")):
        return "string"
    if any(value in normalized for value in ("int", "serial")):
        return "int"
    if any(value in normalized for value in ("decimal", "numeric", "real", "double")):
        return "float"
    if "bool" in normalized:
        return "boolean"
    if "time" in normalized or "date" in normalized:
        return "datetime"
    if "json" in normalized:
        return "json"
    return "string"


def _build_erd(tables):
    entities = []
    relationships = []
    for table in tables:
        table_name = table.get("table_name")
        if not isinstance(table_name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*",
            table_name,
        ):
            raise ValueError(f"Invalid database table name: {table_name!r}")
        entity_name = table_name.upper()
        attributes = []
        for column in table["columns"]:
            column_name = column.get("name")
            if not isinstance(column_name, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*",
                column_name,
            ):
                raise ValueError(f"Invalid database column name: {column_name!r}")
            key = (
                "PK"
                if column.get("primary_key")
                else "FK"
                if column.get("foreign_key")
                else ""
            )
            attribute = (
                f"        {_erd_type(column.get('type'))} "
                f"{column_name}"
            )
            attributes.append(f"{attribute} {key}".rstrip())
            target = _foreign_key_target(column.get("foreign_key"))
            if target:
                relationships.append(
                    (target[0].upper(), entity_name, column_name)
                )
        entities.append(
            f"{entity_name} {{\n"
            + "\n".join(attributes)
            + "\n}"
        )

    relation_lines = []
    for parent, child, foreign_key in relationships:
        if parent not in {table.get("table_name", "").upper() for table in tables}:
            raise ValueError(
                f"Foreign key references unknown table {parent!r}."
            )
        relation_lines.append(
            f"{parent} ||--o{{ {child} : {foreign_key}"
        )

    diagram = ["erDiagram", *entities]
    if relation_lines:
        diagram.extend(relation_lines)
    return "\n\n".join(diagram)


# =======================================
# Parse JSON Response
# =======================================

def parse_json_response(response):

    if not response:

        raise Exception(
            "Table Generator returned an empty response."
        )


    response = response.strip()


    # Remove markdown fences

    response = re.sub(
        r"```json",
        "",
        response,
        flags=re.IGNORECASE
    )

    response = re.sub(
        r"```",
        "",
        response
    )


    response = response.strip()


    # Find JSON array

    start = response.find("[")

    end = response.rfind("]")


    if start == -1 or end == -1:

        raise Exception(
            "Table Generator did not return "
            "a valid JSON array.\n\n"
            f"LLM Response:\n{response}"
        )


    response = response[
        start:end + 1
    ]


    try:

        return json.loads(response)

    except json.JSONDecodeError as e:

        raise Exception(
            "Table JSON parsing error:\n"
            f"{e}\n\n"
            f"LLM Response:\n{response}"
        )


# =======================================
# Generate Database
# =======================================

def generate_database(
    requirements,
    architecture
):

    if not requirements:

        raise Exception(
            "Requirements are required."
        )


    if not architecture:

        raise Exception(
            "Architecture is required."
        )


    # ===================================
    # TABLES
    # ===================================

    tables_response = generate_tables(

        requirements,

        architecture

    )


    tables = parse_json_response(
        tables_response
    )
    if not isinstance(tables, list) or not tables:
        raise ValueError("Table Generator returned no database tables.")


    return {
        "tables": tables,
        "erd": _build_erd(tables),
        "sql_schema": _build_sql_schema(tables),
    }