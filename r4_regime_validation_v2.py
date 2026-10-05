#!/usr/bin/env python3
"""
Brad's Signals Researcher
R4.5 v2 - Leakage-Free Decision-Time Regime Validation

PURPOSE
-------
Research whether regimes constructed ONLY from information stored at opportunity
creation time improve historical directional outcome performance.

SAFETY / METHODOLOGY
--------------------
- PostgreSQL session is READ ONLY.
- No database writes.
- No Telegram.
- No trades.
- No production changes.
- No AI calls.
- Regime construction uses ONLY signals2_opportunities.technical_features.
- Outcome fields are used ONLY as labels after the regime is constructed.
- Chronological split by unique opportunity timestamps keeps paired LONG/SHORT
  observations at the same timestamp on the same side of the split.
- Candidate selection is discovery-only.
- Validation data is held out until candidates have been selected.

IMPORTANT
---------
This is historical research, not a production trading rule.
"""

import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

import psycopg2


VERSION = "R4.5-V2-LEAKAGE-FREE-DECISION-TIME-REGIME"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False
AI_CALLS_ENABLED = False

DISCOVERY_FRACTION = 0.70
MIN_DISCOVERY_SAMPLE = 50
MIN_VALIDATION_SAMPLE = 20
DISCOVERY_EDGE_RATE = 0.55

HORIZONS = {
    "5m": "direction_correct_5m",
    "30m": "direction_correct_30m",
    "1h": "direction_correct_1h",
    "4h": "direction_correct_4h",
    "12h": "direction_correct_12h",
    "24h": "direction_correct_24h",
}

TF_NAMES = ("5m", "15m", "30m", "1h", "4h", "1d")


def banner(text):
    print()
    print("=" * 88)
    print(text)
    print("=" * 88)


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
    try:
        if value is None or isinstance(value, bool):
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def normalize_trend(value):
    text = str(value or "").upper()
    if "BULL" in text:
        return 1
    if "BEAR" in text:
        return -1
    return 0


def volatility_bucket(value):
    text = str(value or "").upper()
    if "HIGH" in text:
        return "HIGH"
    if "LOW" in text:
        return "LOW"
    if "MED" in text or "NORMAL" in text or "MID" in text:
        return "MEDIUM"
    return "UNKNOWN"


def regime_from_features(features):
    """
    Build a compact regime from pre-decision technical features only.

    TREND:
      Weighted multi-timeframe trend votes.
      Higher timeframes receive more weight.

    MOMENTUM:
      Sign of aggregate normalized momentum values available at decision time.

    VOLATILITY:
      Majority bucket from stored timeframe volatility regimes.

    MTF:
      Uses stored mtf_overall / mtf_alignment only as decision-time descriptors.
      It does not use any outcome information.
    """
    f = safe_json(features)

    weights = {
        "5m": 1.0,
        "15m": 1.0,
        "30m": 1.5,
        "1h": 2.0,
        "4h": 2.5,
        "1d": 3.0,
    }

    trend_score = 0.0
    trend_weight = 0.0
    trend_votes = []

    for tf in TF_NAMES:
        vote = normalize_trend(f.get(f"{tf}_trend"))
        if vote != 0:
            w = weights[tf]
            trend_score += vote * w
            trend_weight += w
            trend_votes.append(vote)

    if trend_weight == 0:
        trend_regime = "UNKNOWN"
    else:
        normalized = trend_score / trend_weight
        if normalized >= 0.25:
            trend_regime = "BULLISH"
        elif normalized <= -0.25:
            trend_regime = "BEARISH"
        else:
            trend_regime = "MIXED"

    momentum_values = []
    for tf in TF_NAMES:
        for suffix in ("momentum_3", "momentum_6", "momentum_acceleration"):
            x = numeric(f.get(f"{tf}_{suffix}"))
            if x is not None:
                momentum_values.append(x)

    if not momentum_values:
        momentum_regime = "UNKNOWN"
    else:
        positives = sum(1 for x in momentum_values if x > 0)
        negatives = sum(1 for x in momentum_values if x < 0)
        total = positives + negatives
        if total == 0:
            momentum_regime = "FLAT"
        else:
            balance = (positives - negatives) / total
            if balance >= 0.20:
                momentum_regime = "POSITIVE"
            elif balance <= -0.20:
                momentum_regime = "NEGATIVE"
            else:
                momentum_regime = "MIXED"

    vol_votes = []
    for tf in TF_NAMES:
        bucket = volatility_bucket(f.get(f"{tf}_volatility_regime"))
        if bucket != "UNKNOWN":
            vol_votes.append(bucket)

    if vol_votes:
        counts = Counter(vol_votes)
        volatility_regime = counts.most_common(1)[0][0]
    else:
        volatility_regime = "UNKNOWN"

    mtf_raw = str(f.get("mtf_overall") or "").upper()
    mtf_alignment = numeric(f.get("mtf_alignment"))

    if "BULL" in mtf_raw:
        mtf_regime = "BULLISH"
    elif "BEAR" in mtf_raw:
        mtf_regime = "BEARISH"
    elif "MIX" in mtf_raw or "NEUT" in mtf_raw:
        mtf_regime = "MIXED"
    elif mtf_alignment is not None:
        # Only use sign if the stored value itself is signed.
        if mtf_alignment > 0:
            mtf_regime = "POSITIVE"
        elif mtf_alignment < 0:
            mtf_regime = "NEGATIVE"
        else:
            mtf_regime = "FLAT"
    else:
        mtf_regime = "UNKNOWN"

    return {
        "trend": trend_regime,
        "momentum": momentum_regime,
        "volatility": volatility_regime,
        "mtf": mtf_regime,
    }


