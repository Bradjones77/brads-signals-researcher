import os
import math
import statistics

import psycopg2


# ============================================================
# BRAD'S SIGNALS RESEARCHER
# R8.1 — LOCKED PATTERN PROFITABILITY & COST VALIDATION
# ============================================================

VERSION = "R8.1-LOCKED-PATTERN-PROFITABILITY-VALIDATION"

DATABASE_URL = os.getenv("SIGNALS2_DATABASE_URL")

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False
RULE_SEARCH = False
RULE_RETUNING = False
LOCKED_R7_RULES = True

# Research cost assumptions only.
# These are NOT claimed Bitget fee rates.
COST_SCENARIOS_PCT = (
    0.00,
    0.02,
    0.05,
    0.10,
    0.15,
    0.20,
)

MIN_SAMPLE = 30


# ============================================================
# LOCKED R7 RULES
#
# IMPORTANT:
# These thresholds are frozen.
# R8.1 MUST NOT search for better thresholds.
# ============================================================

LOCKED_RULES = [

    {
        "id": "R7L01",
        "direction": "LONG",
        "horizon": "30m",
        "description":
            "[30m_resistance_distance <= 0.019869] AND "
            "[1h_macd_acceleration <= -0.045800]",
        "conditions": [
            ("30m_resistance_distance", "<=", 0.019869),
            ("1h_macd_acceleration", "<=", -0.045800),
        ],
    },

    {
        "id": "R7L02",
        "direction": "LONG",
        "horizon": "1m",
        "description":
            "30m_bull_breakout == True",
        "conditions": [
            ("30m_bull_breakout", "==", True),
        ],
    },

    {
        "id": "R7L03",
        "direction": "LONG",
        "horizon": "30m",
        "description":
            "[5m_bear_breakout == True] AND "
            "[30m_volume_acceleration <= -32.671162]",
        "conditions": [
            ("5m_bear_breakout", "==", True),
            ("30m_volume_acceleration", "<=", -32.671162),
        ],
    },

    {
        "id": "R7L04",
        "direction": "SHORT",
        "horizon": "1m",
        "description":
            "[1h_bear_breakout == True] AND "
            "[30m_bear_breakout == True]",
        "conditions": [
            ("1h_bear_breakout", "==", True),
            ("30m_bear_breakout", "==", True),
        ],
    },

    {
        "id": "R7L05",
        "direction": "SHORT",
        "horizon": "1m",
        "description":
            "[1h_bear_breakout == True] AND "
            "[5m_momentum_acceleration >= 0.045672]",
        "conditions": [
            ("1h_bear_breakout", "==", True),
            ("5m_momentum_acceleration", ">=", 0.045672),
        ],
    },

    {
        "id": "R7L06",
        "direction": "LONG",
        "horizon": "1m",
        "description":
            "[5m_bear_breakout == True] AND "
            "[1h_macd_acceleration >= 0.022309]",
        "conditions": [
            ("5m_bear_breakout", "==", True),
            ("1h_macd_acceleration", ">=", 0.022309),
        ],
    },

    {
        "id": "R7L07",
        "direction": "SHORT",
        "horizon": "10m",
        "description":
            "[30m_atr_pct >= 1.491912] AND "
            "[15m_volume_acceleration <= -36.185203]",
        "conditions": [
            ("30m_atr_pct", ">=", 1.491912),
            ("15m_volume_acceleration", "<=", -36.185203),
        ],
    },

    {
        "id": "R7L08",
        "direction": "LONG",
        "horizon": "1m",
        "description":
            "[1h_macd_acceleration >= 0.022309] AND "
            "[15m_momentum_3 <= -0.391560]",
        "conditions": [
            ("1h_macd_acceleration", ">=", 0.022309),
            ("15m_momentum_3", "<=", -0.391560),
        ],
    },

    {
        "id": "R7L09",
        "direction": "LONG",
        "horizon": "30m",
        "description":
            "1h_macd_acceleration <= -0.045800",
        "conditions": [
            ("1h_macd_acceleration", "<=", -0.045800),
        ],
    },

    {
        "id": "R7L10",
        "direction": "SHORT",
        "horizon": "5m",
        "description":
            "[5m_momentum_6 >= 0.222632] AND "
            "[30m_momentum_acceleration <= -0.116826]",
        "conditions": [
            ("5m_momentum_6", ">=", 0.222632),
            ("30m_momentum_acceleration", "<=", -0.116826),
        ],
    },

    {
        "id": "R7L11",
        "direction": "LONG",
        "horizon": "10m",
        "description":
            "5m_bull_breakout == True",
        "conditions": [
            ("5m_bull_breakout", "==", True),
        ],
    },

    {
        "id": "R7L12",
        "direction": "LONG",
        "horizon": "10m",
        "description":
            "5m_resistance_distance >= 0.095293",
        "conditions": [
            ("5m_resistance_distance", ">=", 0.095293),
        ],
    },
]


