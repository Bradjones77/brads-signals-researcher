import os
import math
from collections import defaultdict

import psycopg2


# ============================================================
# BRAD'S SIGNALS RESEARCHER
# R4.6 - WALK-FORWARD REGIME VALIDATION
# ============================================================

VERSION = "R4.6-WALK-FORWARD-REGIME-VALIDATION"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False

NUMBER_OF_TIME_BLOCKS = 5

MIN_TRAIN_SAMPLE = 30
MIN_TEST_SAMPLE = 15

STRONG_RATE = 55.0
REGIME_THRESHOLD = 15.0

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

    denominator = (
        1.0
        + (z * z / total)
    )

    centre = (
        p
        + (z * z / (2.0 * total))
    ) / denominator

    margin = (
        z
        * math.sqrt(
            (p * (1.0 - p) / total)
            + (
                z * z
                / (4.0 * total * total)
            )
        )
        / denominator
    )

    low = max(
        0.0,
        centre - margin,
    ) * 100.0

    high = min(
        1.0,
        centre + margin,
    ) * 100.0

    return low, high


def bool_correct(value):
    return value is True


def classify_regime(
    long_rate,
    short_rate,
):
    difference = (
        long_rate - short_rate
    )

    if difference >= REGIME_THRESHOLD:
        return "LONG_DOMINANT"

    if difference <= -REGIME_THRESHOLD:
        return "SHORT_DOMINANT"

    return "MIXED_OR_NEUTRAL"


def regime_matches_direction(
    regime,
    direction,
):
    if (
        regime == "LONG_DOMINANT"
        and direction == "LONG"
    ):
        return True

    if (
        regime == "SHORT_DOMINANT"
        and direction == "SHORT"
    ):
        return True

    return False


# ============================================================
# DATABASE
# ============================================================

def connect_database():
    database_url = os.getenv(
        "SIGNALS2_DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "SIGNALS2_DATABASE_URL "
            "is not configured."
        )

    connection = psycopg2.connect(
        database_url
    )

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
# TIME BLOCKS
# ============================================================

def build_time_blocks(rows):
    timestamps = sorted(
        {
            row["created_at"]
            for row in rows
        }
    )

    if not timestamps:
        return {}

    total_timestamps = len(timestamps)

    timestamp_to_block = {}

    for index, timestamp in enumerate(
        timestamps
    ):
        block_index = min(
            int(
                index
                * NUMBER_OF_TIME_BLOCKS
                / total_timestamps
            ),
            NUMBER_OF_TIME_BLOCKS - 1,
        )

        timestamp_to_block[
            timestamp
        ] = block_index + 1

    blocks = defaultdict(list)

    for row in rows:
        block_number = (
            timestamp_to_block[
                row["created_at"]
            ]
        )

        row_copy = dict(row)

        row_copy["block"] = (
            block_number
        )

        blocks[
            block_number
        ].append(row_copy)

    return dict(blocks)


# ============================================================
# REGIME CALCULATION
# ============================================================

def calculate_regime(
    rows,
    horizon,
):
    stats = {
        "LONG": [0, 0],
        "SHORT": [0, 0],
    }

    for row in rows:
        value = row[horizon]

        if value is None:
            continue

        direction = row["direction"]

        stats[direction][1] += 1

        if bool_correct(value):
            stats[direction][0] += 1

    long_correct, long_total = (
        stats["LONG"]
    )

    short_correct, short_total = (
        stats["SHORT"]
    )

    if (
        long_total == 0
        or short_total == 0
    ):
        return {
            "regime": "INSUFFICIENT_DATA",
            "long_rate": 0.0,
            "short_rate": 0.0,
        }

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

    return {
        "regime": regime,
        "long_rate": long_rate,
        "short_rate": short_rate,
    }


# ============================================================
# PATTERN STATISTICS
# ============================================================

