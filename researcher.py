"""
Brad's Signals Researcher
R3 Schema Inspector

READ ONLY:
- Inspects real PostgreSQL column names
- No INSERT
- No UPDATE
- No DELETE
- No Telegram
- No trades
- No production changes
"""

import os
import psycopg2


RESEARCHER_VERSION = "R3-SCHEMA-INSPECTOR"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


def print_columns(cur, table_name):
    cur.execute(
        """
        SELECT
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )

    rows = cur.fetchall()

    print("=" * 60, flush=True)
    print(f"TABLE: {table_name}", flush=True)
    print("=" * 60, flush=True)

    if not rows:
        print("NO COLUMNS FOUND", flush=True)
        return

    for column_name, data_type in rows:
        print(
            f"COLUMN: {column_name} | TYPE: {data_type}",
            flush=True,
        )


def main():
    print("=" * 60, flush=True)
    print("BRADS-SIGNALS-RESEARCHER", flush=True)
    print(f"VERSION: {RESEARCHER_VERSION}", flush=True)
    print("=" * 60, flush=True)

    print(
        f"DATABASE WRITES: {DATABASE_WRITES_ENABLED}",
        flush=True,
    )
    print(
        f"TELEGRAM SENDING: {TELEGRAM_SENDING_ENABLED}",
        flush=True,
    )
    print(
        f"TRADE EXECUTION: {TRADE_EXECUTION_ENABLED}",
        flush=True,
    )
    print(
        f"PRODUCTION MODIFICATION: "
        f"{PRODUCTION_MODIFICATION_ENABLED}",
        flush=True,
    )

    if (
        DATABASE_WRITES_ENABLED
        or TELEGRAM_SENDING_ENABLED
        or TRADE_EXECUTION_ENABLED
        or PRODUCTION_MODIFICATION_ENABLED
    ):
        raise RuntimeError("SAFETY CHECK FAILED")

    print("SAFETY CHECK: PASS", flush=True)

    database_url = os.environ.get(
        "SIGNALS2_DATABASE_URL",
        "",
    ).strip()

    if not database_url:
        raise RuntimeError(
            "SIGNALS2_DATABASE_URL is not configured"
        )

    conn = None

    try:
        conn = psycopg2.connect(database_url)

        conn.set_session(
            readonly=True,
            autocommit=False,
        )

        print("DATABASE CONNECTION: READY", flush=True)
        print("DATABASE SESSION: READ ONLY", flush=True)

        with conn.cursor() as cur:
            print_columns(
                cur,
                "signals2_opportunities",
            )

            print_columns(
                cur,
                "signals2_outcomes",
            )

        print("=" * 60, flush=True)
        print("SCHEMA INSPECTION: PASS", flush=True)
        print(
            "NO WRITES; NO SENDS; NO TRADES; "
            "NO PRODUCTION CHANGES",
            flush=True,
        )

    finally:
        if conn is not None:
            conn.rollback()
            conn.close()

            print(
                "DATABASE CONNECTION: CLOSED",
                flush=True,
            )


if __name__ == "__main__":
    main()
