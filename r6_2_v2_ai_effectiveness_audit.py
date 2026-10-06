#!/usr/bin/env python3
"""
BRAD'S SIGNALS RESEARCHER
R6.2-V2 AI EFFECTIVENESS AUDIT - READY FOR POST-REPAIR OUTCOMES

Research only:
- PostgreSQL session is READ ONLY.
- No AI/API calls.
- No Telegram.
- No trades.
- No production modification.

Important methodology:
- Uses SIGNALS2_AI_INTEGRATED_V1 only.
- Does NOT require outcome_status='COMPLETE'.
- Each horizon is independently auditable when direction_correct_<horizon> is non-null.
- Genuine AI = ai_confidence non-null AND ai_analysis.available == true AND ai_score present.
- AI-vs-non-AI comparison is descriptive, not causal, because AI is selected by a pre-screen.
"""

import os
import json
import math
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

VERSION = "R6.2-V2-HORIZON-SPECIFIC-AI-EFFECTIVENESS-AUDIT"
MODEL_VERSION = "SIGNALS2_AI_INTEGRATED_V1"

DATABASE_WRITES = False
TELEGRAM_SENDING = False
TRADE_EXECUTION = False
PRODUCTION_MODIFICATION = False
AI_CALLS = False

HORIZONS = [
    ("30s", "direction_correct_30s"),
    ("1m", "direction_correct_1m"),
    ("5m", "direction_correct_5m"),
    ("10m", "direction_correct_10m"),
    ("30m", "direction_correct_30m"),
    ("1h", "direction_correct_1h"),
    ("4h", "direction_correct_4h"),
    ("12h", "direction_correct_12h"),
    ("24h", "direction_correct_24h"),
]

SEP = "=" * 100


def section(title):
    print("\n" + SEP, flush=True)
    print(title, flush=True)
    print(SEP, flush=True)


def pct(x):
    return f"{x * 100:.2f}%"


def wilson(correct, n, z=1.959963984540054):
    if n <= 0:
        return (0.0, 0.0)
    p = correct / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt((p * (1.0 - p) / n) + (z * z / (4.0 * n * n))) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def parse_ai_analysis(value):
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def is_genuine_ai(row):
    analysis = parse_ai_analysis(row.get("ai_analysis"))
    available = analysis.get("available") is True
    ai_score_present = analysis.get("ai_score") is not None
    return row.get("ai_confidence") is not None and available and ai_score_present


def stats(rows, field):
    vals = [r[field] for r in rows if r.get(field) is not None]
    n = len(vals)
    correct = sum(1 for v in vals if bool(v))
    rate = correct / n if n else 0.0
    lo, hi = wilson(correct, n)
    return n, correct, rate, lo, hi


def print_stats(label, rows, field):
    n, correct, rate, lo, hi = stats(rows, field)
    print(
        f"{label}: N={n} CORRECT={correct} RATE={pct(rate)} "
        f"WILSON95={pct(lo)}-{pct(hi)}",
        flush=True,
    )
    return n, rate


