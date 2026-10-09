"""
BRAD'S SIGNALS RESEARCHER
R7.1 - FAST-MOVE LOCKED PROSPECTIVE VALIDATION

PURPOSE
-------
Validate a small, LOCKED set of R7 research leads on observations that
occurred AFTER the R7 discovery run.

SAFETY
------
- READ ONLY PostgreSQL
- NO database writes
- NO Telegram
- NO trades
- NO AI calls
- NO production scoring changes
- NO Bot 2.0 changes
- NO Guardian changes

IMPORTANT
---------
The rules below are frozen from R7.
R7.1 does NOT search for new thresholds or new combinations.

R7 discovery finished at approximately:
2026-10-08 21:36:35 UTC

Only opportunities created AFTER that cutoff are considered prospective.
"""

import os
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor


VERSION = "R7.1-FAST-MOVE-LOCKED-PROSPECTIVE-VALIDATION"

DATABASE_URL_ENV = "SIGNALS2_DATABASE_URL"

# R7 finished at ~21:36:35 UTC.
# Use a slightly later clean cutoff so none of the R7 discovery data leaks
# into prospective validation.
PROSPECTIVE_START_UTC = datetime(
    2026, 10, 8, 21, 37, 0, tzinfo=timezone.utc
)

TARGET_HORIZONS = ("1m", "5m", "10m", "30m")

# Minimum samples before we make even a preliminary judgement.
MIN_PRELIMINARY_SAMPLE = 30

# Better target before taking a lead seriously.
TARGET_SAMPLE = 100

