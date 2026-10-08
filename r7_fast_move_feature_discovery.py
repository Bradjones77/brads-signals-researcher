"""
BRAD'S SIGNALS RESEARCHER
R7 - FAST-MOVE V2 FEATURE DISCOVERY

PURPOSE
-------
Read historical Bot 2.0 opportunities and outcomes and discover which
stored technical feature states are associated with successful fast moves.

FAST HORIZONS
-------------
1m
5m
10m
30m

IMPORTANT
---------
- READ ONLY
- NO DATABASE WRITES
- NO TELEGRAM
- NO TRADES
- NO AI CALLS
- NO PRODUCTION CHANGES
- LONG and SHORT are analysed separately
- This file does NOT authorize production scoring changes
"""

import json
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor


# ============================================================
# VERSION / SAFETY
# ============================================================

VERSION = "R7-FAST-MOVE-V2-FEATURE-DISCOVERY"

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False

HORIZONS = (
    "1m",
    "5m",
    "10m",
    "30m",
)

DIRECTIONS = (
    "LONG",
    "SHORT",
)

# We want enough examples before treating a feature state as interesting.
MIN_GROUP_SIZE = 25

# Minimum observations for a chronological train/holdout split.
MIN_VALIDATION_ROWS = 80

# Oldest 70% discovery / newest 30% holdout.
TRAIN_FRACTION = 0.70

# Maximum number of single-feature discoveries printed per
# direction / horizon.
TOP_SINGLE_FEATURES = 15

# Maximum pair discoveries printed.
TOP_PAIRS = 15

# Do not allow an explosion of pair combinations.
MAX_PAIR_FEATURES = 18

# Features we specifically care about for the fast-move strategy.
FAST_FEATURE_NAMES = (
    "mtf_alignment",

    "5m_trend_strength",
    "5m_rsi",
    "5m_atr_pct",
    "5m_macd_hist",
    "5m_macd_acceleration",
    "5m_momentum_3",
    "5m_momentum_6",
    "5m_momentum_acceleration",
    "5m_volume_ratio",
    "5m_volume_acceleration",
    "5m_bull_breakout",
    "5m_bear_breakout",
    "5m_breakout_volume_confirmed",
    "5m_support_distance",
    "5m_resistance_distance",

    "15m_trend_strength",
    "15m_rsi",
    "15m_atr_pct",
    "15m_macd_hist",
    "15m_macd_acceleration",
    "15m_momentum_3",
    "15m_momentum_6",
    "15m_momentum_acceleration",
    "15m_volume_ratio",
    "15m_volume_acceleration",
    "15m_bull_breakout",
    "15m_bear_breakout",
    "15m_breakout_volume_confirmed",
    "15m_support_distance",
    "15m_resistance_distance",

    "30m_trend_strength",
    "30m_rsi",
    "30m_atr_pct",
    "30m_macd_hist",
    "30m_macd_acceleration",
    "30m_momentum_3",
    "30m_momentum_6",
    "30m_momentum_acceleration",
    "30m_volume_ratio",
    "30m_volume_acceleration",
    "30m_bull_breakout",
    "30m_bear_breakout",
    "30m_breakout_volume_confirmed",
    "30m_support_distance",
    "30m_resistance_distance",

    "1h_trend_strength",
    "1h_rsi",
    "1h_atr_pct",
    "1h_macd_hist",
    "1h_macd_acceleration",
    "1h_momentum_3",
    "1h_momentum_6",
    "1h_momentum_acceleration",
    "1h_volume_ratio",
    "1h_volume_acceleration",
    "1h_bull_breakout",
    "1h_bear_breakout",
    "1h_breakout_volume_confirmed",
    "1h_support_distance",
    "1h_resistance_distance",
)


# ============================================================
# PRINT HELPERS
# ============================================================

def line():
    print("=" * 100)


def section(title):
    print()
    line()
    print(title)
    line()