def connect_read_only():
    url = os.environ.get("SIGNALS2_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("SIGNALS2_DATABASE_URL / DATABASE_URL is not configured")
    conn = psycopg2.connect(url)
    conn.set_session(readonly=True, autocommit=False)
    return conn


def main():
    section("BRADS-SIGNALS-RESEARCHER")
    print(f"RESEARCH VERSION: {VERSION}", flush=True)
    print(f"UTC START: {datetime.now(timezone.utc).isoformat()}", flush=True)
    print(f"DATABASE WRITES: {DATABASE_WRITES}", flush=True)
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING}", flush=True)
    print(f"TRADE EXECUTION: {TRADE_EXECUTION}", flush=True)
    print(f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION}", flush=True)
    print(f"AI CALLS: {AI_CALLS}", flush=True)

    if any((DATABASE_WRITES, TELEGRAM_SENDING, TRADE_EXECUTION,
            PRODUCTION_MODIFICATION, AI_CALLS)):
        raise RuntimeError("Safety flags invalid")

    print("SAFETY CHECK: PASS", flush=True)

    conn = None
    try:
        conn = connect_read_only()
        print("DATABASE CONNECTION: READY", flush=True)
        print("DATABASE SESSION: READ ONLY", flush=True)

        outcome_columns = ",\n                   ".join(
            f"r.{column} AS {column}" for _, column in HORIZONS
        )

        sql = f"""
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
                o.ai_analysis,
                o.decision,
                o.signal_sent,
                o.model_version,
                {outcome_columns}
            FROM public.signals2_opportunities o
            JOIN public.signals2_outcomes r
              ON r.opportunity_id = o.opportunity_id
            WHERE o.model_version = %s
            ORDER BY o.created_at ASC, o.opportunity_id ASC
        """

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (MODEL_VERSION,))
            rows = [dict(r) for r in cur.fetchall()]

        ai_rows = [r for r in rows if is_genuine_ai(r)]
        non_ai_rows = [r for r in rows if not is_genuine_ai(r)]

        section("R6.2 V2 DATASET")
        print(f"INTEGRATED-MODEL OBSERVATIONS: {len(rows)}", flush=True)
        print(f"GENUINE AI OBSERVATIONS: {len(ai_rows)}", flush=True)
        print(f"NON-AI / PLACEHOLDER OBSERVATIONS: {len(non_ai_rows)}", flush=True)
        share = len(ai_rows) / len(rows) if rows else 0.0
        print(f"GENUINE AI SHARE: {pct(share)}", flush=True)
        print(
            "GENUINE AI RULE: ai_confidence non-null + "
            "ai_analysis.available=true + ai_score present",
            flush=True,
        )

        section("R6.2 V2 HORIZON POPULATION HEALTH")
        any_auditable = False
        for horizon, field in HORIZONS:
            n_all = sum(r.get(field) is not None for r in rows)
            n_ai = sum(r.get(field) is not None for r in ai_rows)
            n_non = sum(r.get(field) is not None for r in non_ai_rows)
            if n_all:
                any_auditable = True
            print(
                f"{horizon}: ALL={n_all} GENUINE_AI={n_ai} NON_AI={n_non}",
                flush=True,
            )

        section("R6.2 V2 AI-USED VS NON-AI OUTCOMES")
        print(
            "CAUTION: DESCRIPTIVE ONLY. AI USE IS PRE-SCREEN SELECTED, "
            "SO THIS IS NOT A CAUSAL COUNTERFACTUAL.",
            flush=True,
        )
        for horizon, field in HORIZONS:
            print(f"\nHORIZON {horizon}", flush=True)
            n_ai, rate_ai = print_stats("  GENUINE AI", ai_rows, field)
            n_non, rate_non = print_stats("  NON-AI", non_ai_rows, field)
            if n_ai and n_non:
                print(
                    f"  RAW RATE DIFFERENCE AI-NONAI: "
                    f"{(rate_ai-rate_non)*100:+.2f}pp",
                    flush=True,
                )
            else:
                print("  RAW RATE DIFFERENCE: INSUFFICIENT POPULATION", flush=True)

        section("R6.2 V2 GENUINE AI BY DIRECTION")
        for direction in ("LONG", "SHORT"):
            subset = [r for r in ai_rows if str(r.get("direction")).upper() == direction]
            print(f"\n{direction}: GENUINE AI OBSERVATIONS={len(subset)}", flush=True)
            for horizon, field in HORIZONS:
                print_stats(f"  {horizon}", subset, field)

        section("R6.2 V2 AI CONFIDENCE DISTRIBUTION")
        ai_scores = [float(r["ai_confidence"]) for r in ai_rows
                     if r.get("ai_confidence") is not None]
        if ai_scores:
            ai_scores.sort()
            def quantile(frac):
                idx = int(round((len(ai_scores) - 1) * frac))
                return ai_scores[idx]
            print(f"N={len(ai_scores)}", flush=True)
            print(f"MIN={ai_scores[0]:.2f}", flush=True)
            print(f"Q25={quantile(.25):.2f}", flush=True)
            print(f"MEDIAN={quantile(.50):.2f}", flush=True)
            print(f"Q75={quantile(.75):.2f}", flush=True)
            print(f"MAX={ai_scores[-1]:.2f}", flush=True)
        else:
            print("NO GENUINE AI CONFIDENCE VALUES", flush=True)

        section("R6.2 V2 INTERPRETATION GUARDRAILS")
        print("1. NO PRODUCTION SCORING CHANGE IS AUTHORIZED BY THIS AUDIT.", flush=True)
        print("2. RAW AI-vs-NONAI DIFFERENCES ARE NOT CAUSAL.", flush=True)
        print("3. EACH HORIZON IS AUDITED WHEN ITS OWN OUTCOME FIELD EXISTS.", flush=True)
        print("4. outcome_status='COMPLETE' IS NOT REQUIRED FOR SHORTER HORIZONS.", flush=True)
        print("5. R6.3 SHOULD USE CHRONOLOGICAL / CONDITIONED VALIDATION.", flush=True)

        section("R6.2 V2 FINAL STATUS")
        if any_auditable:
            print("STATUS: R6.2 V2 AI EFFECTIVENESS AUDIT DATA AVAILABLE", flush=True)
            print(
                "NOTE: RESULTS ARE DESCRIPTIVE RESEARCH EVIDENCE ONLY; "
                "NO PRODUCTION PROMOTION.",
                flush=True,
            )
        else:
            print("STATUS: R6.2 V2 WAITING FOR INTEGRATED OUTCOME POPULATION", flush=True)
            print(
                "NO AI EFFECTIVENESS CLAIM: integrated horizon fields are still empty.",
                flush=True,
            )

        print("DATABASE REMAINED READ ONLY", flush=True)
        print(
            "NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES; NO AI CALLS",
            flush=True,
        )

    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            print("DATABASE CONNECTION: CLOSED", flush=True)


if __name__ == "__main__":
    main()