def regime_key(regime):
    # Primary regime deliberately stays compact to preserve sample size.
    return (
        regime["trend"],
        regime["momentum"],
        regime["volatility"],
    )


def wilson_interval(correct, total, z=1.96):
    if total <= 0:
        return (0.0, 0.0)

    p = correct / total
    denom = 1.0 + (z * z / total)
    center = (p + z * z / (2.0 * total)) / denom
    margin = (
        z
        * math.sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total)))
        / denom
    )
    return center - margin, center + margin


def rate(rows, horizon):
    field = HORIZONS[horizon]
    values = [row[field] for row in rows if row[field] is not None]
    if not values:
        return 0, 0, 0.0, (0.0, 0.0)

    correct = sum(1 for x in values if bool(x))
    total = len(values)
    r = correct / total
    return correct, total, r, wilson_interval(correct, total)


def classify_validation(validation_rate):
    if validation_rate >= 0.55:
        return "VALIDATED"
    if validation_rate < 0.50:
        return "FAILED_OR_REVERSED"
    return "WEAKENED"


def fetch_rows(cur):
    """
    Join opportunities to completed outcomes.

    technical_features is the ONLY source used for regime construction.
    Outcome correctness columns are labels only.
    """
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
        WHERE x.outcome_complete = TRUE
          AND o.created_at IS NOT NULL
          AND o.technical_features IS NOT NULL
        ORDER BY o.created_at ASC, o.symbol ASC, o.direction ASC
        """
    )

    columns = [d[0] for d in cur.description]
    result = []

    for values in cur.fetchall():
        row = dict(zip(columns, values))
        row["features"] = safe_json(row.pop("technical_features"))
        row["regime"] = regime_from_features(row["features"])
        row["regime_key"] = regime_key(row["regime"])
        result.append(row)

    return result


def chronological_split(rows):
    timestamps = sorted({row["created_at"] for row in rows})

    if len(timestamps) < 2:
        raise RuntimeError("Not enough unique timestamps for chronological validation")

    split_index = int(len(timestamps) * DISCOVERY_FRACTION)
    split_index = max(1, min(split_index, len(timestamps) - 1))

    discovery_times = set(timestamps[:split_index])
    validation_times = set(timestamps[split_index:])

    discovery = [row for row in rows if row["created_at"] in discovery_times]
    validation = [row for row in rows if row["created_at"] in validation_times]

    return (
        discovery,
        validation,
        timestamps[split_index - 1],
        timestamps[split_index],
        len(timestamps),
    )


def build_candidates(discovery):
    """
    Discovery-only candidate selection.

    Candidate:
      symbol + direction + horizon + decision-time regime

    A candidate must have at least MIN_DISCOVERY_SAMPLE observations and
    discovery correctness >= DISCOVERY_EDGE_RATE.
    """
    groups = defaultdict(list)

    for row in discovery:
        for horizon in HORIZONS:
            if row[HORIZONS[horizon]] is None:
                continue

            key = (
                row["symbol"],
                row["direction"],
                horizon,
                row["regime_key"],
            )
            groups[key].append(row)

    candidates = []

    for key, rows in groups.items():
        correct, total, r, ci = rate(rows, key[2])

        if total >= MIN_DISCOVERY_SAMPLE and r >= DISCOVERY_EDGE_RATE:
            candidates.append(
                {
                    "key": key,
                    "discovery_correct": correct,
                    "discovery_n": total,
                    "discovery_rate": r,
                    "discovery_ci": ci,
                }
            )

    candidates.sort(
        key=lambda x: (
            -x["discovery_rate"],
            -x["discovery_n"],
            x["key"][0],
            x["key"][1],
            x["key"][2],
        )
    )
    return candidates


def evaluate_candidates(candidates, validation):
    exact_groups = defaultdict(list)
    baseline_groups = defaultdict(list)
    nonmatching_groups = defaultdict(list)

    for row in validation:
        for horizon in HORIZONS:
            if row[HORIZONS[horizon]] is None:
                continue

            exact_key = (
                row["symbol"],
                row["direction"],
                horizon,
                row["regime_key"],
            )
            exact_groups[exact_key].append(row)

            base_key = (row["symbol"], row["direction"], horizon)
            baseline_groups[base_key].append(row)

    results = []

    for candidate in candidates:
        symbol, direction, horizon, rkey = candidate["key"]
        exact_rows = exact_groups.get(candidate["key"], [])
        base_key = (symbol, direction, horizon)
        base_rows = baseline_groups.get(base_key, [])

        nonmatch = [
            row for row in base_rows
            if row["regime_key"] != rkey
        ]

        v_correct, v_n, v_rate, v_ci = rate(exact_rows, horizon)
        b_correct, b_n, b_rate, b_ci = rate(base_rows, horizon)
        n_correct, n_n, n_rate, n_ci = rate(nonmatch, horizon)

        if v_n < MIN_VALIDATION_SAMPLE:
            status = "INSUFFICIENT_VALIDATION"
        else:
            status = classify_validation(v_rate)

        result = dict(candidate)
        result.update(
            {
                "validation_correct": v_correct,
                "validation_n": v_n,
                "validation_rate": v_rate,
                "validation_ci": v_ci,
                "baseline_correct": b_correct,
                "baseline_n": b_n,
                "baseline_rate": b_rate,
                "baseline_ci": b_ci,
                "nonmatch_correct": n_correct,
                "nonmatch_n": n_n,
                "nonmatch_rate": n_rate,
                "nonmatch_ci": n_ci,
                "regime_lift_vs_baseline": v_rate - b_rate if v_n else 0.0,
                "regime_lift_vs_nonmatch": (
                    v_rate - n_rate if v_n and n_n else None
                ),
                "status": status,
            }
        )
        results.append(result)

    return results


def pct(x):
    return f"{x * 100.0:.2f}%"


def ci_text(ci):
    return f"[{pct(ci[0])}, {pct(ci[1])}]"


def print_regime_distribution(rows, title):
    banner(title)
    counts = Counter(row["regime_key"] for row in rows)
    for key, n in counts.most_common():
        trend, momentum, vol = key
        print(
            f"TREND={trend:8s} | MOM={momentum:8s} | "
            f"VOL={vol:7s} | N={n}"
        )


def print_results(results):
    banner("R4.5 v2 HELD-OUT VALIDATION SUMMARY")

    statuses = Counter(r["status"] for r in results)

    print(f"TOTAL DISCOVERY CANDIDATES: {len(results)}")
    print(f"VALIDATED: {statuses['VALIDATED']}")
    print(f"WEAKENED: {statuses['WEAKENED']}")
    print(f"FAILED OR REVERSED: {statuses['FAILED_OR_REVERSED']}")
    print(f"INSUFFICIENT VALIDATION: {statuses['INSUFFICIENT_VALIDATION']}")

    eligible = [r for r in results if r["validation_n"] >= MIN_VALIDATION_SAMPLE]

    if eligible:
        positive_lift = [
            r for r in eligible
            if r["regime_lift_vs_baseline"] > 0
        ]
        print(
            "ELIGIBLE CANDIDATES WITH POSITIVE REGIME LIFT VS "
            f"UNFILTERED BASELINE: {len(positive_lift)}/{len(eligible)}"
        )

    banner("TOP HELD-OUT SURVIVORS")

    ranked = sorted(
        eligible,
        key=lambda r: (
            -r["validation_rate"],
            -r["regime_lift_vs_baseline"],
            -r["validation_n"],
        ),
    )

    for r in ranked[:25]:
        symbol, direction, horizon, rkey = r["key"]
        trend, momentum, vol = rkey
        nonmatch_text = (
            "N/A"
            if r["regime_lift_vs_nonmatch"] is None
            else pct(r["regime_lift_vs_nonmatch"])
        )

        print(
            f"{symbol:10s} {direction:5s} {horizon:4s} | "
            f"REGIME={trend}/{momentum}/{vol} | "
            f"DISC={pct(r['discovery_rate'])} N={r['discovery_n']} | "
            f"VALID={pct(r['validation_rate'])} N={r['validation_n']} "
            f"CI={ci_text(r['validation_ci'])} | "
            f"BASE={pct(r['baseline_rate'])} N={r['baseline_n']} | "
            f"LIFT_BASE={pct(r['regime_lift_vs_baseline'])} | "
            f"LIFT_NONMATCH={nonmatch_text} | "
            f"{r['status']}"
        )

    banner("FAILED / REVERSED HELD-OUT CANDIDATES")

    failed = [
        r for r in eligible
        if r["status"] == "FAILED_OR_REVERSED"
    ]
    failed.sort(
        key=lambda r: (
            r["validation_rate"],
            r["regime_lift_vs_baseline"],
            -r["validation_n"],
        )
    )

    for r in failed[:25]:
        symbol, direction, horizon, rkey = r["key"]
        trend, momentum, vol = rkey
        print(
            f"{symbol:10s} {direction:5s} {horizon:4s} | "
            f"REGIME={trend}/{momentum}/{vol} | "
            f"DISC={pct(r['discovery_rate'])} N={r['discovery_n']} | "
            f"VALID={pct(r['validation_rate'])} N={r['validation_n']} | "
            f"BASE={pct(r['baseline_rate'])} | "
            f"LIFT_BASE={pct(r['regime_lift_vs_baseline'])}"
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

    safety_flags = (
        DATABASE_WRITES_ENABLED,
        TELEGRAM_SENDING_ENABLED,
        TRADE_EXECUTION_ENABLED,
        PRODUCTION_MODIFICATION_ENABLED,
        AI_CALLS_ENABLED,
    )

    if any(safety_flags):
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

        banner("R4.5 v2 METHODOLOGY")
        print("REGIME INPUT SOURCE: opportunities.technical_features ONLY")
        print("OUTCOME FIELDS USED FOR REGIME: NONE")
        print("OUTCOME FIELDS USED AS LABELS AFTER REGIME CONSTRUCTION: YES")
        print("SPLIT TYPE: CHRONOLOGICAL BY UNIQUE OPPORTUNITY TIMESTAMP")
        print("PAIRED LONG/SHORT SAME TIMESTAMP KEPT TOGETHER: YES")
        print(f"DISCOVERY FRACTION: {DISCOVERY_FRACTION:.0%}")
        print(f"MIN DISCOVERY SAMPLE: {MIN_DISCOVERY_SAMPLE}")
        print(f"MIN VALIDATION SAMPLE: {MIN_VALIDATION_SAMPLE}")
        print(f"DISCOVERY EDGE THRESHOLD: {DISCOVERY_EDGE_RATE:.0%}")

        rows = fetch_rows(cur)

        banner("R4.5 v2 DATASET")
        print(f"COMPLETED FEATURE-BEARING OBSERVATIONS: {len(rows)}")

        if not rows:
            raise RuntimeError("No completed feature-bearing observations found")

        discovery, validation, discovery_end, validation_start, unique_ts = (
            chronological_split(rows)
        )

        print(f"UNIQUE OPPORTUNITY TIMESTAMPS: {unique_ts}")
        print(f"DISCOVERY OBSERVATIONS: {len(discovery)}")
        print(f"VALIDATION OBSERVATIONS: {len(validation)}")
        print(f"DISCOVERY END: {discovery_end}")
        print(f"VALIDATION START: {validation_start}")

        print_regime_distribution(
            discovery,
            "DISCOVERY DECISION-TIME REGIME DISTRIBUTION",
        )
        print_regime_distribution(
            validation,
            "VALIDATION DECISION-TIME REGIME DISTRIBUTION",
        )

        candidates = build_candidates(discovery)

        banner("R4.5 v2 DISCOVERY")
        print(f"DISCOVERY CANDIDATES MEETING RULES: {len(candidates)}")

        results = evaluate_candidates(candidates, validation)
        print_results(results)

        banner("R4.5 v2 RESEARCH STATUS")
        print("STATUS: R4.5 v2 LEAKAGE-FREE REGIME VALIDATION PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES")
        print("NO OUTCOME DATA WAS USED TO CONSTRUCT THE DECISION-TIME REGIME")
        print(
            "NOTE: RESULTS ARE HISTORICAL RESEARCH ONLY AND DO NOT CREATE "
            "A PRODUCTION TRADING RULE."
        )

        conn.rollback()
        cur.close()

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        banner("R4.5 v2 FAILURE")
        print("STATUS: R4.5 v2 FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise

    finally:
        if conn is not None:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
