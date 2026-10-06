#!/usr/bin/env python3
"""
Brad's Signals Researcher
R6.2A - AI / Outcome Population Inspector

Purpose:
Find exactly where the integrated-AI population overlaps with outcome records
and which outcome horizons are already populated/mature.

READ ONLY:
- No database writes
- No Telegram
- No trades
- No production changes
- No AI/API calls
"""

import os
import psycopg2
from datetime import datetime, timezone

VERSION = "R6.2A-AI-OUTCOME-POPULATION-INSPECTOR"

HORIZONS = [
    ("30s", "direction_correct_30s"),
    ("1m", "direction_correct_1m"),
    ("5m", "direction_correct_5m"),
    ("10m", "direction_correct_10m"),
    ("30m", "direction_correct_30m"),
    ("1h", "direction_correct_1h"),
    ("4h", "direction_correct_4h"),
    ("12h", "direction_correct_12h"),
    ("24h", "direction_correct_24h"),
]


def banner(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print(f"RESEARCH VERSION: {VERSION}")
    print(f"UTC START: {datetime.now(timezone.utc).isoformat()}")
    print("DATABASE WRITES: False")
    print("TELEGRAM SENDING: False")
    print("TRADE EXECUTION: False")
    print("PRODUCTION MODIFICATION: False")
    print("AI CALLS: False")
    print("SAFETY CHECK: PASS")

    url = os.getenv("SIGNALS2_DATABASE_URL")
    if not url:
        raise RuntimeError("SIGNALS2_DATABASE_URL missing")

    conn = None
    try:
        conn = psycopg2.connect(url)
        conn.set_session(readonly=True, autocommit=False)
        cur = conn.cursor()
        print("DATABASE CONNECTION: READY")
        print("DATABASE SESSION: READ ONLY")

        banner("R6.2A OVERALL POPULATIONS")
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE model_version = 'SIGNALS2_AI_INTEGRATED_V1'
                ) AS integrated,
                COUNT(*) FILTER (
                    WHERE model_version = 'SIGNALS2_AI_INTEGRATED_V1'
                      AND ai_confidence IS NOT NULL
                ) AS integrated_ai_conf,
                COUNT(*) FILTER (
                    WHERE model_version = 'SIGNALS2_AI_INTEGRATED_V1'
                      AND outcome_status = 'COMPLETE'
                ) AS integrated_complete
            FROM public.signals2_opportunities
        """)
        total, integrated, integrated_ai_conf, integrated_complete = cur.fetchone()
        print(f"TOTAL OPPORTUNITIES: {total}")
        print(f"INTEGRATED MODEL: {integrated}")
        print(f"INTEGRATED + AI_CONFIDENCE: {integrated_ai_conf}")
        print(f"INTEGRATED + OUTCOME_STATUS COMPLETE: {integrated_complete}")

        banner("R6.2A OUTCOME STATUS BY MODEL VERSION")
        cur.execute("""
            SELECT
                model_version,
                outcome_status,
                COUNT(*)
            FROM public.signals2_opportunities
            GROUP BY model_version, outcome_status
            ORDER BY model_version, COUNT(*) DESC
        """)
        for model, status, count in cur.fetchall():
            print(f"MODEL={model!r} | STATUS={status!r} | N={count}")

        banner("R6.2A JOIN COVERAGE")
        cur.execute("""
            SELECT
                COUNT(*) AS integrated_rows,
                COUNT(o.opportunity_id) AS joined_outcome_rows,
                COUNT(*) FILTER (
                    WHERE p.ai_confidence IS NOT NULL
                ) AS integrated_ai_conf,
                COUNT(*) FILTER (
                    WHERE p.ai_confidence IS NOT NULL
                      AND o.opportunity_id IS NOT NULL
                ) AS ai_conf_joined
            FROM public.signals2_opportunities p
            LEFT JOIN public.signals2_outcomes o
              ON o.opportunity_id = p.opportunity_id
            WHERE p.model_version = 'SIGNALS2_AI_INTEGRATED_V1'
        """)
        a, b, c, d = cur.fetchone()
        print(f"INTEGRATED OPPORTUNITIES: {a}")
        print(f"INTEGRATED JOINED TO OUTCOMES: {b}")
        print(f"INTEGRATED WITH AI_CONFIDENCE: {c}")
        print(f"AI_CONFIDENCE ROWS JOINED TO OUTCOMES: {d}")

        banner("R6.2A HORIZON POPULATION - ALL INTEGRATED ROWS")
        for label, column in HORIZONS:
            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE o.{column} IS NOT NULL),
                    COUNT(*) FILTER (
                        WHERE p.ai_confidence IS NOT NULL
                          AND o.{column} IS NOT NULL
                    ),
                    MIN(p.created_at) FILTER (WHERE o.{column} IS NOT NULL),
                    MAX(p.created_at) FILTER (WHERE o.{column} IS NOT NULL)
                FROM public.signals2_opportunities p
                JOIN public.signals2_outcomes o
                  ON o.opportunity_id = p.opportunity_id
                WHERE p.model_version = 'SIGNALS2_AI_INTEGRATED_V1'
            """)
            all_n, ai_n, first_at, last_at = cur.fetchone()
            print(
                f"{label}: POPULATED={all_n} | AI_CONFIDENCE_POPULATED={ai_n} | "
                f"FIRST={first_at} | LAST={last_at}"
            )

        banner("R6.2A AI-CONFIDENCE ROW STATUS")
        cur.execute("""
            SELECT
                p.outcome_status,
                COUNT(*),
                MIN(p.created_at),
                MAX(p.created_at)
            FROM public.signals2_opportunities p
            WHERE p.model_version = 'SIGNALS2_AI_INTEGRATED_V1'
              AND p.ai_confidence IS NOT NULL
            GROUP BY p.outcome_status
            ORDER BY COUNT(*) DESC
        """)
        for status, count, first_at, last_at in cur.fetchall():
            print(
                f"STATUS={status!r} | N={count} | "
                f"FIRST={first_at} | LAST={last_at}"
            )

        banner("R6.2A RECENT AI ROWS WITH OUTCOME AVAILABILITY")
        horizon_select = ", ".join(f"o.{c}" for _, c in HORIZONS)
        cur.execute(f"""
            SELECT
                p.created_at,
                p.symbol,
                p.direction,
                p.ai_confidence,
                p.outcome_status,
                {horizon_select}
            FROM public.signals2_opportunities p
            LEFT JOIN public.signals2_outcomes o
              ON o.opportunity_id = p.opportunity_id
            WHERE p.model_version = 'SIGNALS2_AI_INTEGRATED_V1'
              AND p.ai_confidence IS NOT NULL
            ORDER BY p.created_at DESC
            LIMIT 12
        """)
        for row in cur.fetchall():
            created_at, symbol, direction, ai_conf, status, *vals = row
            populated = [
                label for (label, _), value in zip(HORIZONS, vals)
                if value is not None
            ]
            print(
                f"{created_at} | {symbol} {direction} | AI={ai_conf} | "
                f"STATUS={status!r} | POPULATED_HORIZONS={populated}"
            )

        banner("R6.2A CONCLUSION TARGET")
        print("USE THESE COUNTS TO CHOOSE THE CORRECT R6.2 DATASET.")
        print("DO NOT TREAT outcome_status='COMPLETE' AS REQUIRED UNTIL THE ACTUAL POPULATION LOGIC IS GROUNDED.")
        print("A HORIZON CAN BE AUDITED WHEN ITS direction_correct_* FIELD IS NON-NULL.")
        print("NO AI EFFECTIVENESS CLAIM IS MADE BY R6.2A.")

        banner("R6.2A FINAL STATUS")
        print("STATUS: R6.2A AI / OUTCOME POPULATION INSPECTOR PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES; NO AI CALLS")

        conn.rollback()
        cur.close()

    except Exception as exc:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        banner("R6.2A FAILURE")
        print("STATUS: R6.2A FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise
    finally:
        if conn:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
