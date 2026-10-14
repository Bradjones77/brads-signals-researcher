
"""
BRAD'S SIGNALS RESEARCHER — R11.1 LOCKED PROSPECTIVE VALIDATION

Read-only research. No Telegram, AI, trades, or production modifications.
Rules below were recovered from R11's frozen historical holdout report.
All opportunities must have been CREATED strictly after R11 finished.
Cost assumptions are hypothetical, not Bitget realized execution costs.
"""
import json
import math
import os
from datetime import datetime, timezone
import psycopg2

VERSION = "R11.1-LOCKED-PROSPECTIVE-VALIDATION"
CUTOFF_UTC = "2026-10-13T01:46:09.273000+00:00"
COSTS = (0.02, 0.05, 0.10)
PRIMARY_COST = 0.05
TARGET_NET = 0.05
MIN_MATCHES = 30
DATABASE_WRITES = TELEGRAM_SENDING = TRADE_EXECUTION = AI_CALLS = PRODUCTION_MODIFICATION = False

# Fixed BEFORE examining any post-R11 prospective returns. No automatic search or tuning.
RULES = (
    ("R11S01", "SHORT", "30m", (("5m_bear_breakout", "==", True), ("30m_support_distance", ">=", 0.295509))),
    ("R11S02", "SHORT", "30m", (("5m_bear_breakout", "==", True), ("1h_momentum_acceleration", ">=", 0.253460))),
    ("R11S03", "SHORT", "30m", (("30m_bull_breakout", "==", True), ("4h_bull_breakout", "==", True))),
    ("R11L01", "LONG", "30m", (("1d_macd_hist", ">=", 0.764474), ("1h_momentum_3", "<=", -1.267228))),
)

