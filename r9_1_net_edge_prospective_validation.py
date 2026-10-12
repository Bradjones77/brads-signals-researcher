"""
BRAD'S SIGNALS RESEARCHER
R9.1 - LOCKED NET-EDGE PROSPECTIVE VALIDATION

PURPOSE
-------
Prospectively validate a frozen subset of R9 net-edge rules on observations
created AFTER the research/discovery period.

IMPORTANT
---------
- READ ONLY
- NO DATABASE WRITES
- NO TELEGRAM
- NO TRADES
- NO PRODUCTION MODIFICATION
- NO AI CALLS
- NO RULE SEARCH
- NO RETUNING
- NO THRESHOLD OPTIMISATION

This file intentionally validates ONLY R9 rules whose exact definitions were
preserved from the completed R9 run.

Missing historical ranks are NOT reconstructed or guessed.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

import psycopg2


# =============================================================================
# VERSION / SAFETY
# =============================================================================

RESEARCH_VERSION = "R9.1-LOCKED-NET-EDGE-PROSPECTIVE-VALIDATION"

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False
RULE_SEARCH = False
RULE_RETUNING = False

# R9 had already completed before R7.1 was restored at this point.
# We deliberately use the later timestamp so R9.1 cannot reuse R9 research data.
PROSPECTIVE_CUTOFF = datetime(
    2026, 10, 12, 22, 53, 27, tzinfo=timezone.utc
)

PRIMARY_COST_PCT = 0.05
COST_SCENARIOS_PCT = (0.02, 0.05, 0.10)

# Desired profit AFTER hypothetical 0.05% round-trip cost.
PRIMARY_NET_TARGET_PCT = 0.05

# Therefore raw directional move must reach at least +0.10%.
PRIMARY_RAW_TARGET_PCT = (
    PRIMARY_COST_PCT + PRIMARY_NET_TARGET_PCT
)

MIN_SAMPLE = 30


# =============================================================================
# FROZEN R9 RULES
# =============================================================================
#
# These are exact rules preserved from the completed R9 output.
#
# We DO NOT recreate missing R9 ranks #1-#5.
# We DO NOT search for alternatives.
# We DO NOT modify thresholds.
#
# Each condition:
#   (feature_name, operator, threshold)
#
# =============================================================================

LOCKED_RULES = [

    {
        "id": "R9R06",
        "original_rank": 6,
        "direction": "LONG",
        "horizon": "30m",
        "conditions": [
            ("1h_momentum_acceleration", "<=", -0.015109),
            ("btc_alignment", ">=", 0.408796),
        ],
        "historical_cost_005_expectancy": 0.45216,
        "historical_cost_005_pf": 1.734,
    },

    {
        "id": "R9R07",
        "original_rank": 7,
        "direction": "LONG",
        "horizon": "30m",
        "conditions": [
            ("4h_momentum_6", "<=", -4.157395),
            ("4h_volume_acceleration", "<=", -31.895919),
        ],
        "historical_cost_005_expectancy": 0.35769,
        "historical_cost_005_pf": 1.828,
    },

    {
        "id": "R9R08",
        "original_rank": 8,
        "direction": "SHORT",
        "horizon": "30m",
        "conditions": [
            ("30m_momentum_acceleration", "<=", -0.167201),
            ("4h_momentum_3", "<=", -2.626809),
        ],
        "historical_cost_005_expectancy": 0.34558,
        "historical_cost_005_pf": 1.666,
    },

    {
        "id": "R9R09",
        "original_rank": 9,
        "direction": "SHORT",
        "horizon": "30m",
        "conditions": [
            ("1h_momentum_acceleration", ">=", 0.252024),
            ("30m_momentum_acceleration", "<=", -0.167201),
        ],
        "historical_cost_005_expectancy": 0.34496,
        "historical_cost_005_pf": 1.647,
    },

    {
        "id": "R9R10",
        "original_rank": 10,
        "direction": "SHORT",
        "horizon": "30m",
        "conditions": [
            ("1h_momentum_acceleration", ">=", 0.252024),
            ("30m_momentum_acceleration", "<=", -0.065245),
        ],
        "historical_cost_005_expectancy": 0.33903,
        "historical_cost_005_pf": 1.684,
    },
]


# =============================================================================
# HELPERS
# =============================================================================

def banner(title):
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def safe_float(value):
    try:
        if value is None:
            return None

        if isinstance(value, bool):
            return float(value)

        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


def parse_json(value):
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    try:
        parsed = json.loads(value)

        if isinstance(parsed, dict):
            return parsed

    except Exception:
        pass

    return {}


def flatten_dict(data, prefix="", output=None):
    """
    Flatten nested JSON while ALSO preserving leaf keys without prefixes.

    Example:
        {
            "technical": {
                "1h_momentum_acceleration": 0.2
            }
        }

    becomes searchable as both:
        technical.1h_momentum_acceleration
        1h_momentum_acceleration
    """

    if output is None:
        output = {}

    if not isinstance(data, dict):
        return output

    for key, value in data.items():

        key_string = str(key)

        full_key = (
            f"{prefix}.{key_string}"
            if prefix
            else key_string
        )

        if isinstance(value, dict):
            flatten_dict(
                value,
                prefix=full_key,
                output=output,
            )

        else:
            output[full_key] = value

            # Preserve simple leaf lookup.
            if key_string not in output:
                output[key_string] = value

    return output


def feature_map(row):
    """
    Merge feature sources.

    Priority:
        combined_features
        technical_features
        market_features

    Earlier sources win if duplicate simple keys exist.
    """

    merged = {}

    sources = [
        row.get("combined_features"),
        row.get("technical_features"),
        row.get("market_features"),
    ]

    for source in sources:

        parsed = parse_json(source)
        flattened = flatten_dict(parsed)

        for key, value in flattened.items():
            if key not in merged:
                merged[key] = value

    return merged


def get_feature(features, feature_name):
    """
    Try exact key first.

    If JSON was nested, also allow a unique key ending in:
        .feature_name
    """

    if feature_name in features:
        return features[feature_name]

    suffix = "." + feature_name

    matches = [
        value
        for key, value in features.items()
        if key.endswith(suffix)
    ]

    if len(matches) == 1:
        return matches[0]

    return None


def condition_matches(features, condition):
    feature_name, operator, threshold = condition

    value = safe_float(
        get_feature(features, feature_name)
    )

    if value is None:
        return False

    if operator == "<=":
        return value <= threshold

    if operator == ">=":
        return value >= threshold

    if operator == "<":
        return value < threshold

    if operator == ">":
        return value > threshold

    if operator == "==":
        return value == threshold

    raise ValueError(
        f"Unsupported operator: {operator}"
    )


def rule_matches(features, rule):
    return all(
        condition_matches(features, condition)
        for condition in rule["conditions"]
    )


def return_column(horizon):
    allowed = {
        "1m": "return_1m_pct",
        "5m": "return_5m_pct",
        "10m": "return_10m_pct",
        "30m": "return_30m_pct",
    }

    if horizon not in allowed:
        raise ValueError(
            f"Unsupported horizon: {horizon}"
        )

    return allowed[horizon]


def mean(values):
    if not values:
        return None

    return sum(values) / len(values)


def median(values):
    if not values:
        return None

    ordered = sorted(values)
    n = len(ordered)
    midpoint = n // 2

    if n % 2 == 1:
        return ordered[midpoint]

    return (
        ordered[midpoint - 1]
        + ordered[midpoint]
    ) / 2.0


def profit_factor(net_returns):
    gains = sum(
        value
        for value in net_returns
        if value > 0
    )

    losses = abs(
        sum(
            value
            for value in net_returns
            if value < 0
        )
    )

    if losses == 0:
        if gains > 0:
            return float("inf")
        return None

    return gains / losses


def pct_rate(count, total):
    if total <= 0:
        return 0.0

    return 100.0 * count / total


def format_number(value, decimals=5):
    if value is None:
        return "N/A"

    if math.isinf(value):
        return "INF"

    return f"{value:.{decimals}f}"


def condition_text(condition):
    feature, operator, threshold = condition

    return (
        f"[{feature} {operator} "
        f"{threshold:.6f}]"
    )


def rule_text(rule):
    return " AND ".join(
        condition_text(condition)
        for condition in rule["conditions"]
    )


# =============================================================================
# DATABASE
# =============================================================================

def connect_database():
    database_url = os.environ.get(
        "SIGNALS2_DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "SIGNALS2_DATABASE_URL is not set."
        )

    connection = psycopg2.connect(database_url)

    # Hard safety layer.
    connection.set_session(
        readonly=True,
        autocommit=False,
    )

    return connection


def load_prospective_rows(connection):
    """
    Load ONLY opportunities created after the frozen prospective cutoff.

    Important:
    We do NOT require outcome_complete = TRUE.

    R9.1 studies fast horizons, especially 30m. Requiring the full 24-hour
    completion contract would unnecessarily delay prospective validation.

    We only use a row for a particular rule if that rule's required return
    column is already populated.
    """

    sql = """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,
            o.combined_features,
            o.technical_features,
            o.market_features,

            out.return_1m_pct,
            out.return_5m_pct,
            out.return_10m_pct,
            out.return_30m_pct

        FROM public.signals2_opportunities o

        JOIN public.signals2_outcomes out
            ON out.opportunity_id = o.opportunity_id

        WHERE o.created_at > %s

          AND UPPER(o.direction) IN ('LONG', 'SHORT')

          AND UPPER(COALESCE(o.symbol, '')) NOT LIKE '%%TEST%%'
          AND UPPER(COALESCE(o.symbol, '')) NOT LIKE '%%DIAGNOSTIC%%'
          AND UPPER(COALESCE(o.symbol, '')) NOT LIKE '%%SYNTHETIC%%'

        ORDER BY o.created_at ASC, o.opportunity_id ASC
    """

    cursor = connection.cursor()

    cursor.execute(
        sql,
        (PROSPECTIVE_CUTOFF,),
    )

    columns = [
        description[0]
        for description in cursor.description
    ]

    rows = [
        dict(zip(columns, record))
        for record in cursor.fetchall()
    ]

    cursor.close()

    return rows


# =============================================================================
# METRICS
# =============================================================================

def calculate_metrics(raw_returns, cost):
    raw_returns = [
        value
        for value in (
            safe_float(item)
            for item in raw_returns
        )
        if value is not None
    ]

    if not raw_returns:
        return None

    net_returns = [
        value - cost
        for value in raw_returns
    ]

    n = len(raw_returns)

    raw_positive = sum(
        1
        for value in raw_returns
        if value > 0
    )

    net_positive = sum(
        1
        for value in net_returns
        if value > 0
    )

    target_hits = sum(
        1
        for value in raw_returns
        if value >= PRIMARY_RAW_TARGET_PCT
    )

    return {
        "n": n,

        "raw_expectancy": mean(raw_returns),
        "raw_median": median(raw_returns),
        "raw_positive_rate": pct_rate(
            raw_positive,
            n,
        ),

        "net_expectancy": mean(net_returns),
        "net_median": median(net_returns),
        "net_positive_rate": pct_rate(
            net_positive,
            n,
        ),

        "target_hit_rate": pct_rate(
            target_hits,
            n,
        ),

        "profit_factor": profit_factor(
            net_returns
        ),
    }


def baseline_returns(rows, direction, horizon):
    column = return_column(horizon)

    values = []

    for row in rows:

        if str(row["direction"]).upper() != direction:
            continue

        value = safe_float(row.get(column))

        if value is not None:
            values.append(value)

    return values


def matched_returns(rows, rule):
    column = return_column(
        rule["horizon"]
    )

    values = []

    matches = []

    for row in rows:

        if (
            str(row["direction"]).upper()
            != rule["direction"]
        ):
            continue

        raw_return = safe_float(
            row.get(column)
        )

        if raw_return is None:
            continue

        features = feature_map(row)

        if rule_matches(features, rule):
            values.append(raw_return)
            matches.append(row)

    return values, matches


# =============================================================================
# REPORTING
# =============================================================================

def print_startup():
    banner("BRADS-SIGNALS-RESEARCHER")

    print(
        f"RESEARCH VERSION: {RESEARCH_VERSION}"
    )

    print(
        f"UTC START: "
        f"{datetime.now(timezone.utc).isoformat()}"
    )

    print(
        f"DATABASE WRITES: {DATABASE_WRITES}"
    )

    print(
        f"TELEGRAM SENDING: {TELEGRAM_SENDING}"
    )

    print(
        f"TRADE EXECUTION: {TRADE_EXECUTION}"
    )

    print(
        f"PRODUCTION MODIFICATION: "
        f"{PRODUCTION_MODIFICATION}"
    )

    print(
        f"AI CALLS: {AI_CALLS}"
    )

    print(
        f"RULE SEARCH: {RULE_SEARCH}"
    )

    print(
        f"RULE RETUNING: {RULE_RETUNING}"
    )

    print(
        "LOCKED R9 RULE SUBSET: TRUE"
    )

    print(
        f"LOCKED RULE COUNT: "
        f"{len(LOCKED_RULES)}"
    )

    print(
        "MISSING R9 RANKS RECONSTRUCTED: FALSE"
    )

    print(
        f"PROSPECTIVE CUTOFF: "
        f"{PROSPECTIVE_CUTOFF.isoformat()}"
    )

    print(
        f"PRIMARY HYPOTHETICAL COST: "
        f"{PRIMARY_COST_PCT:.2f}%"
    )

    print(
        f"DESIRED NET MOVE: "
        f"+{PRIMARY_NET_TARGET_PCT:.2f}%"
    )

    print(
        f"REQUIRED RAW MOVE: "
        f"+{PRIMARY_RAW_TARGET_PCT:.2f}%"
    )


def print_dataset_health(rows):
    banner("R9.1 PROSPECTIVE DATASET HEALTH")

    print(
        f"ROWS AFTER CUTOFF: {len(rows)}"
    )

    if not rows:
        print(
            "NO PROSPECTIVE ROWS AVAILABLE YET."
        )
        return

    long_count = sum(
        1
        for row in rows
        if str(row["direction"]).upper() == "LONG"
    )

    short_count = sum(
        1
        for row in rows
        if str(row["direction"]).upper() == "SHORT"
    )

    print(
        f"LONG: {long_count}"
    )

    print(
        f"SHORT: {short_count}"
    )

    print(
        f"FIRST ROW: {rows[0]['created_at']}"
    )

    print(
        f"LAST ROW:  {rows[-1]['created_at']}"
    )

    for horizon in (
        "1m",
        "5m",
        "10m",
        "30m",
    ):

        column = return_column(horizon)

        available = sum(
            1
            for row in rows
            if safe_float(row.get(column))
            is not None
        )

        print(
            f"{horizon} RETURNS AVAILABLE: "
            f"{available}"
        )


def print_rule_result(
    rule,
    baseline_metrics,
    rule_metrics,
    matches,
):
    banner(
        f"{rule['id']} | "
        f"ORIGINAL R9 RANK {rule['original_rank']} | "
        f"{rule['direction']} | "
        f"{rule['horizon']}"
    )

    print(
        f"RULE: {rule_text(rule)}"
    )

    print(
        "RULE STATUS: FROZEN - NO RETUNING"
    )

    print(
        "HISTORICAL R9 REFERENCE:"
    )

    print(
        "  NET_EXPECTANCY@0.05%="
        f"{rule['historical_cost_005_expectancy']:+.5f}%"
    )

    print(
        "  PF@0.05%="
        f"{rule['historical_cost_005_pf']:.3f}"
    )

    print()

    if baseline_metrics is None:
        print(
            "PROSPECTIVE BASELINE: "
            "NO MATURE RETURNS YET"
        )

    else:
        print(
            "PROSPECTIVE BASELINE:"
        )

        print(
            f"  N={baseline_metrics['n']}"
        )

        print(
            "  RAW_EXPECTANCY="
            f"{baseline_metrics['raw_expectancy']:+.5f}%"
        )

        print(
            "  NET_EXPECTANCY@0.05%="
            f"{baseline_metrics['net_expectancy']:+.5f}%"
        )

        print(
            "  NET_POSITIVE_RATE="
            f"{baseline_metrics['net_positive_rate']:.2f}%"
        )

        print(
            "  +0.05% NET TARGET HIT="
            f"{baseline_metrics['target_hit_rate']:.2f}%"
        )

        print(
            "  PF="
            f"{format_number(baseline_metrics['profit_factor'], 3)}"
        )

    print()

    if rule_metrics is None:
        print(
            "PROSPECTIVE RULE:"
        )

        print(
            "  N=0"
        )

        print(
            "  STATUS: WAITING FOR MATCHES"
        )

        return

    print(
        "PROSPECTIVE RULE:"
    )

    print(
        f"  N={rule_metrics['n']}"
    )

    print(
        "  RAW_EXPECTANCY="
        f"{rule_metrics['raw_expectancy']:+.5f}%"
    )

    print(
        "  RAW_MEDIAN="
        f"{rule_metrics['raw_median']:+.5f}%"
    )

    print(
        "  NET_EXPECTANCY@0.05%="
        f"{rule_metrics['net_expectancy']:+.5f}%"
    )

    print(
        "  NET_MEDIAN@0.05%="
        f"{rule_metrics['net_median']:+.5f}%"
    )

    print(
        "  NET_POSITIVE_RATE="
        f"{rule_metrics['net_positive_rate']:.2f}%"
    )

    print(
        "  +0.05% NET TARGET HIT="
        f"{rule_metrics['target_hit_rate']:.2f}%"
    )

    print(
        "  PF@0.05%="
        f"{format_number(rule_metrics['profit_factor'], 3)}"
    )

    if baseline_metrics is not None:

        expectancy_lift = (
            rule_metrics["net_expectancy"]
            - baseline_metrics["net_expectancy"]
        )

        target_lift = (
            rule_metrics["target_hit_rate"]
            - baseline_metrics["target_hit_rate"]
        )

        print(
            "  NET_EXPECTANCY LIFT="
            f"{expectancy_lift:+.5f}pp"
        )

        print(
            "  TARGET HIT LIFT="
            f"{target_lift:+.2f}pp"
        )

    print()

    print(
        "COST STRESS:"
    )

    raw_returns = []

    column = return_column(
        rule["horizon"]
    )

    for row in matches:
        value = safe_float(
            row.get(column)
        )

        if value is not None:
            raw_returns.append(value)

    for cost in COST_SCENARIOS_PCT:

        metrics = calculate_metrics(
            raw_returns,
            cost,
        )

        if metrics is None:
            continue

        print(
            f"  COST={cost:.2f}%"
            f" | NET_EXPECTANCY="
            f"{metrics['net_expectancy']:+.5f}%"
            f" | NET_POSITIVE="
            f"{metrics['net_positive_rate']:.2f}%"
            f" | TARGET_HIT="
            f"{metrics['target_hit_rate']:.2f}%"
            f" | PF="
            f"{format_number(metrics['profit_factor'], 3)}"
        )

    print()

    if rule_metrics["n"] < MIN_SAMPLE:

        print(
            "STATUS: INSUFFICIENT PROSPECTIVE SAMPLE"
        )

        return

    if baseline_metrics is None:

        print(
            "STATUS: BASELINE NOT AVAILABLE"
        )

        return

    expectancy_lift = (
        rule_metrics["net_expectancy"]
        - baseline_metrics["net_expectancy"]
    )

    target_lift = (
        rule_metrics["target_hit_rate"]
        - baseline_metrics["target_hit_rate"]
    )

    pf = rule_metrics["profit_factor"]

    if (
        rule_metrics["net_expectancy"] > 0
        and expectancy_lift > 0
        and target_lift > 0
        and pf is not None
        and pf > 1.0
    ):
        print(
            "STATUS: PROSPECTIVE NET EDGE CURRENTLY POSITIVE"
        )

    elif (
        expectancy_lift > 0
        and target_lift > 0
    ):
        print(
            "STATUS: BETTER THAN BASELINE BUT "
            "NOT YET NET-PROFITABLE"
        )

    else:
        print(
            "STATUS: NOT CONFIRMED PROSPECTIVELY"
        )


# =============================================================================
# MAIN
# =============================================================================

def main():
    connection = None

    try:
        print_startup()

        # -------------------------------------------------------------
        # Hard safety assertions
        # -------------------------------------------------------------

        assert DATABASE_WRITES is False
        assert TELEGRAM_SENDING is False
        assert TRADE_EXECUTION is False
        assert PRODUCTION_MODIFICATION is False
        assert AI_CALLS is False
        assert RULE_SEARCH is False
        assert RULE_RETUNING is False

        print()
        print("SAFETY CHECK: PASS")

        # -------------------------------------------------------------
        # Database
        # -------------------------------------------------------------

        connection = connect_database()

        print(
            "DATABASE CONNECTION: READY"
        )

        print(
            "DATABASE SESSION: READ ONLY"
        )

        rows = load_prospective_rows(
            connection
        )

        print_dataset_health(rows)

        if not rows:
            banner("R9.1 STATUS")

            print(
                "STATUS: WAITING FOR NEW "
                "POST-R9 PROSPECTIVE DATA"
            )

            print(
                "NO RULES CHANGED."
            )

            return

        # -------------------------------------------------------------
        # Frozen prospective validation
        # -------------------------------------------------------------

        results_summary = []

        for rule in LOCKED_RULES:

            baseline_raw = baseline_returns(
                rows,
                rule["direction"],
                rule["horizon"],
            )

            baseline_metrics = (
                calculate_metrics(
                    baseline_raw,
                    PRIMARY_COST_PCT,
                )
            )

            rule_raw, matches = matched_returns(
                rows,
                rule,
            )

            rule_metrics = (
                calculate_metrics(
                    rule_raw,
                    PRIMARY_COST_PCT,
                )
            )

            print_rule_result(
                rule,
                baseline_metrics,
                rule_metrics,
                matches,
            )

            if rule_metrics is not None:

                baseline_expectancy = (
                    baseline_metrics[
                        "net_expectancy"
                    ]
                    if baseline_metrics
                    else None
                )

                expectancy_lift = (
                    rule_metrics[
                        "net_expectancy"
                    ]
                    - baseline_expectancy
                    if baseline_expectancy
                    is not None
                    else None
                )

                results_summary.append({
                    "rule": rule,
                    "metrics": rule_metrics,
                    "expectancy_lift":
                        expectancy_lift,
                })

        # -------------------------------------------------------------
        # Summary
        # -------------------------------------------------------------

        banner(
            "R9.1 LOCKED PROSPECTIVE SUMMARY"
        )

        if not results_summary:

            print(
                "NO LOCKED RULE HAS A "
                "MATURE PROSPECTIVE MATCH YET."
            )

        else:

            results_summary.sort(
                key=lambda item: (
                    item["metrics"][
                        "net_expectancy"
                    ]
                ),
                reverse=True,
            )

            for rank, item in enumerate(
                results_summary,
                start=1,
            ):

                rule = item["rule"]
                metrics = item["metrics"]

                lift = item[
                    "expectancy_lift"
                ]

                lift_text = (
                    f"{lift:+.5f}pp"
                    if lift is not None
                    else "N/A"
                )

                print(
                    f"{rank}. "
                    f"{rule['id']} | "
                    f"{rule['direction']} "
                    f"{rule['horizon']} | "
                    f"N={metrics['n']} | "
                    f"NET_EXPECTANCY@0.05%="
                    f"{metrics['net_expectancy']:+.5f}% | "
                    f"LIFT={lift_text} | "
                    f"TARGET_HIT="
                    f"{metrics['target_hit_rate']:.2f}% | "
                    f"PF="
                    f"{format_number(metrics['profit_factor'], 3)}"
                )

        # -------------------------------------------------------------
        # Guardrails
        # -------------------------------------------------------------

        banner("R9.1 GUARDRAILS")

        print(
            "1. THIS IS PROSPECTIVE RESEARCH, "
            "NOT LIVE TRADING AUTHORIZATION."
        )

        print(
            "2. ONLY OBSERVATIONS CREATED AFTER "
            "THE FROZEN CUTOFF ARE USED."
        )

        print(
            "3. RULES AND THRESHOLDS ARE FROZEN."
        )

        print(
            "4. NO SEARCH OR RETUNING OCCURS."
        )

        print(
            "5. MISSING R9 RANKS ARE NOT "
            "RECONSTRUCTED OR GUESSED."
        )

        print(
            "6. 0.05% ROUND-TRIP COST IS A "
            "RESEARCH ASSUMPTION, NOT A CLAIMED "
            "BITGET FEE RATE."
        )

        print(
            "7. FUNDING, SPREAD, SLIPPAGE, "
            "LATENCY, LIQUIDATION AND FILL QUALITY "
            "ARE NOT FULLY MODELLED."
        )

        print(
            "8. LEVERAGE DOES NOT CREATE EDGE "
            "AND IS NOT USED IN THIS VALIDATION."
        )

        print(
            "9. LONG AND SHORT OBSERVATIONS MAY "
            "COME FROM THE SAME MARKET SNAPSHOT "
            "AND ARE NOT INDEPENDENT TRADES."
        )

        print(
            "10. NO BOT 2.0 PRODUCTION CHANGE "
            "IS AUTHORIZED BY THIS SCRIPT."
        )

        banner("R9.1 FINAL STATUS")

        print(
            "STATUS: R9.1 LOCKED PROSPECTIVE "
            "VALIDATION COMPLETE"
        )

        print(
            "DATABASE REMAINED READ ONLY"
        )

        print(
            "NO WRITES; NO SENDS; NO TRADES; "
            "NO PRODUCTION CHANGES; NO AI CALLS"
        )

    except Exception as exc:

        banner("R9.1 ERROR")

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

                print(
                    "DATABASE CONNECTION: CLOSED"
                )

            except Exception:
                pass


if __name__ == "__main__":
    main()
