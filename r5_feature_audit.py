#!/usr/bin/env python3
"""
Brad's Signals Researcher
R5.1 - Feature Quality & Predictive Audit

Purpose:
Audit stored decision-time technical features before attempting more complex
feature discovery. Outcomes are used only as labels for retrospective research.

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
from collections import Counter, defaultdict
from datetime import datetime, timezone

import psycopg2


VERSION = "R5.1-FEATURE-QUALITY-PREDICTIVE-AUDIT"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False
AI_CALLS_ENABLED = False

MIN_GROUP_SAMPLE = 50

HORIZONS = {
    "5m": "direction_correct_5m",
    "30m": "direction_correct_30m",
    "1h": "direction_correct_1h",
    "4h": "direction_correct_4h",
    "12h": "direction_correct_12h",
    "24h": "direction_correct_24h",
}

FEATURES = (
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

TIMEFRAMES = ("5m", "15m", "30m", "1h", "4h", "1d")


def banner(text):
    print()
    print("=" * 92)
    print(text)
    print("=" * 92)


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


def label_value(value):
    if value is None:
        return None
    return bool(value)


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
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def wilson_interval(correct, total, z=1.96):
    if total <= 0:
        return (0.0, 0.0)
    p = correct / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    margin = (
        z * math.sqrt(
            p * (1.0 - p) / total
            + z * z / (4.0 * total * total)
        ) / denom
    )
    return center - margin, center + margin


def fetch_rows(cur):
    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,
            o.final_confidence,
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


def feature_inventory(rows):
    counts = Counter()
    for row in rows:
        for key, value in row["technical_features"].items():
            if value is not None:
                counts[key] += 1
    return counts


def print_quality(rows):
    banner("R5.1 FEATURE QUALITY")

    inventory = feature_inventory(rows)
    print(f"FEATURE-BEARING COMPLETED OBSERVATIONS: {len(rows)}")
    print(f"UNIQUE STORED FEATURE KEYS: {len(inventory)}")

    expected = []
    for tf in TIMEFRAMES:
        expected.extend(f"{tf}_{name}" for name in FEATURES)
        expected.extend(f"{tf}_{name}" for name in CATEGORICAL_FEATURES)

    print("--- EXPECTED FEATURE COVERAGE ---")
    for key in expected:
        n = inventory.get(key, 0)
        pct = (n / len(rows) * 100.0) if rows else 0.0
        print(f"{key}: present={n}/{len(rows)} ({pct:.2f}%)")

    extras = sorted(
        (key, n) for key, n in inventory.items()
        if key not in set(expected)
    )
    print("--- OTHER STORED FEATURE KEYS ---")
    for key, n in extras:
        print(f"{key}: present={n}/{len(rows)}")


def numeric_feature_audit(rows):
    banner("R5.1 NUMERIC FEATURE AUDIT")

    results = []

    for tf in TIMEFRAMES:
        for feature in FEATURES:
            key = f"{tf}_{feature}"
            values = []

            for row in rows:
                x = numeric(row["technical_features"].get(key))
                if x is not None:
                    values.append(x)

            if not values:
                continue

            sv = sorted(values)
            q25 = quantile(sv, 0.25)
            q50 = quantile(sv, 0.50)
            q75 = quantile(sv, 0.75)

            results.append({
                "key": key,
                "n": len(values),
                "min": sv[0],
                "q25": q25,
                "median": q50,
                "q75": q75,
                "max": sv[-1],
                "unique": len(set(values)),
            })

    for r in results:
        print(
            f"{r['key']}: N={r['n']} UNIQUE={r['unique']} "
            f"MIN={r['min']:.6g} Q25={r['q25']:.6g} "
            f"MEDIAN={r['median']:.6g} Q75={r['q75']:.6g} "
            f"MAX={r['max']:.6g}"
        )

    return results


def categorical_audit(rows):
    banner("R5.1 CATEGORICAL FEATURE AUDIT")

    for tf in TIMEFRAMES:
        for feature in CATEGORICAL_FEATURES:
            key = f"{tf}_{feature}"
            counts = Counter()

            for row in rows:
                value = row["technical_features"].get(key)
                if value is not None:
                    counts[str(value)] += 1

            if counts:
                print(f"{key}: {dict(counts.most_common())}")


def directional_numeric_screen(rows):
    banner("R5.1 DIRECTION-AWARE NUMERIC PREDICTIVE SCREEN")
    print(
        "Method: for each numeric feature, compare bottom quartile vs top quartile "
        "within LONG and SHORT separately. This is descriptive screening only."
    )

    candidates = []

    for direction in ("LONG", "SHORT"):
        direction_rows = [r for r in rows if r["direction"] == direction]

        for tf in TIMEFRAMES:
            for feature in FEATURES:
                key = f"{tf}_{feature}"
                available = []

                for row in direction_rows:
                    x = numeric(row["technical_features"].get(key))
                    if x is not None:
                        available.append((x, row))

                if len(available) < MIN_GROUP_SAMPLE * 2:
                    continue

                sorted_values = sorted(x for x, _ in available)
                q25 = quantile(sorted_values, 0.25)
                q75 = quantile(sorted_values, 0.75)

                low_rows = [r for x, r in available if x <= q25]
                high_rows = [r for x, r in available if x >= q75]

                for horizon, field in HORIZONS.items():
                    low_labels = [
                        label_value(r[field]) for r in low_rows
                        if r[field] is not None
                    ]
                    high_labels = [
                        label_value(r[field]) for r in high_rows
                        if r[field] is not None
                    ]

                    if (
                        len(low_labels) < MIN_GROUP_SAMPLE
                        or len(high_labels) < MIN_GROUP_SAMPLE
                    ):
                        continue

                    low_correct = sum(low_labels)
                    high_correct = sum(high_labels)
                    low_rate = low_correct / len(low_labels)
                    high_rate = high_correct / len(high_labels)
                    spread = high_rate - low_rate

                    candidates.append({
                        "direction": direction,
                        "feature": key,
                        "horizon": horizon,
                        "low_n": len(low_labels),
                        "low_rate": low_rate,
                        "high_n": len(high_labels),
                        "high_rate": high_rate,
                        "spread": spread,
                    })

    candidates.sort(key=lambda x: abs(x["spread"]), reverse=True)

    print("--- LARGEST ABSOLUTE QUARTILE SPREADS ---")
    for r in candidates[:40]:
        print(
            f"{r['direction']} {r['feature']} -> {r['horizon']} | "
            f"LOW={r['low_rate']*100:.2f}% N={r['low_n']} | "
            f"HIGH={r['high_rate']*100:.2f}% N={r['high_n']} | "
            f"SPREAD={r['spread']*100:+.2f}pp"
        )

    return candidates


def categorical_predictive_screen(rows):
    banner("R5.1 DIRECTION-AWARE CATEGORICAL PREDICTIVE SCREEN")

    findings = []

    for direction in ("LONG", "SHORT"):
        direction_rows = [r for r in rows if r["direction"] == direction]

        for tf in TIMEFRAMES:
            for feature in CATEGORICAL_FEATURES:
                key = f"{tf}_{feature}"
                groups = defaultdict(list)

                for row in direction_rows:
                    value = row["technical_features"].get(key)
                    if value is not None:
                        groups[str(value)].append(row)

                for horizon, field in HORIZONS.items():
                    eligible = []

                    for value, group in groups.items():
                        labels = [
                            label_value(r[field]) for r in group
                            if r[field] is not None
                        ]
                        if len(labels) < MIN_GROUP_SAMPLE:
                            continue
                        correct = sum(labels)
                        n = len(labels)
                        rate = correct / n
                        eligible.append((value, n, rate, wilson_interval(correct, n)))

                    if len(eligible) < 2:
                        continue

                    rates = [x[2] for x in eligible]
                    spread = max(rates) - min(rates)

                    findings.append({
                        "direction": direction,
                        "feature": key,
                        "horizon": horizon,
                        "spread": spread,
                        "groups": sorted(
                            eligible,
                            key=lambda x: (-x[2], -x[1], x[0])
                        ),
                    })

    findings.sort(key=lambda x: x["spread"], reverse=True)

    print("--- LARGEST CATEGORY SPREADS ---")
    for item in findings[:30]:
        group_text = "; ".join(
            f"{value}={rate*100:.2f}% N={n}"
            for value, n, rate, _ in item["groups"]
        )
        print(
            f"{item['direction']} {item['feature']} -> {item['horizon']} | "
            f"SPREAD={item['spread']*100:.2f}pp | {group_text}"
        )

    return findings


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

        banner("R5.1 DATASET")
        print(f"COMPLETED FEATURE-BEARING OBSERVATIONS: {len(rows)}")
        if rows:
            print(f"OLDEST: {rows[0]['created_at']}")
            print(f"NEWEST: {rows[-1]['created_at']}")

        if not rows:
            raise RuntimeError("No completed feature-bearing observations found")

        print_quality(rows)
        numeric_results = numeric_feature_audit(rows)
        categorical_audit(rows)
        numeric_findings = directional_numeric_screen(rows)
        categorical_findings = categorical_predictive_screen(rows)

        banner("R5.1 FINAL STATUS")
        print("STATUS: R5.1 FEATURE QUALITY & PREDICTIVE AUDIT PASS")
        print(f"NUMERIC FEATURES AUDITED: {len(numeric_results)}")
        print(f"NUMERIC SCREEN RESULTS: {len(numeric_findings)}")
        print(f"CATEGORICAL SCREEN RESULTS: {len(categorical_findings)}")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES")
        print(
            "NOTE: RESULTS ARE DESCRIPTIVE RESEARCH LEADS ONLY. "
            "NO FEATURE IS PROMOTED TO PRODUCTION FROM THIS AUDIT."
        )

        conn.rollback()
        cur.close()

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        banner("R5.1 FAILURE")
        print("STATUS: R5.1 FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise

    finally:
        if conn is not None:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
