#!/usr/bin/env python3
"""
Brad's Signals Researcher
R6.2B - Outcome Queue Starvation Diagnostic

Purpose:
- Read-only inspection of the outcome tracking backlog.
- Reproduce the ordering used by memory_engine.get_pending_outcomes().
- Show whether the oldest incomplete rows are monopolising the first 500 slots.
- Compare queue position with the newer integrated-AI population.
- Make NO production changes.

This diagnostic does NOT:
- write to PostgreSQL
- call Bitget
- call OpenAI
- send Telegram
- execute trades
- modify Bot 2.0
"""

import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

VERSION = "R6.2B-OUTCOME-QUEUE-STARVATION-DIAGNOSTIC"
QUEUE_LIMIT = 500
INTEGRATED_MODEL = "SIGNALS2_AI_INTEGRATED_V1"

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False
BITGET_CALLS = False

DATABASE_URL = (os.getenv("SIGNALS2_DATABASE_URL") or "").strip()

HORIZON_FIELDS = [
    "price_30s",
    "price_1m",
    "price_5m",
    "price_10m",
    "price_30m",
    "price_1h",
    "price_4h",
    "price_12h",
    "price_24h",
]


def banner(title):
    print("")
    print("=" * 100)
    print(title)
    print("=" * 100)


def scalar(cur, query, params=()):
    cur.execute(query, params)
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


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

        banner("R6.2B GLOBAL INCOMPLETE BACKLOG")
        total_incomplete = scalar(
            cur,
            """
            SELECT COUNT(*)
            FROM signals2_outcomes
            WHERE outcome_complete = FALSE
            """
        )
        print(f"TOTAL INCOMPLETE OUTCOMES: {total_incomplete}")

        cur.execute(
            """
            SELECT
                COALESCE(o.model_version, '<NULL>') AS model_version,
                COUNT(*) AS n,
                MIN(r.opportunity_time) AS first_time,
                MAX(r.opportunity_time) AS last_time
            FROM signals2_outcomes r
            LEFT JOIN signals2_opportunities o
              ON o.opportunity_id = r.opportunity_id
            WHERE r.outcome_complete = FALSE
            GROUP BY COALESCE(o.model_version, '<NULL>')
            ORDER BY MIN(r.opportunity_time) ASC
            """
        )
        for row in cur.fetchall():
            print(
                f"MODEL={row['model_version']!r} | N={row['n']} | "
                f"FIRST={row['first_time']} | LAST={row['last_time']}"
            )

        banner("R6.2B EXACT FIRST-500 QUEUE USED BY OUTCOME TRACKER")
        checkpoint_expr = " + ".join(
            [f"CASE WHEN r.{field} IS NOT NULL THEN 1 ELSE 0 END" for field in HORIZON_FIELDS]
        )
        cur.execute(
            f"""
            WITH queue AS (
                SELECT
                    r.opportunity_id,
                    r.symbol,
                    r.direction,
                    r.opportunity_time,
                    r.outcome_complete,
                    o.model_version,
                    o.outcome_status,
                    o.ai_confidence,
                    ({checkpoint_expr}) AS populated_checkpoints
                FROM signals2_outcomes r
                LEFT JOIN signals2_opportunities o
                  ON o.opportunity_id = r.opportunity_id
                WHERE r.outcome_complete = FALSE
                ORDER BY r.opportunity_time ASC
                LIMIT %s
            )
            SELECT
                COALESCE(model_version, '<NULL>') AS model_version,
                COUNT(*) AS n,
                MIN(opportunity_time) AS first_time,
                MAX(opportunity_time) AS last_time,
                COUNT(*) FILTER (WHERE populated_checkpoints = 0) AS zero_checkpoint_rows,
                COUNT(*) FILTER (WHERE populated_checkpoints > 0) AS partial_checkpoint_rows,
                COUNT(*) FILTER (WHERE ai_confidence IS NOT NULL) AS ai_confidence_rows
            FROM queue
            GROUP BY COALESCE(model_version, '<NULL>')
            ORDER BY MIN(opportunity_time) ASC
            """,
            (QUEUE_LIMIT,),
        )
        queue_groups = cur.fetchall()
        for row in queue_groups:
            print(
                f"MODEL={row['model_version']!r} | N={row['n']} | "
                f"ZERO_CHECKPOINTS={row['zero_checkpoint_rows']} | "
                f"PARTIAL_CHECKPOINTS={row['partial_checkpoint_rows']} | "
                f"AI_CONFIDENCE={row['ai_confidence_rows']} | "
                f"FIRST={row['first_time']} | LAST={row['last_time']}"
            )

        first500_integrated = scalar(
            cur,
            """
            WITH queue AS (
                SELECT o.model_version
                FROM signals2_outcomes r
                LEFT JOIN signals2_opportunities o
                  ON o.opportunity_id = r.opportunity_id
                WHERE r.outcome_complete = FALSE
                ORDER BY r.opportunity_time ASC
                LIMIT %s
            )
            SELECT COUNT(*)
            FROM queue
            WHERE model_version = %s
            """,
            (QUEUE_LIMIT, INTEGRATED_MODEL),
        )
        print(f"INTEGRATED MODEL ROWS IN FIRST {QUEUE_LIMIT}: {first500_integrated}")

        banner("R6.2B QUEUE HEAD SAMPLE")
        cur.execute(
            f"""
            SELECT
                r.opportunity_time,
                r.symbol,
                r.direction,
                COALESCE(o.model_version, '<NULL>') AS model_version,
                o.outcome_status,
                o.ai_confidence,
                ({checkpoint_expr}) AS populated_checkpoints
            FROM signals2_outcomes r
            LEFT JOIN signals2_opportunities o
              ON o.opportunity_id = r.opportunity_id
            WHERE r.outcome_complete = FALSE
            ORDER BY r.opportunity_time ASC
            LIMIT 20
            """
        )
        for row in cur.fetchall():
            print(
                f"{row['opportunity_time']} | {row['symbol']} {row['direction']} | "
                f"MODEL={row['model_version']} | STATUS={row['outcome_status']!r} | "
                f"AI={row['ai_confidence']} | CHECKPOINTS={row['populated_checkpoints']}/9"
            )

        banner("R6.2B INTEGRATED MODEL QUEUE POSITION")
        cur.execute(
            """
            WITH ranked AS (
                SELECT
                    r.opportunity_id,
                    r.opportunity_time,
                    o.model_version,
                    ROW_NUMBER() OVER (
                        ORDER BY r.opportunity_time ASC, r.opportunity_id ASC
                    ) AS queue_position
                FROM signals2_outcomes r
                LEFT JOIN signals2_opportunities o
                  ON o.opportunity_id = r.opportunity_id
                WHERE r.outcome_complete = FALSE
            )
            SELECT
                MIN(queue_position) AS first_integrated_queue_position,
                MAX(queue_position) AS last_integrated_queue_position,
                COUNT(*) AS integrated_pending
            FROM ranked
            WHERE model_version = %s
            """,
            (INTEGRATED_MODEL,),
        )
        row = cur.fetchone()
        print(f"FIRST INTEGRATED QUEUE POSITION: {row['first_integrated_queue_position']}")
        print(f"LAST INTEGRATED QUEUE POSITION: {row['last_integrated_queue_position']}")
        print(f"INTEGRATED PENDING ROWS: {row['integrated_pending']}")

        banner("R6.2B AGE / MATURITY CHECK")
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE r.opportunity_time <= NOW() - INTERVAL '2 minutes'
                ) AS mature_2m,
                COUNT(*) FILTER (
                    WHERE r.opportunity_time <= NOW() - INTERVAL '5 minutes'
                ) AS mature_5m,
                COUNT(*) FILTER (
                    WHERE r.opportunity_time <= NOW() - INTERVAL '1 hour'
                ) AS mature_1h,
                COUNT(*) FILTER (
                    WHERE r.opportunity_time <= NOW() - INTERVAL '24 hours'
                ) AS mature_24h,
                COUNT(*) AS total
            FROM signals2_outcomes r
            JOIN signals2_opportunities o
              ON o.opportunity_id = r.opportunity_id
            WHERE
                r.outcome_complete = FALSE
                AND o.model_version = %s
            """,
            (INTEGRATED_MODEL,),
        )
        row = cur.fetchone()
        print(
            f"INTEGRATED PENDING: TOTAL={row['total']} | "
            f">=2m={row['mature_2m']} | >=5m={row['mature_5m']} | "
            f">=1h={row['mature_1h']} | >=24h={row['mature_24h']}"
        )

        banner("R6.2B DIAGNOSTIC INTERPRETATION")
        if first500_integrated == 0:
            print("QUEUE STARVATION INDICATOR: STRONG")
            print(
                "The exact first-500 oldest-incomplete queue contains zero integrated-model rows."
            )
            print(
                "This is consistent with older incomplete records blocking newer observations."
            )
        else:
            print("QUEUE STARVATION INDICATOR: NOT PROVEN")
            print(
                "Integrated-model rows are present in the first-500 queue; inspect tracker execution next."
            )

        print("NO FIX IS APPLIED BY THIS DIAGNOSTIC.")

        banner("R6.2B FINAL STATUS")
        print("STATUS: R6.2B OUTCOME QUEUE DIAGNOSTIC PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES; NO AI CALLS; NO BITGET CALLS")

    finally:
        conn.rollback()
        conn.close()
        print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