def safe_round(value, digits=4):
    if value is None:
        return None

    try:
        return round(float(value), digits)
    except Exception:
        return None


# ============================================================
# BASIC HELPERS
# ============================================================

def as_dict(value):
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}

    return {}


def as_float(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except Exception:
        return None

    if not math.isfinite(number):
        return None

    return number


def as_bool(value):
    if isinstance(value, bool):
        return value

    if value is None:
        return None

    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False

    text = str(value).strip().lower()

    if text in ("true", "t", "yes", "y", "1"):
        return True

    if text in ("false", "f", "no", "n", "0"):
        return False

    return None


def percentile(values, p):
    clean = sorted(
        x for x in values
        if x is not None and math.isfinite(x)
    )

    if not clean:
        return None

    if len(clean) == 1:
        return clean[0]

    position = (len(clean) - 1) * p
    lower = int(math.floor(position))
    upper = int(math.ceil(position))

    if lower == upper:
        return clean[lower]

    fraction = position - lower

    return (
        clean[lower] * (1.0 - fraction)
        + clean[upper] * fraction
    )


def mean(values):
    clean = [
        x for x in values
        if x is not None and math.isfinite(x)
    ]

    if not clean:
        return None

    return statistics.fmean(clean)


# ============================================================
# DATABASE
# ============================================================

def get_database_url():
    value = os.getenv("SIGNALS2_DATABASE_URL")

    if not value:
        value = os.getenv("DATABASE_URL")

    if not value:
        raise RuntimeError(
            "Missing SIGNALS2_DATABASE_URL / DATABASE_URL"
        )

    return value


def connect_read_only():
    conn = psycopg2.connect(
        get_database_url(),
        connect_timeout=15,
    )

    conn.autocommit = False

    cur = conn.cursor()
    cur.execute(
        "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
    )
    cur.execute(
        "SET statement_timeout = '120s'"
    )
    cur.close()

    return conn


# ============================================================
# LOAD HISTORICAL DATA
# ============================================================

def load_rows(conn):
    """
    Uses completed real Bot 2.0 outcome rows.

    We deliberately exclude obvious synthetic/test strategy rows.

    combined_features is preferred because this is the flattened feature
    vector used by memory. If unavailable on an older row, technical_features
    is used as a fallback.
    """

    query = """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,

            o.final_confidence,
            o.technical_confidence,
            o.market_confidence,
            o.memory_confidence,
            o.ai_confidence,

            o.model_version,
            o.strategy_version,

            o.technical_features,
            o.combined_features,

            r.return_1m_pct,
            r.return_5m_pct,
            r.return_10m_pct,
            r.return_30m_pct,

            r.direction_correct_1m,
            r.direction_correct_5m,
            r.direction_correct_10m,
            r.direction_correct_30m,

            r.outcome_complete

        FROM signals2_opportunities o

        INNER JOIN signals2_outcomes r
            ON o.opportunity_id = r.opportunity_id

        WHERE
            r.outcome_complete = TRUE

            AND UPPER(COALESCE(o.direction, ''))
                IN ('LONG', 'SHORT')

            AND COALESCE(o.strategy_version, '')
                NOT ILIKE '%TEST%'

            AND COALESCE(o.strategy_version, '')
                NOT ILIKE '%SYNTHETIC%'

            AND COALESCE(o.model_version, '')
                NOT ILIKE '%TEST%'

            AND COALESCE(o.model_version, '')
                NOT ILIKE '%SYNTHETIC%'

        ORDER BY o.created_at ASC
    """

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cur.execute(query)

    rows = [
        dict(row)
        for row in cur.fetchall()
    ]

    cur.close()

    return rows


# ============================================================
# FEATURE EXTRACTION
# ============================================================

def get_feature_dict(row):
    combined = as_dict(
        row.get("combined_features")
    )

    technical = as_dict(
        row.get("technical_features")
    )

    # Prefer the already flattened combined feature vector.
    if combined:
        return combined

    # Some older records may have technical_features already flattened.
    return technical


def numeric_feature_value(features, name):
    value = features.get(name)

    # Booleans are handled separately.
    if isinstance(value, bool):
        return None

    return as_float(value)


def boolean_feature_value(features, name):
    return as_bool(
        features.get(name)
    )


# ============================================================
# OUTCOME HELPERS
# ============================================================

def correct_field(horizon):
    return f"direction_correct_{horizon}"


def return_field(horizon):
    return f"return_{horizon}_pct"


def outcome_correct(row, horizon):
    return as_bool(
        row.get(
            correct_field(horizon)
        )
    )


def outcome_return(row, horizon):
    return as_float(
        row.get(
            return_field(horizon)
        )
    )


# ============================================================
# DATASET HEALTH
# ============================================================

def dataset_health(rows):
    section("R7 DATASET HEALTH")

    print(
        f"COMPLETED REAL ROWS: {len(rows)}"
    )

    for direction in DIRECTIONS:
        subset = [
            row for row in rows
            if str(
                row.get("direction", "")
            ).upper() == direction
        ]

        print(
            f"{direction}: {len(subset)}"
        )

    print()

    for horizon in HORIZONS:
        usable = [
            row for row in rows
            if outcome_correct(
                row,
                horizon,
            ) is not None
        ]

        wins = sum(
            1
            for row in usable
            if outcome_correct(
                row,
                horizon,
            ) is True
        )

        rate = (
            wins / len(usable) * 100.0
            if usable
            else 0.0
        )

        avg_return = mean(
            [
                outcome_return(
                    row,
                    horizon,
                )
                for row in usable
            ]
        )

        print(
            f"{horizon}: "
            f"N={len(usable)} "
            f"CORRECT={wins} "
            f"RATE={rate:.2f}% "
            f"AVG_RETURN={safe_round(avg_return, 5)}%"
        )


# ============================================================
# FEATURE COVERAGE
# ============================================================

def feature_coverage(rows):
    section("R7 FAST FEATURE COVERAGE")

    counts = defaultdict(int)

    for row in rows:
        features = get_feature_dict(row)

        for name in FAST_FEATURE_NAMES:
            value = features.get(name)

            if value is not None:
                counts[name] += 1

    coverage = []

    for name in FAST_FEATURE_NAMES:
        count = counts[name]

        pct = (
            count / len(rows) * 100.0
            if rows
            else 0.0
        )

        coverage.append(
            (
                pct,
                count,
                name,
            )
        )

    coverage.sort(
        reverse=True
    )

    for pct, count, name in coverage:
        if count == 0:
            continue

        print(
            f"{name}: "
            f"N={count} "
            f"COVERAGE={pct:.2f}%"
        )

    available = [
        name
        for pct, count, name in coverage
        if count >= MIN_GROUP_SIZE
    ]

    print()
    print(
        f"FEATURES WITH >= {MIN_GROUP_SIZE} VALUES: "
        f"{len(available)}"
    )

    return available


# ============================================================
# NUMERIC FEATURE DISCOVERY
# ============================================================

def build_numeric_rules(
    training_rows,
    feature_name,
):
    values = []

    for row in training_rows:
        features = get_feature_dict(row)

        value = numeric_feature_value(
            features,
            feature_name,
        )

        if value is not None:
            values.append(value)

    if len(values) < MIN_GROUP_SIZE * 2:
        return []

    q25 = percentile(
        values,
        0.25,
    )

    q50 = percentile(
        values,
        0.50,
    )

    q75 = percentile(
        values,
        0.75,
    )

    if (
        q25 is None
        or q50 is None
        or q75 is None
    ):
        return []

    return [
        {
            "feature": feature_name,
            "operator": "<=",
            "threshold": q25,
            "label": "LOW_Q25",
        },
        {
            "feature": feature_name,
            "operator": ">=",
            "threshold": q75,
            "label": "HIGH_Q75",
        },
        {
            "feature": feature_name,
            "operator": "<=",
            "threshold": q50,
            "label": "LOW_HALF",
        },
        {
            "feature": feature_name,
            "operator": ">=",
            "threshold": q50,
            "label": "HIGH_HALF",
        },
    ]


def build_boolean_rules(
    training_rows,
    feature_name,
):
    values = []

    for row in training_rows:
        features = get_feature_dict(row)

        value = boolean_feature_value(
            features,
            feature_name,
        )

        if value is not None:
            values.append(value)

    if len(values) < MIN_GROUP_SIZE * 2:
        return []

    return [
        {
            "feature": feature_name,
            "operator": "==",
            "threshold": True,
            "label": "TRUE",
        },
        {
            "feature": feature_name,
            "operator": "==",
            "threshold": False,
            "label": "FALSE",
        },
    ]


def make_rules(
    training_rows,
    available_features,
):
    rules = []

    for feature_name in available_features:
        observed = []

        for row in training_rows:
            features = get_feature_dict(row)

            if feature_name in features:
                observed.append(
                    features.get(feature_name)
                )

        if not observed:
            continue

        bool_count = sum(
            1
            for value in observed
            if as_bool(value) is not None
            and (
                isinstance(value, bool)
                or str(value).strip().lower()
                in (
                    "true",
                    "false",
                    "t",
                    "f",
                    "yes",
                    "no",
                )
            )
        )

        numeric_count = sum(
            1
            for value in observed
            if (
                not isinstance(value, bool)
                and as_float(value) is not None
            )
        )

        if numeric_count >= bool_count:
            rules.extend(
                build_numeric_rules(
                    training_rows,
                    feature_name,
                )
            )
        else:
            rules.extend(
                build_boolean_rules(
                    training_rows,
                    feature_name,
                )
            )

    return rules


def rule_matches(
    row,
    rule,
):
    features = get_feature_dict(row)

    name = rule["feature"]
    operator = rule["operator"]
    threshold = rule["threshold"]

    if operator == "==":
        value = boolean_feature_value(
            features,
            name,
        )

        if value is None:
            return False

        return value == threshold

    value = numeric_feature_value(
        features,
        name,
    )

    if value is None:
        return False

    if operator == ">=":
        return value >= threshold

    if operator == "<=":
        return value <= threshold

    return False


# ============================================================
# RULE EVALUATION
# ============================================================

def baseline_stats(
    rows,
    horizon,
):
    usable = [
        row
        for row in rows
        if outcome_correct(
            row,
            horizon,
        ) is not None
    ]

    if not usable:
        return {
            "n": 0,
            "rate": None,
            "avg_return": None,
        }

    wins = sum(
        1
        for row in usable
        if outcome_correct(
            row,
            horizon,
        ) is True
    )

    return {
        "n": len(usable),
        "rate": (
            wins / len(usable)
            * 100.0
        ),
        "avg_return": mean(
            [
                outcome_return(
                    row,
                    horizon,
                )
                for row in usable
            ]
        ),
    }


def evaluate_rule(
    rows,
    rule,
    horizon,
):
    matched = [
        row
        for row in rows
        if rule_matches(
            row,
            rule,
        )
        and outcome_correct(
            row,
            horizon,
        ) is not None
    ]

    if len(matched) < MIN_GROUP_SIZE:
        return None

    wins = sum(
        1
        for row in matched
        if outcome_correct(
            row,
            horizon,
        ) is True
    )

    rate = (
        wins
        / len(matched)
        * 100.0
    )

    avg_return = mean(
        [
            outcome_return(
                row,
                horizon,
            )
            for row in matched
        ]
    )

    return {
        "n": len(matched),
        "wins": wins,
        "rate": rate,
        "avg_return": avg_return,
    }


def evaluate_pair(
    rows,
    rule_a,
    rule_b,
    horizon,
):
    matched = [
        row
        for row in rows
        if (
            rule_matches(
                row,
                rule_a,
            )
            and rule_matches(
                row,
                rule_b,
            )
            and outcome_correct(
                row,
                horizon,
            ) is not None
        )
    ]

    if len(matched) < MIN_GROUP_SIZE:
        return None

    wins = sum(
        1
        for row in matched
        if outcome_correct(
            row,
            horizon,
        ) is True
    )

    return {
        "n": len(matched),
        "wins": wins,
        "rate": (
            wins
            / len(matched)
            * 100.0
        ),
        "avg_return": mean(
            [
                outcome_return(
                    row,
                    horizon,
                )
                for row in matched
            ]
        ),
    }


def rule_text(rule):
    threshold = rule["threshold"]

    if isinstance(threshold, float):
        threshold_text = (
            f"{threshold:.6f}"
        )
    else:
        threshold_text = str(
            threshold
        )

    return (
        f"{rule['feature']} "
        f"{rule['operator']} "
        f"{threshold_text}"
    )


# ============================================================
# CHRONOLOGICAL SPLIT
# ============================================================

def chronological_split(rows):
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("created_at")
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
    )

    if len(ordered) < MIN_VALIDATION_ROWS:
        return ordered, []

    cut = int(
        len(ordered)
        * TRAIN_FRACTION
    )

    cut = max(
        1,
        min(
            cut,
            len(ordered) - 1,
        ),
    )

    return (
        ordered[:cut],
        ordered[cut:],
    )