def pattern_stats(
    rows,
    symbol,
    direction,
    horizon,
):
    selected = [
        row
        for row in rows
        if row["symbol"] == symbol
        and row["direction"] == direction
        and row[horizon] is not None
    ]

    total = len(selected)

    correct = sum(
        1
        for row in selected
        if bool_correct(
            row[horizon]
        )
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


# ============================================================
# WALK-FORWARD ENGINE
# ============================================================

def run_walk_forward(blocks):
    banner(
        "R4.6 WALK-FORWARD TEST"
    )

    symbols = sorted(
        {
            row["symbol"]
            for block_rows
            in blocks.values()
            for row in block_rows
        }
    )

    all_results = []

    block_numbers = sorted(
        blocks.keys()
    )

    # --------------------------------------------------------
    # Train on all earlier blocks.
    # Test only on the NEXT unseen block.
    #
    # B1 -> test B2
    # B1+B2 -> test B3
    # B1+B2+B3 -> test B4
    # B1+B2+B3+B4 -> test B5
    # --------------------------------------------------------

    for test_block in block_numbers[1:]:
        train_blocks = [
            block
            for block in block_numbers
            if block < test_block
        ]

        train_rows = []

        for block in train_blocks:
            train_rows.extend(
                blocks[block]
            )

        test_rows = blocks[
            test_block
        ]

        banner(
            f"WALK-FORWARD TEST BLOCK "
            f"B{test_block}"
        )

        print(
            "TRAIN BLOCKS: "
            + ", ".join(
                f"B{block}"
                for block in train_blocks
            )
        )

        print(
            f"TRAIN OBSERVATIONS: "
            f"{len(train_rows)}"
        )

        print(
            f"TEST OBSERVATIONS: "
            f"{len(test_rows)}"
        )

        block_results = []

        for horizon in HORIZONS:
            train_regime_info = (
                calculate_regime(
                    train_rows,
                    horizon,
                )
            )

            test_regime_info = (
                calculate_regime(
                    test_rows,
                    horizon,
                )
            )

            train_regime = (
                train_regime_info[
                    "regime"
                ]
            )

            test_regime = (
                test_regime_info[
                    "regime"
                ]
            )

            print(
                f"HORIZON={horizon} | "
                f"TRAIN_REGIME="
                f"{train_regime} | "
                f"TEST_REALIZED_REGIME="
                f"{test_regime}"
            )

            if train_regime not in (
                "LONG_DOMINANT",
                "SHORT_DOMINANT",
            ):
                continue

            expected_direction = (
                "LONG"
                if train_regime
                == "LONG_DOMINANT"
                else "SHORT"
            )

            for symbol in symbols:
                train_stats = (
                    pattern_stats(
                        train_rows,
                        symbol,
                        expected_direction,
                        horizon,
                    )
                )

                if (
                    train_stats["n"]
                    < MIN_TRAIN_SAMPLE
                ):
                    continue

                if (
                    train_stats["rate"]
                    < STRONG_RATE
                ):
                    continue

                test_stats = (
                    pattern_stats(
                        test_rows,
                        symbol,
                        expected_direction,
                        horizon,
                    )
                )

                if (
                    test_stats["n"]
                    < MIN_TEST_SAMPLE
                ):
                    status = (
                        "INSUFFICIENT_TEST"
                    )

                elif (
                    test_stats["rate"]
                    >= STRONG_RATE
                ):
                    status = "VALIDATED"

                elif (
                    test_stats["rate"]
                    < 50.0
                ):
                    status = (
                        "FAILED_OR_REVERSED"
                    )

                else:
                    status = "WEAKENED"

                regime_persisted = (
                    train_regime
                    == test_regime
                )

                result = {
                    "test_block":
                        test_block,
                    "train_blocks":
                        list(train_blocks),
                    "symbol":
                        symbol,
                    "direction":
                        expected_direction,
                    "horizon":
                        horizon,
                    "train_regime":
                        train_regime,
                    "test_regime":
                        test_regime,
                    "regime_persisted":
                        regime_persisted,
                    "train":
                        train_stats,
                    "test":
                        test_stats,
                    "status":
                        status,
                }

                block_results.append(
                    result
                )

                all_results.append(
                    result
                )

        print_block_summary(
            block_results,
            test_block,
        )

    return all_results


# ============================================================
# REPORTING
# ============================================================

def print_block_summary(
    results,
    test_block,
):
    print("")

    print(
        f"B{test_block} "
        f"CANDIDATES: {len(results)}"
    )

    validated = sum(
        1
        for result in results
        if result["status"]
        == "VALIDATED"
    )

    weakened = sum(
        1
        for result in results
        if result["status"]
        == "WEAKENED"
    )

    failed = sum(
        1
        for result in results
        if result["status"]
        == "FAILED_OR_REVERSED"
    )

    insufficient = sum(
        1
        for result in results
        if result["status"]
        == "INSUFFICIENT_TEST"
    )

    print(
        f"B{test_block} VALIDATED: "
        f"{validated}"
    )

    print(
        f"B{test_block} WEAKENED: "
        f"{weakened}"
    )

    print(
        f"B{test_block} "
        f"FAILED/REVERSED: {failed}"
    )

    print(
        f"B{test_block} "
        f"INSUFFICIENT: {insufficient}"
    )


def final_report(results):
    banner(
        "R4.6 WALK-FORWARD SUMMARY"
    )

    validated = [
        result
        for result in results
        if result["status"]
        == "VALIDATED"
    ]

    weakened = [
        result
        for result in results
        if result["status"]
        == "WEAKENED"
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
        == "INSUFFICIENT_TEST"
    ]

    persisted = [
        result
        for result in results
        if result["regime_persisted"]
    ]

    changed = [
        result
        for result in results
        if not result[
            "regime_persisted"
        ]
    ]

    print(
        f"TOTAL CANDIDATE TESTS: "
        f"{len(results)}"
    )

    print(
        f"VALIDATED: "
        f"{len(validated)}"
    )

    print(
        f"WEAKENED: "
        f"{len(weakened)}"
    )

    print(
        f"FAILED OR REVERSED: "
        f"{len(failed)}"
    )

    print(
        f"INSUFFICIENT TEST: "
        f"{len(insufficient)}"
    )

    banner(
        "REGIME PERSISTENCE COMPARISON"
    )

    print(
        f"REGIME PERSISTED TESTS: "
        f"{len(persisted)}"
    )

    print(
        f"REGIME CHANGED TESTS: "
        f"{len(changed)}"
    )

    def group_summary(
        name,
        group,
    ):
        eligible = [
            result
            for result in group
            if result["status"]
            != "INSUFFICIENT_TEST"
        ]

        if not eligible:
            print(
                f"{name}: "
                f"NO ELIGIBLE TESTS"
            )
            return

        group_validated = sum(
            1
            for result in eligible
            if result["status"]
            == "VALIDATED"
        )

        rate = safe_rate(
            group_validated,
            len(eligible),
        )

        print(
            f"{name}: "
            f"ELIGIBLE={len(eligible)} | "
            f"VALIDATED="
            f"{group_validated} | "
            f"VALIDATION_RATE="
            f"{rate:.2f}%"
        )

    group_summary(
        "REGIME_PERSISTED",
        persisted,
    )

    group_summary(
        "REGIME_CHANGED",
        changed,
    )

    banner(
        "TOP WALK-FORWARD SURVIVORS"
    )

    ranked = sorted(
        validated,
        key=lambda result: (
            result["test"]["ci_low"],
            result["test"]["rate"],
            result["test"]["n"],
        ),
        reverse=True,
    )

    for index, result in enumerate(
        ranked[:30],
        start=1,
    ):
        print(
            f"{index}. "
            f"B{result['test_block']} | "
            f"{result['symbol']} | "
            f"{result['direction']} | "
            f"{result['horizon']} | "
            f"TRAIN="
            f"{result['train']['rate']:.2f}%/"
            f"N{result['train']['n']} | "
            f"TEST="
            f"{result['test']['rate']:.2f}%/"
            f"N{result['test']['n']} | "
            f"CI_LOW="
            f"{result['test']['ci_low']:.2f}% | "
            f"TRAIN_REGIME="
            f"{result['train_regime']} | "
            f"TEST_REGIME="
            f"{result['test_regime']}"
        )

    banner(
        "WALK-FORWARD FAILURES / REVERSALS"
    )

    failed_ranked = sorted(
        failed,
        key=lambda result: (
            result["test"]["rate"],
            -result["test"]["n"],
        ),
    )

    for index, result in enumerate(
        failed_ranked[:30],
        start=1,
    ):
        print(
            f"{index}. "
            f"B{result['test_block']} | "
            f"{result['symbol']} | "
            f"{result['direction']} | "
            f"{result['horizon']} | "
            f"TRAIN="
            f"{result['train']['rate']:.2f}%/"
            f"N{result['train']['n']} | "
            f"TEST="
            f"{result['test']['rate']:.2f}%/"
            f"N{result['test']['n']} | "
            f"TRAIN_REGIME="
            f"{result['train_regime']} | "
            f"TEST_REGIME="
            f"{result['test_regime']}"
        )


# ============================================================
# DATASET REPORT
# ============================================================

def print_dataset_summary(
    rows,
    blocks,
):
    banner(
        "R4.6 DATASET SUMMARY"
    )

    print(
        f"COMPLETED OBSERVATIONS: "
        f"{len(rows)}"
    )

    if rows:
        print(
            f"OLDEST: "
            f"{rows[0]['created_at']}"
        )

        print(
            f"NEWEST: "
            f"{rows[-1]['created_at']}"
        )

    print(
        f"TIME BLOCKS: "
        f"{len(blocks)}"
    )

    for block_number in sorted(
        blocks
    ):
        block_rows = (
            blocks[block_number]
        )

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
            f"OBSERVATIONS="
            f"{len(block_rows)}"
        )


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
            "R4.6 SAFETY CHECK FAILED."
        )

    print(
        "SAFETY CHECK: PASS"
    )

    try:
        connection = (
            connect_database()
        )

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
                "No completed "
                "observations found."
            )

        blocks = build_time_blocks(
            rows
        )

        print_dataset_summary(
            rows,
            blocks,
        )

        results = run_walk_forward(
            blocks
        )

        final_report(
            results
        )

        banner(
            "R4.6 RESEARCH STATUS"
        )

        print(
            "STATUS: R4.6 "
            "WALK-FORWARD "
            "REGIME VALIDATION PASS"
        )

        print(
            "NOTE: WALK-FORWARD "
            "RESULTS ARE HISTORICAL "
            "RESEARCH ONLY."
        )

        print(
            "NO PRODUCTION TRADING "
            "RULE HAS BEEN CREATED."
        )

        print(
            "DATABASE REMAINED "
            "READ ONLY"
        )

        print(
            "NO WRITES; NO SENDS; "
            "NO TRADES; "
            "NO PRODUCTION CHANGES"
        )

    except Exception as exc:
        print(
            "STATUS: R4.6 FAILED"
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
                "DATABASE CONNECTION: "
                "CLOSED"
            )


if __name__ == "__main__":
    main()
