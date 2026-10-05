"""
BRAD'S SIGNALS RESEARCHER
R4.3 - HELD-OUT TIME VALIDATION

Purpose:
- Discover patterns using EARLIER historical data only
- Validate those patterns on LATER unseen data
- Prevent look-ahead leakage
- Separate LONG and SHORT
- Validate each outcome horizon independently
- Reject small samples
- Detect patterns that persist, weaken, reverse, or fail

IMPORTANT:
This is research only.

NO:
- Database writes
- Telegram sending
- Trade execution
- Production modification
"""

import math
import os

import psycopg2


VERSION = "R4.3-HELDOUT-TIME-VALIDATION"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False

DISCOVERY_RATIO = 0.70

MIN_DISCOVERY_SAMPLE = 50
MIN_VALIDATION_SAMPLE = 20

DISCOVERY_RATE_THRESHOLD = 55.0
VALIDATION_RATE_THRESHOLD = 55.0

HORIZONS = [
    ("5m", "direction_correct_5m"),
    ("30m", "direction_correct_30m"),
    ("1h", "direction_correct_1h"),
    ("4h", "direction_correct_4h"),
    ("12h", "direction_correct_12h"),
    ("24h", "direction_correct_24h"),
]


def section(title):
    print("", flush=True)
    print("=" * 78, flush=True)
    print(title, flush=True)
    print("=" * 78, flush=True)


def safety_check():
    if (
        DATABASE_WRITES_ENABLED
        or TELEGRAM_SENDING_ENABLED
        or TRADE_EXECUTION_ENABLED
        or PRODUCTION_MODIFICATION_ENABLED
    ):
        raise RuntimeError(
            "R4.3 SAFETY CHECK FAILED"
        )

    print("SAFETY CHECK: PASS", flush=True)


def percentage(correct, total):
    if not total:
        return 0.0

    return (
        float(correct)
        / float(total)
        * 100.0
    )


def wilson_interval(correct, total, z=1.96):
    if not total:
        return 0.0, 0.0

    p = float(correct) / float(total)

    denominator = (
        1.0
        + (z * z / total)
    )

    centre = (
        p
        + (z * z / (2.0 * total))
    )

    adjustment = z * math.sqrt(
        (
            p * (1.0 - p)
            + (z * z / (4.0 * total))
        )
        / total
    )

    lower = (
        centre - adjustment
    ) / denominator

    upper = (
        centre + adjustment
    ) / denominator

    return (
        lower * 100.0,
        upper * 100.0,
    )


def determine_split(cur):
    section("R4.3 CHRONOLOGICAL DATA SPLIT")

    cur.execute(
        """
        SELECT
            o.created_at
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id =
               o.opportunity_id
        WHERE x.outcome_complete = TRUE
        ORDER BY
            o.created_at ASC,
            o.opportunity_id ASC
        """
    )

    timestamps = [
        row[0]
        for row in cur.fetchall()
    ]

    total = len(timestamps)

    if total == 0:
        raise RuntimeError(
            "NO COMPLETED OBSERVATIONS FOUND"
        )

    split_index = int(
        total * DISCOVERY_RATIO
    )

    if split_index <= 0:
        raise RuntimeError(
            "INVALID DISCOVERY SPLIT"
        )

    if split_index >= total:
        raise RuntimeError(
            "INVALID VALIDATION SPLIT"
        )

    split_time = timestamps[split_index]

    discovery_count = sum(
        1
        for timestamp in timestamps
        if timestamp < split_time
    )

    validation_count = sum(
        1
        for timestamp in timestamps
        if timestamp >= split_time
    )

    print(
        f"TOTAL COMPLETED OBSERVATIONS: "
        f"{total}",
        flush=True,
    )

    print(
        f"TARGET DISCOVERY RATIO: "
        f"{DISCOVERY_RATIO:.0%}",
        flush=True,
    )

    print(
        f"SPLIT TIME: {split_time}",
        flush=True,
    )

    print(
        f"DISCOVERY OBSERVATIONS: "
        f"{discovery_count}",
        flush=True,
    )

    print(
        f"VALIDATION OBSERVATIONS: "
        f"{validation_count}",
        flush=True,
    )

    print(
        f"MIN DISCOVERY SAMPLE: "
        f"{MIN_DISCOVERY_SAMPLE}",
        flush=True,
    )

    print(
        f"MIN VALIDATION SAMPLE: "
        f"{MIN_VALIDATION_SAMPLE}",
        flush=True,
    )

    return split_time


