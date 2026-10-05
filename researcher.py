"""
Brad's Signals Researcher
Stage R3 - Historical Performance Research Engine

Purpose:
- Separate observer/research service for Brad's Signals Bot 2.0
- Read completed historical outcomes
- Measure confidence calibration
- Measure LONG vs SHORT separately
- Measure symbol performance
- Measure technical / memory / AI confidence populations
- Detect paired LONG/SHORT observation structure
- READ ONLY

Safety:
- No database writes
- No Telegram
- No trades
- No production modification
"""

import os
from datetime import datetime, timezone

import psycopg2


RESEARCHER_VERSION = "R3.0"

RESEARCH_MODE = True
DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def pct(correct, total):
    if not total:
        return 0.0
    return round((correct / total) * 100.0, 2)


def safety_check():
    if (
        DATABASE_WRITES_ENABLED
        or TELEGRAM_SENDING_ENABLED
        or TRADE_EXECUTION_ENABLED
        or PRODUCTION_MODIFICATION_ENABLED
    ):
        raise RuntimeError("RESEARCHER SAFETY CHECK FAILED")

    print("SAFETY CHECK: PASS", flush=True)


def print_header(title):
    print("", flush=True)
    print("=" * 60, flush=True)
    print(title, flush=True)
    print("=" * 60, flush=True)


