#!/usr/bin/env python3
"""
Brad's Signals Researcher
R4.6 v2 - Leakage-Free Walk-Forward Decision-Time Validation

PURPOSE
-------
Test whether patterns built from information available at opportunity creation
time survive repeatedly across later unseen chronological periods.

SAFETY
------
- PostgreSQL READ ONLY.
- No database writes.
- No Telegram.
- No trades.
- No production changes.
- No AI calls.
- Regime construction uses ONLY opportunities.technical_features.
- Outcome correctness fields are labels only, never regime inputs.

METHOD
------
1. Load completed opportunities with decision-time technical_features.
2. Group by unique created_at timestamps so paired LONG/SHORT observations at
   the same timestamp can never be split across train/test.
3. Divide the timeline into five chronological blocks.
4. Run expanding-window walk-forward folds:
      Fold 1: B1 train -> B2 test
      Fold 2: B1+B2 train -> B3 test
      Fold 3: B1+B2+B3 train -> B4 test
      Fold 4: B1+B2+B3+B4 train -> B5 test
5. Discover candidates using TRAIN DATA ONLY.
6. Test those frozen candidates on the next unseen block.
7. Compare regime-matched test performance with the unfiltered
   symbol+direction+horizon baseline in the SAME test block.
8. Summarize repeatability across folds.

This is historical research only. It does not modify Bot 2.0.
"""

import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

import psycopg2


VERSION = "R4.6-V2-LEAKAGE-FREE-WALK-FORWARD"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False
AI_CALLS_ENABLED = False

N_BLOCKS = 5
MIN_TRAIN_SAMPLE = 50
MIN_TEST_SAMPLE = 20
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
    Deterministic regime made only from stored pre-decision technical features.
    Kept intentionally simple/interpretable to reduce overfitting.
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

    for tf in TF_NAMES:
        vote = normalize_trend(f.get(f"{tf}_trend"))
        if vote:
            w = weights[tf]
            trend_score += vote * w
            trend_weight += w

    if not trend_weight:
        trend = "UNKNOWN"
    else:
        score = trend_score / trend_weight
        if score >= 0.25:
            trend = "BULLISH"
        elif score <= -0.25:
            trend = "BEARISH"
        else:
            trend = "MIXED"

    momentum_values = []
    for tf in TF_NAMES:
        for suffix in ("momentum_3", "momentum_6", "momentum_acceleration"):
            x = numeric(f.get(f"{tf}_{suffix}"))
            if x is not None:
                momentum_values.append(x)

    if not momentum_values:
        momentum = "UNKNOWN"
    else:
        pos = sum(x > 0 for x in momentum_values)
        neg = sum(x < 0 for x in momentum_values)
        nonzero = pos + neg

        if nonzero == 0:
            momentum = "FLAT"
        else:
            balance = (pos - neg) / nonzero
            if balance >= 0.20:
                momentum = "POSITIVE"
            elif balance <= -0.20:
                momentum = "NEGATIVE"
            else:
                momentum = "MIXED"

    vol_votes = []
    for tf in TF_NAMES:
        bucket = volatility_bucket(f.get(f"{tf}_volatility_regime"))
        if bucket != "UNKNOWN":
            vol_votes.append(bucket)

    volatility = (
        Counter(vol_votes).most_common(1)[0][0]
        if vol_votes
        else "UNKNOWN"
    )

    return (trend, momentum, volatility)


def wilson_interval(correct, total, z=1.96):
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