def get_period_stats(
    cur,
    symbol,
    direction,
    column,
    split_time,
    period,
):
    if period == "DISCOVERY":
        time_clause = "o.created_at < %s"
    elif period == "VALIDATION":
        time_clause = "o.created_at >= %s"
    else:
        raise ValueError(
            "INVALID PERIOD"
        )

    query = f"""
        SELECT
            COUNT(*) AS sample_count,
            COUNT(*) FILTER (
                WHERE x.{column} = TRUE
            ) AS correct_count
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id =
               o.opportunity_id
        WHERE x.outcome_complete = TRUE
          AND x.{column} IS NOT NULL
          AND o.symbol = %s
          AND o.direction = %s
          AND {time_clause}
    """

    cur.execute(
        query,
        (
            symbol,
            direction,
            split_time,
        ),
    )

    sample, correct = cur.fetchone()

    return sample, correct


def discover_patterns(cur, split_time):
    section(
        "R4.3 DISCOVERY PERIOD PATTERN SEARCH"
    )

    patterns = []

    for horizon, column in HORIZONS:

        query = f"""
            SELECT
                o.symbol,
                o.direction,
                COUNT(*) AS sample_count,
                COUNT(*) FILTER (
                    WHERE x.{column} = TRUE
                ) AS correct_count
            FROM signals2_opportunities o
            JOIN signals2_outcomes x
                ON x.opportunity_id =
                   o.opportunity_id
            WHERE x.outcome_complete = TRUE
              AND x.{column} IS NOT NULL
              AND o.created_at < %s
              AND o.direction IN (
                  'LONG',
                  'SHORT'
              )
            GROUP BY
                o.symbol,
                o.direction
            HAVING COUNT(*) >= %s
        """

        cur.execute(
            query,
            (
                split_time,
                MIN_DISCOVERY_SAMPLE,
            ),
        )

        for (
            symbol,
            direction,
            sample,
            correct,
        ) in cur.fetchall():

            rate = percentage(
                correct,
                sample,
            )

            if rate < DISCOVERY_RATE_THRESHOLD:
                continue

            ci_lower, ci_upper = (
                wilson_interval(
                    correct,
                    sample,
                )
            )

            patterns.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "horizon": horizon,
                    "column": column,
                    "discovery_sample": sample,
                    "discovery_correct": correct,
                    "discovery_rate": rate,
                    "discovery_ci_lower":
                        ci_lower,
                    "discovery_ci_upper":
                        ci_upper,
                }
            )

    patterns.sort(
        key=lambda row: (
            row["discovery_ci_lower"],
            row["discovery_rate"],
            row["discovery_sample"],
        ),
        reverse=True,
    )

    print(
        f"DISCOVERY CANDIDATES >= "
        f"{DISCOVERY_RATE_THRESHOLD:.0f}%: "
        f"{len(patterns)}",
        flush=True,
    )

    for row in patterns:
        print(
            f"DISCOVERED | "
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON={row['horizon']} | "
            f"N={row['discovery_sample']} | "
            f"RATE="
            f"{row['discovery_rate']:.2f}% | "
            f"95CI="
            f"{row['discovery_ci_lower']:.2f}-"
            f"{row['discovery_ci_upper']:.2f}%",
            flush=True,
        )

    return patterns


