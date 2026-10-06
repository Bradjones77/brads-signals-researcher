#!/usr/bin/env python3
"""
Brad's Signals Researcher
R5.3 - Leakage-Free Walk-Forward Feature Validation

Purpose:
Test whether decision-time technical feature rules repeat across multiple
chronological unseen periods.

Method:
- Stored technical_features only.
- Outcomes are labels only.
- Five chronological blocks based on unique timestamps.
- Same-timestamp LONG/SHORT observations stay in the same block.
- Expanding walk-forward:
    B1 -> B2
    B1+B2 -> B3
    B1+B2+B3 -> B4
    B1+B2+B3+B4 -> B5
- Numeric thresholds/categories are learned on training data only, then frozen.
- Same-direction test-block baseline is used for lift.
- Strict repeatability requires validated + positive lift in at least 2 eligible
  folds, with no eligible fold failing that condition.

Safety:
- PostgreSQL READ ONLY
- No database writes
- No Telegram
- No trades
- No production changes
- No AI calls
"""

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone

import psycopg2


VERSION = "R5.3-LEAKAGE-FREE-WALK-FORWARD-FEATURE-VALIDATION"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False
AI_CALLS_ENABLED = False

BLOCK_COUNT = 5
MIN_TRAIN_SAMPLE = 50
MIN_TEST_SAMPLE = 20
MIN_DISCOVERY_RATE = 0.55

HORIZONS = {
    "5m": "direction_correct_5m",
    "30m": "direction_correct_30m",
    "1h": "direction_correct_1h",
    "4h": "direction_correct_4h",
    "12h": "direction_correct_12h",
    "24h": "direction_correct_24h",
}

TIMEFRAMES = ("5m", "15m", "30m", "1h", "4h", "1d")

NUMERIC_FEATURES = (
    "rsi",
    "macd_hist",
    "macd_acceleration",
    "momentum_3",
    "momentum_6",
    "momentum_acceleration",
    "trend_strength",
    "atr_pct",
    "support_distance",
    "resistance_distance",
    "volume_ratio",
    "volume_acceleration",
)

CATEGORICAL_FEATURES = (
    "trend",
    "volatility_regime",
    "bull_breakout",
    "bear_breakout",
    "breakout_volume_confirmed",
)


def banner(text):
    print()
    print("=" * 104)
    print(text)
    print("=" * 104)