# ============================================================
# SINGLE FEATURE DISCOVERY
# ============================================================

def discover_single_features(
    train_rows,
    holdout_rows,
    available_features,
    horizon,
):
    baseline_train = baseline_stats(
        train_rows,
        horizon,
    )

    baseline_holdout = baseline_stats(
        holdout_rows,
        horizon,
    )

    rules = make_rules(
        train_rows,
        available_features,
    )

    discoveries = []

    for rule in rules:
        train_result = evaluate_rule(
            train_rows,
            rule,
            horizon,
        )

        if not train_result:
            continue

        train_lift = (
            train_result["rate"]
            - baseline_train["rate"]
        )

        discoveries.append(
            {
                "rule": rule,
                "train": train_result,
                "train_lift": train_lift,
            }
        )

    discoveries.sort(
        key=lambda item: (
            item["train_lift"],
            item["train"]["n"],
        ),
        reverse=True,
    )

    # Avoid printing four near-identical cuts of the same feature.
    selected = []
    used_features = set()

    for item in discoveries:
        feature_name = (
            item["rule"]["feature"]
        )

        if feature_name in used_features:
            continue

        selected.append(item)
        used_features.add(
            feature_name
        )

        if (
            len(selected)
            >= TOP_SINGLE_FEATURES
        ):
            break

    results = []

    for item in selected:
        holdout_result = evaluate_rule(
            holdout_rows,
            item["rule"],
            horizon,
        )

        holdout_lift = None

        if (
            holdout_result
            and baseline_holdout["rate"]
            is not None
        ):
            holdout_lift = (
                holdout_result["rate"]
                - baseline_holdout["rate"]
            )

        result = {
            **item,
            "holdout": holdout_result,
            "holdout_lift": holdout_lift,
        }

        results.append(result)

    return (
        baseline_train,
        baseline_holdout,
        results,
    )