def parse_json(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            pass
    return {}

def flatten(value, prefix=""):
    output = {}
    for key, val in parse_json(value).items():
        name = f"{prefix}_{key}" if prefix else str(key)
        if isinstance(val, dict):
            output.update(flatten(val, name))
        else:
            output[name] = val
    return output

def features(row):
    merged = {}
    for source in ("combined_features", "technical_features", "market_features"):
        for key, val in flatten(row[source]).items():
            merged.setdefault(key, val)
    return merged

def matches(f, conditions):
    for key, operator, threshold in conditions:
        if key not in f:
            return False
        value = f[key]
        if operator == "==":
            if not isinstance(value, bool) or value is not threshold:
                return False
        else:
            if isinstance(value, bool):
                return False
            try:
                numeric = float(value)
                if not math.isfinite(numeric):
                    return False
            except (ValueError, TypeError):
                return False
            if operator == ">=" and numeric < threshold:
                return False
            if operator == "<=" and numeric > threshold:
                return False
    return True

def metrics(raw, cost):
    if not raw:
        return None
    net = [v - cost for v in raw]
    gains = sum(v for v in net if v > 0)
    losses = -sum(v for v in net if v < 0)
    return {
        "n": len(raw),
        "net_exp": sum(net) / len(net),
        "target_rate": 100 * sum(v >= (cost + TARGET_NET) for v in raw) / len(raw),
        "positive_rate": 100 * sum(v > 0 for v in net) / len(net),
        "pf": gains / losses if losses else (float("inf") if gains else None),
    }

def show(label, result):
    if result is None:
        print(f"{label}: NO COMPLETED MATCHES", flush=True)
        return
    pf = result["pf"]
    pf_text = "N/A" if pf is None else ("INF" if math.isinf(pf) else f"{pf:.3f}")
    print(f'{label}: N={result["n"]} | NET_EXP={result["net_exp"]:+.5f}% '
          f'| NET_TARGET_HIT={result["target_rate"]:.2f}% '
          f'| NET_POSITIVE={result["positive_rate"]:.2f}% | PF={pf_text}', flush=True)

def main():
    print("=" * 90, flush=True)
    print(f"VERSION: {VERSION}", flush=True)
    print(f"RUN UTC: {datetime.now(timezone.utc).isoformat()}", flush=True)
    print(f"STRICT OPPORTUNITY CREATION CUTOFF UTC: {CUTOFF_UTC}", flush=True)
    print("READ ONLY: TRUE | AI: FALSE | TELEGRAM: FALSE | TRADES: FALSE | PRODUCTION CHANGES: FALSE", flush=True)
    print("NO RULE SEARCH, NO THRESHOLD TUNING, NO HISTORICAL DATA", flush=True)
    assert not any((DATABASE_WRITES, TELEGRAM_SENDING, TRADE_EXECUTION, AI_CALLS, PRODUCTION_MODIFICATION))
    url = os.environ.get("SIGNALS2_DATABASE_URL")
    if not url:
        raise RuntimeError("SIGNALS2_DATABASE_URL missing")
    connection = psycopg2.connect(url)
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT o.opportunity_id, o.created_at, o.symbol,
                       UPPER(o.direction) AS direction,
                       o.combined_features, o.technical_features, o.market_features,
                       out.return_30m_pct
                FROM public.signals2_opportunities o
                LEFT JOIN public.signals2_outcomes out
                  ON out.opportunity_id = o.opportunity_id
                WHERE o.created_at > %s::timestamptz
                  AND UPPER(o.direction) IN ('LONG','SHORT')
                  AND UPPER(COALESCE(o.symbol,'')) NOT LIKE '%%TEST%%'
                  AND UPPER(COALESCE(o.symbol,'')) NOT LIKE '%%DIAGNOSTIC%%'
                  AND UPPER(COALESCE(o.symbol,'')) NOT LIKE '%%SYNTHETIC%%'
                ORDER BY o.created_at ASC, o.opportunity_id ASC
            """, (CUTOFF_UTC,))
            names = [d[0] for d in cursor.description]
            rows = [dict(zip(names, record)) for record in cursor.fetchall()]
        print(f"POST-CUTOFF OPPORTUNITIES: {len(rows)}", flush=True)
        valid = []
        for row in rows:
            val = row["return_30m_pct"]
            try:
                if val is None or not math.isfinite(float(val)):
                    continue
                row["raw"] = float(val)
                row["f"] = features(row)
                valid.append(row)
            except (ValueError, TypeError):
                continue
        print(f"POPULATED 30m RETURNS: {len(valid)}", flush=True)
        print(f"PENDING 30m RETURNS: {len(rows)-len(valid)}", flush=True)
        for name, direction, horizon, conditions in RULES:
            print("-" * 90, flush=True)
            print(f"RULE {name} | {direction} {horizon} | {conditions}", flush=True)
            population = [r["raw"] for r in valid if r["direction"] == direction]
            selected = [r["raw"] for r in valid if r["direction"] == direction and matches(r["f"], conditions)]
            print(f"RULE MATCHES: {len(selected)} | MINIMUM SAMPLE: {MIN_MATCHES}", flush=True)
            show("BASELINE @0.05", metrics(population, PRIMARY_COST))
            for cost in COSTS:
                show(f"RULE @COST {cost:.2f}%", metrics(selected, cost))
            if len(selected) < MIN_MATCHES:
                print("RULE STATUS: WAITING FOR SUFFICIENT PROSPECTIVE SAMPLE", flush=True)
            else:
                result = metrics(selected, PRIMARY_COST)
                baseline = metrics(population, PRIMARY_COST)
                if baseline:
                    print(f'NET EXPECTANCY LIFT: {result["net_exp"]-baseline["net_exp"]:+.5f}pp', flush=True)
                    print(f'TARGET HIT LIFT: {result["target_rate"]-baseline["target_rate"]:+.2f}pp', flush=True)
                print("RULE STATUS: OBSERVATIONAL ONLY; NOT LIVE-TRADE APPROVED", flush=True)
        print("=" * 90, flush=True)
        print("R11.1 FINAL STATUS: COMPLETE — READ-ONLY OBSERVATIONAL REPORT", flush=True)
        print("NO WRITES; NO TELEGRAM; NO TRADES; NO AI; NO PRODUCTION CHANGES", flush=True)
        print("Historical selection, dependence, and execution cost uncertainties remain.", flush=True)
    finally:
        connection.rollback()
        connection.close()
        print("DATABASE CONNECTION: CLOSED", flush=True)

if __name__ == "__main__":
    main()
