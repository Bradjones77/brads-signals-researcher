"""
Brad's Signals Researcher
Stage R2 - Read-Only PostgreSQL Connection

Purpose:
- Separate observer/research service for Brad's Signals Bot 2.0
- Connect to the existing PostgreSQL database in READ-ONLY mode
- Verify historical opportunities and outcomes are visible
- No database writes
- No Telegram
- No trades
- No production modification
"""

import os
from datetime import datetime, timezone

import psycopg2


RESEARCHER_VERSION = "R2.0"

RESEARCH_MODE = True
DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safety_check():
    if (
        DATABASE_WRITES_ENABLED
        or TELEGRAM_SENDING_ENABLED
        or TRADE_EXECUTION_ENABLED
        or PRODUCTION_MODIFICATION_ENABLED
    ):
        raise RuntimeError("RESEARCHER SAFETY CHECK FAILED")

    print("SAFETY CHECK: PASS", flush=True)


def read_database_summary(database_url):
    conn = None

    try:
        conn = psycopg2.connect(database_url)

        # PostgreSQL session is explicitly READ ONLY.
        conn.set_session(readonly=True, autocommit=False)

        print("DATABASE CONNECTION: READY", flush=True)
        print("DATABASE SESSION: READ ONLY", flush=True)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM signals2_opportunities
                """
            )
            opportunity_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM signals2_outcomes
                """
            )
            outcome_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM signals2_outcomes
                WHERE outcome_complete = TRUE
                """
            )
            completed_outcome_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT MAX(created_at)
                FROM signals2_opportunities
                """
            )
            latest_opportunity = cur.fetchone()[0]

        print(
            f"RESEARCH DATA: OPPORTUNITIES={opportunity_count}",
            flush=True,
        )
        print(
            f"RESEARCH DATA: OUTCOMES={outcome_count}",
            flush=True,
        )
        print(
            f"RESEARCH DATA: COMPLETED_OUTCOMES={completed_outcome_count}",
            flush=True,
        )
        print(
            f"RESEARCH DATA: LATEST_OPPORTUNITY={latest_opportunity}",
            flush=True,
        )

        print("DATABASE READ TEST: PASS", flush=True)

    finally:
        if conn is not None:
            conn.rollback()
            conn.close()
            print("DATABASE CONNECTION: CLOSED", flush=True)


def main():
    print("=" * 60, flush=True)
    print("BRADS-SIGNALS-RESEARCHER", flush=True)
    print("=" * 60, flush=True)

    print(f"RESEARCHER VERSION: {RESEARCHER_VERSION}", flush=True)
    print(f"STARTED UTC: {utc_now()}", flush=True)

    print(f"RESEARCH MODE: {RESEARCH_MODE}", flush=True)
    print(f"DATABASE WRITES: {DATABASE_WRITES_ENABLED}", flush=True)
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING_ENABLED}", flush=True)
    print(f"TRADE EXECUTION: {TRADE_EXECUTION_ENABLED}", flush=True)
    print(
        f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION_ENABLED}",
        flush=True,
    )

    safety_check()

    database_url = os.environ.get(
        "SIGNALS2_DATABASE_URL",
        "",
    ).strip()

    if not database_url:
        raise RuntimeError(
            "SIGNALS2_DATABASE_URL is not configured"
        )

    print("DATABASE CONNECTION CONFIGURED: True", flush=True)

    read_database_summary(database_url)

    print(
        "STATUS: R2 READ-ONLY RESEARCH DATABASE ACCESS VERIFIED",
        flush=True,
    )
    print(
        "NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES",
        flush=True,
    )


if __name__ == "__main__":
    main()