def safe_json(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def quantile(sorted_values, q):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def wilson(correct, total, z=1.96):
    if total <= 0:
        return (0.0, 0.0)
    p = correct / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    margin = (
        z
        * math.sqrt(
            p * (1.0 - p) / total
            + z * z / (4.0 * total * total)
        )
        / denom
    )
    return center - margin, center + margin


def rate(rows, label_field):
    labels = [bool(r[label_field]) for r in rows if r[label_field] is not None]
    if not labels:
        return None, 0, 0
    correct = sum(labels)
    return correct / len(labels), len(labels), correct


def fetch_rows(cur):
    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,
            o.technical_features,
            x.direction_correct_5m,
            x.direction_correct_30m,
            x.direction_correct_1h,
            x.direction_correct_4h,
            x.direction_correct_12h,
            x.direction_correct_24h
        FROM public.signals2_opportunities o
        JOIN public.signals2_outcomes x
          ON x.opportunity_id = o.opportunity_id
        WHERE o.outcome_status = 'COMPLETE'
          AND o.created_at IS NOT NULL
          AND o.technical_features IS NOT NULL
        ORDER BY o.created_at ASC, o.symbol ASC, o.direction ASC
        """
    )
    columns = [d[0] for d in cur.description]
    rows = []
    for values in cur.fetchall():
        row = dict(zip(columns, values))
        row["technical_features"] = safe_json(row["technical_features"])
        rows.append(row)
    return rows


def make_blocks(rows):
    timestamps = sorted({r["created_at"] for r in rows})
    if len(timestamps) < BLOCK_COUNT:
        raise RuntimeError("Not enough unique timestamps for walk-forward blocks")

    timestamp_blocks = []
    n = len(timestamps)

    for i in range(BLOCK_COUNT):
        start = (i * n) // BLOCK_COUNT
        end = ((i + 1) * n) // BLOCK_COUNT
        timestamp_blocks.append(set(timestamps[start:end]))

    blocks = []
    for ts_set in timestamp_blocks:
        blocks.append([r for r in rows if r["created_at"] in ts_set])

    return blocks, timestamp_blocks


def baseline_for(rows, direction, label_field):
    subset = [r for r in rows if r["direction"] == direction]
    return rate(subset, label_field)


def discover_numeric_rules(train):
    rules = []

    for direction in ("LONG", "SHORT"):
        drows = [r for r in train if r["direction"] == direction]

        for tf in TIMEFRAMES:
            for feature in NUMERIC_FEATURES:
                key = f"{tf}_{feature}"
                values = []

                for row in drows:
                    x = numeric(row["technical_features"].get(key))
                    if x is not None:
                        values.append(x)

                if len(values) < MIN_TRAIN_SAMPLE * 2:
                    continue

                sv = sorted(values)
                q25 = quantile(sv, 0.25)
                q75 = quantile(sv, 0.75)

                conditions = (
                    ("LOW", q25),
                    ("HIGH", q75),
                )

                for horizon, label_field in HORIZONS.items():
                    for side, threshold in conditions:
                        matched = []
                        for row in drows:
                            x = numeric(row["technical_features"].get(key))
                            if x is None:
                                continue
                            if side == "LOW" and x <= threshold:
                                matched.append(row)
                            elif side == "HIGH" and x >= threshold:
                                matched.append(row)

                        r, sample_n, correct = rate(matched, label_field)
                        if r is None or sample_n < MIN_TRAIN_SAMPLE:
                            continue

                        if r >= MIN_DISCOVERY_RATE:
                            rules.append({
                                "kind": "NUMERIC",
                                "direction": direction,
                                "feature": key,
                                "condition": side,
                                "threshold": threshold,
                                "horizon": horizon,
                                "label_field": label_field,
                                "train_rate": r,
                                "train_n": sample_n,
                                "train_correct": correct,
                            })

    return rules


def discover_categorical_rules(train):
    rules = []

    for direction in ("LONG", "SHORT"):
        drows = [r for r in train if r["direction"] == direction]

        for tf in TIMEFRAMES:
            for feature in CATEGORICAL_FEATURES:
                key = f"{tf}_{feature}"
                groups = defaultdict(list)

                for row in drows:
                    value = row["technical_features"].get(key)
                    if value is not None:
                        groups[str(value)].append(row)

                for horizon, label_field in HORIZONS.items():
                    for value, matched in groups.items():
                        r, sample_n, correct = rate(matched, label_field)
                        if r is None or sample_n < MIN_TRAIN_SAMPLE:
                            continue

                        if r >= MIN_DISCOVERY_RATE:
                            rules.append({
                                "kind": "CATEGORICAL",
                                "direction": direction,
                                "feature": key,
                                "condition": value,
                                "threshold": None,
                                "horizon": horizon,
                                "label_field": label_field,
                                "train_rate": r,
                                "train_n": sample_n,
                                "train_correct": correct,
                            })

    return rules


def match_rule(row, rule):
    if row["direction"] != rule["direction"]:
        return False

    value = row["technical_features"].get(rule["feature"])

    if rule["kind"] == "CATEGORICAL":
        return value is not None and str(value) == rule["condition"]

    x = numeric(value)
    if x is None:
        return False

    if rule["condition"] == "LOW":
        return x <= rule["threshold"]
    if rule["condition"] == "HIGH":
        return x >= rule["threshold"]

    return False


def validate_rule(rule, test):
    matched = [r for r in test if match_rule(r, rule)]
    test_rate, test_n, test_correct = rate(matched, rule["label_field"])
    base_rate, base_n, _ = baseline_for(
        test, rule["direction"], rule["label_field"]
    )

    result = dict(rule)
    result["test_rate"] = test_rate
    result["test_n"] = test_n
    result["test_correct"] = test_correct
    result["baseline_rate"] = base_rate
    result["baseline_n"] = base_n

    if test_rate is None or test_n < MIN_TEST_SAMPLE:
        result["status"] = "INSUFFICIENT_TEST"
        result["lift"] = None
        result["ci"] = None
        return result

    result["lift"] = (
        test_rate - base_rate if base_rate is not None else None
    )
    result["ci"] = wilson(test_correct, test_n)

    if test_rate >= 0.55:
        result["status"] = "VALIDATED"
    elif test_rate < 0.50:
        result["status"] = "FAILED_OR_REVERSED"
    else:
        result["status"] = "WEAKENED"

    return result


def rule_identity(rule):
    # Numeric thresholds intentionally excluded: they are relearned on each
    # training window. This tracks the repeatability of the feature-side idea.
    return (
        rule["kind"],
        rule["direction"],
        rule["feature"],
        rule["condition"],
        rule["horizon"],
    )


def rule_text(r):
    if r["kind"] == "NUMERIC":
        op = "<=" if r["condition"] == "LOW" else ">="
        condition = f"{r['feature']} {op} {r['threshold']:.6g}"
    else:
        condition = f"{r['feature']} == {r['condition']}"

    return (
        f"{r['direction']} {r['horizon']} | {condition} | "
        f"TRAIN={r['train_rate']*100:.2f}% N={r['train_n']}"
    )


def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print(f"RESEARCH VERSION: {VERSION}")
    print(f"UTC START: {datetime.now(timezone.utc).isoformat()}")
    print(f"DATABASE WRITES: {DATABASE_WRITES_ENABLED}")
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING_ENABLED}")
    print(f"TRADE EXECUTION: {TRADE_EXECUTION_ENABLED}")
    print(f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION_ENABLED}")
    print(f"AI CALLS: {AI_CALLS_ENABLED}")

    if any((
        DATABASE_WRITES_ENABLED,
        TELEGRAM_SENDING_ENABLED,
        TRADE_EXECUTION_ENABLED,
        PRODUCTION_MODIFICATION_ENABLED,
        AI_CALLS_ENABLED,
    )):
        raise RuntimeError("Safety configuration invalid")

    print("SAFETY CHECK: PASS")

    database_url = os.getenv("SIGNALS2_DATABASE_URL")
    if not database_url:
        raise RuntimeError("SIGNALS2_DATABASE_URL is not configured")

    conn = None

    try:
        conn = psycopg2.connect(database_url)
        conn.set_session(readonly=True, autocommit=False)
        cur = conn.cursor()

        print("DATABASE CONNECTION: READY")
        print("DATABASE SESSION: READ ONLY")

        rows = fetch_rows(cur)
        blocks, timestamp_blocks = make_blocks(rows)

        banner("R5.3 METHODOLOGY")
        print("FEATURE SOURCE: STORED DECISION-TIME technical_features ONLY")
        print("OUTCOMES USED TO CONSTRUCT FEATURES/RULE VALUES: NO")
        print("OUTCOMES USED AS LABELS AFTER RULE CONSTRUCTION: YES")
        print("WALK-FORWARD: EXPANDING TRAIN -> NEXT UNSEEN BLOCK")
        print("BLOCKS: 5 CHRONOLOGICAL BLOCKS BY UNIQUE TIMESTAMP")
        print("PAIRED LONG/SHORT AT SAME TIMESTAMP: KEPT IN SAME BLOCK")
        print(f"MIN TRAIN SAMPLE: {MIN_TRAIN_SAMPLE}")
        print(f"MIN TEST SAMPLE: {MIN_TEST_SAMPLE}")
        print(f"DISCOVERY EDGE THRESHOLD: {MIN_DISCOVERY_RATE*100:.0f}%")
        print("NUMERIC THRESHOLDS: LEARNED ON EACH TRAIN WINDOW ONLY")
        print("PRODUCTION PROMOTION: NONE")

        banner("R5.3 DATASET")
        print(f"TOTAL COMPLETED FEATURE-BEARING OBSERVATIONS: {len(rows)}")
        print(f"UNIQUE TIMESTAMPS: {sum(len(x) for x in timestamp_blocks)}")

        for i, block in enumerate(blocks, start=1):
            timestamps = sorted(timestamp_blocks[i - 1])
            print(
                f"B{i}: OBS={len(block)} | TIMESTAMPS={len(timestamps)} | "
                f"START={timestamps[0]} | END={timestamps[-1]}"
            )

        all_results = []
        identity_history = defaultdict(list)

        for fold in range(BLOCK_COUNT - 1):
            train = []
            for i in range(fold + 1):
                train.extend(blocks[i])

            test = blocks[fold + 1]

            numeric_rules = discover_numeric_rules(train)
            categorical_rules = discover_categorical_rules(train)
            rules = numeric_rules + categorical_rules

            results = []
            for rule in rules:
                result = validate_rule(rule, test)
                result["fold"] = fold + 1
                result["train_blocks"] = f"B1-B{fold + 1}"
                result["test_block"] = f"B{fold + 2}"
                results.append(result)
                identity_history[rule_identity(result)].append(result)

            all_results.extend(results)

            counts = defaultdict(int)
            eligible = []
            positive = []
            validated_positive = []

            for r in results:
                counts[r["status"]] += 1
                if r["test_n"] >= MIN_TEST_SAMPLE:
                    eligible.append(r)
                    if r["lift"] is not None and r["lift"] > 0:
                        positive.append(r)
                    if (
                        r["status"] == "VALIDATED"
                        and r["lift"] is not None
                        and r["lift"] > 0
                    ):
                        validated_positive.append(r)

            banner(
                f"R5.3 FOLD {fold + 1}: B1-B{fold + 1} -> B{fold + 2}"
            )
            print(f"TRAIN OBSERVATIONS: {len(train)}")
            print(f"TEST OBSERVATIONS: {len(test)}")
            print(f"NUMERIC CANDIDATES: {len(numeric_rules)}")
            print(f"CATEGORICAL CANDIDATES: {len(categorical_rules)}")
            print(f"TOTAL CANDIDATES: {len(results)}")
            print(f"VALIDATED: {counts['VALIDATED']}")
            print(f"WEAKENED: {counts['WEAKENED']}")
            print(f"FAILED OR REVERSED: {counts['FAILED_OR_REVERSED']}")
            print(f"INSUFFICIENT TEST: {counts['INSUFFICIENT_TEST']}")
            print(f"ELIGIBLE TEST RULES: {len(eligible)}")
            print(
                f"POSITIVE LIFT VS SAME-DIRECTION TEST BASELINE: "
                f"{len(positive)}/{len(eligible)}"
            )
            print(
                f"VALIDATED + POSITIVE LIFT: "
                f"{len(validated_positive)}/{len(eligible)}"
            )

            ranked = [
                r for r in eligible
                if r["lift"] is not None
            ]
            ranked.sort(
                key=lambda r: (
                    r["status"] == "VALIDATED",
                    r["lift"],
                    r["test_n"],
                ),
                reverse=True,
            )

            print("--- TOP FOLD RESULTS ---")
            for r in ranked[:15]:
                ci_low, ci_high = r["ci"]
                print(
                    f"{rule_text(r)} | TEST={r['test_rate']*100:.2f}% "
                    f"N={r['test_n']} CI=[{ci_low*100:.2f}%,"
                    f"{ci_high*100:.2f}%] | "
                    f"BASE={r['baseline_rate']*100:.2f}% "
                    f"N={r['baseline_n']} | "
                    f"LIFT={r['lift']*100:+.2f}pp | {r['status']}"
                )

        eligible_all = [
            r for r in all_results if r["test_n"] >= MIN_TEST_SAMPLE
        ]
        validated_all = [
            r for r in eligible_all if r["status"] == "VALIDATED"
        ]
        positive_all = [
            r for r in eligible_all
            if r["lift"] is not None and r["lift"] > 0
        ]
        validated_positive_all = [
            r for r in eligible_all
            if r["status"] == "VALIDATED"
            and r["lift"] is not None
            and r["lift"] > 0
        ]

        repeatable = []

        for identity, history in identity_history.items():
            eligible_history = [
                r for r in history if r["test_n"] >= MIN_TEST_SAMPLE
            ]

            if len(eligible_history) < 2:
                continue

            good = [
                r for r in eligible_history
                if r["status"] == "VALIDATED"
                and r["lift"] is not None
                and r["lift"] > 0
            ]

            if len(good) == len(eligible_history):
                avg_test = sum(r["test_rate"] for r in good) / len(good)
                avg_lift = sum(r["lift"] for r in good) / len(good)
                total_test_n = sum(r["test_n"] for r in good)

                repeatable.append({
                    "identity": identity,
                    "history": good,
                    "folds": len(good),
                    "avg_test": avg_test,
                    "avg_lift": avg_lift,
                    "total_test_n": total_test_n,
                })

        repeatable.sort(
            key=lambda x: (
                x["folds"],
                x["avg_lift"],
                x["total_test_n"],
            ),
            reverse=True,
        )

        banner("R5.3 CROSS-FOLD SUMMARY")
        print(f"TOTAL CANDIDATE TESTS: {len(all_results)}")
        print(f"ELIGIBLE CANDIDATE TESTS: {len(eligible_all)}")
        print(f"VALIDATED TESTS: {len(validated_all)}")
        print(f"POSITIVE-LIFT TESTS: {len(positive_all)}")
        print(
            f"VALIDATED + POSITIVE-LIFT TESTS: "
            f"{len(validated_positive_all)}"
        )
        print(
            "STRICT REPEATABLE FEATURE-SIDE SURVIVORS "
            "(>=2 eligible folds, validated + positive lift in every "
            f"eligible fold): {len(repeatable)}"
        )

        banner("R5.3 STRICT REPEATABLE SURVIVORS")
        if not repeatable:
            print("NONE")
        else:
            for item in repeatable[:50]:
                kind, direction, feature, condition, horizon = item["identity"]
                if kind == "NUMERIC":
                    side_text = "LOWER-QUARTILE SIDE" if condition == "LOW" else "UPPER-QUARTILE SIDE"
                    rule_name = f"{direction} {horizon} | {feature} | {side_text}"
                else:
                    rule_name = f"{direction} {horizon} | {feature} == {condition}"

                print(
                    f"{rule_name} | FOLDS={item['folds']} | "
                    f"AVG_TEST={item['avg_test']*100:.2f}% | "
                    f"AVG_LIFT={item['avg_lift']*100:+.2f}pp | "
                    f"TOTAL_TEST_N={item['total_test_n']}"
                )

                for r in item["history"]:
                    threshold_text = ""
                    if r["kind"] == "NUMERIC":
                        op = "<=" if r["condition"] == "LOW" else ">="
                        threshold_text = f" threshold {op} {r['threshold']:.6g}"
                    print(
                        f"  FOLD {r['fold']} {r['train_blocks']}->{r['test_block']} | "
                        f"TEST={r['test_rate']*100:.2f}% N={r['test_n']} | "
                        f"BASE={r['baseline_rate']*100:.2f}% | "
                        f"LIFT={r['lift']*100:+.2f}pp{threshold_text}"
                    )

        banner("R5.3 FINAL STATUS")
        print("STATUS: R5.3 LEAKAGE-FREE WALK-FORWARD FEATURE VALIDATION PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES")
        print(
            "NOTE: REPEATABLE SURVIVORS ARE STILL RESEARCH CANDIDATES. "
            "NO FEATURE IS PROMOTED TO PRODUCTION BY THIS TEST."
        )

        conn.rollback()
        cur.close()

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        banner("R5.3 FAILURE")
        print("STATUS: R5.3 FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise

    finally:
        if conn is not None:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
