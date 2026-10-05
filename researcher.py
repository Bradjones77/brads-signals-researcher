"""
Brad's Signals Researcher
Stage R3 - Multi-Horizon Historical Research Engine

Purpose:
- Read Bot 2.0 historical observations
- Analyse outcome accuracy across multiple time horizons
- Analyse LONG and SHORT separately
- Analyse confidence calibration
- Analyse AI-covered observations separately
- Detect paired LONG/SHORT research observations
- Remain completely read-only

NO:
- Database writes
- Telegram sending
- Trade execution
- Production modification
"""

import os
import psycopg2


RESEARCHER_VERSION = "R3.1-MULTI-HORIZON"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


HORIZONS = [
    ("5m", "direction_correct_5m"),
    ("30m", "direction_correct_30m"),
    ("1h", "direction_correct_1h"),
    ("4h", "direction_correct_4h"),
    ("12h", "direction_correct_12h"),
    ("24h", "direction_correct_24h"),
]


CONFIDENCE_BANDS = [
    ("0-49.99", 0.0, 50.0),
    ("50-59.99", 50.0, 60.0),
    ("60-64.99", 60.0, 65.0),
    ("65-69.99", 65.0, 70.0),
    ("70-74.99", 70.0, 75.0),
    ("75-79.99", 75.0, 80.0),
    ("80-100", 80.0, 100.000001),
]


def rate(correct, total):
    if not total:
        return 0.0

    return round(
        (correct / total) * 100.0,
        2,
    )


def section(title):
    print("", flush=True)
    print("=" * 60, flush=True)
    print(title, flush=True)
    print("=" * 60, flush=True)


def safety_check():
    if (
        DATABASE_WRITES_ENABLED
        or TELEGRAM_SENDING_ENABLED
        or TRADE_EXECUTION_ENABLED
        or PRODUCTION_MODIFICATION_ENABLED
    ):
        raise RuntimeError(
            "RESEARCHER SAFETY CHECK FAILED"
        )

    print("SAFETY CHECK: PASS", flush=True)


def dataset_summary(cur):
    section("R3 DATASET SUMMARY")

    cur.execute(
        """
        SELECT COUNT(*)
        FROM signals2_opportunities
        """
    )
    opportunities = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(*)
        FROM signals2_outcomes
        """
    )
    outcomes = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(*)
        FROM signals2_outcomes
        WHERE outcome_complete = TRUE
        """
    )
    completed = cur.fetchone()[0]

    cur.execute(
        """
        SELECT MAX(created_at)
        FROM signals2_opportunities
        """
    )
    latest = cur.fetchone()[0]

    print(
        f"TOTAL OPPORTUNITIES: {opportunities}",
        flush=True,
    )
    print(
        f"TOTAL OUTCOMES: {outcomes}",
        flush=True,
    )
    print(
        f"COMPLETED OUTCOMES: {completed}",
        flush=True,
    )
    print(
        f"LATEST OPPORTUNITY: {latest}",
        flush=True,
    )


def multi_horizon_performance(cur):
    section("R3 MULTI-HORIZON PERFORMANCE")

    for label, column in HORIZONS:

        query = f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE {column} IS NOT NULL
                ),
                COUNT(*) FILTER (
                    WHERE {column} = TRUE
                )
            FROM signals2_outcomes
            WHERE outcome_complete = TRUE
        """

        cur.execute(query)

        total, correct = cur.fetchone()

        print(
            f"HORIZON {label}: "
            f"observations={total}; "
            f"correct={correct}; "
            f"rate={rate(correct, total)}%",
            flush=True,
        )


def direction_performance(cur):
    section("R3 LONG VS SHORT BY HORIZON")

    for direction in ("LONG", "SHORT"):

        print(
            f"--- {direction} ---",
            flush=True,
        )

        for label, column in HORIZONS:

            query = f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE x.{column} IS NOT NULL
                    ),
                    COUNT(*) FILTER (
                        WHERE x.{column} = TRUE
                    )
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id = o.opportunity_id
                WHERE x.outcome_complete = TRUE
                  AND o.direction = %s
            """

            cur.execute(
                query,
                (direction,),
            )

            total, correct = cur.fetchone()

            print(
                f"{direction} {label}: "
                f"observations={total}; "
                f"correct={correct}; "
                f"rate={rate(correct, total)}%",
                flush=True,
            )