# ============================================================
# PAIR DISCOVERY
# ============================================================

def discover_pairs(
    train_rows,
    holdout_rows,
    single_results,
    horizon,
):
    baseline_train = baseline_stats(
        train_rows,
        horizon,
    )

    baseline_holdout = baseline_stats(
        holdout_rows,
        horizon,
    )

    candidate_rules = [
        item["rule"]
        for item in single_results[
            :MAX_PAIR_FEATURES
        ]
    ]

    discoveries = []

    for i in range(
        len(candidate_rules)
    ):
        for j in range(
            i + 1,
            len(candidate_rules),
        ):
            rule_a = candidate_rules[i]
            rule_b = candidate_rules[j]

            if (
                rule_a["feature"]
                == rule_b["feature"]
            ):
                continue

            train_result = evaluate_pair(
                train_rows,
                rule_a,
                rule_b,
                horizon,
            )

            if not train_result:
                continue

            train_lift = (
                train_result["rate"]
                - baseline_train["rate"]
            )

            discoveries.append(
                {
                    "rule_a": rule_a,
                    "rule_b": rule_b,
                    "train": train_result,
                    "train_lift": train_lift,
                }
            )

    discoveries.sort(
        key=lambda item: (
            item["train_lift"],
            item["train"]["n"],
        ),
        reverse=True,
    )

    final = []

    for item in discoveries[
        :TOP_PAIRS
    ]:
        holdout_result = evaluate_pair(
            holdout_rows,
            item["rule_a"],
            item["rule_b"],
            horizon,
        )

        holdout_lift = None

        if (
            holdout_result
            and baseline_holdout["rate"]
            is not None
        ):
            holdout_lift = (
                holdout_result["rate"]
                - baseline_holdout["rate"]
            )

        final.append(
            {
                **item,
                "holdout": holdout_result,
                "holdout_lift": holdout_lift,
            }
        )

    return final