# R7.1 is intentionally LOCKED.
# These are selected R7 leads. No thresholds are recalculated here.
LOCKED_LEADS = [
    {
        "id": "R7L01",
        "direction": "LONG",
        "horizon": "30m",
        "description": (
            "[30m_resistance_distance <= 0.019869] AND "
            "[1h_macd_acceleration <= -0.045800]"
        ),
        "conditions": [
            ("30m_resistance_distance", "<=", 0.019869),
            ("1h_macd_acceleration", "<=", -0.045800),
        ],
        "r7_holdout_n": 62,
        "r7_holdout_rate": 72.58,
        "r7_holdout_lift_pp": 25.89,
    },
    {
        "id": "R7L02",
        "direction": "LONG",
        "horizon": "1m",
        "description": "30m_bull_breakout == True",
        "conditions": [
            ("30m_bull_breakout", "==", True),
        ],
        "r7_holdout_n": 60,
        "r7_holdout_rate": 65.00,
        "r7_holdout_lift_pp": 15.90,
    },
    {
        "id": "R7L03",
        "direction": "LONG",
        "horizon": "30m",
        "description": (
            "[5m_bear_breakout == True] AND "
            "[30m_volume_acceleration <= -32.671162]"
        ),
        "conditions": [
            ("5m_bear_breakout", "==", True),
            ("30m_volume_acceleration", "<=", -32.671162),
        ],
        "r7_holdout_n": 43,
        "r7_holdout_rate": 60.47,
        "r7_holdout_lift_pp": 13.77,
    },
    {
        "id": "R7L04",
        "direction": "SHORT",
        "horizon": "1m",
        "description": (
            "[1h_bear_breakout == True] AND "
            "[30m_bear_breakout == True]"
        ),
        "conditions": [
            ("1h_bear_breakout", "==", True),
            ("30m_bear_breakout", "==", True),
        ],
        "r7_holdout_n": 148,
        "r7_holdout_rate": 57.43,
        "r7_holdout_lift_pp": 9.34,
    },
    {
        "id": "R7L05",
        "direction": "SHORT",
        "horizon": "1m",
        "description": (
            "[1h_bear_breakout == True] AND "
            "[5m_momentum_acceleration >= 0.045672]"
        ),
        "conditions": [
            ("1h_bear_breakout", "==", True),
            ("5m_momentum_acceleration", ">=", 0.045672),
        ],
        "r7_holdout_n": 72,
        "r7_holdout_rate": 56.94,
        "r7_holdout_lift_pp": 8.85,
    },
    {
        "id": "R7L06",
        "direction": "LONG",
        "horizon": "1m",
        "description": (
            "[5m_bear_breakout == True] AND "
            "[1h_macd_acceleration >= 0.022309]"
        ),
        "conditions": [
            ("5m_bear_breakout", "==", True),
            ("1h_macd_acceleration", ">=", 0.022309),
        ],
        "r7_holdout_n": 57,
        "r7_holdout_rate": 57.89,
        "r7_holdout_lift_pp": 8.80,
    },
    {
        "id": "R7L07",
        "direction": "SHORT",
        "horizon": "10m",
        "description": (
            "[30m_atr_pct >= 1.491912] AND "
            "[15m_volume_acceleration <= -36.185203]"
        ),
        "conditions": [
            ("30m_atr_pct", ">=", 1.491912),
            ("15m_volume_acceleration", "<=", -36.185203),
        ],
        "r7_holdout_n": 32,
        "r7_holdout_rate": 59.38,
        "r7_holdout_lift_pp": 7.64,
    },
    {
        "id": "R7L08",
        "direction": "LONG",
        "horizon": "1m",
        "description": (
            "[1h_macd_acceleration >= 0.022309] AND "
            "[15m_momentum_3 <= -0.391560]"
        ),
        "conditions": [
            ("1h_macd_acceleration", ">=", 0.022309),
            ("15m_momentum_3", "<=", -0.391560),
        ],
        "r7_holdout_n": 150,
        "r7_holdout_rate": 56.67,
        "r7_holdout_lift_pp": 7.57,
    },
    {
        "id": "R7L09",
        "direction": "LONG",
        "horizon": "30m",
        "description": "1h_macd_acceleration <= -0.045800",
        "conditions": [
            ("1h_macd_acceleration", "<=", -0.045800),
        ],
        "r7_holdout_n": 607,
        "r7_holdout_rate": 54.04,
        "r7_holdout_lift_pp": 7.35,
    },
    {
        "id": "R7L10",
        "direction": "SHORT",
        "horizon": "5m",
        "description": (
            "[5m_momentum_6 >= 0.222632] AND "
            "[30m_momentum_acceleration <= -0.116826]"
        ),
        "conditions": [
            ("5m_momentum_6", ">=", 0.222632),
            ("30m_momentum_acceleration", "<=", -0.116826),
        ],
        "r7_holdout_n": None,
        "r7_holdout_rate": None,
        "r7_holdout_lift_pp": None,
    },
    {
        "id": "R7L11",
        "direction": "SHORT",
        "horizon": "10m",
        "description": (
            "[5m_momentum_3 >= 0.175892] AND "
            "[30m_momentum_3 <= -0.577916]"
        ),
        "conditions": [
            ("5m_momentum_3", ">=", 0.175892),
            ("30m_momentum_3", "<=", -0.577916),
        ],
        "r7_holdout_n": 163,
        "r7_holdout_rate": 55.83,
        "r7_holdout_lift_pp": 4.09,
    },
    {
        "id": "R7L12",
        "direction": "SHORT",
        "horizon": "10m",
        "description": (
            "[5m_atr_pct >= 0.278962] AND "
            "[15m_volume_acceleration <= -36.185203]"
        ),
        "conditions": [
            ("5m_atr_pct", ">=", 0.278962),
            ("15m_volume_acceleration", "<=", -36.185203),
        ],
        "r7_holdout_n": 203,
        "r7_holdout_rate": 54.68,
        "r7_holdout_lift_pp": 2.94,
    },
]


def banner(title):
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_bool(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "t", "1", "yes"):
            return True
        if text in ("false", "f", "0", "no"):
            return False

    return None


def feature_value(row, feature_name):
    features = row.get("combined_features")

    if not isinstance(features, dict):
        return None

    return features.get(feature_name)


def condition_matches(row, condition):
    feature_name, operator, target = condition

    raw_value = feature_value(row, feature_name)

    if isinstance(target, bool):
        value = safe_bool(raw_value)

        if value is None:
            return False

        if operator == "==":
            return value == target

        return False

    value = safe_float(raw_value)

    if value is None:
        return False

    if operator == ">=":
        return value >= float(target)

    if operator == "<=":
        return value <= float(target)

    if operator == ">":
        return value > float(target)

    if operator == "<":
        return value < float(target)

    if operator == "==":
        return value == float(target)

    return False


