from agents.table_generator import generate_tables
from agents.erd_generator import generate_erd
from agents.sql_generator import generate_sql

import json
import re


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


    # ===================================
    # ER DIAGRAM
    # ===================================

    erd = generate_erd(

        requirements,

        architecture

    )


    # ===================================
    # SQL SCHEMA
    # ===================================

    sql_schema = generate_sql(

        requirements,

        architecture

    )


    # ===================================
    # RETURN
    # ===================================

    return {

        "tables": tables,

        "erd": erd,

        "sql_schema": sql_schema

    }