"""
Brad's Signals Researcher
R4.2 - Pattern Discovery Engine

Purpose:
- Discover historical patterns in completed observations
- Analyse LONG and SHORT independently
- Analyse symbol + direction performance
- Analyse multiple outcome horizons
- Analyse confidence within direction
- Reject tiny sample patterns
- Rank stronger and weaker historical patterns

IMPORTANT:
This is discovery only.
Patterns found here are NOT production recommendations.
They require later held-out validation.

READ ONLY.

NO:
- Database writes
- Telegram
- Trades
- Production modification
"""

import math
import os

import psycopg2


VERSION = "R4.2-PATTERN-DISCOVERY"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


MIN_SAMPLE = 50

STRONG_RATE = 55.0
VERY_STRONG_RATE = 60.0

WEAK_RATE = 45.0
VERY_WEAK_RATE = 40.0


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
    ("80+", 80.0, 101.0),
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
            "R4.2 SAFETY CHECK FAILED"
        )

    print(
        "SAFETY CHECK: PASS",
        flush=True,
    )


def percentage(correct, total):
    if not total:
        return 0.0

    return (
        float(correct)
        / float(total)
        * 100.0
    )


def wilson_interval(correct, total, z=1.96):
    """
    Approximate 95% Wilson confidence interval.

    Used only as a research stability indicator.
    It does NOT prove future profitability.
    """

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


def classify(rate_value):
    if rate_value >= VERY_STRONG_RATE:
        return "VERY_STRONG"

    if rate_value >= STRONG_RATE:
        return "STRONG"

    if rate_value <= VERY_WEAK_RATE:
        return "VERY_WEAK"

    if rate_value <= WEAK_RATE:
        return "WEAK"

    return "NEUTRAL"


def dataset_summary(cur):
    section("R4.2 DATASET SUMMARY")

    cur.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT o.symbol),
            MIN(o.created_at),
            MAX(o.created_at)
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id =
               o.opportunity_id
        WHERE x.outcome_complete = TRUE
        """
    )

    (
        completed,
        symbols,
        oldest,
        newest,
    ) = cur.fetchone()

    print(
        f"COMPLETED OBSERVATIONS: {completed}",
        flush=True,
    )

    print(
        f"UNIQUE SYMBOLS: {symbols}",
        flush=True,
    )

    print(
        f"OLDEST COMPLETED: {oldest}",
        flush=True,
    )

    print(
        f"NEWEST COMPLETED: {newest}",
        flush=True,
    )

    print(
        f"MINIMUM PATTERN SAMPLE: {MIN_SAMPLE}",
        flush=True,
    )


def discover_symbol_direction(cur):
    section(
        "R4.2 SYMBOL + DIRECTION PATTERNS"
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
            (MIN_SAMPLE,),
        )

        for (
            symbol,
            direction,
            sample,
            correct,
        ) in cur.fetchall():

            rate_value = percentage(
                correct,
                sample,
            )

            lower, upper = wilson_interval(
                correct,
                sample,
            )

            classification = classify(
                rate_value
            )

            patterns.append(
                {
                    "type": "SYMBOL_DIRECTION",
                    "symbol": symbol,
                    "direction": direction,
                    "horizon": horizon,
                    "sample": sample,
                    "correct": correct,
                    "rate": rate_value,
                    "lower": lower,
                    "upper": upper,
                    "classification":
                        classification,
                }
            )

    patterns.sort(
        key=lambda row: (
            row["rate"],
            row["sample"],
        ),
        reverse=True,
    )

    for row in patterns:

        print(
            f"{row['classification']} | "
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON={row['horizon']} | "
            f"N={row['sample']} | "
            f"CORRECT={row['correct']} | "
            f"RATE={row['rate']:.2f}% | "
            f"95CI="
            f"{row['lower']:.2f}-"
            f"{row['upper']:.2f}%",
            flush=True,
        )

    return patterns


def discover_direction_confidence(cur):
    section(
        "R4.2 DIRECTION + CONFIDENCE PATTERNS"
    )

    patterns = []

    for direction in (
        "LONG",
        "SHORT",
    ):

        for (
            band,
            lower_conf,
            upper_conf,
        ) in CONFIDENCE_BANDS:

            for horizon, column in HORIZONS:

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
                      AND o.direction = %s
                      AND o.final_confidence >= %s
                      AND o.final_confidence < %s
                """

                cur.execute(
                    query,
                    (
                        direction,
                        lower_conf,
                        upper_conf,
                    ),
                )

                sample, correct = cur.fetchone()

                if sample < MIN_SAMPLE:
                    continue

                rate_value = percentage(
                    correct,
                    sample,
                )

                ci_lower, ci_upper = (
                    wilson_interval(
                        correct,
                        sample,
                    )
                )

                patterns.append(
                    {
                        "type":
                            "DIRECTION_CONFIDENCE",
                        "direction":
                            direction,
                        "band":
                            band,
                        "horizon":
                            horizon,
                        "sample":
                            sample,
                        "correct":
                            correct,
                        "rate":
                            rate_value,
                        "lower":
                            ci_lower,
                        "upper":
                            ci_upper,
                        "classification":
                            classify(rate_value),
                    }
                )

    patterns.sort(
        key=lambda row: (
            row["rate"],
            row["sample"],
        ),
        reverse=True,
    )

    for row in patterns:

        print(
            f"{row['classification']} | "
            f"{row['direction']} | "
            f"CONFIDENCE={row['band']} | "
            f"HORIZON={row['horizon']} | "
            f"N={row['sample']} | "
            f"CORRECT={row['correct']} | "
            f"RATE={row['rate']:.2f}% | "
            f"95CI="
            f"{row['lower']:.2f}-"
            f"{row['upper']:.2f}%",
            flush=True,
        )

    return patterns


