"""
Brad's Signals Researcher
R4.1 - Sample Distribution Diagnostic

Purpose:
- Measure completed research sample distribution
- Count observations by symbol
- Count LONG and SHORT observations separately
- Show how many symbols meet useful sample thresholds
- Help choose minimum sample sizes for R4 pattern discovery

READ ONLY.

NO:
- Database writes
- Telegram
- Trades
- Production modification
"""

import os
import psycopg2


DIAGNOSTIC_VERSION = "R4.1-SAMPLE-DISTRIBUTION"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


SAMPLE_THRESHOLDS = [
    10,
    20,
    30,
    50,
    100,
]


def section(title):
    print("", flush=True)
    print("=" * 70, flush=True)
    print(title, flush=True)
    print("=" * 70, flush=True)


def safety_check():
    if (
        DATABASE_WRITES_ENABLED
        or TELEGRAM_SENDING_ENABLED
        or TRADE_EXECUTION_ENABLED
        or PRODUCTION_MODIFICATION_ENABLED
    ):
        raise RuntimeError(
            "R4.1 SAFETY CHECK FAILED"
        )

    print(
        "SAFETY CHECK: PASS",
        flush=True,
    )


def dataset_summary(cur):
    section("R4.1 DATASET SUMMARY")

    cur.execute(
        """
        SELECT COUNT(*)
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id = o.opportunity_id
        WHERE x.outcome_complete = TRUE
        """
    )

    completed = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(DISTINCT o.symbol)
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id = o.opportunity_id
        WHERE x.outcome_complete = TRUE
        """
    )

    symbols = cur.fetchone()[0]

    cur.execute(
        """
        SELECT
            MIN(o.created_at),
            MAX(o.created_at)
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id = o.opportunity_id
        WHERE x.outcome_complete = TRUE
        """
    )

    oldest, newest = cur.fetchone()

    print(
        f"COMPLETED OBSERVATIONS: {completed}",
        flush=True,
    )

    print(
        f"UNIQUE SYMBOLS: {symbols}",
        flush=True,
    )

    print(
        f"OLDEST COMPLETED OBSERVATION: {oldest}",
        flush=True,
    )

    print(
        f"NEWEST COMPLETED OBSERVATION: {newest}",
        flush=True,
    )


def symbol_distribution(cur):
    section("R4.1 COMPLETED OBSERVATIONS BY SYMBOL")

    cur.execute(
        """
        SELECT
            o.symbol,
            COUNT(*) AS total_count,
            COUNT(*) FILTER (
                WHERE o.direction = 'LONG'
            ) AS long_count,
            COUNT(*) FILTER (
                WHERE o.direction = 'SHORT'
            ) AS short_count
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id = o.opportunity_id
        WHERE x.outcome_complete = TRUE
        GROUP BY o.symbol
        ORDER BY
            total_count DESC,
            o.symbol ASC
        """
    )

    rows = cur.fetchall()

    for (
        symbol,
        total_count,
        long_count,
        short_count,
    ) in rows:

        print(
            f"SYMBOL={symbol} | "
            f"TOTAL={total_count} | "
            f"LONG={long_count} | "
            f"SHORT={short_count}",
            flush=True,
        )

    return rows


def distribution_statistics(rows):
    section("R4.1 SAMPLE DISTRIBUTION STATISTICS")

    if not rows:
        print(
            "NO COMPLETED SYMBOL DATA",
            flush=True,
        )
        return

    totals = sorted(
        row[1]
        for row in rows
    )

    long_counts = sorted(
        row[2]
        for row in rows
    )

    short_counts = sorted(
        row[3]
        for row in rows
    )

    def median(values):
        length = len(values)

        if length == 0:
            return 0

        middle = length // 2

        if length % 2:
            return values[middle]

        return (
            values[middle - 1]
            + values[middle]
        ) / 2

    print(
        f"SYMBOLS ANALYSED: {len(rows)}",
        flush=True,
    )

    print(
        f"MIN TOTAL SAMPLE: {min(totals)}",
        flush=True,
    )

    print(
        f"MEDIAN TOTAL SAMPLE: {median(totals)}",
        flush=True,
    )

    print(
        f"MAX TOTAL SAMPLE: {max(totals)}",
        flush=True,
    )

    print(
        f"MIN LONG SAMPLE: {min(long_counts)}",
        flush=True,
    )

    print(
        f"MEDIAN LONG SAMPLE: {median(long_counts)}",
        flush=True,
    )

    print(
        f"MAX LONG SAMPLE: {max(long_counts)}",
        flush=True,
    )

    print(
        f"MIN SHORT SAMPLE: {min(short_counts)}",
        flush=True,
    )

    print(
        f"MEDIAN SHORT SAMPLE: {median(short_counts)}",
        flush=True,
    )

    print(
        f"MAX SHORT SAMPLE: {max(short_counts)}",
        flush=True,
    )


def threshold_analysis(cur):
    section("R4.1 SAMPLE THRESHOLD ANALYSIS")

    for threshold in SAMPLE_THRESHOLDS:

        cur.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    o.symbol,
                    COUNT(*) AS sample_count
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id =
                       o.opportunity_id
                WHERE x.outcome_complete = TRUE
                GROUP BY o.symbol
                HAVING COUNT(*) >= %s
            ) samples
            """,
            (threshold,),
        )

        symbols_total = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    o.symbol,
                    o.direction,
                    COUNT(*) AS sample_count
                FROM signals2_opportunities o
                JOIN signals2_outcomes x
                    ON x.opportunity_id =
                       o.opportunity_id
                WHERE x.outcome_complete = TRUE
                  AND o.direction IN (
                      'LONG',
                      'SHORT'
                  )
                GROUP BY
                    o.symbol,
                    o.direction
                HAVING COUNT(*) >= %s
            ) samples
            """,
            (threshold,),
        )

        symbol_directions = cur.fetchone()[0]

        print(
            f"MIN_SAMPLE={threshold} | "
            f"SYMBOLS={symbols_total} | "
            f"SYMBOL_DIRECTION_GROUPS="
            f"{symbol_directions}",
            flush=True,
        )


def confidence_distribution(cur):
    section("R4.1 CONFIDENCE SAMPLE DISTRIBUTION")

    cur.execute(
        """
        SELECT
            CASE
                WHEN o.final_confidence < 50
                    THEN '0-49.99'
                WHEN o.final_confidence < 60
                    THEN '50-59.99'
                WHEN o.final_confidence < 65
                    THEN '60-64.99'
                WHEN o.final_confidence < 70
                    THEN '65-69.99'
                WHEN o.final_confidence < 75
                    THEN '70-74.99'
                WHEN o.final_confidence < 80
                    THEN '75-79.99'
                ELSE '80+'
            END AS confidence_band,
            COUNT(*) AS total_count,
            COUNT(*) FILTER (
                WHERE o.direction = 'LONG'
            ) AS long_count,
            COUNT(*) FILTER (
                WHERE o.direction = 'SHORT'
            ) AS short_count
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id = o.opportunity_id
        WHERE x.outcome_complete = TRUE
        GROUP BY confidence_band
        ORDER BY
            MIN(o.final_confidence)
        """
    )

    rows = cur.fetchall()

    for (
        band,
        total_count,
        long_count,
        short_count,
    ) in rows:

        print(
            f"CONFIDENCE={band} | "
            f"TOTAL={total_count} | "
            f"LONG={long_count} | "
            f"SHORT={short_count}",
            flush=True,
        )


def paired_structure(cur):
    section("R4.1 PAIRED LONG/SHORT STRUCTURE")

    cur.execute(
        """
        SELECT
            COUNT(*)
        FROM (
            SELECT
                o.symbol,
                o.created_at
            FROM signals2_opportunities o
            JOIN signals2_outcomes x
                ON x.opportunity_id =
                   o.opportunity_id
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
        f"PAIRED LONG/SHORT GROUPS: "
        f"{paired_groups}",
        flush=True,
    )

    print(
        "NOTE: paired observations are research "
        "observations, not independent trades.",
        flush=True,
    )


def main():
    print("=" * 70, flush=True)
    print(
        "BRADS-SIGNALS-RESEARCHER",
        flush=True,
    )
    print(
        f"DIAGNOSTIC VERSION: "
        f"{DIAGNOSTIC_VERSION}",
        flush=True,
    )
    print("=" * 70, flush=True)

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

            rows = symbol_distribution(cur)

            distribution_statistics(rows)

            threshold_analysis(cur)

            confidence_distribution(cur)

            paired_structure(cur)

        section("R4.1 DIAGNOSTIC SUMMARY")

        print(
            "STATUS: R4.1 SAMPLE "
            "DISTRIBUTION PASS",
            flush=True,
        )

        print(
            "DATABASE REMAINED READ ONLY",
            flush=True,
        )

        print(
            "NO WRITES; NO SENDS; "
            "NO TRADES; NO PRODUCTION CHANGES",
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
