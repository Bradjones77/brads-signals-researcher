import os
import math
import statistics
from collections import defaultdict

import psycopg2


# ============================================================
# BRAD'S SIGNALS RESEARCHER
# R9 — NET EDGE / MOVE SIZE DISCOVERY
# ============================================================

VERSION = "R9-NET-EDGE-MOVE-SIZE-DISCOVERY"

DATABASE_URL = os.getenv("SIGNALS2_DATABASE_URL")

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False

# ============================================================
# RESEARCH SETTINGS
# ============================================================

HORIZONS = ("1m", "5m", "10m", "30m")

# Hypothetical round-trip cost assumptions.
# These are research assumptions, NOT claimed Bitget fees.
COST_SCENARIOS_PCT = (
    0.02,
    0.05,
    0.10,
)

PRIMARY_COST_PCT = 0.05

# Minimum direction-adjusted move AFTER the primary cost.
# Example:
# 0.05 cost + 0.05 net target = raw move >= 0.10%.
NET_MOVE_TARGETS_PCT = (
    0.00,
    0.05,
    0.10,
    0.20,
)

PRIMARY_NET_TARGET_PCT = 0.05

MIN_SAMPLE = 40

# Chronological discovery / holdout split.
DISCOVERY_FRACTION = 0.70

# Keep output manageable.
TOP_SINGLE_FEATURES_PER_GROUP = 15
TOP_PAIR_FEATURES_PER_GROUP = 15

# Limit pair construction to strongest single-feature leads.
PAIR_SOURCE_LIMIT = 12

# Quantile thresholds used to generate candidate numeric rules.
QUANTILES = (
    0.20,
    0.35,
    0.50,
    0.65,
    0.80,
)

EXCLUDED_FEATURE_TOKENS = (
    "confidence",
    "decision",
    "eligible",
    "selected",
    "signal",
    "sent",
    "outcome",
    "return",
    "future",
    "price_",
    "mfe",
    "mae",
)


# ============================================================
# BASIC HELPERS
# ============================================================

def separator():
    print("=" * 110)


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
        value
        for value in values
        if value is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def median(values):
    values = [
        value
        for value in values
        if value is not None
    ]

    if not values:
        return None

    return statistics.median(values)


def percentile(sorted_values, q):
    if not sorted_values:
        return None

    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (
        (len(sorted_values) - 1)
        * q
    )

    lower = int(
        math.floor(position)
    )

    upper = int(
        math.ceil(position)
    )

    if lower == upper:
        return sorted_values[lower]

    fraction = (
        position - lower
    )

    return (
        sorted_values[lower]
        + (
            sorted_values[upper]
            - sorted_values[lower]
        )
        * fraction
    )


def fmt_pct(value, digits=5):
    if value is None:
        return "N/A"

    return f"{value:.{digits}f}%"


def fmt_number(value, digits=3):
    if value is None:
        return "N/A"

    if value == float("inf"):
        return "INF"

    return f"{value:.{digits}f}"


def profit_factor(values):
    if not values:
        return None

    positive = sum(
        value
        for value in values
        if value > 0
    )

    negative = abs(
        sum(
            value
            for value in values
            if value < 0
        )
    )

    if negative == 0:
        if positive > 0:
            return float("inf")

        return None

    return positive / negative


def positive_rate(values):
    if not values:
        return None

    return (
        sum(
            1
            for value in values
            if value > 0
        )
        / len(values)
        * 100.0
    )


def target_hit_rate(
    raw_returns,
    cost_pct,
    net_target_pct,
):
    if not raw_returns:
        return None

    required_raw = (
        cost_pct
        + net_target_pct
    )

    return (
        sum(
            1
            for value in raw_returns
            if value >= required_raw
        )
        / len(raw_returns)
        * 100.0
    )


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

    cursor = conn.cursor()

    cursor.execute(
        "SET TRANSACTION READ ONLY"
    )

    cursor.close()

    return conn