def strongest_candidates(patterns):
    section(
        "R4.2 STRONGEST DISCOVERY CANDIDATES"
    )

    candidates = [
        row
        for row in patterns
        if (
            row["rate"] >= STRONG_RATE
            and row["sample"] >= MIN_SAMPLE
        )
    ]

    candidates.sort(
        key=lambda row: (
            row["lower"],
            row["rate"],
            row["sample"],
        ),
        reverse=True,
    )

    if not candidates:
        print(
            "NO STRONG CANDIDATES FOUND",
            flush=True,
        )
        return

    for index, row in enumerate(
        candidates[:20],
        start=1,
    ):

        print(
            f"RANK={index} | "
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON={row['horizon']} | "
            f"N={row['sample']} | "
            f"RATE={row['rate']:.2f}% | "
            f"95CI_LOW={row['lower']:.2f}% | "
            f"CLASS={row['classification']}",
            flush=True,
        )


def weakest_candidates(patterns):
    section(
        "R4.2 WEAKEST DISCOVERY CANDIDATES"
    )

    candidates = [
        row
        for row in patterns
        if (
            row["rate"] <= WEAK_RATE
            and row["sample"] >= MIN_SAMPLE
        )
    ]

    candidates.sort(
        key=lambda row: (
            row["upper"],
            row["rate"],
        ),
    )

    if not candidates:
        print(
            "NO WEAK CANDIDATES FOUND",
            flush=True,
        )
        return

    for index, row in enumerate(
        candidates[:20],
        start=1,
    ):

        print(
            f"RANK={index} | "
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON={row['horizon']} | "
            f"N={row['sample']} | "
            f"RATE={row['rate']:.2f}% | "
            f"95CI_HIGH={row['upper']:.2f}% | "
            f"CLASS={row['classification']}",
            flush=True,
        )


def pattern_summary(
    symbol_patterns,
    confidence_patterns,
):
    section("R4.2 PATTERN SUMMARY")

    symbol_strong = sum(
        1
        for row in symbol_patterns
        if row["rate"] >= STRONG_RATE
    )

    symbol_very_strong = sum(
        1
        for row in symbol_patterns
        if row["rate"] >= VERY_STRONG_RATE
    )

    symbol_weak = sum(
        1
        for row in symbol_patterns
        if row["rate"] <= WEAK_RATE
    )

    confidence_strong = sum(
        1
        for row in confidence_patterns
        if row["rate"] >= STRONG_RATE
    )

    confidence_weak = sum(
        1
        for row in confidence_patterns
        if row["rate"] <= WEAK_RATE
    )

    print(
        f"SYMBOL/DIRECTION PATTERNS: "
        f"{len(symbol_patterns)}",
        flush=True,
    )

    print(
        f"SYMBOL/DIRECTION >=55%: "
        f"{symbol_strong}",
        flush=True,
    )

    print(
        f"SYMBOL/DIRECTION >=60%: "
        f"{symbol_very_strong}",
        flush=True,
    )

    print(
        f"SYMBOL/DIRECTION <=45%: "
        f"{symbol_weak}",
        flush=True,
    )

    print(
        f"DIRECTION/CONFIDENCE PATTERNS: "
        f"{len(confidence_patterns)}",
        flush=True,
    )

    print(
        f"DIRECTION/CONFIDENCE >=55%: "
        f"{confidence_strong}",
        flush=True,
    )

    print(
        f"DIRECTION/CONFIDENCE <=45%: "
        f"{confidence_weak}",
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

            dataset_summary(cur)

            symbol_patterns = (
                discover_symbol_direction(
                    cur
                )
            )

            confidence_patterns = (
                discover_direction_confidence(
                    cur
                )
            )

            strongest_candidates(
                symbol_patterns
            )

            weakest_candidates(
                symbol_patterns
            )

            pattern_summary(
                symbol_patterns,
                confidence_patterns,
            )

        section("R4.2 DISCOVERY COMPLETE")

        print(
            "STATUS: R4.2 PATTERN "
            "DISCOVERY PASS",
            flush=True,
        )

        print(
            "IMPORTANT: DISCOVERED PATTERNS "
            "ARE HYPOTHESES, NOT PRODUCTION "
            "RULES.",
            flush=True,
        )

        print(
            "NEXT REQUIREMENT: HELD-OUT "
            "VALIDATION BEFORE ANY PATTERN "
            "CAN BE CONSIDERED RELIABLE.",
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
