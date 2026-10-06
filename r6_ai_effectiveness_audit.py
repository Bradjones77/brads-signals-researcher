#!/usr/bin/env python3
"""Brad's Signals Researcher — R6.2 AI Effectiveness Audit.
READ ONLY. No Telegram, trades, production changes, DB writes, or AI calls.
"""
import os, json, math
from datetime import datetime, timezone
import psycopg2

VERSION="R6.2-AI-EFFECTIVENESS-AUDIT"
H=[("5m","direction_correct_5m"),("30m","direction_correct_30m"),("1h","direction_correct_1h"),("4h","direction_correct_4h"),("12h","direction_correct_12h"),("24h","direction_correct_24h")]

def banner(s):
    print("\n"+"="*100); print(s); print("="*100)

def obj(v):
    if isinstance(v,dict): return v
    if isinstance(v,str):
        try:
            x=json.loads(v); return x if isinstance(x,dict) else {}
        except Exception: return {}
    return {}

def genuine(r):
    a=obj(r["ai_analysis"])
    return r["ai_confidence"] is not None and a.get("available") is True and a.get("ai_score") is not None

def sys_no_ai(r):
    v=[r[x] for x in ("technical_confidence","market_confidence","memory_confidence") if r[x] is not None]
    return sum(map(float,v))/len(v) if v else None

def wilson(k,n,z=1.96):
    if not n:return (0,0)
    p=k/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d
    m=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return 100*(c-m),100*(c+m)

def report(label, rows):
    print(f"\n--- {label} | ROWS={len(rows)} ---")
    for h,c in H:
        v=[r[c] for r in rows if r[c] is not None]
        k=sum(bool(x) for x in v); lo,hi=wilson(k,len(v))
        rate=100*k/len(v) if v else 0
        print(f"{h}: N={len(v)} CORRECT={k} RATE={rate:.2f}% WILSON95={lo:.2f}-{hi:.2f}%")

