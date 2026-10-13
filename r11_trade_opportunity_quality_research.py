"""
BRAD'S SIGNALS RESEARCHER
R11 - TRADE OPPORTUNITY QUALITY RESEARCH

PURPOSE
-------
Discover which pre-trade market conditions are associated with moves large
enough to survive hypothetical trading costs.

R11 is designed around Brad's fast-trade objective:

    Find fewer HIGH-QUALITY moves rather than simply predict direction.

The primary research question is:

    Which observable features increase the probability and expectancy of
    achieving at least +0.05% net after a hypothetical 0.05% round-trip cost?

That means the primary raw directional move target is:

    +0.10%

METHODOLOGY IMPROVEMENT OVER R9
-------------------------------
R11 deliberately avoids using holdout performance to choose candidate rules.

1. Data is split chronologically.
2. Feature thresholds are generated from DISCOVERY data only.
3. Single-feature candidates are ranked using DISCOVERY data only.
4. Pair candidates are constructed using DISCOVERY rankings only.
5. Final candidate shortlist is frozen.
6. ONLY THEN is the untouched HOLDOUT dataset evaluated.

This is still historical research and is NOT prospective proof.

SAFETY
------
- Database read only
- No Telegram
- No trades
- No AI calls
- No production modification
- No Bot 2.0 modification
"""

import json
import math
import os
from datetime import datetime, timezone

import psycopg2


# =============================================================================
# VERSION / SAFETY
# =============================================================================

RESEARCH_VERSION = "R11-TRADE-OPPORTUNITY-QUALITY-RESEARCH"

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False


# =============================================================================
# SETTINGS
# =============================================================================

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

DISCOVERY_FRACTION = 0.70

PRIMARY_COST_PCT = 0.05

DESIRED_NET_MOVE_PCT = 0.05

REQUIRED_RAW_MOVE_PCT = (
    PRIMARY_COST_PCT
    + DESIRED_NET_MOVE_PCT
)

COST_SCENARIOS_PCT = (
    0.02,
    0.05,
    0.10,
)

QUANTILES = (
    0.20,
    0.35,
    0.50,
    0.65,
    0.80,
)

MIN_DISCOVERY_SAMPLE = 60
MIN_HOLDOUT_SAMPLE = 30

TOP_SINGLE_CANDIDATES_PER_GROUP = 20

PAIR_SOURCE_LIMIT = 12

TOP_PAIR_CANDIDATES_PER_GROUP = 20

FINAL_FROZEN_CANDIDATES_PER_GROUP = 10


# Features containing these tokens are excluded to reduce leakage risk.

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
    "profit",
    "loss",
    "pnl",
)


# =============================================================================
# BASIC HELPERS
# =============================================================================

def banner(title):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)


def safe_float(value):
    try:
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        value = float(value)

        if not math.isfinite(value):
            return None

        return value

    except (TypeError, ValueError):
        return None


def mean(values):
    if not values:
        return None

    return sum(values) / len(values)


def median(values):
    if not values:
        return None

    values = sorted(values)

    n = len(values)

    middle = n // 2

    if n % 2:
        return values[middle]

    return (
        values[middle - 1]
        + values[middle]
    ) / 2.0


def percentile(values, q):
    if not values:
        return None

    values = sorted(values)

    if len(values) == 1:
        return values[0]

    position = q * (len(values) - 1)

    lower = int(math.floor(position))
    upper = int(math.ceil(position))

    if lower == upper:
        return values[lower]

    weight = position - lower

    return (
        values[lower] * (1.0 - weight)
        + values[upper] * weight
    )


def percentage(part, total):
    if total <= 0:
        return 0.0

    return (
        float(part)
        / float(total)
        * 100.0
    )


def profit_factor(values):
    if not values:
        return None

    gains = sum(
        value
        for value in values
        if value > 0
    )

    losses = abs(
        sum(
            value
            for value in values
            if value < 0
        )
    )

    if losses == 0:
        if gains > 0:
            return float("inf")

        return None

    return gains / losses


def fmt(value, decimals=5):
    if value is None:
        return "N/A"

    if math.isinf(value):
        return "INF"

    return f"{value:.{decimals}f}"


def return_column(horizon):
    mapping = {
        "1m": "return_1m_pct",
        "5m": "return_5m_pct",
        "10m": "return_10m_pct",
        "30m": "return_30m_pct",
    }

    return mapping[horizon]


