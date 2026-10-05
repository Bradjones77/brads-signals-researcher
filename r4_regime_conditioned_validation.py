import os
import math
from collections import defaultdict
from datetime import datetime

import psycopg2


# ============================================================
# BRAD'S SIGNALS RESEARCHER
# R4.5 - REGIME-CONDITIONED VALIDATION
# ============================================================

VERSION = "R4.5-REGIME-CONDITIONED-VALIDATION"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False

NUMBER_OF_TIME_BLOCKS = 5

MIN_DISCOVERY_SAMPLE = 30
MIN_VALIDATION_SAMPLE = 20

STRONG_RATE = 55.0
VERY_STRONG_RATE = 60.0

HORIZONS = {
    "5m": "direction_correct_5m",
    "30m": "direction_correct_30m",
    "1h": "direction_correct_1h",
    "4h": "direction_correct_4h",
    "12h": "direction_correct_12h",
    "24h": "direction_correct_24h",
}


# ============================================================
# HELPERS
# ============================================================

def banner(title):
    print("")
    print("=" * 78)
    print(title)
    print("=" * 78)


def safe_rate(correct, total):
    if total <= 0:
        return 0.0
    return (correct / total) * 100.0


def wilson_interval(correct, total, z=1.96):
    if total <= 0:
        return 0.0, 0.0

    p = correct / total
    denominator = 1.0 + (z * z / total)

    centre = (
        p
        + (z * z / (2.0 * total))
    ) / denominator

    margin = (
        z
        * math.sqrt(
            (p * (1.0 - p) / total)
            + (z * z / (4.0 * total * total))
        )
        / denominator
    )

    low = max(0.0, centre - margin) * 100.0
    high = min(1.0, centre + margin) * 100.0

    return low, high


def bool_correct(value):
    return value is True


def classify_regime(long_rate, short_rate):
    difference = long_rate - short_rate

    if difference >= 15.0:
        return "LONG_DOMINANT"

    if difference <= -15.0:
        return "SHORT_DOMINANT"

    return "MIXED_OR_NEUTRAL"


def regime_matches_direction(regime, direction):
    if direction == "LONG" and regime == "LONG_DOMINANT":
        return True

    if direction == "SHORT" and regime == "SHORT_DOMINANT":
        return True

    return False


# ============================================================
# DATABASE
# ============================================================

def connect_database():
    database_url = os.getenv("SIGNALS2_DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "SIGNALS2_DATABASE_URL is not configured."
        )

    connection = psycopg2.connect(database_url)

    connection.set_session(
        readonly=True,
        autocommit=False,
    )

    return connection


def load_completed_rows(connection):
    query = """
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
            ON x.opportunity_id = o.opportunity_id
        WHERE x.outcome_complete = TRUE
          AND o.direction IN ('LONG', 'SHORT')
        ORDER BY
            o.created_at ASC,
            o.opportunity_id ASC
    """

    with connection.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()

    parsed = []

    for row in rows:
        parsed.append(
            {
                "opportunity_id": row[0],
                "created_at": row[1],
                "symbol": row[2],
                "direction": row[3],
                "5m": row[4],
                "30m": row[5],
                "1h": row[6],
                "4h": row[7],
                "12h": row[8],
                "24h": row[9],
            }
        )

    return parsed


# ============================================================
# CHRONOLOGICAL BLOCKS
# ============================================================

def build_time_blocks(rows):
    timestamps = sorted(
        {
            row["created_at"]
            for row in rows
        }
    )

    if not timestamps:
        return []

    total_timestamps = len(timestamps)

    timestamp_to_block = {}

    for index, timestamp in enumerate(timestamps):
        block_index = min(
            int(
                index
                * NUMBER_OF_TIME_BLOCKS
                / total_timestamps
            ),
            NUMBER_OF_TIME_BLOCKS - 1,
        )

        timestamp_to_block[timestamp] = block_index + 1

    blocks = defaultdict(list)

    for row in rows:
        block_number = timestamp_to_block[
            row["created_at"]
        ]

        row_copy = dict(row)
        row_copy["block"] = block_number

        blocks[block_number].append(row_copy)

    return blocks


# ============================================================
# REGIME MAP
# ============================================================

