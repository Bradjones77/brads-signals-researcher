"""
Brad's Signals Researcher
Stage R1 - Safe Researcher Foundation

Separate observer/research service for Brad's Signals Bot 2.0.
"""

import os
from datetime import datetime, timezone

RESEARCHER_VERSION = "R1.0"

RESEARCH_MODE = True
DATABASE_WRITES_ENABLED = False
TELEGRAM_SENDING_ENABLED = False
TRADE_EXECUTION_ENABLED = False
PRODUCTION_MODIFICATION_ENABLED = False


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    print("=" * 60, flush=True)
    print("BRADS-SIGNALS-RESEARCHER", flush=True)
    print("=" * 60, flush=True)

    print(f"RESEARCHER VERSION: {RESEARCHER_VERSION}", flush=True)
    print(f"STARTED UTC: {utc_now()}", flush=True)
    print(f"RESEARCH MODE: {RESEARCH_MODE}", flush=True)

    print(f"DATABASE WRITES: {DATABASE_WRITES_ENABLED}", flush=True)
    print(f"TELEGRAM SENDING: {TELEGRAM_SENDING_ENABLED}", flush=True)
    print(f"TRADE EXECUTION: {TRADE_EXECUTION_ENABLED}", flush=True)
    print(
        f"PRODUCTION MODIFICATION: {PRODUCTION_MODIFICATION_ENABLED}",
        flush=True,
    )

    database_configured = bool(
        os.environ.get("SIGNALS2_DATABASE_URL", "").strip()
    )

    print(
        f"DATABASE CONNECTION CONFIGURED: {database_configured}",
        flush=True,
    )

    if (
        DATABASE_WRITES_ENABLED
        or TELEGRAM_SENDING_ENABLED
        or TRADE_EXECUTION_ENABLED
        or PRODUCTION_MODIFICATION_ENABLED
    ):
        raise RuntimeError("RESEARCHER SAFETY CHECK FAILED")

    print("SAFETY CHECK: PASS", flush=True)
    print(
        "STATUS: FOUNDATION READY - OBSERVER ONLY; "
        "NO WRITES; NO SENDS; NO TRADES",
        flush=True,
    )


if __name__ == "__main__":
    main()