def confidence_calibration(cur):
    section("R3 CONFIDENCE CALIBRATION")

    for horizon_label, column in HORIZONS:

        print(
            f"--- HORIZON {horizon_label} ---",
            flush=True,
        )

        for band_label, lower, upper in CONFIDENCE_BANDS:

            query = f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE x.{column} IS NOT NULL
                    ),
                    COUNT(*) FILTER (
                        WHERE x.{column} = TRUE
                    )
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id = o.opportunity_id
                WHERE x.outcome_complete = TRUE
                  AND o.final_confidence >= %s
                  AND o.final_confidence < %s
            """

            cur.execute(
                query,
                (lower, upper),
            )

            total, correct = cur.fetchone()

            print(
                f"{horizon_label} CONFIDENCE "
                f"{band_label}: "
                f"observations={total}; "
                f"correct={correct}; "
                f"rate={rate(correct, total)}%",
                flush=True,
            )


def directional_confidence(cur):
    section("R3 DIRECTIONAL CONFIDENCE CALIBRATION")

    # Concentrate this section on the more useful
    # medium/longer research horizons.
    selected_horizons = [
        ("30m", "direction_correct_30m"),
        ("1h", "direction_correct_1h"),
        ("4h", "direction_correct_4h"),
        ("24h", "direction_correct_24h"),
    ]

    for direction in ("LONG", "SHORT"):

        print(
            f"--- {direction} ---",
            flush=True,
        )

        for horizon_label, column in selected_horizons:

            for band_label, lower, upper in CONFIDENCE_BANDS:

                query = f"""
                    SELECT
                        COUNT(*) FILTER (
                            WHERE x.{column} IS NOT NULL
                        ),
                        COUNT(*) FILTER (
                            WHERE x.{column} = TRUE
                        )
                    FROM signals2_opportunities o
                    JOIN signals2_outcomes x
                        ON x.opportunity_id = o.opportunity_id
                    WHERE x.outcome_complete = TRUE
                      AND o.direction = %s
                      AND o.final_confidence >= %s
                      AND o.final_confidence < %s
                """

                cur.execute(
                    query,
                    (
                        direction,
                        lower,
                        upper,
                    ),
                )

                total, correct = cur.fetchone()

                print(
                    f"{direction} {horizon_label} "
                    f"{band_label}: "
                    f"n={total}; "
                    f"correct={correct}; "
                    f"rate={rate(correct, total)}%",
                    flush=True,
                )


def ai_population(cur):
    section("R3 AI POPULATION ANALYSIS")

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

    total, with_ai = cur.fetchone()

    print(
        f"COMPLETED OBSERVATIONS: {total}",
        flush=True,
    )
    print(
        f"WITH AI CONFIDENCE: {with_ai}",
        flush=True,
    )

    coverage = (
        round(
            (with_ai / total) * 100.0,
            2,
        )
        if total
        else 0.0
    )

    print(
        f"AI COVERAGE: {coverage}%",
        flush=True,
    )

    for label, column in HORIZONS:

        query = f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE x.{column} IS NOT NULL
                ),
                COUNT(*) FILTER (
                    WHERE x.{column} = TRUE
                )
            FROM signals2_opportunities o
            JOIN signals2_outcomes x
                ON x.opportunity_id = o.opportunity_id
            WHERE x.outcome_complete = TRUE
              AND o.ai_confidence IS NOT NULL
        """

        cur.execute(query)

        sample, correct = cur.fetchone()

        print(
            f"AI {label}: "
            f"observations={sample}; "
            f"correct={correct}; "
            f"rate={rate(correct, sample)}%",
            flush=True,
        )