def build_regime_map(blocks):
    regime_map = {}

    for block_number in sorted(blocks):
        block_rows = blocks[block_number]

        for horizon in HORIZONS:
            direction_stats = {
                "LONG": [0, 0],
                "SHORT": [0, 0],
            }

            for row in block_rows:
                direction = row["direction"]
                value = row[horizon]

                if value is None:
                    continue

                direction_stats[direction][1] += 1

                if bool_correct(value):
                    direction_stats[direction][0] += 1

            long_correct, long_total = (
                direction_stats["LONG"]
            )

            short_correct, short_total = (
                direction_stats["SHORT"]
            )

            if long_total == 0 or short_total == 0:
                regime = "INSUFFICIENT_DATA"
                long_rate = 0.0
                short_rate = 0.0
            else:
                long_rate = safe_rate(
                    long_correct,
                    long_total,
                )

                short_rate = safe_rate(
                    short_correct,
                    short_total,
                )

                regime = classify_regime(
                    long_rate,
                    short_rate,
                )

            regime_map[
                (block_number, horizon)
            ] = {
                "regime": regime,
                "long_rate": long_rate,
                "short_rate": short_rate,
                "long_n": long_total,
                "short_n": short_total,
            }

    return regime_map


# ============================================================
# DATASET SUMMARY
# ============================================================

def dataset_summary(rows, blocks, regime_map):
    banner("R4.5 DATASET SUMMARY")

    print(
        f"COMPLETED OBSERVATIONS: {len(rows)}"
    )

    if rows:
        print(
            f"OLDEST: {rows[0]['created_at']}"
        )

        print(
            f"NEWEST: {rows[-1]['created_at']}"
        )

    print(
        f"TIME BLOCKS: {len(blocks)}"
    )

    for block_number in sorted(blocks):
        block_rows = blocks[block_number]

        start = min(
            row["created_at"]
            for row in block_rows
        )

        end = max(
            row["created_at"]
            for row in block_rows
        )

        print(
            f"BLOCK={block_number} | "
            f"START={start} | "
            f"END={end} | "
            f"OBSERVATIONS={len(block_rows)}"
        )

    banner("R4.5 REGIME MAP")

    for horizon in HORIZONS:
        sequence = []

        for block_number in sorted(blocks):
            info = regime_map[
                (block_number, horizon)
            ]

            sequence.append(
                f"B{block_number}:"
                f"{info['regime']}"
            )

        print(
            f"HORIZON={horizon} | "
            + " -> ".join(sequence)
        )


# ============================================================
# REGIME-CONDITIONED PATTERN TEST
# ============================================================

def build_pattern_records(
    rows,
    regime_map,
):
    records = defaultdict(list)

    for row in rows:
        block_number = row["block"]
        symbol = row["symbol"]
        direction = row["direction"]

        for horizon in HORIZONS:
            value = row[horizon]

            if value is None:
                continue

            regime_info = regime_map.get(
                (block_number, horizon)
            )

            if not regime_info:
                continue

            regime = regime_info["regime"]

            key = (
                symbol,
                direction,
                horizon,
            )

            records[key].append(
                {
                    "created_at": row[
                        "created_at"
                    ],
                    "block": block_number,
                    "regime": regime,
                    "correct": bool_correct(
                        value
                    ),
                }
            )

    return records


def chronological_split(records):
    ordered = sorted(
        records,
        key=lambda item: item[
            "created_at"
        ],
    )

    unique_timestamps = sorted(
        {
            item["created_at"]
            for item in ordered
        }
    )

    if len(unique_timestamps) < 2:
        return [], []

    split_index = int(
        len(unique_timestamps) * 0.70
    )

    split_index = max(
        1,
        min(
            split_index,
            len(unique_timestamps) - 1,
        ),
    )

    split_timestamp = unique_timestamps[
        split_index
    ]

    discovery = [
        item
        for item in ordered
        if item["created_at"]
        < split_timestamp
    ]

    validation = [
        item
        for item in ordered
        if item["created_at"]
        >= split_timestamp
    ]

    return discovery, validation


def calculate_stats(records):
    total = len(records)

    correct = sum(
        1
        for item in records
        if item["correct"]
    )

    rate = safe_rate(
        correct,
        total,
    )

    low, high = wilson_interval(
        correct,
        total,
    )

    return {
        "n": total,
        "correct": correct,
        "rate": rate,
        "ci_low": low,
        "ci_high": high,
    }


def filter_matching_regime(
    records,
    direction,
):
    return [
        item
        for item in records
        if regime_matches_direction(
            item["regime"],
            direction,
        )
    ]