def lead_matches(row, lead):
    if str(row.get("direction") or "").upper() != lead["direction"]:
        return False

    return all(
        condition_matches(row, condition)
        for condition in lead["conditions"]
    )


def outcome_correct(row, horizon):
    value = row.get(f"direction_correct_{horizon}")
    return safe_bool(value)


def outcome_return(row, horizon):
    return safe_float(row.get(f"return_{horizon}_pct"))


def evaluate_population(rows, horizon):
    usable = []

    for row in rows:
        correct = outcome_correct(row, horizon)
        ret = outcome_return(row, horizon)

        if correct is None:
            continue

        usable.append((correct, ret))

    n = len(usable)

    if n == 0:
        return {
            "n": 0,
            "correct": 0,
            "rate": None,
            "avg_return": None,
        }

    correct_count = sum(1 for correct, _ in usable if correct)

    returns = [
        ret for _, ret in usable
        if ret is not None
    ]

    avg_return = (
        sum(returns) / len(returns)
        if returns
        else None
    )

    return {
        "n": n,
        "correct": correct_count,
        "rate": (correct_count / n) * 100.0,
        "avg_return": avg_return,
    }


def fmt_pct(value):
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def fmt_return(value):
    if value is None:
        return "N/A"
    return f"{value:.5f}%"


def classify_result(n, lift_pp):
    if n < MIN_PRELIMINARY_SAMPLE:
        return "WAITING FOR SAMPLE"

    if lift_pp is None:
        return "NO RESULT"

    if lift_pp >= 3.0:
        return "PROMISING - KEEP OBSERVING"

    if lift_pp > 0.0:
        return "POSITIVE BUT WEAK"

    if lift_pp <= -3.0:
        return "FAILED SO FAR"

    return "NO CLEAR EDGE"


def connect_read_only():
    database_url = os.getenv(DATABASE_URL_ENV)

    if not database_url:
        raise RuntimeError(
            f"Missing required environment variable: {DATABASE_URL_ENV}"
        )

    conn = psycopg2.connect(database_url)

    conn.set_session(
        readonly=True,
        autocommit=False,
    )

    return conn


