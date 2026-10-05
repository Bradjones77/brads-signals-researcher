"""
BRAD'S SIGNALS RESEARCHER
R4.4 - MARKET REGIME VALIDATION

Purpose:
- Investigate regime dependence behind R4.3 results
- Measure market direction across chronological time blocks
- Compare LONG vs SHORT performance inside each block
- Compare symbol/direction/horizon behaviour through time
- Detect persistence, reversal and regime sensitivity
- Research only: no production changes

NO:
- Database writes
- Telegram sending
- Trade execution
- Production modification
"""

import math
import os
from collections import defaultdict

import psycopg2


VERSION = "R4.4-REGIME-VALIDATION"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False

NUMBER_OF_TIME_BLOCKS = 5
MIN_BLOCK_SAMPLE = 15
MIN_SYMBOL_SAMPLE = 20

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
            "R4.4 SAFETY CHECK FAILED"
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
        max(0.0, lower * 100.0),
        min(100.0, upper * 100.0),
    )


def load_completed_rows(cur):
    section("R4.4 LOAD COMPLETED OBSERVATIONS")

    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,
            x.direction_correct_5m,
            x.direction_correct_30m,
            x.direction_correct_1h,
            x.direction_correct_4h,
            x.direction_correct_12h,
            x.direction_correct_24h
        FROM signals2_opportunities o
        JOIN signals2_outcomes x
            ON x.opportunity_id =
               o.opportunity_id
        WHERE x.outcome_complete = TRUE
          AND o.direction IN (
              'LONG',
              'SHORT'
          )
        ORDER BY
            o.created_at ASC,
            o.opportunity_id ASC
        """
    )

    rows = cur.fetchall()

    if not rows:
        raise RuntimeError(
            "NO COMPLETED OBSERVATIONS FOUND"
        )

    print(
        f"COMPLETED OBSERVATIONS: {len(rows)}",
        flush=True,
    )

    print(
        f"OLDEST: {rows[0][1]}",
        flush=True,
    )

    print(
        f"NEWEST: {rows[-1][1]}",
        flush=True,
    )

    return rows


def build_time_blocks(rows):
    section("R4.4 CHRONOLOGICAL REGIME BLOCKS")

    unique_times = sorted(
        set(row[1] for row in rows)
    )

    if len(unique_times) < NUMBER_OF_TIME_BLOCKS:
        raise RuntimeError(
            "NOT ENOUGH UNIQUE TIMES "
            "FOR REGIME BLOCKS"
        )

    block_times = []

    total_times = len(unique_times)

    for block_index in range(
        NUMBER_OF_TIME_BLOCKS
    ):
        start_index = int(
            block_index
            * total_times
            / NUMBER_OF_TIME_BLOCKS
        )

        end_index = int(
            (block_index + 1)
            * total_times
            / NUMBER_OF_TIME_BLOCKS
        )

        selected_times = unique_times[
            start_index:end_index
        ]

        if not selected_times:
            continue

        block_times.append(
            {
                "block":
                    block_index + 1,
                "start":
                    selected_times[0],
                "end":
                    selected_times[-1],
                "times":
                    set(selected_times),
            }
        )

    for block in block_times:
        count = sum(
            1
            for row in rows
            if row[1] in block["times"]
        )

        print(
            f"BLOCK {block['block']} | "
            f"START={block['start']} | "
            f"END={block['end']} | "
            f"OBSERVATIONS={count}",
            flush=True,
        )

    return block_times


def horizon_value(row, horizon_index):
    return row[4 + horizon_index]


def block_direction_analysis(
    rows,
    blocks,
):
    section(
        "R4.4 LONG VS SHORT BY TIME BLOCK"
    )

    results = []

    for block in blocks:
        block_rows = [
            row
            for row in rows
            if row[1] in block["times"]
        ]

        for horizon_index, (
            horizon,
            _,
        ) in enumerate(HORIZONS):

            direction_stats = {}

            for direction in (
                "LONG",
                "SHORT",
            ):
                relevant = [
                    row
                    for row in block_rows
                    if row[3] == direction
                    and horizon_value(
                        row,
                        horizon_index,
                    ) is not None
                ]

                sample = len(relevant)

                correct = sum(
                    1
                    for row in relevant
                    if horizon_value(
                        row,
                        horizon_index,
                    ) is True
                )

                rate = percentage(
                    correct,
                    sample,
                )

                direction_stats[
                    direction
                ] = {
                    "sample": sample,
                    "correct": correct,
                    "rate": rate,
                }

            long_rate = (
                direction_stats[
                    "LONG"
                ]["rate"]
            )

            short_rate = (
                direction_stats[
                    "SHORT"
                ]["rate"]
            )

            difference = (
                long_rate - short_rate
            )

            if (
                direction_stats[
                    "LONG"
                ]["sample"]
                < MIN_BLOCK_SAMPLE
                or direction_stats[
                    "SHORT"
                ]["sample"]
                < MIN_BLOCK_SAMPLE
            ):
                regime = (
                    "INSUFFICIENT_DATA"
                )

            elif difference >= 15.0:
                regime = (
                    "LONG_DOMINANT"
                )

            elif difference <= -15.0:
                regime = (
                    "SHORT_DOMINANT"
                )

            else:
                regime = (
                    "MIXED_OR_NEUTRAL"
                )

            result = {
                "block":
                    block["block"],
                "horizon":
                    horizon,
                "long_sample":
                    direction_stats[
                        "LONG"
                    ]["sample"],
                "long_rate":
                    long_rate,
                "short_sample":
                    direction_stats[
                        "SHORT"
                    ]["sample"],
                "short_rate":
                    short_rate,
                "difference":
                    difference,
                "regime":
                    regime,
            }

            results.append(result)

            print(
                f"BLOCK={block['block']} | "
                f"HORIZON={horizon} | "
                f"LONG="
                f"{long_rate:.2f}%"
                f"/N{result['long_sample']} | "
                f"SHORT="
                f"{short_rate:.2f}%"
                f"/N{result['short_sample']} | "
                f"DIFF="
                f"{difference:+.2f}pp | "
                f"REGIME={regime}",
                flush=True,
            )

    return results


def regime_transition_summary(results):
    section("R4.4 REGIME TRANSITIONS")

    for horizon, _ in HORIZONS:
        horizon_rows = [
            row
            for row in results
            if row["horizon"] == horizon
        ]

        horizon_rows.sort(
            key=lambda row:
            row["block"]
        )

        sequence = " -> ".join(
            (
                f"B{row['block']}:"
                f"{row['regime']}"
            )
            for row in horizon_rows
        )

        print(
            f"HORIZON={horizon} | "
            f"{sequence}",
            flush=True,
        )


def symbol_regime_analysis(
    rows,
    blocks,
):
    section(
        "R4.4 SYMBOL REGIME SENSITIVITY"
    )

    summary = defaultdict(
        lambda: {
            "strong": 0,
            "weak": 0,
            "neutral": 0,
            "blocks": 0,
            "rates": [],
        }
    )

    for block in blocks:
        block_rows = [
            row
            for row in rows
            if row[1] in block["times"]
        ]

        symbols = sorted(
            set(
                row[2]
                for row in block_rows
            )
        )

        for symbol in symbols:
            for direction in (
                "LONG",
                "SHORT",
            ):
                for horizon_index, (
                    horizon,
                    _,
                ) in enumerate(
                    HORIZONS
                ):
                    relevant = [
                        row
                        for row in block_rows
                        if row[2] == symbol
                        and row[3] == direction
                        and horizon_value(
                            row,
                            horizon_index,
                        ) is not None
                    ]

                    sample = len(relevant)

                    if (
                        sample
                        < MIN_SYMBOL_SAMPLE
                    ):
                        continue

                    correct = sum(
                        1
                        for row in relevant
                        if horizon_value(
                            row,
                            horizon_index,
                        ) is True
                    )

                    rate = percentage(
                        correct,
                        sample,
                    )

                    key = (
                        symbol,
                        direction,
                        horizon,
                    )

                    summary[key][
                        "blocks"
                    ] += 1

                    summary[key][
                        "rates"
                    ].append(
                        (
                            block["block"],
                            rate,
                            sample,
                        )
                    )

                    if rate >= 60.0:
                        summary[key][
                            "strong"
                        ] += 1

                    elif rate <= 40.0:
                        summary[key][
                            "weak"
                        ] += 1

                    else:
                        summary[key][
                            "neutral"
                        ] += 1

    sensitivity_rows = []

    for key, stats in summary.items():
        symbol, direction, horizon = key

        rates = [
            item[1]
            for item in stats["rates"]
        ]

        if len(rates) < 2:
            continue

        spread = max(rates) - min(rates)

        sensitivity_rows.append(
            {
                "symbol": symbol,
                "direction": direction,
                "horizon": horizon,
                "blocks": stats[
                    "blocks"
                ],
                "strong": stats[
                    "strong"
                ],
                "weak": stats[
                    "weak"
                ],
                "neutral": stats[
                    "neutral"
                ],
                "spread": spread,
                "rates": stats[
                    "rates"
                ],
            }
        )

    sensitivity_rows.sort(
        key=lambda row: (
            row["spread"],
            row["blocks"],
        ),
        reverse=True,
    )

    for row in sensitivity_rows[:40]:
        rates_text = ", ".join(
            (
                f"B{block}:"
                f"{rate:.1f}%"
                f"/N{sample}"
            )
            for (
                block,
                rate,
                sample,
            ) in row["rates"]
        )

        print(
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON="
            f"{row['horizon']} | "
            f"BLOCKS="
            f"{row['blocks']} | "
            f"STRONG="
            f"{row['strong']} | "
            f"WEAK="
            f"{row['weak']} | "
            f"SPREAD="
            f"{row['spread']:.2f}pp | "
            f"{rates_text}",
            flush=True,
        )

    return sensitivity_rows


def persistent_patterns(
    rows,
    blocks,
):
    section(
        "R4.4 CROSS-REGIME PERSISTENCE"
    )

    candidates = []

    symbols = sorted(
        set(row[2] for row in rows)
    )

    for symbol in symbols:
        for direction in (
            "LONG",
            "SHORT",
        ):
            for horizon_index, (
                horizon,
                _,
            ) in enumerate(HORIZONS):

                block_results = []

                for block in blocks:
                    relevant = [
                        row
                        for row in rows
                        if (
                            row[1]
                            in block["times"]
                            and row[2]
                            == symbol
                            and row[3]
                            == direction
                            and horizon_value(
                                row,
                                horizon_index,
                            )
                            is not None
                        )
                    ]

                    sample = len(relevant)

                    if (
                        sample
                        < MIN_SYMBOL_SAMPLE
                    ):
                        continue

                    correct = sum(
                        1
                        for row in relevant
                        if horizon_value(
                            row,
                            horizon_index,
                        ) is True
                    )

                    rate = percentage(
                        correct,
                        sample,
                    )

                    block_results.append(
                        (
                            block["block"],
                            sample,
                            correct,
                            rate,
                        )
                    )

                if len(block_results) < 2:
                    continue

                rates = [
                    result[3]
                    for result
                    in block_results
                ]

                strong_blocks = sum(
                    1
                    for rate in rates
                    if rate >= 55.0
                )

                weak_blocks = sum(
                    1
                    for rate in rates
                    if rate < 50.0
                )

                total_sample = sum(
                    result[1]
                    for result
                    in block_results
                )

                total_correct = sum(
                    result[2]
                    for result
                    in block_results
                )

                overall_rate = percentage(
                    total_correct,
                    total_sample,
                )

                ci_low, ci_high = (
                    wilson_interval(
                        total_correct,
                        total_sample,
                    )
                )

                if (
                    strong_blocks
                    >= max(
                        2,
                        len(
                            block_results
                        ) - 1,
                    )
                    and weak_blocks == 0
                ):
                    classification = (
                        "PERSISTENT"
                    )

                elif (
                    max(rates)
                    - min(rates)
                    >= 30.0
                ):
                    classification = (
                        "REGIME_SENSITIVE"
                    )

                else:
                    classification = (
                        "MIXED"
                    )

                candidates.append(
                    {
                        "symbol":
                            symbol,
                        "direction":
                            direction,
                        "horizon":
                            horizon,
                        "blocks":
                            len(
                                block_results
                            ),
                        "strong_blocks":
                            strong_blocks,
                        "weak_blocks":
                            weak_blocks,
                        "overall_rate":
                            overall_rate,
                        "ci_low":
                            ci_low,
                        "ci_high":
                            ci_high,
                        "spread":
                            max(rates)
                            - min(rates),
                        "classification":
                            classification,
                        "results":
                            block_results,
                    }
                )

    persistent = [
        row
        for row in candidates
        if row["classification"]
        == "PERSISTENT"
    ]

    persistent.sort(
        key=lambda row: (
            row["ci_low"],
            row["overall_rate"],
            row["blocks"],
        ),
        reverse=True,
    )

    print(
        f"PERSISTENT CANDIDATES: "
        f"{len(persistent)}",
        flush=True,
    )

    for row in persistent[:30]:
        blocks_text = ", ".join(
            (
                f"B{block}:"
                f"{rate:.1f}%"
                f"/N{sample}"
            )
            for (
                block,
                sample,
                _,
                rate,
            ) in row["results"]
        )

        print(
            f"PERSISTENT | "
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON="
            f"{row['horizon']} | "
            f"OVERALL="
            f"{row['overall_rate']:.2f}% | "
            f"95CI="
            f"{row['ci_low']:.2f}-"
            f"{row['ci_high']:.2f}% | "
            f"STRONG_BLOCKS="
            f"{row['strong_blocks']}/"
            f"{row['blocks']} | "
            f"SPREAD="
            f"{row['spread']:.2f}pp | "
            f"{blocks_text}",
            flush=True,
        )

    sensitive = [
        row
        for row in candidates
        if row["classification"]
        == "REGIME_SENSITIVE"
    ]

    sensitive.sort(
        key=lambda row:
        row["spread"],
        reverse=True,
    )

    section(
        "R4.4 MOST REGIME-SENSITIVE PATTERNS"
    )

    print(
        f"REGIME-SENSITIVE CANDIDATES: "
        f"{len(sensitive)}",
        flush=True,
    )

    for row in sensitive[:30]:
        blocks_text = ", ".join(
            (
                f"B{block}:"
                f"{rate:.1f}%"
                f"/N{sample}"
            )
            for (
                block,
                sample,
                _,
                rate,
            ) in row["results"]
        )

        print(
            f"REGIME_SENSITIVE | "
            f"{row['symbol']} | "
            f"{row['direction']} | "
            f"HORIZON="
            f"{row['horizon']} | "
            f"SPREAD="
            f"{row['spread']:.2f}pp | "
            f"{blocks_text}",
            flush=True,
        )

    return candidates


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
            rows = load_completed_rows(cur)

            blocks = build_time_blocks(
                rows
            )

            regime_results = (
                block_direction_analysis(
                    rows,
                    blocks,
                )
            )

            regime_transition_summary(
                regime_results
            )

            symbol_regime_analysis(
                rows,
                blocks,
            )

            persistent_patterns(
                rows,
                blocks,
            )

        section(
            "R4.4 REGIME VALIDATION COMPLETE"
        )

        print(
            "STATUS: R4.4 REGIME "
            "VALIDATION PASS",
            flush=True,
        )

        print(
            "NOTE: RESULTS ARE RESEARCH "
            "HYPOTHESES ONLY.",
            flush=True,
        )

        print(
            "REGIME ANALYSIS DOES NOT "
            "CREATE A PRODUCTION RULE.",
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