def run_research(database_url):
    conn = None

    try:
        conn = psycopg2.connect(database_url)
        conn.set_session(readonly=True, autocommit=False)

        print("DATABASE CONNECTION: READY", flush=True)
        print("DATABASE SESSION: READ ONLY", flush=True)

        with conn.cursor() as cur:

            # ---------------------------------------------------------
            # 1. DATASET SUMMARY
            # ---------------------------------------------------------

            print_header("R3 DATASET SUMMARY")

            cur.execute(
                """
                SELECT COUNT(*)
                FROM signals2_opportunities
                """
            )
            total_opportunities = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM signals2_outcomes
                WHERE outcome_complete = TRUE
                """
            )
            completed_outcomes = cur.fetchone()[0]

            cur.execute(
                """
                SELECT MAX(created_at)
                FROM signals2_opportunities
                """
            )
            latest_opportunity = cur.fetchone()[0]

            print(
                f"TOTAL OPPORTUNITIES: {total_opportunities}",
                flush=True,
            )

            print(
                f"COMPLETED OUTCOMES: {completed_outcomes}",
                flush=True,
            )

            print(
                f"LATEST OPPORTUNITY: {latest_opportunity}",
                flush=True,
            )

            # ---------------------------------------------------------
            # 2. LONG VS SHORT
            # ---------------------------------------------------------

            print_header("R3 DIRECTION PERFORMANCE")

            cur.execute(
                """
                SELECT
                    o.direction,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (
                        WHERE x.direction_correct = TRUE
                    ) AS correct
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id = o.opportunity_id
                WHERE x.outcome_complete = TRUE
                GROUP BY o.direction
                ORDER BY o.direction
                """
            )

            direction_rows = cur.fetchall()

            for direction, total, correct in direction_rows:
                print(
                    f"DIRECTION {direction}: "
                    f"observations={total}; "
                    f"correct={correct}; "
                    f"rate={pct(correct, total)}%",
                    flush=True,
                )

            # ---------------------------------------------------------
            # 3. FINAL CONFIDENCE CALIBRATION
            # ---------------------------------------------------------

            print_header("R3 FINAL CONFIDENCE CALIBRATION")

            confidence_bands = [
                ("0-49.99", 0.0, 50.0),
                ("50-59.99", 50.0, 60.0),
                ("60-64.99", 60.0, 65.0),
                ("65-69.99", 65.0, 70.0),
                ("70-74.99", 70.0, 75.0),
                ("75-79.99", 75.0, 80.0),
                ("80-100", 80.0, 100.000001),
            ]

            for label, lower, upper in confidence_bands:

                cur.execute(
                    """
                    SELECT
                        COUNT(*),
                        COUNT(*) FILTER (
                            WHERE x.direction_correct = TRUE
                        )
                    FROM signals2_opportunities o
                    JOIN signals2_outcomes x
                        ON x.opportunity_id = o.opportunity_id
                    WHERE x.outcome_complete = TRUE
                      AND o.final_confidence >= %s
                      AND o.final_confidence < %s
                    """,
                    (lower, upper),
                )

                total, correct = cur.fetchone()

                print(
                    f"CONFIDENCE {label}: "
                    f"observations={total}; "
                    f"correct={correct}; "
                    f"rate={pct(correct, total)}%",
                    flush=True,
                )

            # ---------------------------------------------------------
            # 4. LONG CONFIDENCE CALIBRATION
            # ---------------------------------------------------------

            print_header("R3 LONG CONFIDENCE CALIBRATION")

            for label, lower, upper in confidence_bands:

                cur.execute(
                    """
                    SELECT
                        COUNT(*),
                        COUNT(*) FILTER (
                            WHERE x.direction_correct = TRUE
                        )
                    FROM signals2_opportunities o
                    JOIN signals2_outcomes x
                        ON x.opportunity_id = o.opportunity_id
                    WHERE x.outcome_complete = TRUE
                      AND o.direction = 'LONG'
                      AND o.final_confidence >= %s
                      AND o.final_confidence < %s
                    """,
                    (lower, upper),
                )

                total, correct = cur.fetchone()

                print(
                    f"LONG {label}: "
                    f"observations={total}; "
                    f"correct={correct}; "
                    f"rate={pct(correct, total)}%",
                    flush=True,
                )

            # ---------------------------------------------------------
            # 5. SHORT CONFIDENCE CALIBRATION
            # ---------------------------------------------------------

            print_header("R3 SHORT CONFIDENCE CALIBRATION")

            for label, lower, upper in confidence_bands:

                cur.execute(
                    """
                    SELECT
                        COUNT(*),
                        COUNT(*) FILTER (
                            WHERE x.direction_correct = TRUE
                        )
                    FROM signals2_opportunities o
                    JOIN signals2_outcomes x
                        ON x.opportunity_id = o.opportunity_id
                    WHERE x.outcome_complete = TRUE
                      AND o.direction = 'SHORT'
                      AND o.final_confidence >= %s
                      AND o.final_confidence < %s
                    """,
                    (lower, upper),
                )

                total, correct = cur.fetchone()

                print(
                    f"SHORT {label}: "
                    f"observations={total}; "
                    f"correct={correct}; "
                    f"rate={pct(correct, total)}%",
                    flush=True,
                )

            # ---------------------------------------------------------
            # 6. TOP SYMBOLS BY SAMPLE SIZE
            # ---------------------------------------------------------

            print_header("R3 SYMBOL PERFORMANCE")

            cur.execute(
                """
                SELECT
                    o.symbol,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (
                        WHERE x.direction_correct = TRUE
                    ) AS correct
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id = o.opportunity_id
                WHERE x.outcome_complete = TRUE
                GROUP BY o.symbol
                HAVING COUNT(*) >= 10
                ORDER BY COUNT(*) DESC
                LIMIT 20
                """
            )

            symbol_rows = cur.fetchall()

            for symbol, total, correct in symbol_rows:
                print(
                    f"SYMBOL {symbol}: "
                    f"observations={total}; "
                    f"correct={correct}; "
                    f"rate={pct(correct, total)}%",
                    flush=True,
                )

            # ---------------------------------------------------------
            # 7. COMPONENT CONFIDENCE AVERAGES
            # ---------------------------------------------------------

            print_header("R3 COMPONENT CONFIDENCE")

            cur.execute(
                """
                SELECT
                    AVG(o.technical_confidence),
                    AVG(o.memory_confidence),
                    AVG(o.ai_confidence),
                    AVG(o.market_confidence)
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id = o.opportunity_id
                WHERE x.outcome_complete = TRUE
                """
            )

            (
                avg_technical,
                avg_memory,
                avg_ai,
                avg_market,
            ) = cur.fetchone()

            print(
                f"AVG TECHNICAL CONFIDENCE: {avg_technical}",
                flush=True,
            )

            print(
                f"AVG MEMORY CONFIDENCE: {avg_memory}",
                flush=True,
            )

            print(
                f"AVG AI CONFIDENCE: {avg_ai}",
                flush=True,
            )

            print(
                f"AVG MARKET CONFIDENCE: {avg_market}",
                flush=True,
            )

            # ---------------------------------------------------------
            # 8. AI POPULATION
            # ---------------------------------------------------------

            print_header("R3 AI OBSERVATION POPULATION")

            cur.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (
                        WHERE o.ai_confidence IS NOT NULL
                    )
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id = o.opportunity_id
                WHERE x.outcome_complete = TRUE
                """
            )

            total_completed, ai_rows = cur.fetchone()

            print(
                f"COMPLETED OBSERVATIONS: {total_completed}",
                flush=True,
            )

            print(
                f"OBSERVATIONS WITH AI CONFIDENCE: {ai_rows}",
                flush=True,
            )

            if total_completed:
                print(
                    f"AI COVERAGE: "
                    f"{round((ai_rows / total_completed) * 100.0, 2)}%",
                    flush=True,
                )

            # ---------------------------------------------------------
            # 9. PAIRED LONG / SHORT STRUCTURE
            # ---------------------------------------------------------

            print_header("R3 PAIRED OBSERVATION CHECK")

            cur.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT
                        o.symbol,
                        o.created_at
                    FROM signals2_opportunities o
                    JOIN signals2_outcomes x
                        ON x.opportunity_id = o.opportunity_id
                    WHERE x.outcome_complete = TRUE
                    GROUP BY
                        o.symbol,
                        o.created_at
                    HAVING
                        COUNT(*) FILTER (
                            WHERE o.direction = 'LONG'
                        ) > 0
                        AND
                        COUNT(*) FILTER (
                            WHERE o.direction = 'SHORT'
                        ) > 0
                ) paired
                """
            )

            paired_groups = cur.fetchone()[0]

            print(
                f"PAIRED LONG/SHORT GROUPS: {paired_groups}",
                flush=True,
            )

            print(
                "NOTE: Paired LONG/SHORT observations are research "
                "observations and must not be treated as independent "
                "executed trades.",
                flush=True,
            )

            # ---------------------------------------------------------
            # 10. ACTUAL SIGNAL POPULATION
            # ---------------------------------------------------------

            print_header("R3 SIGNAL POPULATION")

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE o.final_confidence >= 80
                    ),
                    COUNT(*) FILTER (
                        WHERE o.signal_sent = TRUE
                    )
                FROM signals2_opportunities o
                """
            )

            eligible_80_plus, sent_signals = cur.fetchone()

            print(
                f"80+ CONFIDENCE OBSERVATIONS: {eligible_80_plus}",
                flush=True,
            )

            print(
                f"SIGNALS MARKED SENT: {sent_signals}",
                flush=True,
            )

            print(
                "NOTE: Historical observations, signal candidates, "
                "sent signals and executed trades are separate populations.",
                flush=True,
            )

        print_header("R3 RESEARCH COMPLETE")

        print(
            "STATUS: HISTORICAL RESEARCH ANALYSIS PASS",
            flush=True,
        )

        print(
            "DATABASE REMAINED READ ONLY",
            flush=True,
        )

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


def main():
    print("=" * 60, flush=True)
    print("BRADS-SIGNALS-RESEARCHER", flush=True)
    print("=" * 60, flush=True)

    print(
        f"RESEARCHER VERSION: {RESEARCHER_VERSION}",
        flush=True,
    )

    print(
        f"STARTED UTC: {utc_now()}",
        flush=True,
    )

    print(
        f"RESEARCH MODE: {RESEARCH_MODE}",
        flush=True,
    )

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

    safety_check()

    database_url = os.environ.get(
        "SIGNALS2_DATABASE_URL",
        "",
    ).strip()

    if not database_url:
        raise RuntimeError(
            "SIGNALS2_DATABASE_URL is not configured"
        )

    print(
        "DATABASE CONNECTION CONFIGURED: True",
        flush=True,
    )

    run_research(database_url)


if __name__ == "__main__":
    main()