def load_prospective_rows(conn):
    query = """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,
            o.strategy_version,
            o.combined_features,

            out.direction_correct_1m,
            out.direction_correct_5m,
            out.direction_correct_10m,
            out.direction_correct_30m,

            out.return_1m_pct,
            out.return_5m_pct,
            out.return_10m_pct,
            out.return_30m_pct,

            out.outcome_complete

        FROM public.signals2_opportunities AS o

        INNER JOIN public.signals2_outcomes AS out
            ON out.opportunity_id = o.opportunity_id

        WHERE
            o.created_at >= %s
            AND out.outcome_complete = TRUE

            AND (
                o.strategy_version IS NULL
                OR (
                    o.strategy_version NOT ILIKE '%%TEST%%'
                    AND o.strategy_version NOT ILIKE '%%DIAGNOSTIC%%'
                    AND o.strategy_version NOT ILIKE '%%SYNTHETIC%%'
                )
            )

        ORDER BY
            o.created_at ASC,
            o.opportunity_id ASC
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (PROSPECTIVE_START_UTC,))
        return cur.fetchall()


def print_dataset_health(rows):
    banner("R7.1 PROSPECTIVE DATASET HEALTH")

    print(f"PROSPECTIVE START UTC: {PROSPECTIVE_START_UTC.isoformat()}")
    print(f"COMPLETED REAL ROWS AFTER CUTOFF: {len(rows)}")

    long_rows = [
        row for row in rows
        if str(row.get("direction") or "").upper() == "LONG"
    ]

    short_rows = [
        row for row in rows
        if str(row.get("direction") or "").upper() == "SHORT"
    ]

    print(f"LONG: {len(long_rows)}")
    print(f"SHORT: {len(short_rows)}")

    if rows:
        print(f"FIRST ROW: {rows[0].get('created_at')}")
        print(f"LAST ROW:  {rows[-1].get('created_at')}")

    for direction, direction_rows in (
        ("LONG", long_rows),
        ("SHORT", short_rows),
    ):
        print()

        for horizon in TARGET_HORIZONS:
            result = evaluate_population(
                direction_rows,
                horizon,
            )

            print(
                f"{direction} {horizon}: "
                f"N={result['n']} "
                f"RATE={fmt_pct(result['rate'])} "
                f"AVG_RETURN={fmt_return(result['avg_return'])}"
            )


def evaluate_locked_leads(rows):
    banner("R7.1 LOCKED LEAD VALIDATION")

    results = []

    for lead in LOCKED_LEADS:
        direction_rows = [
            row for row in rows
            if str(row.get("direction") or "").upper()
            == lead["direction"]
        ]

        baseline = evaluate_population(
            direction_rows,
            lead["horizon"],
        )

        matched_rows = [
            row for row in direction_rows
            if lead_matches(row, lead)
        ]

        matched = evaluate_population(
            matched_rows,
            lead["horizon"],
        )

        lift_pp = None

        if (
            matched["rate"] is not None
            and baseline["rate"] is not None
        ):
            lift_pp = (
                matched["rate"]
                - baseline["rate"]
            )

        status = classify_result(
            matched["n"],
            lift_pp,
        )

        results.append(
            {
                "lead": lead,
                "baseline": baseline,
                "matched": matched,
                "lift_pp": lift_pp,
                "status": status,
            }
        )

        print()
        print(
            f"{lead['id']} | "
            f"{lead['direction']} | "
            f"{lead['horizon']}"
        )
        print(f"RULE: {lead['description']}")

        if lead["r7_holdout_rate"] is not None:
            print(
                "R7 HOLDOUT: "
                f"N={lead['r7_holdout_n']} "
                f"RATE={lead['r7_holdout_rate']:.2f}% "
                f"LIFT={lead['r7_holdout_lift_pp']:+.2f}pp"
            )
        else:
            print("R7 HOLDOUT: LOCKED LEAD - SUMMARY VALUE NOT STORED")

        print(
            "PROSPECTIVE BASELINE: "
            f"N={baseline['n']} "
            f"RATE={fmt_pct(baseline['rate'])} "
            f"AVG_RETURN={fmt_return(baseline['avg_return'])}"
        )

        lift_text = (
            "N/A"
            if lift_pp is None
            else f"{lift_pp:+.2f}pp"
        )

        print(
            "PROSPECTIVE LEAD: "
            f"N={matched['n']} "
            f"RATE={fmt_pct(matched['rate'])} "
            f"LIFT={lift_text} "
            f"AVG_RETURN={fmt_return(matched['avg_return'])}"
        )

        print(f"STATUS: {status}")

    return results


def print_summary(results):
    banner("R7.1 PROSPECTIVE VALIDATION SUMMARY")

    ready = [
        result for result in results
        if result["matched"]["n"] >= MIN_PRELIMINARY_SAMPLE
    ]

    waiting = [
        result for result in results
        if result["matched"]["n"] < MIN_PRELIMINARY_SAMPLE
    ]

    target_ready = [
        result for result in results
        if result["matched"]["n"] >= TARGET_SAMPLE
    ]

    positive = [
        result for result in ready
        if result["lift_pp"] is not None
        and result["lift_pp"] > 0.0
    ]

    promising = [
        result for result in ready
        if result["lift_pp"] is not None
        and result["lift_pp"] >= 3.0
    ]

    failed = [
        result for result in ready
        if result["lift_pp"] is not None
        and result["lift_pp"] <= -3.0
    ]

    print(f"LOCKED LEADS: {len(results)}")
    print(
        f"LEADS WITH >= {MIN_PRELIMINARY_SAMPLE} "
        f"PROSPECTIVE MATCHES: {len(ready)}"
    )
    print(
        f"LEADS WITH >= {TARGET_SAMPLE} "
        f"PROSPECTIVE MATCHES: {len(target_ready)}"
    )
    print(f"POSITIVE LIFT: {len(positive)}")
    print(f"PROMISING >= +3.00pp: {len(promising)}")
    print(f"FAILED <= -3.00pp: {len(failed)}")
    print(f"WAITING FOR SAMPLE: {len(waiting)}")

    ranked = sorted(
        ready,
        key=lambda item: (
            item["lift_pp"]
            if item["lift_pp"] is not None
            else -999999.0,
            item["matched"]["n"],
        ),
        reverse=True,
    )

    if ranked:
        print()
        print("RANKED PROSPECTIVE RESULTS")

        for index, result in enumerate(ranked, start=1):
            lead = result["lead"]
            matched = result["matched"]
            lift_pp = result["lift_pp"]

            lift_text = (
                "N/A"
                if lift_pp is None
                else f"{lift_pp:+.2f}pp"
            )

            print(
                f"{index}. {lead['id']} "
                f"{lead['direction']} {lead['horizon']} | "
                f"N={matched['n']} "
                f"RATE={fmt_pct(matched['rate'])} "
                f"LIFT={lift_text} "
                f"AVG_RETURN={fmt_return(matched['avg_return'])} | "
                f"{lead['description']}"
            )

    print()
    print("INTERPRETATION")
    print(
        "1. These rules were frozen before this prospective sample."
    )
    print(
        "2. R7.1 does not discover or retune thresholds."
    )
    print(
        "3. Small samples are not proof of an edge."
    )
    print(
        "4. Paired LONG/SHORT observations are not independent trades."
    )
    print(
        "5. Fees, slippage, funding, leverage, entries and exits "
        "are not modelled here."
    )
    print(
        "6. No production scoring change is authorized by R7.1 alone."
    )
    print(
        "7. Strong leads should accumulate a larger prospective sample "
        "before any production experiment."
    )


def main():
    banner("BRADS-SIGNALS-RESEARCHER")

    print(f"RESEARCH VERSION: {VERSION}")
    print(
        f"UTC START: "
        f"{datetime.now(timezone.utc).isoformat()}"
    )
    print("DATABASE WRITES: False")
    print("TELEGRAM SENDING: False")
    print("TRADE EXECUTION: False")
    print("PRODUCTION MODIFICATION: False")
    print("AI CALLS: False")
    print("RULE SEARCH / RETUNING: False")
    print("LOCKED R7 LEADS: True")
    print(
        "TARGET HORIZONS: "
        + ", ".join(TARGET_HORIZONS)
    )
    print(
        f"PROSPECTIVE CUTOFF: "
        f"{PROSPECTIVE_START_UTC.isoformat()}"
    )

    conn = None

    try:
        conn = connect_read_only()

        print("DATABASE CONNECTION: READY")
        print("DATABASE SESSION: READ ONLY")
        print("SAFETY CHECK: PASS")

        rows = load_prospective_rows(conn)

        print_dataset_health(rows)

        if not rows:
            banner("R7.1 FINAL STATUS")
            print(
                "STATUS: WAITING FOR PROSPECTIVE COMPLETED OUTCOMES"
            )
            print("DATABASE REMAINED READ ONLY")
            print(
                "NO WRITES; NO SENDS; NO TRADES; "
                "NO PRODUCTION CHANGES; NO AI CALLS"
            )
            return 0

        results = evaluate_locked_leads(rows)

        print_summary(results)

        banner("R7.1 FINAL STATUS")

        mature_results = [
            result for result in results
            if result["matched"]["n"]
            >= MIN_PRELIMINARY_SAMPLE
        ]

        if not mature_results:
            print(
                "STATUS: WAITING FOR SUFFICIENT "
                "PROSPECTIVE LEAD SAMPLES"
            )
        else:
            print(
                "STATUS: PROSPECTIVE RESULTS AVAILABLE - "
                "RESEARCH REVIEW REQUIRED"
            )

        print("DATABASE REMAINED READ ONLY")
        print(
            "NO WRITES; NO SENDS; NO TRADES; "
            "NO PRODUCTION CHANGES; NO AI CALLS"
        )

        return 0

    except Exception as exc:
        banner("R7.1 ERROR")

        print(
            f"{type(exc).__name__}: {exc}"
        )
        print(
            "NO PRODUCTION CHANGE WAS MADE."
        )

        return 1

    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

            try:
                conn.close()
                print("DATABASE CONNECTION: CLOSED")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