# ============================================================
# REPORTING
# ============================================================

def print_single_results(
    direction,
    horizon,
    baseline_train,
    baseline_holdout,
    results,
):
    section(
        f"R7 SINGLE FEATURES | "
        f"{direction} | {horizon}"
    )

    print(
        "TRAIN BASELINE: "
        f"N={baseline_train['n']} "
        f"RATE={safe_round(baseline_train['rate'], 2)}% "
        f"AVG_RETURN={safe_round(baseline_train['avg_return'], 5)}%"
    )

    print(
        "HOLDOUT BASELINE: "
        f"N={baseline_holdout['n']} "
        f"RATE={safe_round(baseline_holdout['rate'], 2)}% "
        f"AVG_RETURN={safe_round(baseline_holdout['avg_return'], 5)}%"
    )

    print()

    if not results:
        print(
            "NO SINGLE FEATURE DISCOVERIES "
            "MET MINIMUM SAMPLE REQUIREMENTS"
        )
        return

    for index, item in enumerate(
        results,
        start=1,
    ):
        train = item["train"]
        holdout = item["holdout"]

        print(
            f"{index}. {rule_text(item['rule'])}"
        )

        print(
            "   TRAIN: "
            f"N={train['n']} "
            f"RATE={train['rate']:.2f}% "
            f"LIFT={item['train_lift']:+.2f}pp "
            f"AVG_RETURN={safe_round(train['avg_return'], 5)}%"
        )

        if holdout:
            print(
                "   HOLDOUT: "
                f"N={holdout['n']} "
                f"RATE={holdout['rate']:.2f}% "
                f"LIFT={item['holdout_lift']:+.2f}pp "
                f"AVG_RETURN={safe_round(holdout['avg_return'], 5)}%"
            )
        else:
            print(
                "   HOLDOUT: "
                "INSUFFICIENT SAMPLE"
            )