def filter_nonmatching_regime(
    records,
    direction,
):
    return [
        item
        for item in records
        if (
            item["regime"]
            != "INSUFFICIENT_DATA"
            and not regime_matches_direction(
                item["regime"],
                direction,
            )
        )
    ]


# ============================================================
# VALIDATION ENGINE
# ============================================================

def regime_conditioned_validation(
    pattern_records,
):
    banner(
        "R4.5 REGIME-CONDITIONED HELD-OUT VALIDATION"
    )

    results = []

    for key, records in sorted(
        pattern_records.items()
    ):
        symbol, direction, horizon = key

        discovery, validation = (
            chronological_split(records)
        )

        discovery_matching = (
            filter_matching_regime(
                discovery,
                direction,
            )
        )

        validation_matching = (
            filter_matching_regime(
                validation,
                direction,
            )
        )

        discovery_nonmatching = (
            filter_nonmatching_regime(
                discovery,
                direction,
            )
        )

        validation_nonmatching = (
            filter_nonmatching_regime(
                validation,
                direction,
            )
        )

        if (
            len(discovery_matching)
            < MIN_DISCOVERY_SAMPLE
        ):
            continue

        discovery_stats = calculate_stats(
            discovery_matching
        )

        if (
            discovery_stats["rate"]
            < STRONG_RATE
        ):
            continue

        if (
            len(validation_matching)
            < MIN_VALIDATION_SAMPLE
        ):
            status = (
                "INSUFFICIENT_VALIDATION"
            )

            validation_stats = (
                calculate_stats(
                    validation_matching
                )
            )

        else:
            validation_stats = (
                calculate_stats(
                    validation_matching
                )
            )

            if (
                validation_stats["rate"]
                >= STRONG_RATE
            ):
                status = "VALIDATED"

            elif (
                validation_stats["rate"]
                < 50.0
            ):
                status = (
                    "FAILED_OR_REVERSED"
                )

            else:
                status = "WEAKENED"

        discovery_nonmatching_stats = (
            calculate_stats(
                discovery_nonmatching
            )
        )

        validation_nonmatching_stats = (
            calculate_stats(
                validation_nonmatching
            )
        )

        result = {
            "symbol": symbol,
            "direction": direction,
            "horizon": horizon,
            "status": status,
            "discovery": discovery_stats,
            "validation": validation_stats,
            "discovery_nonmatching":
                discovery_nonmatching_stats,
            "validation_nonmatching":
                validation_nonmatching_stats,
        }

        results.append(result)

    return results


# ============================================================
# REPORTING
# ============================================================