def validate_patterns(
    cur,
    split_time,
    patterns,
):
    section(
        "R4.3 UNSEEN VALIDATION RESULTS"
    )

    results = []

    for pattern in patterns:

        sample, correct = get_period_stats(
            cur=cur,
            symbol=pattern["symbol"],
            direction=pattern["direction"],
            column=pattern["column"],
            split_time=split_time,
            period="VALIDATION",
        )

        validation_rate = percentage(
            correct,
            sample,
        )

        if sample:
            ci_lower, ci_upper = (
                wilson_interval(
                    correct,
                    sample,
                )
            )
        else:
            ci_lower = 0.0
            ci_upper = 0.0

        discovery_rate = (
            pattern["discovery_rate"]
        )

        rate_change = (
            validation_rate
            - discovery_rate
        )

        if sample < MIN_VALIDATION_SAMPLE:
            status = "INSUFFICIENT_VALIDATION"

        elif (
            validation_rate
            >= VALIDATION_RATE_THRESHOLD
        ):
            status = "VALIDATED"

        elif validation_rate < 50.0:
            status = "FAILED_OR_REVERSED"

        else:
            status = "WEAKENED"

        result = dict(pattern)

        result.update(
            {
                "validation_sample":
                    sample,
                "validation_correct":
                    correct,
                "validation_rate":
                    validation_rate,
                "validation_ci_lower":
                    ci_lower,
                "validation_ci_upper":
                    ci_upper,
                "rate_change":
                    rate_change,
                "status":
                    status,
            }
        )

        results.append(result)

    results.sort(
        key=lambda row: (
            row["status"] == "VALIDATED",
            row["validation_ci_lower"],
            row["validation_rate"],
            row["validation_sample"],
        ),
        reverse=True,
    )

    for row in results:

        print(
            f"{row['status']} | "
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON={row['horizon']} | "
            f"DISCOVERY="
            f"{row['discovery_rate']:.2f}%"
            f"/N{row['discovery_sample']} | "
            f"VALIDATION="
            f"{row['validation_rate']:.2f}%"
            f"/N{row['validation_sample']} | "
            f"CHANGE="
            f"{row['rate_change']:+.2f}pp | "
            f"VAL_95CI="
            f"{row['validation_ci_lower']:.2f}-"
            f"{row['validation_ci_upper']:.2f}%",
            flush=True,
        )

    return results


def validation_summary(results):
    section("R4.3 VALIDATION SUMMARY")

    validated = [
        row
        for row in results
        if row["status"] == "VALIDATED"
    ]

    weakened = [
        row
        for row in results
        if row["status"] == "WEAKENED"
    ]

    failed = [
        row
        for row in results
        if row["status"] ==
        "FAILED_OR_REVERSED"
    ]

    insufficient = [
        row
        for row in results
        if row["status"] ==
        "INSUFFICIENT_VALIDATION"
    ]

    print(
        f"TOTAL DISCOVERED PATTERNS: "
        f"{len(results)}",
        flush=True,
    )

    print(
        f"VALIDATED: {len(validated)}",
        flush=True,
    )

    print(
        f"WEAKENED: {len(weakened)}",
        flush=True,
    )

    print(
        f"FAILED OR REVERSED: "
        f"{len(failed)}",
        flush=True,
    )

    print(
        f"INSUFFICIENT VALIDATION: "
        f"{len(insufficient)}",
        flush=True,
    )

    if validated:
        section(
            "R4.3 STRONGEST HELD-OUT SURVIVORS"
        )

        validated.sort(
            key=lambda row: (
                row["validation_ci_lower"],
                row["validation_rate"],
                row["validation_sample"],
            ),
            reverse=True,
        )

        for index, row in enumerate(
            validated[:20],
            start=1,
        ):
            print(
                f"RANK={index} | "
                f"{row['symbol']} | "
                f"{row['direction']} | "
                f"HORIZON="
                f"{row['horizon']} | "
                f"DISCOVERY="
                f"{row['discovery_rate']:.2f}% | "
                f"VALIDATION="
                f"{row['validation_rate']:.2f}% | "
                f"VAL_N="
                f"{row['validation_sample']} | "
                f"VAL_95CI_LOW="
                f"{row['validation_ci_lower']:.2f}%",
                flush=True,
            )


def main():
    print("=" * 78, flush=True)
    print(
        "BRADS-SIGNALS-RESEARCHER",
        flush=True,
    )
    print(
        f"VERSION: {VERSION}",
        flush=True,
    )
    print("=" * 78, flush=True)

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

            split_time = determine_split(cur)

            patterns = discover_patterns(
                cur,
                split_time,
            )

            results = validate_patterns(
                cur,
                split_time,
                patterns,
            )

            validation_summary(results)

        section("R4.3 VALIDATION COMPLETE")

        print(
            "STATUS: R4.3 HELD-OUT "
            "VALIDATION PASS",
            flush=True,
        )

        print(
            "NOTE: A VALIDATED HISTORICAL "
            "PATTERN IS STILL NOT A "
            "PRODUCTION TRADING RULE.",
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
