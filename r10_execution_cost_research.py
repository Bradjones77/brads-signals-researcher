"""
BRAD'S SIGNALS RESEARCHER
R10 - EXECUTION & COST REALITY RESEARCH

PURPOSE
-------
Study how much directional price movement is required for a fast trading
strategy to remain profitable after realistic hypothetical trading costs.

R10 DOES NOT:
- place trades
- send Telegram messages
- call AI
- write to PostgreSQL
- modify Bot 2.0
- modify confidence thresholds
- modify R9/R9.1 rules
- use leverage to manufacture an edge

R10 DOES:
- analyse completed historical fast outcomes
- measure raw move distributions
- apply hypothetical round-trip cost scenarios
- calculate break-even move requirements
- study LONG and SHORT separately
- study 1m / 5m / 10m / 30m separately
- calculate cost-adjusted expectancy
- calculate profit factor
- calculate target-hit rates
- calculate the effect of leverage AFTER costs
- show how leverage magnifies both positive and negative expectancy

IMPORTANT
---------
Cost scenarios are RESEARCH ASSUMPTIONS.
They are NOT claimed Bitget fee rates.

True live execution would additionally depend on:
spread, slippage, order type, fill quality, funding, latency,
liquidation distance and actual exchange fees.
"""

import math
import os
from datetime import datetime, timezone

import psycopg2


# =============================================================================
# VERSION / SAFETY
# =============================================================================

RESEARCH_VERSION = "R10-EXECUTION-COST-REALITY-RESEARCH"

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False
STRATEGY_MODIFICATION = False


# =============================================================================
# RESEARCH SETTINGS
# =============================================================================

HORIZONS = (
    "1m",
    "5m",
    "10m",
    "30m",
)

# Hypothetical total entry + exit trading friction.
# These are research assumptions only.
COST_SCENARIOS_PCT = (
    0.00,
    0.02,
    0.05,
    0.075,
    0.10,
    0.15,
    0.20,
)

PRIMARY_COST_PCT = 0.05


# Net profit targets AFTER costs.
NET_TARGETS_PCT = (
    0.00,
    0.05,
    0.10,
    0.20,
    0.30,
    0.50,
)


# Leverage is analysed only as arithmetic AFTER edge/cost.
# It is NOT used to turn a losing setup into a winning setup.
LEVERAGE_SCENARIOS = (
    1,
    2,
    5,
    10,
    20,
)


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

    ordered = sorted(values)

    n = len(ordered)

    middle = n // 2

    if n % 2:
        return ordered[middle]

    return (
        ordered[middle - 1]
        + ordered[middle]
    ) / 2.0