def load_rows(conn):
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            UPPER(o.direction),
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
            o.created_at ASC,
            o.opportunity_id ASC
        """
    )

    raw_rows = cursor.fetchall()

    cursor.close()

    rows = []

    for item in raw_rows:
        combined_features = item[4]
        technical_features = item[5]

        if (
            isinstance(combined_features, dict)
            and combined_features
        ):
            features = combined_features

        elif isinstance(
            technical_features,
            dict,
        ):
            features = technical_features

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
                "features": features,
                "strategy_version": item[6],

                "return_1m_pct":
                    safe_float(item[7]),

                "return_5m_pct":
                    safe_float(item[8]),

                "return_10m_pct":
                    safe_float(item[9]),

                "return_30m_pct":
                    safe_float(item[10]),
            }
        )

    return rows


# ============================================================
# FEATURE SAFETY
# ============================================================

def feature_allowed(name):
    lowered = str(
        name
    ).lower()

    for token in EXCLUDED_FEATURE_TOKENS:
        if token in lowered:
            return False

    return True


def get_feature(
    row,
    feature_name,
):
    features = row.get(
        "features",
        {}
    )

    if not isinstance(
        features,
        dict,
    ):
        return None

    return features.get(
        feature_name
    )


def collect_feature_catalog(rows):
    numeric_values = defaultdict(
        list
    )

    boolean_counts = defaultdict(
        lambda: {
            True: 0,
            False: 0,
        }
    )

    for row in rows:
        features = row.get(
            "features",
            {}
        )

        if not isinstance(
            features,
            dict,
        ):
            continue

        for name, value in features.items():
            if not feature_allowed(
                name
            ):
                continue

            if isinstance(
                value,
                bool,
            ):
                boolean_counts[
                    name
                ][value] += 1

                continue

            numeric = safe_float(
                value
            )

            if numeric is None:
                continue

            numeric_values[
                name
            ].append(
                numeric
            )

    return (
        numeric_values,
        boolean_counts,
    )


# ============================================================
# RULE GENERATION
# ============================================================

def build_single_rules(
    discovery_rows,
):
    numeric_values, boolean_counts = (
        collect_feature_catalog(
            discovery_rows
        )
    )

    rules = []

    for feature_name, values in (
        numeric_values.items()
    ):
        if len(values) < MIN_SAMPLE:
            continue

        sorted_values = sorted(
            values
        )

        thresholds = []

        for q in QUANTILES:
            threshold = percentile(
                sorted_values,
                q,
            )

            if threshold is None:
                continue

            thresholds.append(
                threshold
            )

        unique_thresholds = []

        for threshold in thresholds:
            if not any(
                math.isclose(
                    threshold,
                    existing,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                for existing
                in unique_thresholds
            ):
                unique_thresholds.append(
                    threshold
                )

        for threshold in (
            unique_thresholds
        ):
            rules.append(
                {
                    "type": "single",
                    "conditions": [
                        (
                            feature_name,
                            "<=",
                            threshold,
                        )
                    ],
                }
            )

            rules.append(
                {
                    "type": "single",
                    "conditions": [
                        (
                            feature_name,
                            ">=",
                            threshold,
                        )
                    ],
                }
            )

    for feature_name, counts in (
        boolean_counts.items()
    ):
        total = (
            counts[True]
            + counts[False]
        )

        if total < MIN_SAMPLE:
            continue

        if counts[True] >= MIN_SAMPLE:
            rules.append(
                {
                    "type": "single",
                    "conditions": [
                        (
                            feature_name,
                            "==",
                            True,
                        )
                    ],
                }
            )

        if counts[False] >= MIN_SAMPLE:
            rules.append(
                {
                    "type": "single",
                    "conditions": [
                        (
                            feature_name,
                            "==",
                            False,
                        )
                    ],
                }
            )

    return rules


# ============================================================
# RULE MATCHING
# ============================================================

def compare(
    value,
    operator,
    target,
):
    if operator == "==":
        if isinstance(
            target,
            bool,
        ):
            if not isinstance(
                value,
                bool,
            ):
                return False

            return value is target

        return value == target

    numeric = safe_float(
        value
    )

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

    return False


def row_matches_rule(
    row,
    rule,
):
    for (
        feature_name,
        operator,
        target,
    ) in rule["conditions"]:

        value = get_feature(
            row,
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


def rule_description(rule):
    parts = []

    for (
        feature_name,
        operator,
        target,
    ) in rule["conditions"]:

        if isinstance(
            target,
            bool,
        ):
            target_text = str(
                target
            )

        else:
            target_text = (
                f"{target:.6f}"
            )

        parts.append(
            f"[{feature_name} "
            f"{operator} "
            f"{target_text}]"
        )

    return " AND ".join(
        parts
    )


# ============================================================
# PERFORMANCE
# ============================================================

def get_returns(
    rows,
    horizon,
):
    field = (
        f"return_{horizon}_pct"
    )

    return [
        row[field]
        for row in rows
        if row.get(field)
        is not None
    ]


def evaluate_rule(
    rows,
    rule,
    horizon,
):
    field = (
        f"return_{horizon}_pct"
    )

    matched_returns = []

    for row in rows:
        value = row.get(
            field
        )

        if value is None:
            continue

        if not row_matches_rule(
            row,
            rule,
        ):
            continue

        matched_returns.append(
            value
        )

    if not matched_returns:
        return None

    raw_expectancy = mean(
        matched_returns
    )

    net_returns = [
        value
        - PRIMARY_COST_PCT
        for value
        in matched_returns
    ]

    net_expectancy = mean(
        net_returns
    )

    primary_hit_rate = (
        target_hit_rate(
            matched_returns,
            PRIMARY_COST_PCT,
            PRIMARY_NET_TARGET_PCT,
        )
    )

    return {
        "n":
            len(matched_returns),

        "raw_expectancy":
            raw_expectancy,

        "net_expectancy":
            net_expectancy,

        "raw_median":
            median(
                matched_returns
            ),

        "raw_positive_rate":
            positive_rate(
                matched_returns
            ),

        "primary_hit_rate":
            primary_hit_rate,

        "profit_factor":
            profit_factor(
                net_returns
            ),

        "returns":
            matched_returns,
    }


def baseline_metrics(
    rows,
    horizon,
):
    values = get_returns(
        rows,
        horizon,
    )

    if not values:
        return None

    net_values = [
        value
        - PRIMARY_COST_PCT
        for value
        in values
    ]

    return {
        "n":
            len(values),

        "raw_expectancy":
            mean(values),

        "net_expectancy":
            mean(net_values),

        "primary_hit_rate":
            target_hit_rate(
                values,
                PRIMARY_COST_PCT,
                PRIMARY_NET_TARGET_PCT,
            ),

        "profit_factor":
            profit_factor(
                net_values
            ),
    }


def candidate_score(
    metrics,
    baseline,
):
    if (
        metrics is None
        or baseline is None
    ):
        return None

    if metrics["n"] < MIN_SAMPLE:
        return None

    expectancy_lift = (
        metrics["net_expectancy"]
        - baseline["net_expectancy"]
    )

    hit_rate_lift = (
        metrics["primary_hit_rate"]
        - baseline["primary_hit_rate"]
    )

    # Discovery ranking only.
    # Higher net expectancy matters most.
    # Hit-rate lift adds secondary support.
    return (
        expectancy_lift * 100.0
        + hit_rate_lift * 0.10
    )


# ============================================================
# CHRONOLOGICAL SPLIT
# ============================================================

def chronological_split(rows):
    if not rows:
        return [], []

    split_index = int(
        len(rows)
        * DISCOVERY_FRACTION
    )

    split_index = max(
        1,
        min(
            split_index,
            len(rows) - 1,
        ),
    )

    return (
        rows[:split_index],
        rows[split_index:],
    )


# ============================================================
# SINGLE FEATURE DISCOVERY
# ============================================================

def discover_single_rules(
    discovery_rows,
    holdout_rows,
    direction,
    horizon,
):
    direction_discovery = [
        row
        for row in discovery_rows
        if (
            row["direction"]
            == direction
        )
    ]

    direction_holdout = [
        row
        for row in holdout_rows
        if (
            row["direction"]
            == direction
        )
    ]

    discovery_baseline = (
        baseline_metrics(
            direction_discovery,
            horizon,
        )
    )

    holdout_baseline = (
        baseline_metrics(
            direction_holdout,
            horizon,
        )
    )

    if (
        discovery_baseline is None
        or holdout_baseline is None
    ):
        return []

    candidate_rules = (
        build_single_rules(
            direction_discovery
        )
    )

    scored = []

    for rule in candidate_rules:
        discovery_metrics = (
            evaluate_rule(
                direction_discovery,
                rule,
                horizon,
            )
        )

        score = candidate_score(
            discovery_metrics,
            discovery_baseline,
        )

        if score is None:
            continue

        scored.append(
            (
                score,
                rule,
                discovery_metrics,
            )
        )

    scored.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )

    # Validate only strongest discovery leads.
    shortlist = scored[
        : max(
            TOP_SINGLE_FEATURES_PER_GROUP
            * 4,
            PAIR_SOURCE_LIMIT,
        )
    ]

    validated = []

    for (
        discovery_score,
        rule,
        discovery_metrics,
    ) in shortlist:

        holdout_metrics = (
            evaluate_rule(
                direction_holdout,
                rule,
                horizon,
            )
        )

        if (
            holdout_metrics is None
            or holdout_metrics["n"]
            < MIN_SAMPLE
        ):
            continue

        discovery_lift = (
            discovery_metrics[
                "net_expectancy"
            ]
            - discovery_baseline[
                "net_expectancy"
            ]
        )

        holdout_lift = (
            holdout_metrics[
                "net_expectancy"
            ]
            - holdout_baseline[
                "net_expectancy"
            ]
        )

        holdout_hit_lift = (
            holdout_metrics[
                "primary_hit_rate"
            ]
            - holdout_baseline[
                "primary_hit_rate"
            ]
        )

        consistent = (
            discovery_lift > 0
            and holdout_lift > 0
            and holdout_hit_lift > 0
        )

        validated.append(
            {
                "direction":
                    direction,

                "horizon":
                    horizon,

                "rule":
                    rule,

                "description":
                    rule_description(
                        rule
                    ),

                "discovery":
                    discovery_metrics,

                "holdout":
                    holdout_metrics,

                "discovery_baseline":
                    discovery_baseline,

                "holdout_baseline":
                    holdout_baseline,

                "discovery_lift":
                    discovery_lift,

                "holdout_lift":
                    holdout_lift,

                "holdout_hit_lift":
                    holdout_hit_lift,

                "consistent":
                    consistent,
            }
        )

    validated.sort(
        key=lambda item: (
            item["consistent"],
            item["holdout_lift"],
            item["holdout_hit_lift"],
            item["holdout"]["n"],
        ),
        reverse=True,
    )

    return validated[
        :TOP_SINGLE_FEATURES_PER_GROUP
    ]


# ============================================================
# PAIR RULE DISCOVERY
# ============================================================

def build_pair_rules(
    single_results,
):
    source_rules = []

    for result in single_results:
        rule = result["rule"]

        if len(
            rule["conditions"]
        ) != 1:
            continue

        source_rules.append(
            rule
        )

        if len(
            source_rules
        ) >= PAIR_SOURCE_LIMIT:
            break

    pair_rules = []

    seen = set()

    for left_index in range(
        len(source_rules)
    ):
        for right_index in range(
            left_index + 1,
            len(source_rules),
        ):
            left_condition = (
                source_rules[
                    left_index
                ]["conditions"][0]
            )

            right_condition = (
                source_rules[
                    right_index
                ]["conditions"][0]
            )

            if (
                left_condition[0]
                == right_condition[0]
            ):
                continue

            conditions = sorted(
                [
                    left_condition,
                    right_condition,
                ],
                key=lambda item:
                    (
                        item[0],
                        item[1],
                        str(item[2]),
                    ),
            )

            key = tuple(
                (
                    condition[0],
                    condition[1],
                    str(
                        condition[2]
                    ),
                )
                for condition
                in conditions
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            pair_rules.append(
                {
                    "type":
                        "pair",

                    "conditions":
                        conditions,
                }
            )

    return pair_rules


def discover_pair_rules(
    discovery_rows,
    holdout_rows,
    direction,
    horizon,
    single_results,
):
    direction_discovery = [
        row
        for row in discovery_rows
        if (
            row["direction"]
            == direction
        )
    ]

    direction_holdout = [
        row
        for row in holdout_rows
        if (
            row["direction"]
            == direction
        )
    ]

    discovery_baseline = (
        baseline_metrics(
            direction_discovery,
            horizon,
        )
    )

    holdout_baseline = (
        baseline_metrics(
            direction_holdout,
            horizon,
        )
    )

    if (
        discovery_baseline is None
        or holdout_baseline is None
    ):
        return []

    pair_rules = build_pair_rules(
        single_results
    )

    scored = []

    for rule in pair_rules:
        discovery_metrics = (
            evaluate_rule(
                direction_discovery,
                rule,
                horizon,
            )
        )

        score = candidate_score(
            discovery_metrics,
            discovery_baseline,
        )

        if score is None:
            continue

        scored.append(
            (
                score,
                rule,
                discovery_metrics,
            )
        )

    scored.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )

    shortlist = scored[
        :TOP_PAIR_FEATURES_PER_GROUP
        * 4
    ]

    validated = []

    for (
        discovery_score,
        rule,
        discovery_metrics,
    ) in shortlist:

        holdout_metrics = (
            evaluate_rule(
                direction_holdout,
                rule,
                horizon,
            )
        )

        if (
            holdout_metrics is None
            or holdout_metrics["n"]
            < MIN_SAMPLE
        ):
            continue

        discovery_lift = (
            discovery_metrics[
                "net_expectancy"
            ]
            - discovery_baseline[
                "net_expectancy"
            ]
        )

        holdout_lift = (
            holdout_metrics[
                "net_expectancy"
            ]
            - holdout_baseline[
                "net_expectancy"
            ]
        )

        holdout_hit_lift = (
            holdout_metrics[
                "primary_hit_rate"
            ]
            - holdout_baseline[
                "primary_hit_rate"
            ]
        )

        consistent = (
            discovery_lift > 0
            and holdout_lift > 0
            and holdout_hit_lift > 0
        )

        validated.append(
            {
                "direction":
                    direction,

                "horizon":
                    horizon,

                "rule":
                    rule,

                "description":
                    rule_description(
                        rule
                    ),

                "discovery":
                    discovery_metrics,

                "holdout":
                    holdout_metrics,

                "discovery_baseline":
                    discovery_baseline,

                "holdout_baseline":
                    holdout_baseline,

                "discovery_lift":
                    discovery_lift,

                "holdout_lift":
                    holdout_lift,

                "holdout_hit_lift":
                    holdout_hit_lift,

                "consistent":
                    consistent,
            }
        )

    validated.sort(
        key=lambda item: (
            item["consistent"],
            item["holdout_lift"],
            item["holdout_hit_lift"],
            item["holdout"]["n"],
        ),
        reverse=True,
    )

    return validated[
        :TOP_PAIR_FEATURES_PER_GROUP
    ]


# ============================================================
# PRINTING
# ============================================================

def print_baseline(
    discovery_rows,
    holdout_rows,
):
    separator()

    print(
        "R9 BASELINE NET-EDGE PERFORMANCE"
    )

    print(
        f"PRIMARY HYPOTHETICAL COST: "
        f"{PRIMARY_COST_PCT:.2f}%"
    )

    print(
        f"PRIMARY NET MOVE TARGET: "
        f"+{PRIMARY_NET_TARGET_PCT:.2f}%"
    )

    print(
        "PRIMARY REQUIRED RAW MOVE: "
        f"+{PRIMARY_COST_PCT + PRIMARY_NET_TARGET_PCT:.2f}%"
    )

    separator()

    for direction in (
        "LONG",
        "SHORT",
    ):
        print()
        print(direction)

        discovery_direction = [
            row
            for row in discovery_rows
            if (
                row["direction"]
                == direction
            )
        ]

        holdout_direction = [
            row
            for row in holdout_rows
            if (
                row["direction"]
                == direction
            )
        ]

        for horizon in HORIZONS:
            discovery = baseline_metrics(
                discovery_direction,
                horizon,
            )

            holdout = baseline_metrics(
                holdout_direction,
                horizon,
            )

            if (
                discovery is None
                or holdout is None
            ):
                continue

            print(
                f"  {horizon} | "
                f"DISC N={discovery['n']} "
                f"NET={fmt_pct(discovery['net_expectancy'])} "
                f"TARGET_HIT={discovery['primary_hit_rate']:.2f}% | "
                f"HOLD N={holdout['n']} "
                f"NET={fmt_pct(holdout['net_expectancy'])} "
                f"TARGET_HIT={holdout['primary_hit_rate']:.2f}%"
            )


def print_result(
    rank,
    result,
    label,
):
    discovery = result[
        "discovery"
    ]

    holdout = result[
        "holdout"
    ]

    print(
        f"{rank}. "
        f"{label} | "
        f"{result['direction']} "
        f"{result['horizon']} | "
        f"{result['description']}"
    )

    print(
        f"   DISCOVERY: "
        f"N={discovery['n']} | "
        f"RAW_AVG={fmt_pct(discovery['raw_expectancy'])} | "
        f"NET@0.05={fmt_pct(discovery['net_expectancy'])} | "
        f"TARGET_HIT={discovery['primary_hit_rate']:.2f}% | "
        f"PF={fmt_number(discovery['profit_factor'])}"
    )

    print(
        f"   HOLDOUT:   "
        f"N={holdout['n']} | "
        f"RAW_AVG={fmt_pct(holdout['raw_expectancy'])} | "
        f"NET@0.05={fmt_pct(holdout['net_expectancy'])} | "
        f"TARGET_HIT={holdout['primary_hit_rate']:.2f}% | "
        f"PF={fmt_number(holdout['profit_factor'])}"
    )

    print(
        f"   HOLDOUT NET LIFT: "
        f"{result['holdout_lift']:+.5f}pp | "
        f"HOLDOUT TARGET-HIT LIFT: "
        f"{result['holdout_hit_lift']:+.2f}pp | "
        f"CONSISTENT={result['consistent']}"
    )


# ============================================================
# COST STRESS TEST
# ============================================================

def cost_stress_test(
    holdout_rows,
    result,
):
    direction_rows = [
        row
        for row in holdout_rows
        if (
            row["direction"]
            == result["direction"]
        )
    ]

    field = (
        f"return_{result['horizon']}_pct"
    )

    raw_returns = []

    for row in direction_rows:
        if (
            row.get(field)
            is None
        ):
            continue

        if not row_matches_rule(
            row,
            result["rule"],
        ):
            continue

        raw_returns.append(
            row[field]
        )

    if not raw_returns:
        return []

    output = []

    for cost in COST_SCENARIOS_PCT:
        net_returns = [
            value - cost
            for value in raw_returns
        ]

        output.append(
            {
                "cost":
                    cost,

                "net_expectancy":
                    mean(net_returns),

                "profit_factor":
                    profit_factor(
                        net_returns
                    ),

                "net_positive_rate":
                    positive_rate(
                        net_returns
                    ),

                "target_hit_rate":
                    target_hit_rate(
                        raw_returns,
                        cost,
                        PRIMARY_NET_TARGET_PCT,
                    ),
            }
        )

    return output


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

    print()

    print(
        "PURPOSE:"
    )

    print(
        "Discover technical feature conditions associated "
        "with direction-adjusted moves large enough to "
        "retain positive edge after hypothetical costs."
    )

    print()

    print(
        "R9 OPTIMIZES MOVE SIZE / NET EDGE, "
        "NOT SIMPLE DIRECTIONAL WIN RATE."
    )

    print(
        "R9 DOES NOT MODIFY R7.1."
    )

    print(
        "R9 DOES NOT MODIFY BOT 2.0."
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
            "R9 DATASET HEALTH"
        )

        separator()

        print(
            f"ROWS WITH FAST OUTCOMES: "
            f"{len(rows)}"
        )

        print(
            "LONG: "
            f"{sum(1 for row in rows if row['direction'] == 'LONG')}"
        )

        print(
            "SHORT: "
            f"{sum(1 for row in rows if row['direction'] == 'SHORT')}"
        )

        discovery_rows, holdout_rows = (
            chronological_split(
                rows
            )
        )

        print(
            f"DISCOVERY ROWS: "
            f"{len(discovery_rows)}"
        )

        print(
            f"HOLDOUT ROWS: "
            f"{len(holdout_rows)}"
        )

        if discovery_rows:
            print(
                "DISCOVERY RANGE: "
                f"{discovery_rows[0]['created_at']} "
                "-> "
                f"{discovery_rows[-1]['created_at']}"
            )

        if holdout_rows:
            print(
                "HOLDOUT RANGE: "
                f"{holdout_rows[0]['created_at']} "
                "-> "
                f"{holdout_rows[-1]['created_at']}"
            )

        print_baseline(
            discovery_rows,
            holdout_rows,
        )

        all_single_results = []
        all_pair_results = []

        for direction in (
            "LONG",
            "SHORT",
        ):
            for horizon in HORIZONS:
                separator()

                print(
                    f"R9 SINGLE FEATURE DISCOVERY | "
                    f"{direction} | {horizon}"
                )

                separator()

                singles = discover_single_rules(
                    discovery_rows,
                    holdout_rows,
                    direction,
                    horizon,
                )

                if not singles:
                    print(
                        "NO VALIDATED SINGLE-FEATURE LEADS"
                    )

                else:
                    for rank, result in enumerate(
                        singles,
                        start=1,
                    ):
                        print_result(
                            rank,
                            result,
                            "SINGLE",
                        )

                all_single_results.extend(
                    singles
                )

                separator()

                print(
                    f"R9 PAIR FEATURE DISCOVERY | "
                    f"{direction} | {horizon}"
                )

                separator()

                pairs = discover_pair_rules(
                    discovery_rows,
                    holdout_rows,
                    direction,
                    horizon,
                    singles,
                )

                if not pairs:
                    print(
                        "NO VALIDATED PAIR-FEATURE LEADS"
                    )

                else:
                    for rank, result in enumerate(
                        pairs,
                        start=1,
                    ):
                        print_result(
                            rank,
                            result,
                            "PAIR",
                        )

                all_pair_results.extend(
                    pairs
                )

        all_results = (
            all_single_results
            + all_pair_results
        )

        consistent_results = [
            result
            for result in all_results
            if result["consistent"]
        ]

        consistent_results.sort(
            key=lambda result: (
                result["holdout_lift"],
                result["holdout_hit_lift"],
                result["holdout"]["n"],
            ),
            reverse=True,
        )

        separator()

        print(
            "R9 CONSISTENT HELD-OUT NET-EDGE LEADS"
        )

        separator()

        print(
            f"CONSISTENT LEADS: "
            f"{len(consistent_results)}"
        )

        top_consistent = (
            consistent_results[:25]
        )

        if not top_consistent:
            print(
                "NO CONSISTENT HELD-OUT NET-EDGE "
                "LEADS FOUND."
            )

        else:
            for rank, result in enumerate(
                top_consistent,
                start=1,
            ):
                print_result(
                    rank,
                    result,
                    "NET-EDGE",
                )

        separator()

        print(
            "R9 TOP LEAD COST STRESS TEST"
        )

        separator()

        for rank, result in enumerate(
            top_consistent[:10],
            start=1,
        ):
            print(
                f"{rank}. "
                f"{result['direction']} "
                f"{result['horizon']} | "
                f"{result['description']}"
            )

            stress = cost_stress_test(
                holdout_rows,
                result,
            )

            for item in stress:
                print(
                    f"   COST={item['cost']:.2f}% | "
                    f"NET_EXPECTANCY="
                    f"{fmt_pct(item['net_expectancy'])} | "
                    f"PF="
                    f"{fmt_number(item['profit_factor'])} | "
                    f"NET_POSITIVE="
                    f"{item['net_positive_rate']:.2f}% | "
                    f"+{PRIMARY_NET_TARGET_PCT:.2f}% "
                    f"NET TARGET HIT="
                    f"{item['target_hit_rate']:.2f}%"
                )

        separator()

        print(
            "R9 FINAL STATUS"
        )

        separator()

        print(
            "STATUS: R9 NET-EDGE DISCOVERY COMPLETE"
        )

        print(
            "DATABASE REMAINED READ ONLY"
        )

        print(
            "NO WRITES; NO SENDS; NO TRADES; "
            "NO PRODUCTION CHANGES; NO AI CALLS"
        )

        print()

        print(
            "GUARDRAILS:"
        )

        print(
            "1. R9 is historical research, not live trading proof."
        )

        print(
            "2. The 30% chronological holdout reduces leakage "
            "but is not a future prospective test."
        )

        print(
            "3. Multiple-testing risk remains because many "
            "feature conditions are evaluated."
        )

        print(
            "4. LONG and SHORT observations may be paired "
            "from the same market opportunity."
        )

        print(
            "5. Cost assumptions are hypothetical and are "
            "not claimed exchange fee rates."
        )

        print(
            "6. Funding, spread, slippage, latency, liquidation "
            "and fill quality are not fully modelled."
        )

        print(
            "7. Leverage is intentionally not used to create edge."
        )

        print(
            "8. Any R9 lead must be frozen and independently "
            "validated prospectively before production use."
        )

        print(
            "9. R9 does not authorize any Bot 2.0 change."
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
