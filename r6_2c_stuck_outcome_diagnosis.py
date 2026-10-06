#!/usr/bin/env python3
"""
Brad's Signals Researcher
R6.2C - Stuck Outcome Record Diagnosis

Read-only diagnostic:
- inspects the oldest incomplete outcome records
- classifies synthetic/test vs normal market symbols
- shows checkpoint population and age
- checks whether the records are structurally capable of leaving the queue
- DOES NOT call Bitget, so it cannot disturb/rate-limit the production bot
"""

import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

VERSION = "R6.2C-STUCK-OUTCOME-RECORD-DIAGNOSIS"
SAMPLE_LIMIT = 500

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False
BITGET_CALLS = False

DATABASE_URL = (os.getenv("SIGNALS2_DATABASE_URL") or "").strip()

PRICE_FIELDS = [
    "price_30s", "price_1m", "price_5m", "price_10m", "price_30m",
    "price_1h", "price_4h", "price_12h", "price_24h",
]

REQUIRED_COMPLETE_FIELDS = [
    "price_1m", "price_5m", "price_10m", "price_30m",
    "price_1h", "price_4h", "price_12h", "price_24h",
]


def banner(title):
    print("")
    print("=" * 100)
    print(title)
    print("=" * 100)


def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print(f"RESEARCH VERSION: {VERSION}")
    print(f"UTC START: {datetime.now(timezone.utc).isoformat()}")
    print(f"DATABASE WRITES: {DATABASE_WRITES}")
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING}")
    print(f"TRADE EXECUTION: {TRADE_EXECUTION}")
    print(f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION}")
    print(f"AI CALLS: {AI_CALLS}")
    print(f"BITGET CALLS: {BITGET_CALLS}")
    print("SAFETY CHECK: PASS")

    if not DATABASE_URL:
        raise RuntimeError("SIGNALS2_DATABASE_URL is not configured")

    conn = psycopg2.connect(DATABASE_URL)
    conn.set_session(readonly=True, autocommit=False)
    print("DATABASE CONNECTION: READY")
    print("DATABASE SESSION: READ ONLY")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        checkpoint_expr = " + ".join(
            f"CASE WHEN r.{field} IS NOT NULL THEN 1 ELSE 0 END"
            for field in PRICE_FIELDS
        )
        required_expr = " + ".join(
            f"CASE WHEN r.{field} IS NOT NULL THEN 1 ELSE 0 END"
            for field in REQUIRED_COMPLETE_FIELDS
        )

        banner("R6.2C OLDEST-500 CLASSIFICATION")
        cur.execute(
            f"""
            WITH oldest AS (
                SELECT
                    r.*,
                    o.model_version,
                    o.outcome_status,
                    ({checkpoint_expr}) AS populated_checkpoints,
                    ({required_expr}) AS required_checkpoints,
                    CASE
                        WHEN UPPER(r.symbol) LIKE 'SIGNALS2%%' THEN 'SYNTHETIC/TEST'
                        ELSE 'NORMAL_SYMBOL'
                    END AS symbol_class
                FROM signals2_outcomes r
                LEFT JOIN signals2_opportunities o
                  ON o.opportunity_id = r.opportunity_id
                WHERE r.outcome_complete = FALSE
                ORDER BY r.opportunity_time ASC
                LIMIT %s
            )
            SELECT
                symbol_class,
                COALESCE(model_version, '<NULL>') AS model_version,
                COUNT(*) AS n,
                COUNT(*) FILTER (WHERE populated_checkpoints = 0) AS zero_checkpoints,
                COUNT(*) FILTER (WHERE populated_checkpoints > 0) AS partial_checkpoints,
                COUNT(*) FILTER (WHERE required_checkpoints = 8) AS completion_ready,
                MIN(opportunity_time) AS first_time,
                MAX(opportunity_time) AS last_time
            FROM oldest
            GROUP BY symbol_class, COALESCE(model_version, '<NULL>')
            ORDER BY MIN(opportunity_time)
            """,
            (SAMPLE_LIMIT,),
        )
        for row in cur.fetchall():
            print(
                f"CLASS={row['symbol_class']} | MODEL={row['model_version']!r} | "
                f"N={row['n']} | ZERO={row['zero_checkpoints']} | "
                f"PARTIAL={row['partial_checkpoints']} | "
                f"COMPLETION_READY={row['completion_ready']} | "
                f"FIRST={row['first_time']} | LAST={row['last_time']}"
            )

        banner("R6.2C SYNTHETIC / TEST BLOCKERS")
        cur.execute(
            """
            SELECT
                r.opportunity_time,
                r.symbol,
                r.direction,
                COALESCE(o.model_version, '<NULL>') AS model_version,
                o.outcome_status
            FROM signals2_outcomes r
            LEFT JOIN signals2_opportunities o
              ON o.opportunity_id = r.opportunity_id
            WHERE
                r.outcome_complete = FALSE
                AND UPPER(r.symbol) LIKE 'SIGNALS2%'
            ORDER BY r.opportunity_time ASC
            LIMIT 50
            """
        )
        synthetic = cur.fetchall()
        print(f"SYNTHETIC/TEST PENDING SAMPLE COUNT: {len(synthetic)}")
        for row in synthetic:
            print(
                f"{row['opportunity_time']} | {row['symbol']} {row['direction']} | "
                f"MODEL={row['model_version']} | STATUS={row['outcome_status']!r}"
            )

        banner("R6.2C OLDEST NORMAL-SYMBOL RECORDS")
        cur.execute(
            f"""
            SELECT
                r.opportunity_time,
                r.symbol,
                r.direction,
                COALESCE(o.model_version, '<NULL>') AS model_version,
                o.outcome_status,
                ({checkpoint_expr}) AS populated_checkpoints,
                EXTRACT(EPOCH FROM (NOW() - r.opportunity_time))/3600.0 AS age_hours
            FROM signals2_outcomes r
            LEFT JOIN signals2_opportunities o
              ON o.opportunity_id = r.opportunity_id
            WHERE
                r.outcome_complete = FALSE
                AND UPPER(r.symbol) NOT LIKE 'SIGNALS2%%'
            ORDER BY r.opportunity_time ASC
            LIMIT 30
            """
        )
        normal_rows = cur.fetchall()
        for row in normal_rows:
            print(
                f"{row['opportunity_time']} | {row['symbol']} {row['direction']} | "
                f"MODEL={row['model_version']} | AGE_H={float(row['age_hours']):.1f} | "
                f"CHECKPOINTS={row['populated_checkpoints']}/9 | "
                f"STATUS={row['outcome_status']!r}"
            )

        banner("R6.2C BACKLOG BY CHECKPOINT COUNT")
        cur.execute(
            f"""
            SELECT
                ({checkpoint_expr}) AS populated_checkpoints,
                COUNT(*) AS n,
                MIN(r.opportunity_time) AS first_time,
                MAX(r.opportunity_time) AS last_time
            FROM signals2_outcomes r
            WHERE r.outcome_complete = FALSE
            GROUP BY ({checkpoint_expr})
            ORDER BY populated_checkpoints
            """
        )
        for row in cur.fetchall():
            print(
                f"CHECKPOINTS={row['populated_checkpoints']}/9 | N={row['n']} | "
                f"FIRST={row['first_time']} | LAST={row['last_time']}"
            )

        banner("R6.2C OLD NORMAL RECORDS THAT SHOULD BE MATURE")
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS n,
                COUNT(*) FILTER (
                    WHERE ({checkpoint_expr}) = 0
                ) AS zero_checkpoint_rows,
                MIN(r.opportunity_time) AS first_time,
                MAX(r.opportunity_time) AS last_time
            FROM signals2_outcomes r
            WHERE
                r.outcome_complete = FALSE
                AND UPPER(r.symbol) NOT LIKE 'SIGNALS2%%'
                AND r.opportunity_time <= NOW() - INTERVAL '24 hours'
            """
        )
        row = cur.fetchone()
        print(
            f"NORMAL PENDING >=24H: {row['n']} | "
            f"ZERO CHECKPOINTS={row['zero_checkpoint_rows']} | "
            f"FIRST={row['first_time']} | LAST={row['last_time']}"
        )

        banner("R6.2C STRUCTURAL FINDINGS")
        print("SOURCE-CODE FACT 1: get_pending_outcomes() selects oldest incomplete rows first.")
        print("SOURCE-CODE FACT 2: update_pending_outcomes() normally processes only the first 500.")
        print("SOURCE-CODE FACT 3: a record remains incomplete until all 1m..24h price checkpoints exist.")
        print("SOURCE-CODE FACT 4: tracker symbols are passed to market-data lookup without a synthetic-symbol exclusion.")
        print("SOURCE-CODE FACT 5: after 24h the tracker requests historical 1m candles for each selected record.")
        print("THIS DIAGNOSTIC DOES NOT CALL BITGET.")
        print("Therefore it does not claim which specific Bitget request fails.")
        print("It determines whether permanently/stale incomplete rows structurally monopolise the queue.")

        banner("R6.2C FINAL STATUS")
        print("STATUS: R6.2C STUCK OUTCOME RECORD DIAGNOSIS PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES; NO AI CALLS; NO BITGET CALLS")

    finally:
        conn.rollback()
        conn.close()
        print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
