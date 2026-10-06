#!/usr/bin/env python3
"""
Brad's Signals Researcher
R6.1 - AI Data Inspector

Purpose:
Inspect how AI-related data is actually persisted before attempting any
AI-vs-system performance audit.

This diagnostic does NOT assume that a numeric ai_confidence proves a real
OpenAI call. It separately inspects ai_confidence and ai_analysis.

Safety:
- PostgreSQL READ ONLY
- No database writes
- No Telegram
- No trades
- No production changes
- No AI/API calls
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone

import psycopg2


VERSION = "R6.1-AI-DATA-INSPECTOR"

DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False
AI_CALLS_ENABLED = False

SAMPLE_LIMIT = 8


def banner(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def parse_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def meaningful_ai_analysis(value):
    parsed = parse_json(value)
    if parsed is None:
        return False
    if isinstance(parsed, dict):
        return len(parsed) > 0
    if isinstance(parsed, list):
        return len(parsed) > 0
    if isinstance(parsed, str):
        return bool(parsed.strip())
    return True


def shape_of(value):
    parsed = parse_json(value)
    if parsed is None:
        return "NULL/EMPTY"
    if isinstance(parsed, dict):
        return "DICT:" + ",".join(sorted(str(k) for k in parsed.keys()))
    if isinstance(parsed, list):
        return f"LIST:length={len(parsed)}"
    return type(parsed).__name__.upper()


def compact(value, limit=900):
    parsed = parse_json(value)
    if parsed is None:
        return "None"
    try:
        text = json.dumps(parsed, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        text = str(parsed)
    return text if len(text) <= limit else text[:limit] + "...[TRUNCATED]"


def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print(f"RESEARCH VERSION: {VERSION}")
    print(f"UTC START: {datetime.now(timezone.utc).isoformat()}")
    print(f"DATABASE WRITES: {DATABASE_WRITES_ENABLED}")
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING_ENABLED}")
    print(f"TRADE EXECUTION: {TRADE_EXECUTION_ENABLED}")
    print(f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION_ENABLED}")
    print(f"AI CALLS: {AI_CALLS_ENABLED}")

    if any((
        DATABASE_WRITES_ENABLED,
        TELEGRAM_SENDING_ENABLED,
        TRADE_EXECUTION_ENABLED,
        PRODUCTION_MODIFICATION_ENABLED,
        AI_CALLS_ENABLED,
    )):
        raise RuntimeError("Safety configuration invalid")

    print("SAFETY CHECK: PASS")

    database_url = os.getenv("SIGNALS2_DATABASE_URL")
    if not database_url:
        raise RuntimeError("SIGNALS2_DATABASE_URL is not configured")

    conn = None

    try:
        conn = psycopg2.connect(database_url)
        conn.set_session(readonly=True, autocommit=False)
        cur = conn.cursor()

        print("DATABASE CONNECTION: READY")
        print("DATABASE SESSION: READ ONLY")

        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'signals2_opportunities'
            ORDER BY ordinal_position
        """)
        columns = [r[0] for r in cur.fetchall()]

        required = {
            "opportunity_id", "created_at", "symbol", "direction",
            "final_confidence", "technical_confidence", "market_confidence",
            "memory_confidence", "ai_confidence", "decision",
            "rejection_reason", "signal_sent", "ai_analysis",
            "model_version", "strategy_version", "outcome_status"
        }

        missing = sorted(required - set(columns))

        banner("R6.1 SCHEMA CHECK")
        print("TABLE: public.signals2_opportunities")
        print(f"COLUMN COUNT: {len(columns)}")
        print(f"REQUIRED AI-AUDIT COLUMNS PRESENT: {not missing}")
        if missing:
            print("MISSING COLUMNS:", ", ".join(missing))
            raise RuntimeError("Required AI-audit columns are missing")

        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(ai_confidence) AS ai_confidence_nonnull,
                COUNT(*) FILTER (
                    WHERE ai_analysis IS NOT NULL
                      AND BTRIM(ai_analysis::text) NOT IN ('', '{}', '[]', 'null')
                ) AS ai_analysis_nonempty,
                COUNT(*) FILTER (WHERE signal_sent IS TRUE) AS signal_sent_true,
                COUNT(*) FILTER (WHERE outcome_status = 'COMPLETE') AS completed
            FROM public.signals2_opportunities
        """)
        total, conf_nonnull, analysis_nonempty_sql, sent, completed = cur.fetchone()

        banner("R6.1 AI POPULATION")
        print(f"TOTAL OPPORTUNITIES: {total}")
        print(f"AI_CONFIDENCE NON-NULL: {conf_nonnull}")
        print(f"AI_ANALYSIS NON-EMPTY (SQL TEXT CHECK): {analysis_nonempty_sql}")
        print(f"SIGNAL_SENT TRUE: {sent}")
        print(f"COMPLETED OUTCOMES: {completed}")
        if total:
            print(f"AI_CONFIDENCE COVERAGE: {100.0 * conf_nonnull / total:.2f}%")
            print(f"AI_ANALYSIS COVERAGE: {100.0 * analysis_nonempty_sql / total:.2f}%")

        cur.execute("""
            SELECT
                decision,
                COUNT(*) AS total,
                COUNT(ai_confidence) AS ai_confidence_nonnull,
                COUNT(*) FILTER (
                    WHERE ai_analysis IS NOT NULL
                      AND BTRIM(ai_analysis::text) NOT IN ('', '{}', '[]', 'null')
                ) AS ai_analysis_nonempty,
                COUNT(*) FILTER (WHERE signal_sent IS TRUE) AS signal_sent_true
            FROM public.signals2_opportunities
            GROUP BY decision
            ORDER BY total DESC
        """)

        banner("R6.1 AI COVERAGE BY DECISION")
        for decision, n, conf_n, analysis_n, sent_n in cur.fetchall():
            print(
                f"DECISION={decision!r} | TOTAL={n} | "
                f"AI_CONFIDENCE={conf_n} | AI_ANALYSIS={analysis_n} | "
                f"SIGNAL_SENT={sent_n}"
            )

        cur.execute("""
            SELECT
                model_version,
                strategy_version,
                COUNT(*) AS total,
                COUNT(ai_confidence) AS ai_confidence_nonnull,
                COUNT(*) FILTER (
                    WHERE ai_analysis IS NOT NULL
                      AND BTRIM(ai_analysis::text) NOT IN ('', '{}', '[]', 'null')
                ) AS ai_analysis_nonempty
            FROM public.signals2_opportunities
            GROUP BY model_version, strategy_version
            ORDER BY total DESC
            LIMIT 20
        """)

        banner("R6.1 AI COVERAGE BY MODEL / STRATEGY VERSION")
        for model, strategy, n, conf_n, analysis_n in cur.fetchall():
            print(
                f"MODEL={model!r} | STRATEGY={strategy!r} | TOTAL={n} | "
                f"AI_CONFIDENCE={conf_n} | AI_ANALYSIS={analysis_n}"
            )

        cur.execute("""
            SELECT
                opportunity_id,
                created_at,
                symbol,
                direction,
                final_confidence,
                technical_confidence,
                market_confidence,
                memory_confidence,
                ai_confidence,
                decision,
                rejection_reason,
                signal_sent,
                ai_analysis,
                model_version,
                strategy_version,
                outcome_status
            FROM public.signals2_opportunities
            WHERE ai_confidence IS NOT NULL
               OR (
                    ai_analysis IS NOT NULL
                    AND BTRIM(ai_analysis::text) NOT IN ('', '{}', '[]', 'null')
               )
            ORDER BY created_at DESC
        """)
        rows = cur.fetchall()

        shapes = Counter()
        meaningful_count = 0
        conf_without_analysis = 0
        analysis_without_conf = 0

        for row in rows:
            ai_conf = row[8]
            ai_analysis = row[12]
            has_analysis = meaningful_ai_analysis(ai_analysis)
            shapes[shape_of(ai_analysis)] += 1

            if has_analysis:
                meaningful_count += 1
            if ai_conf is not None and not has_analysis:
                conf_without_analysis += 1
            if ai_conf is None and has_analysis:
                analysis_without_conf += 1

        banner("R6.1 AI FIELD CONSISTENCY")
        print(f"ROWS WITH AI FIELD ACTIVITY: {len(rows)}")
        print(f"MEANINGFUL AI_ANALYSIS ROWS (PYTHON CHECK): {meaningful_count}")
        print(f"AI_CONFIDENCE PRESENT BUT AI_ANALYSIS EMPTY: {conf_without_analysis}")
        print(f"AI_ANALYSIS PRESENT BUT AI_CONFIDENCE NULL: {analysis_without_conf}")
        print("AI_ANALYSIS SHAPES:")
        for shape, count in shapes.most_common(20):
            print(f"  {count} | {shape}")

        cur.execute("""
            SELECT
                MIN(ai_confidence),
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ai_confidence),
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ai_confidence),
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ai_confidence),
                MAX(ai_confidence),
                COUNT(DISTINCT ai_confidence)
            FROM public.signals2_opportunities
            WHERE ai_confidence IS NOT NULL
        """)
        stats = cur.fetchone()

        banner("R6.1 AI CONFIDENCE DISTRIBUTION")
        print(f"MIN: {stats[0]}")
        print(f"Q25: {stats[1]}")
        print(f"MEDIAN: {stats[2]}")
        print(f"Q75: {stats[3]}")
        print(f"MAX: {stats[4]}")
        print(f"DISTINCT VALUES: {stats[5]}")

        banner("R6.1 RECENT AI-ACTIVE SAMPLES")
        for i, row in enumerate(rows[:SAMPLE_LIMIT], start=1):
            (
                opportunity_id, created_at, symbol, direction,
                final_conf, tech_conf, market_conf, memory_conf, ai_conf,
                decision, rejection_reason, signal_sent, ai_analysis,
                model_version, strategy_version, outcome_status
            ) = row

            print(f"--- SAMPLE {i} ---")
            print(f"OPPORTUNITY_ID: {opportunity_id}")
            print(f"CREATED_AT: {created_at}")
            print(f"SYMBOL / DIRECTION: {symbol} / {direction}")
            print(
                f"CONFIDENCE: FINAL={final_conf} | TECH={tech_conf} | "
                f"MARKET={market_conf} | MEMORY={memory_conf} | AI={ai_conf}"
            )
            print(
                f"DECISION={decision!r} | SIGNAL_SENT={signal_sent} | "
                f"OUTCOME_STATUS={outcome_status!r}"
            )
            print(f"REJECTION_REASON: {rejection_reason!r}")
            print(f"MODEL_VERSION: {model_version!r}")
            print(f"STRATEGY_VERSION: {strategy_version!r}")
            print(f"AI_ANALYSIS_SHAPE: {shape_of(ai_analysis)}")
            print(f"AI_ANALYSIS: {compact(ai_analysis)}")

        banner("R6.1 INTERPRETATION GUARDRAILS")
        print("AI_CONFIDENCE ALONE IS NOT TREATED AS PROOF OF A REAL AI/API CALL.")
        print("AI_ANALYSIS CONTENT/SHAPE MUST BE GROUNDED BEFORE PERFORMANCE AUDITING.")
        print("THIS INSPECTOR DOES NOT MEASURE WHETHER AI IMPROVES WIN RATE.")
        print("NO PRODUCTION DECISION SHOULD BE MADE FROM R6.1 ALONE.")

        banner("R6.1 FINAL STATUS")
        print("STATUS: R6.1 AI DATA INSPECTOR PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES; NO AI CALLS")

        conn.rollback()
        cur.close()

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        banner("R6.1 FAILURE")
        print("STATUS: R6.1 FAILED")
        print(f"ERROR TYPE: {type(exc).__name__}")
        print(f"ERROR: {exc}")
        raise

    finally:
        if conn is not None:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")


if __name__ == "__main__":
    main()