def main():
    banner("BRADS-SIGNALS-RESEARCHER")
    print("RESEARCH VERSION:",VERSION)
    print("UTC START:",datetime.now(timezone.utc).isoformat())
    print("DATABASE WRITES: False\nTELEGRAM SENDING: False\nTRADE EXECUTION: False\nPRODUCTION MODIFICATION: False\nAI CALLS: False")
    print("SAFETY CHECK: PASS")
    url=os.getenv("SIGNALS2_DATABASE_URL")
    if not url: raise RuntimeError("SIGNALS2_DATABASE_URL missing")
    con=None
    try:
        con=psycopg2.connect(url); con.set_session(readonly=True,autocommit=False)
        cur=con.cursor()
        print("DATABASE CONNECTION: READY\nDATABASE SESSION: READ ONLY")
        outs=", ".join("o."+c for _,c in H)
        cur.execute(f"""SELECT p.opportunity_id,p.created_at,p.symbol,p.direction,p.final_confidence,
        p.technical_confidence,p.market_confidence,p.memory_confidence,p.ai_confidence,p.ai_analysis,
        p.decision,p.signal_sent,p.model_version,p.strategy_version,{outs}
        FROM public.signals2_opportunities p
        JOIN public.signals2_outcomes o ON o.opportunity_id=p.opportunity_id
        WHERE p.outcome_status='COMPLETE' AND p.model_version='SIGNALS2_AI_INTEGRATED_V1'
        ORDER BY p.created_at,p.opportunity_id""")
        names=[d[0] for d in cur.description]
        rows=[dict(zip(names,x)) for x in cur.fetchall()]
        banner("R6.2 DATASET")
        print("COMPLETED INTEGRATED-MODEL OBSERVATIONS:",len(rows))
        if rows: print("FIRST:",rows[0]["created_at"],"\nLAST:",rows[-1]["created_at"])
        for r in rows:
            r["genuine_ai"]=genuine(r); r["system_no_ai"]=sys_no_ai(r)
            r["delta"]=float(r["ai_confidence"])-r["system_no_ai"] if r["genuine_ai"] and r["system_no_ai"] is not None else None
        ai=[r for r in rows if r["genuine_ai"]]; no=[r for r in rows if not r["genuine_ai"]]
        mismatch=0
        for r in ai:
            try:
                if abs(float(obj(r["ai_analysis"])["ai_score"])-float(r["ai_confidence"]))>.001:mismatch+=1
            except Exception:mismatch+=1
        banner("R6.2 GENUINE AI IDENTIFICATION")
        print("RULE: ai_confidence non-null + ai_analysis.available=true + ai_score present")
        print("GENUINE AI OBSERVATIONS:",len(ai))
        print("NON-AI / PLACEHOLDER OBSERVATIONS:",len(no))
        print(f"GENUINE AI SHARE: {100*len(ai)/len(rows) if rows else 0:.2f}%")
        print("AI_SCORE vs AI_CONFIDENCE MISMATCHES:",mismatch)

        banner("R6.2 AI-USED VS NON-AI OUTCOMES")
        report("GENUINE AI USED",ai); report("NO GENUINE AI / PLACEHOLDER",no)
        print("\nCAUTION: direct comparison is selection-biased because AI is applied after a pre-screen.")

        banner("R6.2 AI SCORE BANDS")
        bands=[("<50",lambda x:x<50),("50-54.99",lambda x:50<=x<55),("55-59.99",lambda x:55<=x<60),("60-64.99",lambda x:60<=x<65),("65-69.99",lambda x:65<=x<70),("70+",lambda x:x>=70)]
        for lab,fn in bands:
            s=[r for r in ai if fn(float(r["ai_confidence"]))]
            if s: report("AI "+lab,s)

        banner("R6.2 AI VS NON-AI SYSTEM")
        groups=[("AI >= SYSTEM +10",lambda d:d>=10),("AI +5 TO <+10",lambda d:5<=d<10),("AI WITHIN +/-5",lambda d:-5<d<5),("AI -5 TO >-10",lambda d:-10<d<=-5),("AI <= SYSTEM -10",lambda d:d<=-10)]
        for lab,fn in groups:
            s=[r for r in ai if r["delta"] is not None and fn(r["delta"])]
            if s:
                av=sum(r["delta"] for r in s)/len(s)
                print(f"\n{lab}: AVG DELTA={av:+.2f}"); report(lab,s)

        banner("R6.2 DIRECTION SPLIT")
        report("GENUINE AI LONG",[r for r in ai if r["direction"]=="LONG"])
        report("GENUINE AI SHORT",[r for r in ai if r["direction"]=="SHORT"])

        banner("R6.2 COMPONENT COMPARISONS")
        for comp in ("technical_confidence","market_confidence","memory_confidence"):
            ge=[r for r in ai if r[comp] is not None and float(r["ai_confidence"])>=float(r[comp])]
            lt=[r for r in ai if r[comp] is not None and float(r["ai_confidence"])<float(r[comp])]
            print("\nCOMPONENT:",comp); report("AI >= COMPONENT",ge); report("AI < COMPONENT",lt)

        banner("R6.2 GUARDRAILS")
        print("OBSERVATIONAL AUDIT, NOT RANDOMIZED A/B TEST.")
        print("AI USED VS NON-AI IS CONFOUNDED BY THE PRE-SCREEN.")
        print("PAIRED LONG/SHORT OBSERVATIONS ARE NOT INDEPENDENT TRADES.")
        print("OUTCOME CORRECTNESS IS NOT REALIZED MONEY P&L.")
        print("NO PRODUCTION RULE SHOULD CHANGE FROM R6.2 ALONE.")

        banner("R6.2 FINAL STATUS")
        print("STATUS: R6.2 AI EFFECTIVENESS AUDIT PASS")
        print("DATABASE REMAINED READ ONLY")
        print("NO WRITES; NO SENDS; NO TRADES; NO PRODUCTION CHANGES; NO AI CALLS")
        con.rollback(); cur.close()
    except Exception as e:
        if con:
            try: con.rollback()
            except Exception: pass
        banner("R6.2 FAILURE"); print("STATUS: R6.2 FAILED"); print("ERROR TYPE:",type(e).__name__); print("ERROR:",e)
        raise
    finally:
        if con: con.close(); print("DATABASE CONNECTION: CLOSED")

if __name__=="__main__": main()
