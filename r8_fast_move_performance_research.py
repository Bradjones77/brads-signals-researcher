import os
import math
import statistics
from collections import defaultdict

import psycopg2


# ============================================================
# BRAD'S SIGNALS RESEARCHER
# R8 — FAST-MOVE PERFORMANCE RESEARCH
# ============================================================

VERSION = "R8-FAST-MOVE-PERFORMANCE-RESEARCH"

DATABASE_URL = os.getenv("SIGNALS2_DATABASE_URL")

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False

HORIZONS = ("1m", "5m", "10m", "30m")

# ------------------------------------------------------------
# Research-only round-trip cost assumptions.
#
# These are NOT claimed Bitget fees.
# They let us see how sensitive a fast strategy is to costs.
#
# Example:
# 0.10% means entry + exit + slippage combined cost assumption.
# ------------------------------------------------------------

ROUND_TRIP_COST_SCENARIOS_PCT = (
    0.00,
    0.05,
    0.10,
    0.15,
    0.20,
)

# ------------------------------------------------------------
# Leverage scenarios.
#
# These are research illustrations only.
# They do NOT model liquidation, margin rules, funding,
# maintenance margin, execution latency, or position sizing.
# ------------------------------------------------------------

LEVERAGE_SCENARIOS = (
    1,
    5,
    10,
    20,
)

MIN_SAMPLE = 30


# ============================================================
# HELPERS
# ============================================================

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


def pct(value, digits=4):
    if value is None:
        return "N/A"

    return f"{value:.{digits}f}%"


def number(value, digits=2):
    if value is None:
        return "N/A"

    return f"{value:.{digits}f}"


def separator():
    print("=" * 100)


def direction_correct_from_return(value):
    if value is None:
        return None

    return value > 0.0