def print_pair_results(
    direction,
    horizon,
    pairs,
):
    section(
        f"R7 FEATURE COMBINATIONS | "
        f"{direction} | {horizon}"
    )

    if not pairs:
        print(
            "NO FEATURE PAIRS MET "
            "MINIMUM SAMPLE REQUIREMENTS"
        )
        return

    for index, item in enumerate(
        pairs,
        start=1,
    ):
        train = item["train"]
        holdout = item["holdout"]

        print(
            f"{index}. "
            f"[{rule_text(item['rule_a'])}] "
            f"AND "
            f"[{rule_text(item['rule_b'])}]"
        )

        print(
            "   TRAIN: "
            f"N={train['n']} "
            f"RATE={train['rate']:.2f}% "
            f"LIFT={item['train_lift']:+.2f}pp "
            f"AVG_RETURN={safe_round(train['avg_return'], 5)}%"
        )

        if holdout:
            print(
                "   HOLDOUT: "
                f"N={holdout['n']} "
                f"RATE={holdout['rate']:.2f}% "
                f"LIFT={item['holdout_lift']:+.2f}pp "
                f"AVG_RETURN={safe_round(holdout['avg_return'], 5)}%"
            )
        else:
            print(
                "   HOLDOUT: "
                "INSUFFICIENT SAMPLE"
            )