def percentile(values, percentile_value):
    if not values:
        return None

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        percentile_value / 100.0
    ) * (len(ordered) - 1)

    lower = int(math.floor(position))
    upper = int(math.ceil(position))

    if lower == upper:
        return ordered[lower]

    weight = position - lower

    return (
        ordered[lower] * (1.0 - weight)
        + ordered[upper] * weight
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


def percentage(count, total):
    if total <= 0:
        return 0.0

    return (
        float(count)
        / float(total)
        * 100.0
    )


def fmt(value, decimals=5):
    if value is None:
        return "N/A"

    if math.isinf(value):
        return "INF"

    return f"{value:.{decimals}f}"


def return_column(horizon):
    columns = {
        "1m": "return_1m_pct",
        "5m": "return_5m_pct",
        "10m": "return_10m_pct",
        "30m": "return_30m_pct",
    }

    if horizon not in columns:
        raise ValueError(
            f"Unsupported horizon: {horizon}"
        )

    return columns[horizon]


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

    # Hard safety barrier.
    connection.set_session(
        readonly=True,
        autocommit=False,
    )

    return connection


def load_rows(connection):
    """
    Historical research dataset.

    We only require at least one fast return to exist.

    We deliberately exclude obvious synthetic/test/diagnostic records.
    """

    sql = """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            UPPER(o.direction) AS direction,

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

    return rows


# =============================================================================
# DATA EXTRACTION
# =============================================================================

def get_returns(
    rows,
    direction,
    horizon,
):
    column = return_column(horizon)

    values = []

    for row in rows:

        if row["direction"] != direction:
            continue

        value = safe_float(
            row.get(column)
        )

        if value is not None:
            values.append(value)

    return values


# =============================================================================
# METRICS
# =============================================================================

def raw_metrics(values):
    if not values:
        return None

    n = len(values)

    positive = sum(
        1
        for value in values
        if value > 0
    )

    negative = sum(
        1
        for value in values
        if value < 0
    )

    zero = (
        n
        - positive
        - negative
    )

    return {
        "n": n,

        "mean": mean(values),
        "median": median(values),

        "p05": percentile(values, 5),
        "p10": percentile(values, 10),
        "p25": percentile(values, 25),
        "p50": percentile(values, 50),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),

        "positive_rate": percentage(
            positive,
            n,
        ),

        "negative_rate": percentage(
            negative,
            n,
        ),

        "zero_rate": percentage(
            zero,
            n,
        ),

        "profit_factor": profit_factor(
            values
        ),
    }


def cost_metrics(
    raw_returns,
    cost_pct,
):
    if not raw_returns:
        return None

    net_returns = [
        value - cost_pct
        for value in raw_returns
    ]

    n = len(net_returns)

    profitable = sum(
        1
        for value in net_returns
        if value > 0
    )

    return {
        "n": n,

        "cost": cost_pct,

        "expectancy": mean(
            net_returns
        ),

        "median": median(
            net_returns
        ),

        "net_positive_rate": percentage(
            profitable,
            n,
        ),

        "profit_factor": profit_factor(
            net_returns
        ),
    }


def target_metrics(
    raw_returns,
    cost_pct,
    desired_net_pct,
):
    """
    Example:

    cost = 0.05%
    desired net = +0.05%

    raw move required = +0.10%
    """

    if not raw_returns:
        return None

    required_raw_move = (
        cost_pct
        + desired_net_pct
    )

    hits = sum(
        1
        for value in raw_returns
        if value >= required_raw_move
    )

    return {
        "required_raw_move":
            required_raw_move,

        "hit_count":
            hits,

        "hit_rate":
            percentage(
                hits,
                len(raw_returns),
            ),
    }


# =============================================================================
# LEVERAGE RESEARCH
# =============================================================================

def leveraged_expectancy(
    raw_expectancy,
    cost_pct,
    leverage,
):
    """
    Simplified arithmetic research model.

    We first subtract trading cost from the underlying directional return.

    THEN leverage multiplies that net return.

    This deliberately demonstrates:

        positive edge * leverage = larger positive expectation

        negative edge * leverage = larger negative expectation

    It does NOT model:
        liquidation
        maintenance margin
        funding
        spread
        slippage
        order-book depth
        fill quality
    """

    underlying_net = (
        raw_expectancy
        - cost_pct
    )

    leveraged_net = (
        underlying_net
        * leverage
    )

    return (
        underlying_net,
        leveraged_net,
    )


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

    print(
        f"STRATEGY MODIFICATION: "
        f"{STRATEGY_MODIFICATION}"
    )

    print(
        "PURPOSE: EXECUTION / COST / "
        "MOVE-SIZE REALITY RESEARCH"
    )

    print(
        "COST VALUES ARE HYPOTHETICAL "
        "RESEARCH ASSUMPTIONS"
    )


def print_dataset_health(rows):
    banner(
        "R10 DATASET HEALTH"
    )

    print(
        f"ROWS WITH FAST OUTCOMES: "
        f"{len(rows)}"
    )

    if not rows:
        return

    long_count = sum(
        1
        for row in rows
        if row["direction"] == "LONG"
    )

    short_count = sum(
        1
        for row in rows
        if row["direction"] == "SHORT"
    )

    print(
        f"LONG ROWS: {long_count}"
    )

    print(
        f"SHORT ROWS: {short_count}"
    )

    print(
        f"FIRST ROW: "
        f"{rows[0]['created_at']}"
    )

    print(
        f"LAST ROW:  "
        f"{rows[-1]['created_at']}"
    )

    print()

    for direction in (
        "LONG",
        "SHORT",
    ):

        for horizon in HORIZONS:

            values = get_returns(
                rows,
                direction,
                horizon,
            )

            print(
                f"{direction} {horizon}: "
                f"N={len(values)}"
            )


def print_raw_distribution(
    direction,
    horizon,
    values,
):
    metrics = raw_metrics(values)

    banner(
        f"R10 RAW MOVE DISTRIBUTION | "
        f"{direction} | {horizon}"
    )

    if metrics is None:
        print(
            "NO DATA"
        )
        return

    print(
        f"N={metrics['n']}"
    )

    print(
        "RAW EXPECTANCY="
        f"{metrics['mean']:+.5f}%"
    )

    print(
        "RAW MEDIAN="
        f"{metrics['median']:+.5f}%"
    )

    print(
        "RAW POSITIVE RATE="
        f"{metrics['positive_rate']:.2f}%"
    )

    print(
        "RAW NEGATIVE RATE="
        f"{metrics['negative_rate']:.2f}%"
    )

    print(
        "RAW PROFIT FACTOR="
        f"{fmt(metrics['profit_factor'], 3)}"
    )

    print()

    print(
        "RETURN DISTRIBUTION:"
    )

    print(
        f"  P05={metrics['p05']:+.5f}%"
    )

    print(
        f"  P10={metrics['p10']:+.5f}%"
    )

    print(
        f"  P25={metrics['p25']:+.5f}%"
    )

    print(
        f"  P50={metrics['p50']:+.5f}%"
    )

    print(
        f"  P75={metrics['p75']:+.5f}%"
    )

    print(
        f"  P90={metrics['p90']:+.5f}%"
    )

    print(
        f"  P95={metrics['p95']:+.5f}%"
    )


def print_cost_sensitivity(
    direction,
    horizon,
    values,
):
    banner(
        f"R10 COST SENSITIVITY | "
        f"{direction} | {horizon}"
    )

    if not values:
        print(
            "NO DATA"
        )
        return

    for cost in COST_SCENARIOS_PCT:

        metrics = cost_metrics(
            values,
            cost,
        )

        print(
            f"COST={cost:.3f}%"
            f" | EXPECTANCY="
            f"{metrics['expectancy']:+.5f}%"
            f" | MEDIAN="
            f"{metrics['median']:+.5f}%"
            f" | NET_POSITIVE="
            f"{metrics['net_positive_rate']:.2f}%"
            f" | PF="
            f"{fmt(metrics['profit_factor'], 3)}"
        )


def print_move_requirements(
    direction,
    horizon,
    values,
):
    banner(
        f"R10 MOVE REQUIREMENTS | "
        f"{direction} | {horizon}"
    )

    if not values:
        print(
            "NO DATA"
        )
        return

    print(
        f"PRIMARY COST ASSUMPTION: "
        f"{PRIMARY_COST_PCT:.2f}%"
    )

    print()

    for desired_net in NET_TARGETS_PCT:

        metrics = target_metrics(
            values,
            PRIMARY_COST_PCT,
            desired_net,
        )

        print(
            f"DESIRED NET=+{desired_net:.2f}%"
            f" | REQUIRED RAW MOVE="
            f"+{metrics['required_raw_move']:.2f}%"
            f" | HIT RATE="
            f"{metrics['hit_rate']:.2f}%"
            f" | HITS="
            f"{metrics['hit_count']}"
            f"/{len(values)}"
        )


def print_leverage_reality(
    direction,
    horizon,
    values,
):
    banner(
        f"R10 LEVERAGE REALITY | "
        f"{direction} | {horizon}"
    )

    if not values:
        print(
            "NO DATA"
        )
        return

    raw_expectancy = mean(values)

    print(
        "THIS IS SIMPLIFIED EXPECTANCY "
        "ARITHMETIC ONLY."
    )

    print(
        "IT DOES NOT MODEL LIQUIDATION, "
        "FUNDING, SPREAD, SLIPPAGE OR "
        "ACTUAL FILLS."
    )

    print()

    print(
        f"RAW EXPECTANCY="
        f"{raw_expectancy:+.5f}%"
    )

    print(
        f"COST ASSUMPTION="
        f"{PRIMARY_COST_PCT:.2f}%"
    )

    print()

    for leverage in LEVERAGE_SCENARIOS:

        (
            underlying_net,
            leveraged_net,
        ) = leveraged_expectancy(
            raw_expectancy,
            PRIMARY_COST_PCT,
            leverage,
        )

        print(
            f"{leverage:>2}x"
            f" | UNDERLYING NET EXPECTANCY="
            f"{underlying_net:+.5f}%"
            f" | SIMPLE LEVERAGED EXPECTANCY="
            f"{leveraged_net:+.5f}%"
        )


# =============================================================================
# CROSS-HORIZON SUMMARY
# =============================================================================

def print_summary(rows):
    banner(
        "R10 PRIMARY COST SUMMARY"
    )

    print(
        f"PRIMARY HYPOTHETICAL COST: "
        f"{PRIMARY_COST_PCT:.2f}%"
    )

    print()

    summary_rows = []

    for direction in (
        "LONG",
        "SHORT",
    ):

        for horizon in HORIZONS:

            values = get_returns(
                rows,
                direction,
                horizon,
            )

            if not values:
                continue

            raw_expectancy = mean(values)

            metrics = cost_metrics(
                values,
                PRIMARY_COST_PCT,
            )

            target = target_metrics(
                values,
                PRIMARY_COST_PCT,
                0.05,
            )

            summary_rows.append({
                "direction": direction,
                "horizon": horizon,
                "n": len(values),

                "raw_expectancy":
                    raw_expectancy,

                "net_expectancy":
                    metrics["expectancy"],

                "net_positive_rate":
                    metrics[
                        "net_positive_rate"
                    ],

                "profit_factor":
                    metrics[
                        "profit_factor"
                    ],

                "target_rate":
                    target["hit_rate"],
            })

    summary_rows.sort(
        key=lambda row:
            row["net_expectancy"],
        reverse=True,
    )

    for rank, row in enumerate(
        summary_rows,
        start=1,
    ):

        print(
            f"{rank}. "
            f"{row['direction']} "
            f"{row['horizon']}"
            f" | N={row['n']}"
            f" | RAW_EXP="
            f"{row['raw_expectancy']:+.5f}%"
            f" | NET_EXP@0.05="
            f"{row['net_expectancy']:+.5f}%"
            f" | NET_POSITIVE="
            f"{row['net_positive_rate']:.2f}%"
            f" | +0.05 NET TARGET="
            f"{row['target_rate']:.2f}%"
            f" | PF="
            f"{fmt(row['profit_factor'], 3)}"
        )


# =============================================================================
# BREAK-EVEN COST ANALYSIS
# =============================================================================

def print_break_even_cost(rows):
    banner(
        "R10 BREAK-EVEN COST ANALYSIS"
    )

    print(
        "BREAK-EVEN COST BELOW IS SIMPLY "
        "THE RAW MEAN RETURN."
    )

    print(
        "IF TOTAL ROUND-TRIP COST IS ABOVE "
        "THAT NUMBER, MEAN EXPECTANCY BECOMES "
        "NEGATIVE."
    )

    print()

    for direction in (
        "LONG",
        "SHORT",
    ):

        for horizon in HORIZONS:

            values = get_returns(
                rows,
                direction,
                horizon,
            )

            if not values:
                continue

            raw_expectancy = mean(values)

            if raw_expectancy > 0:

                print(
                    f"{direction} {horizon}"
                    f" | RAW EXPECTANCY="
                    f"{raw_expectancy:+.5f}%"
                    f" | SIMPLE BREAK-EVEN "
                    f"ROUND-TRIP COST="
                    f"{raw_expectancy:.5f}%"
                )

            else:

                print(
                    f"{direction} {horizon}"
                    f" | RAW EXPECTANCY="
                    f"{raw_expectancy:+.5f}%"
                    f" | ALREADY NEGATIVE "
                    f"BEFORE COST"
                )


# =============================================================================
# FINAL GUARDRAILS
# =============================================================================

def print_guardrails():
    banner(
        "R10 GUARDRAILS"
    )

    print(
        "1. R10 IS HISTORICAL RESEARCH, "
        "NOT LIVE TRADING PROOF."
    )

    print(
        "2. COST VALUES ARE HYPOTHETICAL "
        "RESEARCH ASSUMPTIONS."
    )

    print(
        "3. R10 DOES NOT CLAIM THESE ARE "
        "BITGET'S ACTUAL FEES."
    )

    print(
        "4. TRUE EXECUTION ALSO DEPENDS ON "
        "SPREAD, SLIPPAGE, ORDER TYPE, "
        "FILL QUALITY AND LATENCY."
    )

    print(
        "5. PERPETUAL FUTURES MAY ALSO HAVE "
        "FUNDING COSTS."
    )

    print(
        "6. LEVERAGE MAGNIFIES BOTH PROFITS "
        "AND LOSSES."
    )

    print(
        "7. LEVERAGE DOES NOT TURN NEGATIVE "
        "EXPECTANCY INTO POSITIVE EXPECTANCY."
    )

    print(
        "8. LIQUIDATION AND MAINTENANCE "
        "MARGIN ARE NOT MODELLED HERE."
    )

    print(
        "9. LONG AND SHORT OBSERVATIONS MAY "
        "BE PAIRED FROM THE SAME MARKET "
        "SNAPSHOT AND ARE NOT INDEPENDENT "
        "TRADES."
    )

    print(
        "10. R10 DOES NOT MODIFY R9 OR R9.1."
    )

    print(
        "11. R10 DOES NOT MODIFY BOT 2.0."
    )

    print(
        "12. NO PRODUCTION STRATEGY CHANGE "
        "IS AUTHORIZED BY THIS SCRIPT."
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    connection = None

    try:
        print_startup()

        # -------------------------------------------------------------
        # Hard safety checks
        # -------------------------------------------------------------

        assert DATABASE_WRITES is False
        assert TELEGRAM_SENDING is False
        assert TRADE_EXECUTION is False
        assert PRODUCTION_MODIFICATION is False
        assert AI_CALLS is False
        assert STRATEGY_MODIFICATION is False

        print()
        print(
            "SAFETY CHECK: PASS"
        )

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

        rows = load_rows(
            connection
        )

        print_dataset_health(
            rows
        )

        if not rows:

            banner(
                "R10 STATUS"
            )

            print(
                "NO FAST OUTCOME DATA "
                "AVAILABLE."
            )

            return

        # -------------------------------------------------------------
        # Main analysis
        # -------------------------------------------------------------

        for direction in (
            "LONG",
            "SHORT",
        ):

            for horizon in HORIZONS:

                values = get_returns(
                    rows,
                    direction,
                    horizon,
                )

                if not values:
                    continue

                print_raw_distribution(
                    direction,
                    horizon,
                    values,
                )

                print_cost_sensitivity(
                    direction,
                    horizon,
                    values,
                )

                print_move_requirements(
                    direction,
                    horizon,
                    values,
                )

                print_leverage_reality(
                    direction,
                    horizon,
                    values,
                )

        # -------------------------------------------------------------
        # Summaries
        # -------------------------------------------------------------

        print_summary(
            rows
        )

        print_break_even_cost(
            rows
        )

        print_guardrails()

        banner(
            "R10 FINAL STATUS"
        )

        print(
            "STATUS: R10 EXECUTION / COST "
            "REALITY RESEARCH COMPLETE"
        )

        print(
            "DATABASE REMAINED READ ONLY"
        )

        print(
            "NO WRITES; NO SENDS; NO TRADES; "
            "NO PRODUCTION CHANGES; "
            "NO AI CALLS"
        )

    except Exception as exc:

        banner(
            "R10 ERROR"
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
