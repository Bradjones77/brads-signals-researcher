#!/usr/bin/env python3
"""
R4 Feature Inspector v1.1
READ-ONLY diagnostic for Brad's Signals Researcher.

Discovers the actual schema/table used for opportunity records, then inspects
decision-time stored feature structures without modifying any data.
"""

import json
import os
from datetime import datetime, timezone

import psycopg2
from psycopg2 import sql

VERSION = "R4-FEATURE-INSPECTOR-1.1"
SAMPLE_ROWS = 3

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


def banner(text):
    print()
    print("=" * 78)
    print(text)
    print("=" * 78)


def parse_jsonish(value):
    if isinstance(value, (dict, list)) or value is None:
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def compact(value, limit=180):
    value = parse_jsonish(value)
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, sort_keys=True, default=str)
        else:
            text = repr(value)
    except Exception:
        text = repr(value)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def print_structure(label, value, depth=0, max_depth=3):
    value = parse_jsonish(value)
    pad = "  " * depth

    if isinstance(value, dict):
        print(f"{pad}{label}: dict | keys={sorted(map(str, value.keys()))}")
        if depth < max_depth:
            for key in sorted(value.keys(), key=lambda x: str(x)):
                child = parse_jsonish(value[key])
                if isinstance(child, (dict, list)):
                    print_structure(str(key), child, depth + 1, max_depth)
                else:
                    print(
                        f"{'  ' * (depth + 1)}{key}: "
                        f"{type(child).__name__} | {compact(child)}"
                    )
    elif isinstance(value, list):
        print(f"{pad}{label}: list | length={len(value)}")
        if value and depth < max_depth:
            print_structure("[0]", value[0], depth + 1, max_depth)
    else:
        print(f"{pad}{label}: {type(value).__name__} | {compact(value)}")


def discover_tables(cur):
    cur.execute(
        """
        SELECT
            n.nspname AS schema_name,
            c.relname AS table_name
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n
          ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_toast%'
        ORDER BY n.nspname, c.relname
        """
    )
    return cur.fetchall()


def get_columns(cur, schema_name, table_name):
    cur.execute(
        """
        SELECT a.attname
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c
          ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n
          ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema_name, table_name),
    )
    return [row[0] for row in cur.fetchall()]


def choose_opportunity_table(cur, tables):
    required = {"symbol", "direction"}
    preferred = {
        "created_at",
        "entry_price",
        "final_confidence",
        "technical_features",
        "market_features",
        "raw_analysis",
        "raw_market_context",
    }

    candidates = []

    for schema_name, table_name in tables:
        columns = get_columns(cur, schema_name, table_name)
        column_set = set(columns)

        if required.issubset(column_set):
            score = len(preferred.intersection(column_set))
            if "opportun" in table_name.lower():
                score += 10

            candidates.append(
                (score, schema_name, table_name, columns)
            )

    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    return candidates


def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print(f"DIAGNOSTIC VERSION: {VERSION}")
    print(f"UTC START: {datetime.now(timezone.utc).isoformat()}")
    print(f"DATABASE WRITES: {DATABASE_WRITES_ENABLED}")
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING_ENABLED}")
    print(f"TRADE EXECUTION: {TRADE_EXECUTION_ENABLED}")
    print(f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION_ENABLED}")

    if any(
        (
            DATABASE_WRITES_ENABLED,
            TELEGRAM_SENDING_ENABLED,
            TRADE_EXECUTION_ENABLED,
            PRODUCTION_MODIFICATION_ENABLED,
        )
    ):
        raise RuntimeError("Safety flags invalid")

    print("SAFETY CHECK: PASS")

    database_url = os.getenv("SIGNALS2_DATABASE_URL")
    if not database_url:
        raise RuntimeError("SIGNALS2_DATABASE_URL is not configured")

    conn = None

    try:
        conn = psycopg2.connect(database_url)
        conn.set_session(readonly=True, autocommit=False)

        print("DATABASE CONNECTION: READY")
        print("DATABASE SESSION: READ ONLY")

        cur = conn.cursor()

        banner("DATABASE OBJECT DISCOVERY")
        tables = discover_tables(cur)
        print(f"NON-SYSTEM TABLES/VIEWS FOUND: {len(tables)}")

        for schema_name, table_name in tables:
            print(f"  - {schema_name}.{table_name}")

        candidates = choose_opportunity_table(cur, tables)

        banner("OPPORTUNITY TABLE CANDIDATES")

        if not candidates:
            raise RuntimeError(
                "No table/view containing both symbol and direction was found"
            )

        for score, schema_name, table_name, columns in candidates:
            print(
                f"  - {schema_name}.{table_name} | "
                f"score={score} | columns={columns}"
            )

        score, schema_name, table_name, columns = candidates[0]

        print()
        print(f"SELECTED TABLE: {schema_name}.{table_name}")
        print(f"SELECTED TABLE SCORE: {score}")

        wanted_candidates = [
            "id",
            "opportunity_id",
            "created_at",
            "symbol",
            "direction",
            "entry_price",
            "final_confidence",
            "technical_confidence",
            "market_confidence",
            "memory_confidence",
            "ai_confidence",
            "decision",
            "signal_sent",
            "technical_features",
            "market_features",
            "features",
            "raw_analysis",
            "raw_market_context",
            "raw_data",
            "ai_analysis",
            "model_version",
            "strategy_version",
        ]

        wanted = [name for name in wanted_candidates if name in columns]

        nested_fields = {
            "technical_features",
            "market_features",
            "features",
            "raw_analysis",
            "raw_market_context",
            "raw_data",
            "ai_analysis",
        }

        banner("SELECTED COLUMNS")
        for name in wanted:
            print(f"  - {name}")

        if not wanted:
            raise RuntimeError("Selected table contains no inspectable columns")

        if "created_at" in columns:
            order_column = "created_at"
        elif "id" in columns:
            order_column = "id"
        else:
            order_column = wanted[0]

        query = sql.SQL(
            "SELECT {fields} FROM {schema}.{table} "
            "ORDER BY {order_col} DESC LIMIT %s"
        ).format(
            fields=sql.SQL(", ").join(
                [sql.Identifier(name) for name in wanted]
            ),
            schema=sql.Identifier(schema_name),
            table=sql.Identifier(table_name),
            order_col=sql.Identifier(order_column),
        )

        cur.execute(query, (SAMPLE_ROWS,))
        rows = cur.fetchall()

        banner("RECENT OPPORTUNITY SAMPLES")
        print(f"SAMPLE ROWS RETURNED: {len(rows)}")

        for index, row in enumerate(rows, start=1):
            record = dict(zip(wanted, row))

            print()
            print("-" * 78)
            print(f"SAMPLE {index}")
            print("-" * 78)

            for key in wanted:
                if key not in nested_fields:
                    print(f"{key}: {compact(record[key])}")

            for key in wanted:
                if key in nested_fields:
                    print()
                    print_structure(key, record[key])

        banner("DIAGNOSTIC STATUS")
        print("STATUS: R4 FEATURE INSPECTOR v1.1 PASS")
        print(f"DISCOVERED TABLE: {schema_name}.{table_name}")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES")

        cur.close()
        conn.rollback()

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        banner("DIAGNOSTIC FAILURE")
        print("STATUS: R4 FEATURE INSPECTOR v1.1 FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise

    finally:
        if conn is not None:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