# ============================================================
# VALIDATION SUMMARY
# ============================================================

def validation_summary(
    all_results,
):
    section(
        "R7 HELD-OUT VALIDATION SUMMARY"
    )

    validated = []

    for item in all_results:
        holdout = item.get(
            "holdout"
        )

        holdout_lift = item.get(
            "holdout_lift"
        )

        if (
            not holdout
            or holdout_lift is None
        ):
            continue

        # A lead is only called "validated" here when:
        # - training lift is positive
        # - holdout lift is also positive
        # - holdout average direction-adjusted return is positive
        #
        # This is still research evidence, not authorization
        # for production use.
        avg_return = holdout.get(
            "avg_return"
        )

        if (
            item.get(
                "train_lift",
                0.0,
            ) > 0.0
            and holdout_lift > 0.0
            and avg_return is not None
            and avg_return > 0.0
        ):
            validated.append(
                item
            )

    validated.sort(
        key=lambda item: (
            item.get(
                "holdout_lift",
                0.0,
            ),
            item.get(
                "holdout",
                {},
            ).get(
                "n",
                0,
            ),
        ),
        reverse=True,
    )

    if not validated:
        print(
            "NO FEATURE LEADS PASSED THE "
            "BASIC TRAIN + HOLDOUT CONSISTENCY TEST."
        )

        print(
            "DO NOT CHANGE PRODUCTION SCORING."
        )

        return

    print(
        f"CONSISTENT HELD-OUT LEADS: "
        f"{len(validated)}"
    )

    print()

    for index, item in enumerate(
        validated[:25],
        start=1,
    ):
        direction = item[
            "direction"
        ]

        horizon = item[
            "horizon"
        ]

        holdout = item[
            "holdout"
        ]

        if "rule" in item:
            description = rule_text(
                item["rule"]
            )
        else:
            description = (
                f"[{rule_text(item['rule_a'])}] "
                f"AND "
                f"[{rule_text(item['rule_b'])}]"
            )

        print(
            f"{index}. "
            f"{direction} {horizon} | "
            f"{description}"
        )

        print(
            "   "
            f"TRAIN_LIFT={item['train_lift']:+.2f}pp "
            f"HOLDOUT_N={holdout['n']} "
            f"HOLDOUT_RATE={holdout['rate']:.2f}% "
            f"HOLDOUT_LIFT={item['holdout_lift']:+.2f}pp "
            f"HOLDOUT_AVG_RETURN="
            f"{safe_round(holdout['avg_return'], 5)}%"
        )


# ============================================================
# MAIN
# ============================================================