def component_confidence(cur):
    section("R3 COMPONENT CONFIDENCE SUMMARY")

    cur.execute(
        """
        SELECT
            AVG(o.final_confidence),
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
        final_conf,
        technical_conf,
        memory_conf,
        ai_conf,
        market_conf,
    ) = cur.fetchone()

    print(
        f"AVG FINAL CONFIDENCE: {final_conf}",
        flush=True,
    )
    print(
        f"AVG TECHNICAL CONFIDENCE: {technical_conf}",
        flush=True,
    )
    print(
        f"AVG MEMORY CONFIDENCE: {memory_conf}",
        flush=True,
    )
    print(
        f"AVG AI CONFIDENCE: {ai_conf}",
        flush=True,
    )
    print(
        f"AVG MARKET CONFIDENCE: {market_conf}",
        flush=True,
    )


def paired_observations(cur):
    section("R3 PAIRED OBSERVATION STRUCTURE")

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

    paired = cur.fetchone()[0]

    print(
        f"PAIRED LONG/SHORT GROUPS: {paired}",
        flush=True,
    )

    print(
        "IMPORTANT: paired LONG/SHORT research observations "
        "must not be interpreted as independent executed trades.",
        flush=True,
    )


def signal_population(cur):
    section("R3 SIGNAL POPULATION")

    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE final_confidence >= 80
            ),
            COUNT(*) FILTER (
                WHERE signal_sent = TRUE
            ),
            COUNT(*) FILTER (
                WHERE decision = 'SELECTED'
            )
        FROM signals2_opportunities
        """
    )

    confidence_80,
    sent,
    selected = cur.fetchone()

    print(
        f"80+ CONFIDENCE OBSERVATIONS: {confidence_80}",
        flush=True,
    )
    print(
        f"SELECTED OBSERVATIONS: {selected}",
        flush=True,
    )
    print(
        f"SIGNALS MARKED SENT: {sent}",
        flush=True,
    )

    print(
        "OBSERVATIONS, SELECTED SIGNALS, SENT SIGNALS "
        "AND EXECUTED TRADES ARE DIFFERENT POPULATIONS.",
        flush=True,
    )


def excursion_analysis(cur):
    section("R3 MFE / MAE RESEARCH")

    cur.execute(
        """
        SELECT
            AVG(max_favorable_excursion_pct),
            AVG(max_adverse_excursion_pct)
        FROM signals2_outcomes
        WHERE outcome_complete = TRUE
        """
    )

    mfe, mae = cur.fetchone()

    print(
        f"AVG MAX FAVORABLE EXCURSION: {mfe}",
        flush=True,
    )
    print(
        f"AVG MAX ADVERSE EXCURSION: {mae}",
        flush=True,
    )


def run_research(database_url):
    conn = None

    try:
        conn = psycopg2.connect(
            database_url
        )

        conn.set_session(
            readonly=True,
            autocommit=False,
        )

        print(
            "DATABASE CONNECTION: READY",
            flush=True,
        )
        print(
            "DATABASE SESSION: READ ONLY",
            flush=True,
        )

        with conn.cursor() as cur:

            dataset_summary(cur)

            multi_horizon_performance(cur)

            direction_performance(cur)

            confidence_calibration(cur)

            directional_confidence(cur)

            ai_population(cur)

            component_confidence(cur)

            paired_observations(cur)

            signal_population(cur)

            excursion_analysis(cur)

        section("R3 RESEARCH COMPLETE")

        print(
            "STATUS: MULTI-HORIZON RESEARCH PASS",
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
    print(
        "BRADS-SIGNALS-RESEARCHER",
        flush=True,
    )
    print("=" * 60, flush=True)

    print(
        f"RESEARCHER VERSION: "
        f"{RESEARCHER_VERSION}",
        flush=True,
    )

    print(
        f"DATABASE WRITES: "
        f"{DATABASE_WRITES_ENABLED}",
        flush=True,
    )

    print(
        f"TELEGRAM SENDING: "
        f"{TELEGRAM_SENDING_ENABLED}",
        flush=True,
    )

    print(
        f"TRADE EXECUTION: "
        f"{TRADE_EXECUTION_ENABLED}",
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
            "SIGNALS2_DATABASE_URL "
            "is not configured"
        )

    print(
        "DATABASE CONNECTION CONFIGURED: True",
        flush=True,
    )

    run_research(
        database_url
    )


if __name__ == "__main__":
    main()
