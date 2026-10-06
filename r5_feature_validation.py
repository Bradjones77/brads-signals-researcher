#!/usr/bin/env python3
"""
Brad's Signals Researcher
R5.2 - Leakage-Free Feature Validation

Purpose:
Discover simple feature rules on earlier observations, freeze them, then test
them on later unseen observations. Feature rules use only stored decision-time
technical_features. Outcomes are labels only.

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


VERSION = "R5.2-LEAKAGE-FREE-FEATURE-VALIDATION"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False
AI_CALLS_ENABLED = False

DISCOVERY_FRACTION = 0.70
MIN_DISCOVERY_SAMPLE = 50
MIN_VALIDATION_SAMPLE = 20
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
    print("=" * 96)
    print(text)
    print("=" * 96)


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


def chronological_split(rows):
    timestamps = sorted({r["created_at"] for r in rows})
    if len(timestamps) < 2:
        raise RuntimeError("Not enough unique timestamps for chronological split")

    cut_index = int(len(timestamps) * DISCOVERY_FRACTION)
    cut_index = max(1, min(cut_index, len(timestamps) - 1))
    validation_start = timestamps[cut_index]

    discovery = [r for r in rows if r["created_at"] < validation_start]
    validation = [r for r in rows if r["created_at"] >= validation_start]

    return discovery, validation, validation_start, len(timestamps)


def baseline_for(rows, direction, label_field):
    subset = [r for r in rows if r["direction"] == direction]
    return rate(subset, label_field)


def discover_numeric_rules(discovery):
    rules = []

    for direction in ("LONG", "SHORT"):
        drows = [r for r in discovery if r["direction"] == direction]

        for tf in TIMEFRAMES:
            for feature in NUMERIC_FEATURES:
                key = f"{tf}_{feature}"
                values = []

                for row in drows:
                    x = numeric(row["technical_features"].get(key))
                    if x is not None:
                        values.append(x)

                if len(values) < MIN_DISCOVERY_SAMPLE * 2:
                    continue

                sv = sorted(values)
                q25 = quantile(sv, 0.25)
                q75 = quantile(sv, 0.75)

                groups = (
                    ("LOW", lambda x, q=q25: x <= q, q25),
                    ("HIGH", lambda x, q=q75: x >= q, q75),
                )

                for horizon, label_field in HORIZONS.items():
                    for side, predicate, threshold in groups:
                        matched = []
                        for row in drows:
                            x = numeric(row["technical_features"].get(key))
                            if x is not None and predicate(x):
                                matched.append(row)

                        r, n, correct = rate(matched, label_field)
                        if r is None or n < MIN_DISCOVERY_SAMPLE:
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
                                "discovery_rate": r,
                                "discovery_n": n,
                                "discovery_correct": correct,
                            })

    return rules


def discover_categorical_rules(discovery):
    rules = []

    for direction in ("LONG", "SHORT"):
        drows = [r for r in discovery if r["direction"] == direction]

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
                        r, n, correct = rate(matched, label_field)
                        if r is None or n < MIN_DISCOVERY_SAMPLE:
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
                                "discovery_rate": r,
                                "discovery_n": n,
                                "discovery_correct": correct,
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


def validate_rules(rules, validation):
    results = []

    baseline_cache = {}

    for rule in rules:
        matched = [r for r in validation if match_rule(r, rule)]

        validation_rate, validation_n, validation_correct = rate(
            matched, rule["label_field"]
        )

        baseline_key = (rule["direction"], rule["label_field"])
        if baseline_key not in baseline_cache:
            baseline_cache[baseline_key] = baseline_for(
                validation,
                rule["direction"],
                rule["label_field"],
            )

        baseline_rate, baseline_n, _ = baseline_cache[baseline_key]

        result = dict(rule)
        result["validation_rate"] = validation_rate
        result["validation_n"] = validation_n
        result["validation_correct"] = validation_correct
        result["baseline_rate"] = baseline_rate
        result["baseline_n"] = baseline_n

        if validation_rate is None or validation_n < MIN_VALIDATION_SAMPLE:
            result["status"] = "INSUFFICIENT_VALIDATION"
            result["lift"] = None
            result["ci"] = None
        else:
            result["lift"] = (
                validation_rate - baseline_rate
                if baseline_rate is not None else None
            )
            result["ci"] = wilson(validation_correct, validation_n)

            if validation_rate >= 0.55:
                result["status"] = "VALIDATED"
            elif validation_rate < 0.50:
                result["status"] = "FAILED_OR_REVERSED"
            else:
                result["status"] = "WEAKENED"

        results.append(result)

    return results


def rule_text(r):
    if r["kind"] == "NUMERIC":
        op = "<=" if r["condition"] == "LOW" else ">="
        condition = f"{r['feature']} {op} {r['threshold']:.6g}"
    else:
        condition = f"{r['feature']} == {r['condition']}"

    return (
        f"{r['direction']} {r['horizon']} | {condition} | "
        f"DISC={r['discovery_rate']*100:.2f}% N={r['discovery_n']}"
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

        banner("R5.2 METHODOLOGY")
        print("FEATURE SOURCE: STORED DECISION-TIME technical_features ONLY")
        print("OUTCOMES USED TO CONSTRUCT FEATURES/RULE VALUES: NO")
        print("OUTCOMES USED AS LABELS AFTER FEATURE VALUES EXIST: YES")
        print("SPLIT: CHRONOLOGICAL 70% DISCOVERY / 30% LATER VALIDATION")
        print("PAIRED LONG/SHORT AT SAME TIMESTAMP: KEPT ON SAME SIDE OF SPLIT")
        print(f"MIN DISCOVERY SAMPLE: {MIN_DISCOVERY_SAMPLE}")
        print(f"MIN VALIDATION SAMPLE: {MIN_VALIDATION_SAMPLE}")
        print(f"DISCOVERY EDGE THRESHOLD: {MIN_DISCOVERY_RATE*100:.0f}%")
        print("RULE THRESHOLDS/CATEGORIES: LEARNED ON DISCOVERY DATA ONLY")
        print("PRODUCTION PROMOTION: NONE")

        discovery, validation, validation_start, timestamp_count = (
            chronological_split(rows)
        )

        banner("R5.2 DATASET")
        print(f"TOTAL COMPLETED FEATURE-BEARING OBSERVATIONS: {len(rows)}")
        print(f"UNIQUE TIMESTAMPS: {timestamp_count}")
        print(f"DISCOVERY OBSERVATIONS: {len(discovery)}")
        print(f"VALIDATION OBSERVATIONS: {len(validation)}")
        print(f"VALIDATION START: {validation_start}")
        if rows:
            print(f"OLDEST: {rows[0]['created_at']}")
            print(f"NEWEST: {rows[-1]['created_at']}")

        numeric_rules = discover_numeric_rules(discovery)
        categorical_rules = discover_categorical_rules(discovery)
        rules = numeric_rules + categorical_rules

        banner("R5.2 DISCOVERY")
        print(f"NUMERIC CANDIDATE RULES: {len(numeric_rules)}")
        print(f"CATEGORICAL CANDIDATE RULES: {len(categorical_rules)}")
        print(f"TOTAL FROZEN CANDIDATE RULES: {len(rules)}")

        results = validate_rules(rules, validation)

        counts = defaultdict(int)
        eligible = []
        positive_lift = []

        for r in results:
            counts[r["status"]] += 1
            if r["validation_n"] >= MIN_VALIDATION_SAMPLE:
                eligible.append(r)
                if r["lift"] is not None and r["lift"] > 0:
                    positive_lift.append(r)

        banner("R5.2 VALIDATION SUMMARY")
        print(f"TOTAL CANDIDATES: {len(results)}")
        print(f"VALIDATED: {counts['VALIDATED']}")
        print(f"WEAKENED: {counts['WEAKENED']}")
        print(f"FAILED OR REVERSED: {counts['FAILED_OR_REVERSED']}")
        print(f"INSUFFICIENT VALIDATION: {counts['INSUFFICIENT_VALIDATION']}")
        print(f"ELIGIBLE VALIDATION RULES: {len(eligible)}")
        print(
            f"POSITIVE LIFT VS SAME-DIRECTION VALIDATION BASELINE: "
            f"{len(positive_lift)}/{len(eligible)}"
        )

        ranked = [
            r for r in eligible
            if r["lift"] is not None
        ]
        ranked.sort(
            key=lambda r: (
                r["status"] == "VALIDATED",
                r["lift"],
                r["validation_n"],
            ),
            reverse=True,
        )

        banner("R5.2 TOP OUT-OF-TIME RESULTS")
        for r in ranked[:50]:
            ci_low, ci_high = r["ci"]
            print(
                f"{rule_text(r)} | "
                f"VALID={r['validation_rate']*100:.2f}% N={r['validation_n']} "
                f"CI=[{ci_low*100:.2f}%,{ci_high*100:.2f}%] | "
                f"BASE={r['baseline_rate']*100:.2f}% N={r['baseline_n']} | "
                f"LIFT={r['lift']*100:+.2f}pp | {r['status']}"
            )

        strict = [
            r for r in eligible
            if r["status"] == "VALIDATED"
            and r["lift"] is not None
            and r["lift"] > 0
        ]
        strict.sort(
            key=lambda r: (r["lift"], r["validation_n"]),
            reverse=True,
        )

        banner("R5.2 VALIDATED + POSITIVE-LIFT LEADS")
        print(f"COUNT: {len(strict)}")
        for r in strict[:30]:
            ci_low, ci_high = r["ci"]
            print(
                f"{rule_text(r)} | "
                f"VALID={r['validation_rate']*100:.2f}% N={r['validation_n']} "
                f"CI=[{ci_low*100:.2f}%,{ci_high*100:.2f}%] | "
                f"BASE={r['baseline_rate']*100:.2f}% | "
                f"LIFT={r['lift']*100:+.2f}pp"
            )

        banner("R5.2 FINAL STATUS")
        print("STATUS: R5.2 LEAKAGE-FREE FEATURE VALIDATION PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES")
        print(
            "NOTE: EVEN VALIDATED LEADS ARE RESEARCH CANDIDATES ONLY. "
            "THEY REQUIRE WALK-FORWARD/REPEATABILITY TESTING BEFORE ANY "
            "PRODUCTION CONSIDERATION."
        )

        conn.rollback()
        cur.close()

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        banner("R5.2 FAILURE")
        print("STATUS: R5.2 FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise

    finally:
        if conn is not None:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
