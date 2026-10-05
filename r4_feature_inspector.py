#!/usr/bin/env python3
"""R4 decision-time feature inspector. READ ONLY."""
import json, os
from datetime import datetime, timezone
import psycopg2

VERSION = "R4-FEATURE-INSPECTOR-1.0"
SAMPLE_ROWS = 3

def banner(s):
    print("\n" + "=" * 78)
    print(s)
    print("=" * 78)

def parse(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v

def short(v, n=180):
    try:
        s = json.dumps(v, sort_keys=True, default=str) if isinstance(v,(dict,list)) else repr(v)
    except Exception:
        s = repr(v)
    return s if len(s) <= n else s[:n] + "...<truncated>"

def structure(label, value, depth=0, max_depth=3):
    value = parse(value)
    pad = "  " * depth
    if isinstance(value, dict):
        print(f"{pad}{label}: dict | keys={sorted(map(str,value.keys()))}")
        if depth < max_depth:
            for k in sorted(value, key=lambda x: str(x)):
                v = parse(value[k])
                if isinstance(v,(dict,list)):
                    structure(str(k), v, depth+1, max_depth)
                else:
                    print(f"{'  '*(depth+1)}{k}: {type(v).__name__} | {short(v)}")
    elif isinstance(value, list):
        print(f"{pad}{label}: list | length={len(value)}")
        if value and depth < max_depth:
            structure("[0]", value[0], depth+1, max_depth)
    else:
        print(f"{pad}{label}: {type(value).__name__} | {short(value)}")

def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print("DIAGNOSTIC VERSION:", VERSION)
    print("UTC START:", datetime.now(timezone.utc).isoformat())
    print("DATABASE WRITES: False")
    print("TELEGRAM SENDING: False")
    print("TRADE EXECUTION: False")
    print("PRODUCTION MODIFICATION: False")
    print("SAFETY CHECK: PASS")

    url = os.getenv("SIGNALS2_DATABASE_URL")
    if not url:
        raise RuntimeError("SIGNALS2_DATABASE_URL is not configured")

    conn = None
    try:
        conn = psycopg2.connect(url)
        conn.set_session(readonly=True, autocommit=False)
        print("DATABASE CONNECTION: READY")
        print("DATABASE SESSION: READ ONLY")
        cur = conn.cursor()

        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='opportunities'
            ORDER BY ordinal_position
        """)
        columns = [r[0] for r in cur.fetchall()]
        banner("OPPORTUNITIES TABLE")
        print("COLUMNS:", columns)

        candidates = [
            "id","opportunity_id","created_at","symbol","direction","entry_price",
            "final_confidence","technical_confidence","market_confidence",
            "memory_confidence","ai_confidence","decision","signal_sent",
            "technical_features","market_features","features","raw_analysis",
            "raw_market_context","raw_data","ai_analysis",
            "model_version","strategy_version"
        ]
        wanted = [c for c in candidates if c in columns]
        if not wanted:
            raise RuntimeError("No expected opportunity columns found")

        order_col = "created_at" if "created_at" in columns else wanted[0]
        quoted = ", ".join('"' + c + '"' for c in wanted)
        cur.execute(
            f'SELECT {quoted} FROM public.opportunities '
            f'ORDER BY "{order_col}" DESC LIMIT %s',
            (SAMPLE_ROWS,)
        )
        rows = cur.fetchall()

        banner("RECENT OPPORTUNITY SAMPLES")
        print("SAMPLE ROWS RETURNED:", len(rows))
        nested = {
            "technical_features","market_features","features","raw_analysis",
            "raw_market_context","raw_data","ai_analysis"
        }
        for i,row in enumerate(rows,1):
            rec = dict(zip(wanted,row))
            print("\n" + "-"*78)
            print("SAMPLE", i)
            print("-"*78)
            for k in wanted:
                if k not in nested:
                    print(f"{k}: {short(rec[k])}")
            for k in wanted:
                if k in nested:
                    print()
                    structure(k, rec[k])

        banner("DIAGNOSTIC STATUS")
        print("STATUS: R4 FEATURE INSPECTOR PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES")
        cur.close()
        conn.rollback()
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        banner("DIAGNOSTIC FAILURE")
        print("STATUS: R4 FEATURE INSPECTOR FAILED")
        print("ERROR TYPE:", type(e).__name__)
        print("ERROR:", e)
        raise
    finally:
        if conn:
            conn.close()
            print("DATABASE CONNECTION: CLOSED")

if __name__ == "__main__":
    main()