def stats(rows, horizon):
    field = HORIZONS[horizon]
    values = [row[field] for row in rows if row[field] is not None]

    if not values:
        return {
            "correct": 0,
            "n": 0,
            "rate": 0.0,
            "ci": (0.0, 0.0),
        }

    correct = sum(bool(x) for x in values)
    n = len(values)
    rate = correct / n

    return {
        "correct": correct,
        "n": n,
        "rate": rate,
        "ci": wilson_interval(correct, n),
    }


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
        WHERE x.outcome_complete = TRUE
          AND o.created_at IS NOT NULL
          AND o.technical_features IS NOT NULL
        ORDER BY o.created_at ASC, o.symbol ASC, o.direction ASC
        """
    )

    columns = [d[0] for d in cur.description]
    rows = []

    for values in cur.fetchall():
        row = dict(zip(columns, values))
        features = safe_json(row.pop("technical_features"))
        row["regime_key"] = regime_from_features(features)
        rows.append(row)

    return rows


def make_time_blocks(rows, n_blocks=N_BLOCKS):
    timestamps = sorted({row["created_at"] for row in rows})

    if len(timestamps) < n_blocks:
        raise RuntimeError(
            f"Need at least {n_blocks} unique timestamps; got {len(timestamps)}"
        )

    base = len(timestamps) // n_blocks
    remainder = len(timestamps) % n_blocks

    blocks = []
    start = 0

    for i in range(n_blocks):
        size = base + (1 if i < remainder else 0)
        ts_block = timestamps[start:start + size]
        ts_set = set(ts_block)

        block_rows = [
            row for row in rows
            if row["created_at"] in ts_set
        ]

        blocks.append(
            {
                "name": f"B{i + 1}",
                "timestamps": ts_block,
                "rows": block_rows,
                "start": ts_block[0],
                "end": ts_block[-1],
            }
        )

        start += size

    return blocks


def discover_candidates(train_rows):
    """
    Candidate identity:
      symbol + direction + horizon + decision-time regime

    Selection uses training data only.
    """
    groups = defaultdict(list)

    for row in train_rows:
        for horizon, field in HORIZONS.items():
            if row[field] is None:
                continue

            key = (
                row["symbol"],
                row["direction"],
                horizon,
                row["regime_key"],
            )
            groups[key].append(row)

    candidates = []

    for key, group in groups.items():
        s = stats(group, key[2])

        if (
            s["n"] >= MIN_TRAIN_SAMPLE
            and s["rate"] >= DISCOVERY_EDGE_RATE
        ):
            candidates.append(
                {
                    "key": key,
                    "train": s,
                }
            )

    candidates.sort(
        key=lambda x: (
            -x["train"]["rate"],
            -x["train"]["n"],
            x["key"][0],
            x["key"][1],
            x["key"][2],
        )
    )

    return candidates


def evaluate_fold(fold_number, train_rows, test_rows):
    candidates = discover_candidates(train_rows)

    exact_test = defaultdict(list)
    baseline_test = defaultdict(list)

    for row in test_rows:
        for horizon, field in HORIZONS.items():
            if row[field] is None:
                continue

            exact_key = (
                row["symbol"],
                row["direction"],
                horizon,
                row["regime_key"],
            )
            exact_test[exact_key].append(row)

            baseline_key = (
                row["symbol"],
                row["direction"],
                horizon,
            )
            baseline_test[baseline_key].append(row)

    results = []

    for candidate in candidates:
        symbol, direction, horizon, regime = candidate["key"]

        matched_rows = exact_test.get(candidate["key"], [])
        baseline_rows = baseline_test.get(
            (symbol, direction, horizon),
            [],
        )
        nonmatch_rows = [
            row for row in baseline_rows
            if row["regime_key"] != regime
        ]

        test_s = stats(matched_rows, horizon)
        base_s = stats(baseline_rows, horizon)
        nonmatch_s = stats(nonmatch_rows, horizon)

        if test_s["n"] < MIN_TEST_SAMPLE:
            status = "INSUFFICIENT_TEST"
        elif test_s["rate"] >= 0.55:
            status = "VALIDATED"
        elif test_s["rate"] < 0.50:
            status = "FAILED_OR_REVERSED"
        else:
            status = "WEAKENED"

        lift_base = (
            test_s["rate"] - base_s["rate"]
            if test_s["n"] and base_s["n"]
            else None
        )
        lift_nonmatch = (
            test_s["rate"] - nonmatch_s["rate"]
            if test_s["n"] and nonmatch_s["n"]
            else None
        )

        results.append(
            {
                "fold": fold_number,
                "key": candidate["key"],
                "train": candidate["train"],
                "test": test_s,
                "baseline": base_s,
                "nonmatch": nonmatch_s,
                "lift_base": lift_base,
                "lift_nonmatch": lift_nonmatch,
                "status": status,
            }
        )

    return candidates, results


def pct(value):
    if value is None:
        return "N/A"
    return f"{value * 100.0:.2f}%"


def ci_text(ci):
    return f"[{pct(ci[0])}, {pct(ci[1])}]"


def key_text(key):
    symbol, direction, horizon, regime = key
    trend, momentum, volatility = regime
    return (
        f"{symbol} {direction} {horizon} "
        f"{trend}/{momentum}/{volatility}"
    )


def print_fold(fold_no, train_blocks, test_block, candidates, results):
    banner(
        f"FOLD {fold_no}: TRAIN {train_blocks} -> TEST {test_block['name']}"
    )

    print(f"TEST START: {test_block['start']}")
    print(f"TEST END: {test_block['end']}")
    print(f"TEST OBSERVATIONS: {len(test_block['rows'])}")
    print(f"DISCOVERED TRAIN CANDIDATES: {len(candidates)}")

    counts = Counter(r["status"] for r in results)

    print(f"VALIDATED: {counts['VALIDATED']}")
    print(f"WEAKENED: {counts['WEAKENED']}")
    print(f"FAILED OR REVERSED: {counts['FAILED_OR_REVERSED']}")
    print(f"INSUFFICIENT TEST: {counts['INSUFFICIENT_TEST']}")

    eligible = [
        r for r in results
        if r["test"]["n"] >= MIN_TEST_SAMPLE
    ]
    positive_lift = [
        r for r in eligible
        if r["lift_base"] is not None and r["lift_base"] > 0
    ]

    print(
        "ELIGIBLE WITH POSITIVE REGIME LIFT VS SAME-BLOCK BASELINE: "
        f"{len(positive_lift)}/{len(eligible)}"
    )

    ranked = sorted(
        eligible,
        key=lambda r: (
            -r["test"]["rate"],
            -(r["lift_base"] or 0.0),
            -r["test"]["n"],
        ),
    )

    print("--- TOP ELIGIBLE RESULTS ---")
    for r in ranked[:12]:
        print(
            f"{key_text(r['key'])} | "
            f"TRAIN={pct(r['train']['rate'])} N={r['train']['n']} | "
            f"TEST={pct(r['test']['rate'])} N={r['test']['n']} "
            f"CI={ci_text(r['test']['ci'])} | "
            f"BASE={pct(r['baseline']['rate'])} "
            f"N={r['baseline']['n']} | "
            f"LIFT_BASE={pct(r['lift_base'])} | "
            f"{r['status']}"
        )


def summarize_repeatability(all_results):
    banner("R4.6 v2 CROSS-FOLD REPEATABILITY")

    by_key = defaultdict(list)

    for result in all_results:
        if result["test"]["n"] >= MIN_TEST_SAMPLE:
            by_key[result["key"]].append(result)

    summaries = []

    for key, results in by_key.items():
        tested_folds = len(results)
        validated_folds = sum(
            r["status"] == "VALIDATED"
            for r in results
        )
        positive_lift_folds = sum(
            r["lift_base"] is not None and r["lift_base"] > 0
            for r in results
        )
        failed_folds = sum(
            r["status"] == "FAILED_OR_REVERSED"
            for r in results
        )

        total_test_n = sum(r["test"]["n"] for r in results)
        weighted_rate = (
            sum(r["test"]["correct"] for r in results) / total_test_n
            if total_test_n
            else 0.0
        )

        total_base_n = sum(r["baseline"]["n"] for r in results)
        weighted_base_rate = (
            sum(r["baseline"]["correct"] for r in results) / total_base_n
            if total_base_n
            else 0.0
        )

        summaries.append(
            {
                "key": key,
                "tested_folds": tested_folds,
                "validated_folds": validated_folds,
                "positive_lift_folds": positive_lift_folds,
                "failed_folds": failed_folds,
                "test_n": total_test_n,
                "test_rate": weighted_rate,
                "baseline_rate": weighted_base_rate,
                "lift": weighted_rate - weighted_base_rate,
            }
        )

    summaries.sort(
        key=lambda x: (
            -x["tested_folds"],
            -x["validated_folds"],
            -x["positive_lift_folds"],
            -x["lift"],
            -x["test_n"],
        )
    )

    print(f"UNIQUE ELIGIBLE PATTERNS ACROSS FOLDS: {len(summaries)}")

    repeat_2 = [s for s in summaries if s["tested_folds"] >= 2]
    repeat_3 = [s for s in summaries if s["tested_folds"] >= 3]

    print(f"TESTED IN >=2 UNSEEN FOLDS: {len(repeat_2)}")
    print(f"TESTED IN >=3 UNSEEN FOLDS: {len(repeat_3)}")

    robust = [
        s for s in summaries
        if (
            s["tested_folds"] >= 2
            and s["validated_folds"] == s["tested_folds"]
            and s["positive_lift_folds"] == s["tested_folds"]
            and s["lift"] > 0
        )
    ]

    print(
        "STRICT REPEATABLE SURVIVORS "
        "(validated + positive lift in every eligible fold, >=2 folds): "
        f"{len(robust)}"
    )

    print("--- MOST REPEATABLE PATTERNS ---")
    for s in summaries[:25]:
        print(
            f"{key_text(s['key'])} | "
            f"FOLDS={s['tested_folds']} | "
            f"VALIDATED={s['validated_folds']} | "
            f"POS_LIFT={s['positive_lift_folds']} | "
            f"FAILED={s['failed_folds']} | "
            f"TEST={pct(s['test_rate'])} N={s['test_n']} | "
            f"BASE={pct(s['baseline_rate'])} | "
            f"LIFT={pct(s['lift'])}"
        )

    return robust


def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print(f"RESEARCH VERSION: {VERSION}")
    print(f"UTC START: {datetime.now(timezone.utc).isoformat()}")
    print(f"DATABASE WRITES: {DATABASE_WRITES_ENABLED}")
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING_ENABLED}")
    print(f"TRADE EXECUTION: {TRADE_EXECUTION_ENABLED}")
    print(f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION_ENABLED}")
    print(f"AI CALLS: {AI_CALLS_ENABLED}")

    if any(
        (
            DATABASE_WRITES_ENABLED,
            TELEGRAM_SENDING_ENABLED,
            TRADE_EXECUTION_ENABLED,
            PRODUCTION_MODIFICATION_ENABLED,
            AI_CALLS_ENABLED,
        )
    ):
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

        banner("R4.6 v2 METHODOLOGY")
        print("REGIME INPUT: opportunities.technical_features ONLY")
        print("OUTCOME DATA USED TO CONSTRUCT REGIME: NO")
        print("OUTCOME DATA USED AS LABELS: YES")
        print("SPLIT: 5 CHRONOLOGICAL TIMESTAMP BLOCKS")
        print("WALK-FORWARD: EXPANDING TRAIN -> NEXT UNSEEN BLOCK")
        print("PAIRED LONG/SHORT SAME TIMESTAMP KEPT TOGETHER: YES")
        print(f"MIN TRAIN SAMPLE: {MIN_TRAIN_SAMPLE}")
        print(f"MIN TEST SAMPLE: {MIN_TEST_SAMPLE}")
        print(f"DISCOVERY EDGE: {DISCOVERY_EDGE_RATE:.0%}")

        rows = fetch_rows(cur)

        banner("R4.6 v2 DATASET")
        print(f"COMPLETED FEATURE-BEARING OBSERVATIONS: {len(rows)}")

        if not rows:
            raise RuntimeError("No completed feature-bearing observations found")

        blocks = make_time_blocks(rows)

        for block in blocks:
            print(
                f"{block['name']}: "
                f"timestamps={len(block['timestamps'])}; "
                f"observations={len(block['rows'])}; "
                f"start={block['start']}; end={block['end']}"
            )

        all_results = []

        for test_index in range(1, len(blocks)):
            train_blocks = blocks[:test_index]
            test_block = blocks[test_index]

            train_rows = [
                row
                for block in train_blocks
                for row in block["rows"]
            ]
            test_rows = test_block["rows"]

            candidates, results = evaluate_fold(
                fold_number=test_index,
                train_rows=train_rows,
                test_rows=test_rows,
            )

            print_fold(
                fold_no=test_index,
                train_blocks="+".join(
                    block["name"] for block in train_blocks
                ),
                test_block=test_block,
                candidates=candidates,
                results=results,
            )

            all_results.extend(results)

        robust = summarize_repeatability(all_results)

        banner("R4.6 v2 FINAL STATUS")
        print(
            "STATUS: R4.6 v2 LEAKAGE-FREE WALK-FORWARD VALIDATION PASS"
        )
        print(f"STRICT REPEATABLE SURVIVORS: {len(robust)}")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES")
        print("NO OUTCOME DATA WAS USED TO CONSTRUCT MARKET REGIMES")
        print(
            "NOTE: EVEN REPEATABLE SURVIVORS REMAIN RESEARCH HYPOTHESES; "
            "THEY ARE NOT AUTOMATIC PRODUCTION RULES."
        )

        conn.rollback()
        cur.close()

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        banner("R4.6 v2 FAILURE")
        print("STATUS: R4.6 v2 FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise

    finally:
        if conn is not None:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