# ============================================================
# HELPERS
# ============================================================

def separator():
    print("=" * 100)


def safe_float(value):

    try:
        value = float(value)

        if not math.isfinite(value):
            return None

        return value

    except (TypeError, ValueError):
        return None


def mean(values):

    values = [
        x for x in values
        if x is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def median(values):

    values = [
        x for x in values
        if x is not None
    ]

    if not values:
        return None

    return statistics.median(values)


def fmt_pct(value):

    if value is None:
        return "N/A"

    return f"{value:.5f}%"


def fmt_num(value, digits=3):

    if value is None:
        return "N/A"

    if value == float("inf"):
        return "INF"

    return f"{value:.{digits}f}"


def win_rate(values):

    if not values:
        return None

    return (
        sum(
            1 for x in values
            if x > 0
        )
        / len(values)
        * 100.0
    )


def profit_factor(values):

    wins = sum(
        x for x in values
        if x > 0
    )

    losses = abs(
        sum(
            x for x in values
            if x < 0
        )
    )

    if losses == 0:

        if wins > 0:
            return float("inf")

        return None

    return wins / losses


# ============================================================
# FEATURE HANDLING
# ============================================================

def feature_value(features, name):

    if not isinstance(features, dict):
        return None

    return features.get(name)


def compare(value, operator, target):

    if operator == "==":

        if isinstance(target, bool):
            return bool(value) is target

        return value == target

    numeric = safe_float(value)

    if numeric is None:
        return False

    if operator == "<=":
        return numeric <= target

    if operator == ">=":
        return numeric >= target

    if operator == "<":
        return numeric < target

    if operator == ">":
        return numeric > target

    raise ValueError(
        f"Unsupported operator: {operator}"
    )


def rule_matches(row, rule):

    if row["direction"] != rule["direction"]:
        return False

    features = row["features"]

    for (
        feature_name,
        operator,
        target,
    ) in rule["conditions"]:

        value = feature_value(
            features,
            feature_name,
        )

        if value is None:
            return False

        if not compare(
            value,
            operator,
            target,
        ):
            return False

    return True


# ============================================================
# DATABASE
# ============================================================

def connect():

    if not DATABASE_URL:

        raise RuntimeError(
            "SIGNALS2_DATABASE_URL is not configured."
        )

    conn = psycopg2.connect(
        DATABASE_URL
    )

    conn.autocommit = False

    cur = conn.cursor()

    cur.execute(
        "SET TRANSACTION READ ONLY"
    )

    cur.close()

    return conn


def load_rows(conn):

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,
            o.final_confidence,

            o.combined_features,
            o.technical_features,

            o.strategy_version,

            out.return_1m_pct,
            out.return_5m_pct,
            out.return_10m_pct,
            out.return_30m_pct

        FROM signals2_opportunities o

        INNER JOIN signals2_outcomes out
            ON out.opportunity_id = o.opportunity_id

        WHERE
            UPPER(o.direction)
                IN ('LONG', 'SHORT')

            AND (
                o.strategy_version IS NULL
                OR (
                    UPPER(o.strategy_version)
                        NOT LIKE '%%TEST%%'

                    AND UPPER(o.strategy_version)
                        NOT LIKE '%%DIAGNOSTIC%%'

                    AND UPPER(o.strategy_version)
                        NOT LIKE '%%SYNTHETIC%%'
                )
            )

            AND (
                out.return_1m_pct IS NOT NULL
                OR out.return_5m_pct IS NOT NULL
                OR out.return_10m_pct IS NOT NULL
                OR out.return_30m_pct IS NOT NULL
            )

        ORDER BY
            o.created_at ASC
        """
    )

    raw = cur.fetchall()

    cur.close()

    rows = []

    for item in raw:

        combined = item[5]
        technical = item[6]

        # Same preference used by R7:
        # combined_features first,
        # technical_features fallback.

        if (
            isinstance(combined, dict)
            and combined
        ):
            features = combined

        elif isinstance(technical, dict):
            features = technical

        else:
            features = {}

        rows.append(
            {
                "opportunity_id": item[0],
                "created_at": item[1],
                "symbol": str(
                    item[2]
                ).upper(),
                "direction": str(
                    item[3]
                ).upper(),
                "final_confidence":
                    safe_float(item[4]),
                "features": features,
                "strategy_version": item[7],

                "return_1m_pct":
                    safe_float(item[8]),

                "return_5m_pct":
                    safe_float(item[9]),

                "return_10m_pct":
                    safe_float(item[10]),

                "return_30m_pct":
                    safe_float(item[11]),
            }
        )

    return rows


# ============================================================
# RULE PERFORMANCE
# ============================================================

def analyse_rule(rows, rule):

    field = (
        f"return_{rule['horizon']}_pct"
    )

    matched = []

    for row in rows:

        if not rule_matches(
            row,
            rule,
        ):
            continue

        value = row.get(field)

        if value is None:
            continue

        matched.append(
            {
                "created_at":
                    row["created_at"],
                "symbol":
                    row["symbol"],
                "return":
                    value,
            }
        )

    returns = [
        item["return"]
        for item in matched
    ]

    return matched, returns


def baseline_for_rule(rows, rule):

    field = (
        f"return_{rule['horizon']}_pct"
    )

    return [
        row[field]
        for row in rows
        if (
            row["direction"]
            == rule["direction"]

            and row[field]
            is not None
        )
    ]


def print_rule_result(
    rows,
    rule,
):

    matched, returns = analyse_rule(
        rows,
        rule,
    )

    baseline = baseline_for_rule(
        rows,
        rule,
    )

    separator()

    print(
        f"{rule['id']} | "
        f"{rule['direction']} | "
        f"{rule['horizon']}"
    )

    print(
        rule["description"]
    )

    print()

    print(
        f"MATCHED N: {len(returns)}"
    )

    if not returns:

        print(
            "NO MATCHED OUTCOMES"
        )

        return None

    raw_rate = win_rate(
        returns
    )

    baseline_rate = win_rate(
        baseline
    )

    lift = None

    if (
        raw_rate is not None
        and baseline_rate is not None
    ):
        lift = (
            raw_rate
            - baseline_rate
        )

    print(
        f"RAW WIN RATE: "
        f"{raw_rate:.2f}%"
    )

    print(
        f"DIRECTION/HORIZON BASELINE: "
        f"{baseline_rate:.2f}%"
    )

    print(
        f"RAW LIFT: "
        f"{lift:+.2f}pp"
    )

    print(
        f"RAW AVG RETURN: "
        f"{fmt_pct(mean(returns))}"
    )

    print(
        f"RAW MEDIAN RETURN: "
        f"{fmt_pct(median(returns))}"
    )

    print()

    print(
        "COST SENSITIVITY:"
    )

    results = {}

    for cost in COST_SCENARIOS_PCT:

        net = [
            value - cost
            for value in returns
        ]

        rate = win_rate(
            net
        )

        expectancy = mean(
            net
        )

        pf = profit_factor(
            net
        )

        results[cost] = {
            "win_rate": rate,
            "expectancy": expectancy,
            "profit_factor": pf,
        }

        print(
            f"  COST={cost:.2f}% | "
            f"NET_WIN_RATE={rate:.2f}% | "
            f"EXPECTANCY={fmt_pct(expectancy)} | "
            f"PF={fmt_num(pf)}"
        )

    return {
        "rule": rule,
        "n": len(returns),
        "raw_win_rate": raw_rate,
        "baseline_rate": baseline_rate,
        "lift": lift,
        "raw_expectancy":
            mean(returns),
        "cost_results": results,
    }


# ============================================================
# COMBINED LOCKED PORTFOLIO
# ============================================================

def build_unique_matches(rows):

    matches = {}

    for rule in LOCKED_RULES:

        field = (
            f"return_{rule['horizon']}_pct"
        )

        for row in rows:

            if not rule_matches(
                row,
                rule,
            ):
                continue

            value = row.get(field)

            if value is None:
                continue

            key = (
                rule["id"],
                row["opportunity_id"],
                rule["horizon"],
            )

            matches[key] = {
                "rule_id":
                    rule["id"],
                "opportunity_id":
                    row["opportunity_id"],
                "created_at":
                    row["created_at"],
                "symbol":
                    row["symbol"],
                "direction":
                    rule["direction"],
                "horizon":
                    rule["horizon"],
                "return":
                    value,
            }

    return list(
        matches.values()
    )


def print_combined_summary(
    rows,
):

    separator()
    print(
        "R8.1 COMBINED LOCKED-RULE RESEARCH SUMMARY"
    )
    separator()

    matches = build_unique_matches(
        rows
    )

    print(
        f"RULE-MATCH OBSERVATIONS: "
        f"{len(matches)}"
    )

    if not matches:

        print(
            "NO LOCKED RULE MATCHES AVAILABLE"
        )

        return

    for direction in (
        "LONG",
        "SHORT",
        "ALL",
    ):

        if direction == "ALL":
            subset = matches

        else:
            subset = [
                item
                for item in matches
                if (
                    item["direction"]
                    == direction
                )
            ]

        values = [
            item["return"]
            for item in subset
        ]

        if not values:
            continue

        print()
        print(
            f"{direction}: N={len(values)}"
        )

        print(
            f"  RAW_WIN_RATE="
            f"{win_rate(values):.2f}%"
        )

        print(
            f"  RAW_EXPECTANCY="
            f"{fmt_pct(mean(values))}"
        )

        print(
            f"  RAW_MEDIAN="
            f"{fmt_pct(median(values))}"
        )

        for cost in COST_SCENARIOS_PCT:

            net = [
                value - cost
                for value in values
            ]

            print(
                f"  COST={cost:.2f}% | "
                f"NET_WIN_RATE="
                f"{win_rate(net):.2f}% | "
                f"EXPECTANCY="
                f"{fmt_pct(mean(net))} | "
                f"PF="
                f"{fmt_num(profit_factor(net))}"
            )


# ============================================================
# RANKING
# ============================================================

def print_research_ranking(
    results,
):

    separator()
    print(
        "R8.1 LOCKED RULE RANKING"
    )
    print(
        "RANKED BY 0.05% COST-ADJUSTED EXPECTANCY"
    )
    print(
        "NO RULES ARE CREATED, REMOVED OR RETUNED HERE"
    )
    separator()

    valid = [
        result
        for result in results
        if (
            result is not None
            and result["n"] >= MIN_SAMPLE
        )
    ]

    valid.sort(
        key=lambda x:
            x["cost_results"][
                0.05
            ]["expectancy"]
            if (
                x["cost_results"][
                    0.05
                ]["expectancy"]
                is not None
            )
            else -999999,
        reverse=True,
    )

    if not valid:

        print(
            "NO RULE HAS THE MINIMUM SAMPLE."
        )

        return

    for rank, result in enumerate(
        valid,
        start=1,
    ):

        rule = result["rule"]

        cost_result = (
            result["cost_results"][
                0.05
            ]
        )

        print(
            f"{rank}. "
            f"{rule['id']} | "
            f"{rule['direction']} "
            f"{rule['horizon']} | "
            f"N={result['n']} | "
            f"RAW_RATE="
            f"{result['raw_win_rate']:.2f}% | "
            f"RAW_LIFT="
            f"{result['lift']:+.2f}pp | "
            f"NET_EXPECTANCY@0.05%="
            f"{fmt_pct(cost_result['expectancy'])} | "
            f"PF="
            f"{fmt_num(cost_result['profit_factor'])}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    separator()

    print(
        "BRADS-SIGNALS-RESEARCHER"
    )

    separator()

    print(
        f"RESEARCH VERSION: {VERSION}"
    )

    print(
        f"DATABASE WRITES: "
        f"{DATABASE_WRITES}"
    )

    print(
        f"TELEGRAM SENDING: "
        f"{TELEGRAM_SENDING}"
    )

    print(
        f"TRADE EXECUTION: "
        f"{TRADE_EXECUTION}"
    )

    print(
        f"PRODUCTION MODIFICATION: "
        f"{PRODUCTION_MODIFICATION}"
    )

    print(
        f"AI CALLS: "
        f"{AI_CALLS}"
    )

    print(
        f"RULE SEARCH: "
        f"{RULE_SEARCH}"
    )

    print(
        f"RULE RETUNING: "
        f"{RULE_RETUNING}"
    )

    print(
        f"LOCKED R7 RULES: "
        f"{LOCKED_R7_RULES}"
    )

    print(
        f"LOCKED RULE COUNT: "
        f"{len(LOCKED_RULES)}"
    )

    print()

    print(
        "PURPOSE:"
    )

    print(
        "Test whether the already-locked R7 "
        "fast-move patterns retain enough return "
        "to survive hypothetical trading costs."
    )

    print()

    print(
        "THIS SCRIPT DOES NOT MODIFY R7.1."
    )

    print(
        "THIS SCRIPT DOES NOT AUTHORIZE "
        "A PRODUCTION STRATEGY CHANGE."
    )

    conn = None

    try:

        conn = connect()

        print(
            "DATABASE CONNECTION: READY"
        )

        print(
            "DATABASE SESSION: READ ONLY"
        )

        rows = load_rows(
            conn
        )

        separator()

        print(
            "R8.1 DATASET HEALTH"
        )

        separator()

        print(
            f"REAL FAST-OUTCOME ROWS: "
            f"{len(rows)}"
        )

        print(
            "LONG: "
            f"{sum(1 for x in rows if x['direction'] == 'LONG')}"
        )

        print(
            "SHORT: "
            f"{sum(1 for x in rows if x['direction'] == 'SHORT')}"
        )

        results = []

        for rule in LOCKED_RULES:

            result = print_rule_result(
                rows,
                rule,
            )

            results.append(
                result
            )

        print_combined_summary(
            rows
        )

        print_research_ranking(
            results
        )

        separator()

        print(
            "R8.1 FINAL STATUS"
        )

        separator()

        print(
            "STATUS: R8.1 LOCKED PATTERN "
            "PROFITABILITY VALIDATION COMPLETE"
        )

        print(
            "DATABASE REMAINED READ ONLY"
        )

        print(
            "NO WRITES; NO SENDS; NO TRADES; "
            "NO PRODUCTION CHANGES; NO AI CALLS"
        )

        print(
            "NO RULE SEARCH OR RETUNING PERFORMED"
        )

        print()

        print(
            "GUARDRAILS:"
        )

        print(
            "1. R7 rules remain research leads, not proven trading rules."
        )

        print(
            "2. This reuses historical data already involved in R7."
        )

        print(
            "3. R7.1 remains the independent prospective validation."
        )

        print(
            "4. Cost values are hypothetical research assumptions."
        )

        print(
            "5. Funding, liquidation, margin, latency and fill quality "
            "are not modelled."
        )

        print(
            "6. Overlapping rule matches are not independent trades."
        )

        print(
            "7. No production change is authorized by R8.1."
        )

    finally:

        if conn is not None:

            conn.rollback()

            conn.close()

            print(
                "DATABASE CONNECTION: CLOSED"
            )


if __name__ == "__main__":
    main()