def print_validation_results(results):
    banner(
        "R4.5 VALIDATION RESULTS"
    )

    validated = [
        result
        for result in results
        if result["status"] == "VALIDATED"
    ]

    weakened = [
        result
        for result in results
        if result["status"] == "WEAKENED"
    ]

    failed = [
        result
        for result in results
        if result["status"]
        == "FAILED_OR_REVERSED"
    ]

    insufficient = [
        result
        for result in results
        if result["status"]
        == "INSUFFICIENT_VALIDATION"
    ]

    print(
        f"TOTAL REGIME-CONDITIONED "
        f"CANDIDATES: {len(results)}"
    )

    print(
        f"VALIDATED: {len(validated)}"
    )

    print(
        f"WEAKENED: {len(weakened)}"
    )

    print(
        f"FAILED OR REVERSED: "
        f"{len(failed)}"
    )

    print(
        f"INSUFFICIENT VALIDATION: "
        f"{len(insufficient)}"
    )

    banner(
        "TOP VALIDATED "
        "REGIME-CONDITIONED PATTERNS"
    )

    ranked = sorted(
        validated,
        key=lambda item: (
            item["validation"]["ci_low"],
            item["validation"]["rate"],
            item["validation"]["n"],
        ),
        reverse=True,
    )

    for index, result in enumerate(
        ranked[:30],
        start=1,
    ):
        discovery = result["discovery"]
        validation = result["validation"]
        nonmatching = result[
            "validation_nonmatching"
        ]

        print(
            f"{index}. "
            f"{result['symbol']} | "
            f"{result['direction']} | "
            f"HORIZON={result['horizon']} | "
            f"DISCOVERY="
            f"{discovery['rate']:.2f}%/"
            f"N{discovery['n']} | "
            f"VALIDATION="
            f"{validation['rate']:.2f}%/"
            f"N{validation['n']} | "
            f"CI_LOW="
            f"{validation['ci_low']:.2f}% | "
            f"NONMATCHING="
            f"{nonmatching['rate']:.2f}%/"
            f"N{nonmatching['n']}"
        )

    banner(
        "FAILED / REVERSED "
        "REGIME-CONDITIONED PATTERNS"
    )

    failed_ranked = sorted(
        failed,
        key=lambda item: (
            item["validation"]["rate"],
            -item["validation"]["n"],
        ),
    )

    for index, result in enumerate(
        failed_ranked[:30],
        start=1,
    ):
        discovery = result["discovery"]
        validation = result["validation"]

        print(
            f"{index}. "
            f"{result['symbol']} | "
            f"{result['direction']} | "
            f"HORIZON={result['horizon']} | "
            f"DISCOVERY="
            f"{discovery['rate']:.2f}%/"
            f"N{discovery['n']} | "
            f"VALIDATION="
            f"{validation['rate']:.2f}%/"
            f"N{validation['n']}"
        )

    return {
        "total": len(results),
        "validated": len(validated),
        "weakened": len(weakened),
        "failed": len(failed),
        "insufficient": len(insufficient),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    connection = None

    banner(
        "BRADS-SIGNALS-RESEARCHER"
    )

    print(
        f"VERSION: {VERSION}"
    )

    print(
        f"DATABASE WRITES: "
        f"{DATABASE_WRITES_ENABLED}"
    )

    print(
        f"TELEGRAM SENDING: "
        f"{TELEGRAM_SENDING_ENABLED}"
    )

    print(
        f"TRADE EXECUTION: "
        f"{TRADE_EXECUTION_ENABLED}"
    )

    print(
        f"PRODUCTION MODIFICATION: "
        f"{PRODUCTION_MODIFICATION_ENABLED}"
    )

    if any(
        [
            DATABASE_WRITES_ENABLED,
            TELEGRAM_SENDING_ENABLED,
            TRADE_EXECUTION_ENABLED,
            PRODUCTION_MODIFICATION_ENABLED,
        ]
    ):
        raise RuntimeError(
            "R4.5 SAFETY CHECK FAILED."
        )

    print("SAFETY CHECK: PASS")

    try:
        connection = connect_database()

        print(
            "DATABASE CONNECTION: READY"
        )

        print(
            "DATABASE SESSION: READ ONLY"
        )

        rows = load_completed_rows(
            connection
        )

        if not rows:
            raise RuntimeError(
                "No completed observations found."
            )

        blocks = build_time_blocks(
            rows
        )

        rows_with_blocks = []

        for block_number in sorted(blocks):
            rows_with_blocks.extend(
                blocks[block_number]
            )

        regime_map = build_regime_map(
            blocks
        )

        dataset_summary(
            rows_with_blocks,
            blocks,
            regime_map,
        )

        pattern_records = (
            build_pattern_records(
                rows_with_blocks,
                regime_map,
            )
        )

        results = (
            regime_conditioned_validation(
                pattern_records
            )
        )

        summary = print_validation_results(
            results
        )

        banner("R4.5 RESEARCH SUMMARY")

        print(
            f"CANDIDATES TESTED: "
            f"{summary['total']}"
        )

        print(
            f"VALIDATED: "
            f"{summary['validated']}"
        )

        print(
            f"WEAKENED: "
            f"{summary['weakened']}"
        )

        print(
            f"FAILED OR REVERSED: "
            f"{summary['failed']}"
        )

        print(
            f"INSUFFICIENT VALIDATION: "
            f"{summary['insufficient']}"
        )

        print(
            "STATUS: R4.5 "
            "REGIME-CONDITIONED "
            "VALIDATION PASS"
        )

        print(
            "NOTE: VALIDATED HISTORICAL "
            "REGIME PATTERNS ARE RESEARCH "
            "HYPOTHESES ONLY."
        )

        print(
            "NO PRODUCTION TRADING RULE "
            "HAS BEEN CREATED."
        )

        print(
            "DATABASE REMAINED READ ONLY"
        )

        print(
            "NO WRITES; NO SENDS; "
            "NO TRADES; "
            "NO PRODUCTION CHANGES"
        )

    except Exception as exc:
        print(
            "STATUS: R4.5 FAILED"
        )

        print(
            f"ERROR TYPE: "
            f"{type(exc).__name__}"
        )

        print(
            f"ERROR: {exc}"
        )

        raise

    finally:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass

            try:
                connection.close()
            except Exception:
                pass

            print(
                "DATABASE CONNECTION: CLOSED"
            )


if __name__ == "__main__":
    main()