# =============================================================================
# JSON / FEATURE HELPERS
# =============================================================================

def parse_json(value):
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


def flatten_dict(data, prefix=""):
    """
    Flatten nested dictionaries.

    Example:
        {"5m": {"momentum_3": 1.2}}

    becomes:
        {"5m_momentum_3": 1.2}
    """

    output = {}

    if not isinstance(data, dict):
        return output

    for key, value in data.items():

        key = str(key)

        full_key = (
            f"{prefix}_{key}"
            if prefix
            else key
        )

        if isinstance(value, dict):

            nested = flatten_dict(
                value,
                full_key,
            )

            output.update(nested)

        elif isinstance(
            value,
            (str, int, float, bool)
        ) or value is None:

            output[full_key] = value

    return output


def build_feature_map(row):
    """
    Merge feature sources.

    combined_features gets first priority.
    technical_features and market_features then fill missing keys.
    """

    merged = {}

    sources = (
        row.get("combined_features"),
        row.get("technical_features"),
        row.get("market_features"),
    )

    for source in sources:

        flattened = flatten_dict(
            parse_json(source)
        )

        for key, value in flattened.items():

            if key not in merged:
                merged[key] = value

    return merged


def excluded_feature(name):
    lowered = name.lower()

    return any(
        token in lowered
        for token in EXCLUDED_FEATURE_TOKENS
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

    connection = psycopg2.connect(
        database_url
    )

    connection.set_session(
        readonly=True,
        autocommit=False,
    )

    return connection


def load_rows(connection):
    sql = """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            UPPER(o.direction) AS direction,

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

        WHERE UPPER(o.direction) IN ('LONG', 'SHORT')

          AND UPPER(COALESCE(o.symbol, ''))
              NOT LIKE '%%TEST%%'

          AND UPPER(COALESCE(o.symbol, ''))
              NOT LIKE '%%DIAGNOSTIC%%'

          AND UPPER(COALESCE(o.symbol, ''))
              NOT LIKE '%%SYNTHETIC%%'

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

    cursor = connection.cursor()

    cursor.execute(sql)

    columns = [
        description[0]
        for description in cursor.description
    ]

    rows = [
        dict(zip(columns, record))
        for record in cursor.fetchall()
    ]

    cursor.close()

    for row in rows:
        row["_features"] = build_feature_map(
            row
        )

    return rows


# =============================================================================
# CHRONOLOGICAL SPLIT
# =============================================================================

def split_rows(rows):
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

    discovery = rows[:split_index]
    holdout = rows[split_index:]

    return discovery, holdout


# =============================================================================
# GROUP HELPERS
# =============================================================================

def group_rows(
    rows,
    direction,
    horizon,
):
    column = return_column(horizon)

    output = []

    for row in rows:

        if row["direction"] != direction:
            continue

        result = safe_float(
            row.get(column)
        )

        if result is None:
            continue

        output.append(row)

    return output


def group_returns(
    rows,
    direction,
    horizon,
):
    column = return_column(horizon)

    values = []

    for row in rows:

        if row["direction"] != direction:
            continue

        result = safe_float(
            row.get(column)
        )

        if result is not None:
            values.append(result)

    return values


# =============================================================================
# BASELINE METRICS
# =============================================================================

def calculate_metrics(
    raw_returns,
    cost_pct=PRIMARY_COST_PCT,
):
    if not raw_returns:
        return None

    net_returns = [
        value - cost_pct
        for value in raw_returns
    ]

    raw_target_hits = sum(
        1
        for value in raw_returns
        if value >= REQUIRED_RAW_MOVE_PCT
    )

    net_positive = sum(
        1
        for value in net_returns
        if value > 0
    )

    return {
        "n":
            len(raw_returns),

        "raw_expectancy":
            mean(raw_returns),

        "raw_median":
            median(raw_returns),

        "net_expectancy":
            mean(net_returns),

        "net_median":
            median(net_returns),

        "net_positive_rate":
            percentage(
                net_positive,
                len(net_returns),
            ),

        "target_hit_rate":
            percentage(
                raw_target_hits,
                len(raw_returns),
            ),

        "profit_factor":
            profit_factor(
                net_returns
            ),
    }


# =============================================================================
# FEATURE CATALOG
# =============================================================================

def build_feature_catalog(rows):
    """
    IMPORTANT:
    Called ONLY with DISCOVERY rows.

    Thresholds are therefore discovery-only.
    """

    numeric_values = {}
    boolean_values = {}

    for row in rows:

        features = row["_features"]

        for name, value in features.items():

            if excluded_feature(name):
                continue

            if isinstance(value, bool):

                boolean_values.setdefault(
                    name,
                    set(),
                ).add(value)

                continue

            numeric = safe_float(value)

            if numeric is None:
                continue

            numeric_values.setdefault(
                name,
                [],
            ).append(numeric)

    catalog = {}

    for name, values in numeric_values.items():

        if len(values) < MIN_DISCOVERY_SAMPLE:
            continue

        thresholds = []

        for q in QUANTILES:

            threshold = percentile(
                values,
                q,
            )

            if threshold is None:
                continue

            rounded = round(
                threshold,
                6,
            )

            if rounded not in thresholds:
                thresholds.append(rounded)

        if thresholds:

            catalog[name] = {
                "type": "numeric",
                "thresholds": thresholds,
            }

    for name, values in boolean_values.items():

        if len(values) == 0:
            continue

        catalog[name] = {
            "type": "boolean",
            "values": sorted(values),
        }

    return catalog


# =============================================================================
# RULES
# =============================================================================

def make_numeric_rule(
    feature,
    operator,
    threshold,
):
    return {
        "conditions": [
            {
                "feature": feature,
                "operator": operator,
                "value": threshold,
            }
        ]
    }


def make_boolean_rule(
    feature,
    value,
):
    return {
        "conditions": [
            {
                "feature": feature,
                "operator": "==",
                "value": value,
            }
        ]
    }


def condition_matches(
    features,
    condition,
):
    feature = condition["feature"]

    if feature not in features:
        return False

    actual = features[feature]

    operator = condition["operator"]
    expected = condition["value"]

    if operator == "==":
        return actual == expected

    actual_number = safe_float(actual)
    expected_number = safe_float(expected)

    if (
        actual_number is None
        or expected_number is None
    ):
        return False

    if operator == "<=":
        return actual_number <= expected_number

    if operator == ">=":
        return actual_number >= expected_number

    if operator == "<":
        return actual_number < expected_number

    if operator == ">":
        return actual_number > expected_number

    return False


def rule_matches(
    row,
    rule,
):
    features = row["_features"]

    return all(
        condition_matches(
            features,
            condition,
        )
        for condition in rule["conditions"]
    )


def rule_text(rule):
    pieces = []

    for condition in rule["conditions"]:

        value = condition["value"]

        if isinstance(value, float):
            value_text = f"{value:.6f}"
        else:
            value_text = str(value)

        pieces.append(
            "["
            f"{condition['feature']} "
            f"{condition['operator']} "
            f"{value_text}"
            "]"
        )

    return " AND ".join(pieces)


# =============================================================================
# RULE EVALUATION
# =============================================================================

def evaluate_rule(
    rows,
    direction,
    horizon,
    rule,
):
    column = return_column(horizon)

    returns = []

    for row in rows:

        if row["direction"] != direction:
            continue

        result = safe_float(
            row.get(column)
        )

        if result is None:
            continue

        if rule_matches(
            row,
            rule,
        ):
            returns.append(result)

    return calculate_metrics(
        returns
    )


def add_lifts(
    metrics,
    baseline,
):
    if (
        metrics is None
        or baseline is None
    ):
        return None

    result = dict(metrics)

    result["net_expectancy_lift"] = (
        metrics["net_expectancy"]
        - baseline["net_expectancy"]
    )

    result["target_hit_lift"] = (
        metrics["target_hit_rate"]
        - baseline["target_hit_rate"]
    )

    return result


# =============================================================================
# DISCOVERY-ONLY SINGLE FEATURE SEARCH
# =============================================================================

def discover_single_rules(
    discovery_rows,
    catalog,
    direction,
    horizon,
):
    baseline_returns = group_returns(
        discovery_rows,
        direction,
        horizon,
    )

    baseline = calculate_metrics(
        baseline_returns
    )

    results = []

    for feature, definition in catalog.items():

        candidate_rules = []

        if definition["type"] == "numeric":

            for threshold in definition[
                "thresholds"
            ]:

                candidate_rules.append(
                    make_numeric_rule(
                        feature,
                        "<=",
                        threshold,
                    )
                )

                candidate_rules.append(
                    make_numeric_rule(
                        feature,
                        ">=",
                        threshold,
                    )
                )

        elif definition["type"] == "boolean":

            for value in definition[
                "values"
            ]:

                candidate_rules.append(
                    make_boolean_rule(
                        feature,
                        value,
                    )
                )

        for rule in candidate_rules:

            metrics = evaluate_rule(
                discovery_rows,
                direction,
                horizon,
                rule,
            )

            if metrics is None:
                continue

            if (
                metrics["n"]
                < MIN_DISCOVERY_SAMPLE
            ):
                continue

            metrics = add_lifts(
                metrics,
                baseline,
            )

            # Discovery score intentionally prioritises
            # net expectancy improvement.
            discovery_score = (
                metrics[
                    "net_expectancy_lift"
                ] * 100.0
                + metrics[
                    "target_hit_lift"
                ] * 0.10
            )

            results.append({
                "direction": direction,
                "horizon": horizon,
                "rule": rule,
                "rule_text": rule_text(rule),
                "metrics": metrics,
                "discovery_score":
                    discovery_score,
            })

    results.sort(
        key=lambda item:
            item["discovery_score"],
        reverse=True,
    )

    return (
        baseline,
        results[
            :TOP_SINGLE_CANDIDATES_PER_GROUP
        ],
    )


# =============================================================================
# DISCOVERY-ONLY PAIR CONSTRUCTION
# =============================================================================

def build_pair_candidates(
    discovery_single_results,
):
    """
    CRITICAL METHODOLOGY RULE:

    Pair source features come ONLY from discovery rankings.

    Holdout data has not been evaluated at this point.
    """

    sources = (
        discovery_single_results[
            :PAIR_SOURCE_LIMIT
        ]
    )

    pairs = []

    seen = set()

    for i in range(len(sources)):

        for j in range(
            i + 1,
            len(sources),
        ):

            first = sources[i]["rule"][
                "conditions"
            ][0]

            second = sources[j]["rule"][
                "conditions"
            ][0]

            if (
                first["feature"]
                == second["feature"]
            ):
                continue

            conditions = [
                dict(first),
                dict(second),
            ]

            key = tuple(
                sorted(
                    (
                        condition["feature"],
                        condition["operator"],
                        str(condition["value"]),
                    )
                    for condition
                    in conditions
                )
            )

            if key in seen:
                continue

            seen.add(key)

            pairs.append({
                "conditions": conditions
            })

    return pairs


def discover_pair_rules(
    discovery_rows,
    direction,
    horizon,
    baseline,
    single_results,
):
    candidates = build_pair_candidates(
        single_results
    )

    results = []

    for rule in candidates:

        metrics = evaluate_rule(
            discovery_rows,
            direction,
            horizon,
            rule,
        )

        if metrics is None:
            continue

        if (
            metrics["n"]
            < MIN_DISCOVERY_SAMPLE
        ):
            continue

        metrics = add_lifts(
            metrics,
            baseline,
        )

        discovery_score = (
            metrics[
                "net_expectancy_lift"
            ] * 100.0
            + metrics[
                "target_hit_lift"
            ] * 0.10
        )

        results.append({
            "direction": direction,
            "horizon": horizon,
            "rule": rule,
            "rule_text": rule_text(rule),
            "metrics": metrics,
            "discovery_score":
                discovery_score,
        })

    results.sort(
        key=lambda item:
            item["discovery_score"],
        reverse=True,
    )

    return results[
        :TOP_PAIR_CANDIDATES_PER_GROUP
    ]


# =============================================================================
# FREEZE SHORTLIST BEFORE HOLDOUT
# =============================================================================

def freeze_candidates(
    singles,
    pairs,
):
    """
    This function is called BEFORE holdout evaluation.

    The shortlist is frozen entirely from discovery performance.
    """

    combined = (
        list(singles)
        + list(pairs)
    )

    combined.sort(
        key=lambda item:
            item["discovery_score"],
        reverse=True,
    )

    frozen = []

    seen = set()

    for item in combined:

        key = item["rule_text"]

        if key in seen:
            continue

        seen.add(key)

        frozen.append(item)

        if (
            len(frozen)
            >= FINAL_FROZEN_CANDIDATES_PER_GROUP
        ):
            break

    return frozen


# =============================================================================
# HOLDOUT VALIDATION
# =============================================================================

def validate_frozen_candidate(
    candidate,
    holdout_rows,
):
    direction = candidate["direction"]
    horizon = candidate["horizon"]

    baseline_returns = group_returns(
        holdout_rows,
        direction,
        horizon,
    )

    baseline = calculate_metrics(
        baseline_returns
    )

    metrics = evaluate_rule(
        holdout_rows,
        direction,
        horizon,
        candidate["rule"],
    )

    if metrics is None:
        return {
            **candidate,
            "holdout_baseline": baseline,
            "holdout_metrics": None,
            "consistent": False,
        }

    metrics = add_lifts(
        metrics,
        baseline,
    )

    enough_sample = (
        metrics["n"]
        >= MIN_HOLDOUT_SAMPLE
    )

    positive_net_lift = (
        metrics[
            "net_expectancy_lift"
        ] > 0
    )

    positive_target_lift = (
        metrics[
            "target_hit_lift"
        ] > 0
    )

    discovery_positive = (
        candidate["metrics"][
            "net_expectancy_lift"
        ] > 0
    )

    consistent = (
        enough_sample
        and discovery_positive
        and positive_net_lift
        and positive_target_lift
    )

    return {
        **candidate,

        "holdout_baseline":
            baseline,

        "holdout_metrics":
            metrics,

        "consistent":
            consistent,
    }


# =============================================================================
# COST STRESS
# =============================================================================

def evaluate_cost_stress(
    rows,
    candidate,
):
    direction = candidate["direction"]
    horizon = candidate["horizon"]

    column = return_column(horizon)

    raw_returns = []

    for row in rows:

        if row["direction"] != direction:
            continue

        result = safe_float(
            row.get(column)
        )

        if result is None:
            continue

        if rule_matches(
            row,
            candidate["rule"],
        ):
            raw_returns.append(result)

    results = []

    for cost in COST_SCENARIOS_PCT:

        metrics = calculate_metrics(
            raw_returns,
            cost_pct=cost,
        )

        results.append({
            "cost": cost,
            "metrics": metrics,
        })

    return results


# =============================================================================
# REPORTING
# =============================================================================

def print_startup():
    banner(
        "BRADS-SIGNALS-RESEARCHER"
    )

    print(
        f"RESEARCH VERSION: "
        f"{RESEARCH_VERSION}"
    )

    print(
        f"UTC START: "
        f"{datetime.now(timezone.utc).isoformat()}"
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

    print()

    print(
        "PRIMARY RESEARCH TARGET:"
    )

    print(
        f"  HYPOTHETICAL COST="
        f"{PRIMARY_COST_PCT:.2f}%"
    )

    print(
        f"  DESIRED NET MOVE="
        f"+{DESIRED_NET_MOVE_PCT:.2f}%"
    )

    print(
        f"  REQUIRED RAW MOVE="
        f"+{REQUIRED_RAW_MOVE_PCT:.2f}%"
    )


def print_dataset_health(
    rows,
    discovery,
    holdout,
):
    banner(
        "R11 DATASET HEALTH"
    )

    print(
        f"TOTAL ROWS: {len(rows)}"
    )

    print(
        f"DISCOVERY ROWS: "
        f"{len(discovery)}"
    )

    print(
        f"HOLDOUT ROWS: "
        f"{len(holdout)}"
    )

    if discovery:

        print(
            f"DISCOVERY FIRST: "
            f"{discovery[0]['created_at']}"
        )

        print(
            f"DISCOVERY LAST:  "
            f"{discovery[-1]['created_at']}"
        )

    if holdout:

        print(
            f"HOLDOUT FIRST: "
            f"{holdout[0]['created_at']}"
        )

        print(
            f"HOLDOUT LAST:  "
            f"{holdout[-1]['created_at']}"
        )

    print()

    print(
        "METHODOLOGY:"
    )

    print(
        "  FEATURE THRESHOLDS: "
        "DISCOVERY ONLY"
    )

    print(
        "  SINGLE RULE RANKING: "
        "DISCOVERY ONLY"
    )

    print(
        "  PAIR CONSTRUCTION: "
        "DISCOVERY ONLY"
    )

    print(
        "  FINAL SHORTLIST: "
        "FROZEN BEFORE HOLDOUT"
    )

    print(
        "  HOLDOUT USED ONLY AFTER "
        "SHORTLIST FREEZE"
    )


def print_baseline(
    direction,
    horizon,
    baseline,
):
    print(
        f"{direction} {horizon}"
        f" | N={baseline['n']}"
        f" | NET_EXP="
        f"{baseline['net_expectancy']:+.5f}%"
        f" | TARGET_HIT="
        f"{baseline['target_hit_rate']:.2f}%"
        f" | PF="
        f"{fmt(baseline['profit_factor'], 3)}"
    )


def print_discovery_candidate(
    rank,
    candidate,
):
    metrics = candidate["metrics"]

    print()
    print(
        f"{rank}. "
        f"{candidate['direction']} "
        f"{candidate['horizon']}"
    )

    print(
        f"   RULE: "
        f"{candidate['rule_text']}"
    )

    print(
        f"   DISCOVERY N="
        f"{metrics['n']}"
    )

    print(
        f"   RAW_EXPECTANCY="
        f"{metrics['raw_expectancy']:+.5f}%"
    )

    print(
        f"   NET_EXPECTANCY@0.05="
        f"{metrics['net_expectancy']:+.5f}%"
    )

    print(
        f"   NET_EXPECTANCY_LIFT="
        f"{metrics['net_expectancy_lift']:+.5f}pp"
    )

    print(
        f"   TARGET_HIT="
        f"{metrics['target_hit_rate']:.2f}%"
    )

    print(
        f"   TARGET_HIT_LIFT="
        f"{metrics['target_hit_lift']:+.2f}pp"
    )

    print(
        f"   PF="
        f"{fmt(metrics['profit_factor'], 3)}"
    )


def print_holdout_candidate(
    rank,
    result,
):
    discovery = result["metrics"]
    holdout = result["holdout_metrics"]

    print()
    print(
        f"{rank}. "
        f"{result['direction']} "
        f"{result['horizon']}"
    )

    print(
        f"   RULE: "
        f"{result['rule_text']}"
    )

    print(
        "   DISCOVERY:"
    )

    print(
        f"     N={discovery['n']}"
        f" | NET_EXP="
        f"{discovery['net_expectancy']:+.5f}%"
        f" | NET_LIFT="
        f"{discovery['net_expectancy_lift']:+.5f}pp"
        f" | TARGET="
        f"{discovery['target_hit_rate']:.2f}%"
        f" | PF="
        f"{fmt(discovery['profit_factor'], 3)}"
    )

    print(
        "   HOLDOUT:"
    )

    if holdout is None:

        print(
            "     NO MATCHES"
        )

        print(
            "   CONSISTENT: False"
        )

        return

    print(
        f"     N={holdout['n']}"
        f" | RAW_EXP="
        f"{holdout['raw_expectancy']:+.5f}%"
        f" | NET_EXP="
        f"{holdout['net_expectancy']:+.5f}%"
    )

    print(
        f"     NET_LIFT="
        f"{holdout['net_expectancy_lift']:+.5f}pp"
        f" | TARGET="
        f"{holdout['target_hit_rate']:.2f}%"
        f" | TARGET_LIFT="
        f"{holdout['target_hit_lift']:+.2f}pp"
        f" | PF="
        f"{fmt(holdout['profit_factor'], 3)}"
    )

    print(
        f"   CONSISTENT: "
        f"{result['consistent']}"
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    connection = None

    try:
        print_startup()

        assert DATABASE_WRITES is False
        assert TELEGRAM_SENDING is False
        assert TRADE_EXECUTION is False
        assert PRODUCTION_MODIFICATION is False
        assert AI_CALLS is False

        print()
        print(
            "SAFETY CHECK: PASS"
        )

        connection = connect_database()

        print(
            "DATABASE CONNECTION: READY"
        )

        print(
            "DATABASE SESSION: READ ONLY"
        )

        rows = load_rows(
            connection
        )

        if len(rows) < 2:
            raise RuntimeError(
                "Not enough historical rows "
                "for R11."
            )

        discovery, holdout = split_rows(
            rows
        )

        print_dataset_health(
            rows,
            discovery,
            holdout,
        )

        # -------------------------------------------------------------
        # Build feature thresholds from DISCOVERY ONLY.
        # -------------------------------------------------------------

        banner(
            "R11 DISCOVERY-ONLY FEATURE CATALOG"
        )

        catalog = build_feature_catalog(
            discovery
        )

        print(
            f"FEATURES AVAILABLE FOR RESEARCH: "
            f"{len(catalog)}"
        )

        print(
            "HOLDOUT USED TO BUILD CATALOG: FALSE"
        )

        # -------------------------------------------------------------
        # Discovery stage.
        # Holdout is deliberately untouched here.
        # -------------------------------------------------------------

        frozen_candidates = []

        for direction in DIRECTIONS:

            for horizon in HORIZONS:

                banner(
                    f"R11 DISCOVERY | "
                    f"{direction} | {horizon}"
                )

                (
                    baseline,
                    singles,
                ) = discover_single_rules(
                    discovery,
                    catalog,
                    direction,
                    horizon,
                )

                if baseline is None:
                    print(
                        "NO BASELINE DATA"
                    )
                    continue

                print(
                    "DISCOVERY BASELINE:"
                )

                print_baseline(
                    direction,
                    horizon,
                    baseline,
                )

                print()
                print(
                    "TOP DISCOVERY SINGLE "
                    "FEATURE RULES:"
                )

                for rank, candidate in enumerate(
                    singles[:10],
                    start=1,
                ):
                    print_discovery_candidate(
                        rank,
                        candidate,
                    )

                pairs = discover_pair_rules(
                    discovery,
                    direction,
                    horizon,
                    baseline,
                    singles,
                )

                print()
                print(
                    "TOP DISCOVERY PAIR RULES:"
                )

                for rank, candidate in enumerate(
                    pairs[:10],
                    start=1,
                ):
                    print_discovery_candidate(
                        rank,
                        candidate,
                    )

                frozen = freeze_candidates(
                    singles,
                    pairs,
                )

                print()
                print(
                    "FROZEN BEFORE HOLDOUT:"
                )

                for rank, candidate in enumerate(
                    frozen,
                    start=1,
                ):

                    print(
                        f"  {rank}. "
                        f"{candidate['rule_text']}"
                    )

                frozen_candidates.extend(
                    frozen
                )

        # -------------------------------------------------------------
        # HOLDOUT BEGINS ONLY HERE.
        # -------------------------------------------------------------

        banner(
            "R11 HOLDOUT UNLOCKED"
        )

        print(
            "DISCOVERY COMPLETE: TRUE"
        )

        print(
            "PAIR CONSTRUCTION COMPLETE: TRUE"
        )

        print(
            "SHORTLIST FROZEN: TRUE"
        )

        print(
            "HOLDOUT EVALUATION NOW STARTING"
        )

        validated = []

        for candidate in frozen_candidates:

            result = validate_frozen_candidate(
                candidate,
                holdout,
            )

            validated.append(
                result
            )

        # -------------------------------------------------------------
        # Consistent held-out candidates
        # -------------------------------------------------------------

        consistent = [
            result
            for result in validated
            if result["consistent"]
        ]

        consistent.sort(
            key=lambda result:
                (
                    result["holdout_metrics"][
                        "net_expectancy"
                    ]
                    if result[
                        "holdout_metrics"
                    ]
                    else -999999
                ),
            reverse=True,
        )

        banner(
            "R11 CONSISTENT HELD-OUT "
            "OPPORTUNITY-QUALITY LEADS"
        )

        print(
            f"CONSISTENT LEADS: "
            f"{len(consistent)}"
        )

        if not consistent:

            print(
                "NO FROZEN R11 CANDIDATE "
                "PASSED THE CONSISTENCY "
                "REQUIREMENTS."
            )

        else:

            for rank, result in enumerate(
                consistent[:25],
                start=1,
            ):

                print_holdout_candidate(
                    rank,
                    result,
                )

        # -------------------------------------------------------------
        # Cost stress on strongest consistent leads.
        # -------------------------------------------------------------

        banner(
            "R11 HOLDOUT COST STRESS"
        )

        if not consistent:

            print(
                "NO CONSISTENT LEADS "
                "AVAILABLE FOR COST STRESS."
            )

        else:

            for rank, candidate in enumerate(
                consistent[:10],
                start=1,
            ):

                print()
                print(
                    f"{rank}. "
                    f"{candidate['direction']} "
                    f"{candidate['horizon']}"
                )

                print(
                    f"   RULE: "
                    f"{candidate['rule_text']}"
                )

                stress = evaluate_cost_stress(
                    holdout,
                    candidate,
                )

                for item in stress:

                    metrics = item[
                        "metrics"
                    ]

                    if metrics is None:
                        continue

                    print(
                        f"   COST="
                        f"{item['cost']:.2f}%"
                        f" | NET_EXP="
                        f"{metrics['net_expectancy']:+.5f}%"
                        f" | NET_POSITIVE="
                        f"{metrics['net_positive_rate']:.2f}%"
                        f" | PF="
                        f"{fmt(metrics['profit_factor'], 3)}"
                    )

        # -------------------------------------------------------------
        # Final methodology statement
        # -------------------------------------------------------------

        banner(
            "R11 METHODOLOGY AUDIT"
        )

        print(
            "THRESHOLDS BUILT FROM "
            "DISCOVERY ONLY: TRUE"
        )

        print(
            "SINGLE RULE RANKING USED "
            "DISCOVERY ONLY: TRUE"
        )

        print(
            "PAIR SOURCE SELECTION USED "
            "DISCOVERY ONLY: TRUE"
        )

        print(
            "PAIR RULE RANKING USED "
            "DISCOVERY ONLY: TRUE"
        )

        print(
            "FINAL SHORTLIST FROZEN "
            "BEFORE HOLDOUT: TRUE"
        )

        print(
            "HOLDOUT USED FOR CANDIDATE "
            "DISCOVERY: FALSE"
        )

        # -------------------------------------------------------------
        # Guardrails
        # -------------------------------------------------------------

        banner(
            "R11 GUARDRAILS"
        )

        print(
            "1. R11 IS HISTORICAL RESEARCH, "
            "NOT LIVE OR PROSPECTIVE PROOF."
        )

        print(
            "2. HOLDOUT DATA WAS NOT USED "
            "TO CREATE OR RANK THE FROZEN "
            "CANDIDATES."
        )

        print(
            "3. MULTIPLE-TESTING RISK STILL "
            "EXISTS BECAUSE MANY FEATURES "
            "AND THRESHOLDS ARE TESTED."
        )

        print(
            "4. THE 0.05% COST IS A "
            "HYPOTHETICAL RESEARCH "
            "ASSUMPTION, NOT A CLAIMED "
            "BITGET FEE."
        )

        print(
            "5. SPREAD, SLIPPAGE, FUNDING, "
            "LATENCY, LIQUIDATION AND FILL "
            "QUALITY ARE NOT FULLY MODELLED."
        )

        print(
            "6. LONG AND SHORT OBSERVATIONS "
            "CAN COME FROM THE SAME MARKET "
            "SNAPSHOT AND ARE NOT "
            "INDEPENDENT TRADES."
        )

        print(
            "7. LEVERAGE IS NOT USED TO "
            "CREATE OR RESCUE EDGE."
        )

        print(
            "8. ANY PROMISING R11 LEAD MUST "
            "BE FROZEN AND PROSPECTIVELY "
            "VALIDATED BEFORE PRODUCTION."
        )

        print(
            "9. R11 DOES NOT AUTHORIZE ANY "
            "BOT 2.0 STRATEGY CHANGE."
        )

        print(
            "10. R11 DOES NOT CHANGE THE "
            "65 AI PRE-SCREEN OR 80 SIGNAL "
            "THRESHOLD."
        )

        banner(
            "R11 FINAL STATUS"
        )

        print(
            "STATUS: R11 TRADE OPPORTUNITY "
            "QUALITY RESEARCH COMPLETE"
        )

        print(
            f"FROZEN CANDIDATES TESTED: "
            f"{len(validated)}"
        )

        print(
            f"CONSISTENT HELD-OUT LEADS: "
            f"{len(consistent)}"
        )

        print(
            "DATABASE REMAINED READ ONLY"
        )

        print(
            "NO WRITES; NO TELEGRAM; "
            "NO TRADES; NO AI; "
            "NO PRODUCTION CHANGES"
        )

    except Exception as exc:

        banner(
            "R11 ERROR"
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