def profit_factor(net_returns):
    wins = sum(
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
        if wins > 0:
            return float("inf")

        return None

    return wins / losses


def expectancy(net_returns):
    if not net_returns:
        return None

    return mean(net_returns)


def win_rate(net_returns):
    if not net_returns:
        return None

    wins = sum(
        1
        for value in net_returns
        if value > 0
    )

    return (
        wins
        / len(net_returns)
        * 100.0
    )


def average_win(net_returns):
    wins = [
        value
        for value in net_returns
        if value > 0
    ]

    return mean(wins)


def average_loss(net_returns):
    losses = [
        value
        for value in net_returns
        if value < 0
    ]

    return mean(losses)


def max_consecutive_losses(net_returns):
    maximum = 0
    current = 0

    for value in net_returns:

        if value < 0:
            current += 1
            maximum = max(
                maximum,
                current,
            )
        else:
            current = 0

    return maximum


def simple_equity_drawdown(net_returns):
    """
    Simple additive research drawdown.

    This is NOT an account-margin simulation.
    Returns are treated as sequential percentage-point results.
    """

    equity = 0.0
    peak = 0.0
    worst_drawdown = 0.0

    for value in net_returns:

        equity += value

        if equity > peak:
            peak = equity

        drawdown = equity - peak

        if drawdown < worst_drawdown:
            worst_drawdown = drawdown

    return worst_drawdown


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


# ============================================================
# LOAD DATA
# ============================================================

def load_rows(conn):

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.created_at,
            o.symbol,
            o.direction,
            o.entry_price,
            o.final_confidence,
            o.technical_confidence,
            o.market_confidence,
            o.memory_confidence,
            o.ai_confidence,
            o.decision,
            o.signal_sent,
            o.strategy_version,

            out.return_1m_pct,
            out.return_5m_pct,
            out.return_10m_pct,
            out.return_30m_pct,

            out.direction_correct_1m,
            out.direction_correct_5m,
            out.direction_correct_10m,
            out.direction_correct_30m

        FROM signals2_opportunities o

        INNER JOIN signals2_outcomes out
            ON out.opportunity_id = o.opportunity_id

        WHERE
            UPPER(o.direction) IN ('LONG', 'SHORT')

            AND o.entry_price IS NOT NULL

            AND (
                o.strategy_version IS NULL
                OR (
                    UPPER(o.strategy_version) NOT LIKE '%%TEST%%'
                    AND UPPER(o.strategy_version) NOT LIKE '%%DIAGNOSTIC%%'
                    AND UPPER(o.strategy_version) NOT LIKE '%%SYNTHETIC%%'
                )
            )

            AND (
                out.return_1m_pct IS NOT NULL
                OR out.return_5m_pct IS NOT NULL
                OR out.return_10m_pct IS NOT NULL
                OR out.return_30m_pct IS NOT NULL
            )

        ORDER BY o.created_at ASC
        """
    )

    raw = cur.fetchall()

    cur.close()

    rows = []

    for item in raw:

        rows.append(
            {
                "opportunity_id": item[0],
                "created_at": item[1],
                "symbol": str(item[2]).upper(),
                "direction": str(item[3]).upper(),
                "entry_price": safe_float(item[4]),
                "final_confidence": safe_float(item[5]),
                "technical_confidence": safe_float(item[6]),
                "market_confidence": safe_float(item[7]),
                "memory_confidence": safe_float(item[8]),
                "ai_confidence": safe_float(item[9]),
                "decision": item[10],
                "signal_sent": bool(item[11]),
                "strategy_version": item[12],

                "return_1m_pct": safe_float(item[13]),
                "return_5m_pct": safe_float(item[14]),
                "return_10m_pct": safe_float(item[15]),
                "return_30m_pct": safe_float(item[16]),

                "direction_correct_1m": item[17],
                "direction_correct_5m": item[18],
                "direction_correct_10m": item[19],
                "direction_correct_30m": item[20],
            }
        )

    return rows


# ============================================================
# BASIC DATA HEALTH
# ============================================================

def print_dataset_health(rows):

    separator()
    print("R8 DATASET HEALTH")
    separator()

    print(
        f"ROWS WITH AT LEAST ONE FAST OUTCOME: {len(rows)}"
    )

    for direction in ("LONG", "SHORT"):

        subset = [
            row
            for row in rows
            if row["direction"] == direction
        ]

        print(
            f"{direction}: {len(subset)}"
        )

    sent = sum(
        1
        for row in rows
        if row["signal_sent"]
    )

    print(
        f"ACTUAL TELEGRAM SIGNAL_SENT ROWS: {sent}"
    )

    print()

    for horizon in HORIZONS:

        field = f"return_{horizon}_pct"

        values = [
            row[field]
            for row in rows
            if row[field] is not None
        ]

        print(
            f"{horizon}: "
            f"N={len(values)} "
            f"AVG={pct(mean(values))} "
            f"MEDIAN={pct(median(values))}"
        )


# ============================================================
# RAW FAST-MOVE PERFORMANCE
# ============================================================

def print_raw_performance(rows):

    separator()
    print("R8 RAW FAST-MOVE PERFORMANCE")
    print("NO FEES | NO SLIPPAGE | NO LEVERAGE")
    separator()

    for direction in ("LONG", "SHORT"):

        print()
        print(direction)

        subset = [
            row
            for row in rows
            if row["direction"] == direction
        ]

        for horizon in HORIZONS:

            field = f"return_{horizon}_pct"

            returns = [
                row[field]
                for row in subset
                if row[field] is not None
            ]

            if not returns:
                continue

            positive = sum(
                1
                for value in returns
                if value > 0
            )

            raw_rate = (
                positive
                / len(returns)
                * 100.0
            )

            print(
                f"{horizon}: "
                f"N={len(returns)} "
                f"POSITIVE={raw_rate:.2f}% "
                f"AVG={pct(mean(returns))} "
                f"MEDIAN={pct(median(returns))}"
            )


# ============================================================
# COST SENSITIVITY
# ============================================================

def performance_for_cost(
    rows,
    direction,
    horizon,
    cost_pct,
):

    field = f"return_{horizon}_pct"

    selected = [
        row
        for row in rows
        if (
            row["direction"] == direction
            and row[field] is not None
        )
    ]

    net_returns = [
        row[field] - cost_pct
        for row in selected
    ]

    if not net_returns:
        return None

    pf = profit_factor(
        net_returns
    )

    return {
        "n": len(net_returns),
        "win_rate": win_rate(
            net_returns
        ),
        "expectancy": expectancy(
            net_returns
        ),
        "median": median(
            net_returns
        ),
        "average_win": average_win(
            net_returns
        ),
        "average_loss": average_loss(
            net_returns
        ),
        "profit_factor": pf,
        "max_consecutive_losses":
            max_consecutive_losses(
                net_returns
            ),
        "simple_drawdown":
            simple_equity_drawdown(
                net_returns
            ),
    }


def print_cost_sensitivity(rows):

    separator()
    print("R8 ROUND-TRIP COST SENSITIVITY")
    print(
        "COST = RESEARCH ASSUMPTION FOR ENTRY + EXIT + SLIPPAGE"
    )
    print(
        "THESE ARE NOT CLAIMED BITGET FEE RATES"
    )
    separator()

    for direction in ("LONG", "SHORT"):

        print()
        print(direction)

        for horizon in HORIZONS:

            print()
            print(
                f"  HORIZON: {horizon}"
            )

            for cost in ROUND_TRIP_COST_SCENARIOS_PCT:

                result = performance_for_cost(
                    rows=rows,
                    direction=direction,
                    horizon=horizon,
                    cost_pct=cost,
                )

                if result is None:
                    continue

                pf = result[
                    "profit_factor"
                ]

                if pf == float("inf"):
                    pf_text = "INF"
                else:
                    pf_text = number(
                        pf,
                        3,
                    )

                print(
                    f"    COST={cost:.2f}% | "
                    f"N={result['n']} | "
                    f"NET_WIN_RATE={result['win_rate']:.2f}% | "
                    f"EXPECTANCY={pct(result['expectancy'])} | "
                    f"MEDIAN={pct(result['median'])} | "
                    f"PF={pf_text}"
                )


# ============================================================
# CONFIDENCE ANALYSIS
# ============================================================

def confidence_bucket(value):

    if value is None:
        return "NO_CONFIDENCE"

    if value < 50:
        return "<50"

    if value < 60:
        return "50-59.99"

    if value < 65:
        return "60-64.99"

    if value < 70:
        return "65-69.99"

    if value < 80:
        return "70-79.99"

    return "80+"


def print_confidence_performance(rows):

    separator()
    print("R8 FINAL-CONFIDENCE PERFORMANCE")
    print("RAW RETURNS | NO COST ASSUMPTION")
    separator()

    bucket_order = (
        "<50",
        "50-59.99",
        "60-64.99",
        "65-69.99",
        "70-79.99",
        "80+",
        "NO_CONFIDENCE",
    )

    for direction in ("LONG", "SHORT"):

        print()
        print(direction)

        direction_rows = [
            row
            for row in rows
            if row["direction"] == direction
        ]

        for horizon in HORIZONS:

            field = f"return_{horizon}_pct"

            print()
            print(
                f"  HORIZON: {horizon}"
            )

            grouped = defaultdict(list)

            for row in direction_rows:

                value = row[field]

                if value is None:
                    continue

                bucket = confidence_bucket(
                    row["final_confidence"]
                )

                grouped[bucket].append(
                    value
                )

            for bucket in bucket_order:

                values = grouped.get(
                    bucket,
                    [],
                )

                if not values:
                    continue

                print(
                    f"    {bucket}: "
                    f"N={len(values)} "
                    f"POSITIVE={win_rate(values):.2f}% "
                    f"AVG={pct(mean(values))} "
                    f"MEDIAN={pct(median(values))}"
                )


# ============================================================
# SIGNAL-SENT POPULATION
# ============================================================

def print_signal_sent_performance(rows):

    separator()
    print("R8 ACTUAL SIGNAL_SENT POPULATION")
    print(
        "ONLY ROWS WHERE signals2_opportunities.signal_sent = TRUE"
    )
    separator()

    sent_rows = [
        row
        for row in rows
        if row["signal_sent"]
    ]

    print(
        f"SIGNAL_SENT ROWS: {len(sent_rows)}"
    )

    if not sent_rows:

        print(
            "NO SIGNAL_SENT PERFORMANCE DATA AVAILABLE YET."
        )

        return

    for direction in ("LONG", "SHORT"):

        subset = [
            row
            for row in sent_rows
            if row["direction"] == direction
        ]

        print()
        print(
            f"{direction}: N={len(subset)}"
        )

        for horizon in HORIZONS:

            field = f"return_{horizon}_pct"

            values = [
                row[field]
                for row in subset
                if row[field] is not None
            ]

            if not values:
                continue

            print(
                f"  {horizon}: "
                f"N={len(values)} "
                f"POSITIVE={win_rate(values):.2f}% "
                f"AVG={pct(mean(values))} "
                f"MEDIAN={pct(median(values))}"
            )


# ============================================================
# LEVERAGE ILLUSTRATION
# ============================================================

def print_leverage_research(rows):

    separator()
    print("R8 LEVERAGE SENSITIVITY — RESEARCH ILLUSTRATION")
    print(
        "THIS IS NOT A REAL ACCOUNT OR LIQUIDATION SIMULATION"
    )
    print(
        "LEVERAGE MULTIPLIES BOTH POSITIVE AND NEGATIVE RETURNS"
    )
    separator()

    # Use a middle research cost assumption.
    cost = 0.10

    print(
        f"ILLUSTRATIVE ROUND-TRIP COST ASSUMPTION: {cost:.2f}%"
    )

    for direction in ("LONG", "SHORT"):

        print()
        print(direction)

        subset = [
            row
            for row in rows
            if row["direction"] == direction
        ]

        for horizon in HORIZONS:

            field = f"return_{horizon}_pct"

            base_net = [
                row[field] - cost
                for row in subset
                if row[field] is not None
            ]

            if not base_net:
                continue

            base_expectancy = mean(
                base_net
            )

            print()
            print(
                f"  {horizon}: "
                f"N={len(base_net)} "
                f"UNLEVERAGED_NET_EXPECTANCY="
                f"{pct(base_expectancy)}"
            )

            for leverage in LEVERAGE_SCENARIOS:

                leveraged = [
                    value * leverage
                    for value in base_net
                ]

                print(
                    f"    {leverage}x: "
                    f"AVG={pct(mean(leveraged))} "
                    f"MEDIAN={pct(median(leveraged))} "
                    f"SIMPLE_DRAWDOWN="
                    f"{pct(simple_equity_drawdown(leveraged))}"
                )


# ============================================================
# FAST-MOVE THRESHOLD ANALYSIS
# ============================================================

def print_move_thresholds(rows):

    separator()
    print("R8 FAST-MOVE SIZE DISTRIBUTION")
    print("HOW OFTEN DID THE PREDICTED MOVE EXCEED A GIVEN SIZE?")
    separator()

    thresholds = (
        0.05,
        0.10,
        0.20,
        0.30,
        0.50,
        1.00,
    )

    for direction in ("LONG", "SHORT"):

        print()
        print(direction)

        subset = [
            row
            for row in rows
            if row["direction"] == direction
        ]

        for horizon in HORIZONS:

            field = f"return_{horizon}_pct"

            values = [
                row[field]
                for row in subset
                if row[field] is not None
            ]

            if not values:
                continue

            print()
            print(
                f"  HORIZON: {horizon} | N={len(values)}"
            )

            for threshold in thresholds:

                count = sum(
                    1
                    for value in values
                    if value >= threshold
                )

                rate = (
                    count
                    / len(values)
                    * 100.0
                )

                print(
                    f"    >= +{threshold:.2f}%: "
                    f"{count} ({rate:.2f}%)"
                )


# ============================================================
# MAIN
# ============================================================

def main():

    separator()
    print("BRADS-SIGNALS-RESEARCHER")
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
        f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION}"
    )

    print(
        f"AI CALLS: {AI_CALLS}"
    )

    print()

    print(
        "PURPOSE:"
    )

    print(
        "Measure whether fast LONG/SHORT moves have enough "
        "raw edge to survive realistic trading costs."
    )

    print()

    print(
        "IMPORTANT:"
    )

    print(
        "This is hypothetical research. Bot 2.0 does not "
        "execute these observations as trades."
    )

    print(
        "No liquidation, funding, margin rules, latency, "
        "order-book depth or real fill modelling is included."
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

        print_dataset_health(
            rows
        )

        if not rows:

            separator()
            print(
                "STATUS: NO FAST OUTCOME DATA AVAILABLE"
            )
            separator()

            return

        print_raw_performance(
            rows
        )

        print_move_thresholds(
            rows
        )

        print_cost_sensitivity(
            rows
        )

        print_confidence_performance(
            rows
        )

        print_signal_sent_performance(
            rows
        )

        print_leverage_research(
            rows
        )

        separator()
        print("R8 FINAL STATUS")
        separator()

        print(
            "STATUS: R8 FAST-MOVE PERFORMANCE RESEARCH COMPLETE"
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
            "INTERPRETATION GUARDRAILS:"
        )

        print(
            "1. These observations are not independent executed trades."
        )

        print(
            "2. LONG and SHORT observations may exist for the same market/time."
        )

        print(
            "3. Cost scenarios are research assumptions, not claimed exchange fees."
        )

        print(
            "4. Leveraged returns do not model liquidation or margin requirements."
        )

        print(
            "5. Historical profitability does not prove future profitability."
        )

        print(
            "6. R8 must not be used to alter the locked R7.1 prospective test."
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