def main():
    line()
    print("BRADS-SIGNALS-RESEARCHER")
    line()

    print(
        f"RESEARCH VERSION: {VERSION}"
    )

    print(
        "UTC START: "
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
        "TARGET HORIZONS: "
        + ", ".join(HORIZONS)
    )

    print(
        "DIRECTION HANDLING: "
        "LONG AND SHORT SEPARATE"
    )

    print(
        "VALIDATION: "
        "OLDEST 70% DISCOVERY / "
        "NEWEST 30% HOLDOUT"
    )

    print(
        "SAFETY CHECK: PASS"
    )

    conn = None

    try:
        conn = connect_read_only()

        print(
            "DATABASE CONNECTION: READY"
        )

        print(
            "DATABASE SESSION: READ ONLY"
        )

        rows = load_rows(conn)

        dataset_health(rows)

        if not rows:
            section(
                "R7 FINAL STATUS"
            )

            print(
                "STATUS: NO USABLE DATA"
            )

            return

        available_features = (
            feature_coverage(rows)
        )

        if not available_features:
            section(
                "R7 FINAL STATUS"
            )

            print(
                "STATUS: NO FAST FEATURES "
                "AVAILABLE"
            )

            return

        all_validation_results = []

        for direction in DIRECTIONS:
            direction_rows = [
                row
                for row in rows
                if str(
                    row.get(
                        "direction",
                        "",
                    )
                ).upper()
                == direction
            ]

            train_rows, holdout_rows = (
                chronological_split(
                    direction_rows
                )
            )

            section(
                f"R7 SPLIT | {direction}"
            )

            print(
                f"TOTAL={len(direction_rows)} "
                f"TRAIN={len(train_rows)} "
                f"HOLDOUT={len(holdout_rows)}"
            )

            for horizon in HORIZONS:
                (
                    baseline_train,
                    baseline_holdout,
                    single_results,
                ) = discover_single_features(
                    train_rows,
                    holdout_rows,
                    available_features,
                    horizon,
                )

                print_single_results(
                    direction,
                    horizon,
                    baseline_train,
                    baseline_holdout,
                    single_results,
                )

                for item in single_results:
                    all_validation_results.append(
                        {
                            **item,
                            "direction": direction,
                            "horizon": horizon,
                            "type": "SINGLE",
                        }
                    )

                pairs = discover_pairs(
                    train_rows,
                    holdout_rows,
                    single_results,
                    horizon,
                )

                print_pair_results(
                    direction,
                    horizon,
                    pairs,
                )

                for item in pairs:
                    all_validation_results.append(
                        {
                            **item,
                            "direction": direction,
                            "horizon": horizon,
                            "type": "PAIR",
                        }
                    )

        validation_summary(
            all_validation_results
        )

        section(
            "R7 INTERPRETATION GUARDRAILS"
        )

        print(
            "1. THIS IS RESEARCH ONLY."
        )

        print(
            "2. NO PRODUCTION SCORING CHANGE "
            "IS AUTHORIZED BY R7."
        )

        print(
            "3. LONG AND SHORT WERE ANALYSED "
            "SEPARATELY."
        )

        print(
            "4. FEATURE CUTS WERE DISCOVERED "
            "ONLY FROM THE OLDEST 70%."
        )

        print(
            "5. THE NEWEST 30% WAS USED AS "
            "A CHRONOLOGICAL HOLDOUT."
        )

        print(
            "6. MULTIPLE TESTING CAN CREATE "
            "FALSE DISCOVERIES."
        )

        print(
            "7. PAIRED LONG/SHORT OBSERVATIONS "
            "ARE NOT INDEPENDENT TRADES."
        )

        print(
            "8. FEES, SLIPPAGE, FUNDING, "
            "LEVERAGE, ENTRIES AND EXITS "
            "ARE NOT MODELLED HERE."
        )

        print(
            "9. A POSITIVE HOLDOUT RESULT "
            "IS A RESEARCH LEAD, NOT PROOF."
        )

        print(
            "10. R7.1 SHOULD VALIDATE THE "
            "STRONGEST LEADS MORE STRICTLY "
            "BEFORE ANY PRODUCTION CHANGE."
        )

        section(
            "R7 FINAL STATUS"
        )

        print(
            "STATUS: R7 FAST-MOVE FEATURE "
            "DISCOVERY COMPLETE"
        )

        print(
            "DATABASE REMAINED READ ONLY"
        )

        print(
            "NO WRITES; NO SENDS; NO TRADES; "
            "NO PRODUCTION CHANGES; NO AI CALLS"
        )

    except Exception as exc:
        section(
            "R7 FAILURE"
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
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

            try:
                conn.close()

                print(
                    "DATABASE CONNECTION: CLOSED"
                )
            except Exception:
                pass


if __name__ == "__main__":
    main()
