#!/usr/bin/env python3
"""Cost report — query token_usage table and estimate daily cost in IDR.

Usage:
    uv run python scripts/cost_report.py              # today
    uv run python scripts/cost_report.py --days 7     # last 7 days
    uv run python scripts/cost_report.py --days 30    # last 30 days
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Gemini 2.5 Flash Lite pricing (per 1M tokens)
PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.015, "output": 0.075},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    # Fallback for unknown models
    "__default__": {"input": 0.015, "output": 0.075},
}

USD_TO_IDR = 16500  # approximate rate, update if needed

WIB = timezone(timedelta(hours=7))

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "assistant.db"


def get_pricing(model: str) -> dict:
    model_key = model.strip().lower()
    return PRICING.get(model_key, PRICING["__default__"])


def fmt_idr(amount_usd: float) -> str:
    idr = amount_usd * USD_TO_IDR
    if idr < 1:
        return f"Rp {idr:.2f}"
    elif idr < 1000:
        return f"Rp {idr:,.0f}"
    else:
        return f"Rp {idr:,.0f}"


def report(days: int) -> None:
    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Check if table exists
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE name='token_usage'"
    )
    if not cursor.fetchone():
        print("📭 No token usage data yet. Send some messages first!")
        conn.close()
        return

    since = (datetime.now(WIB) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    # Daily breakdown
    rows = conn.execute(
        """
        SELECT DATE(created_at) as day,
               model,
               SUM(input_tokens) as total_input,
               SUM(output_tokens) as total_output,
               COUNT(*) as requests
        FROM token_usage
        WHERE created_at >= ?
        GROUP BY DATE(created_at), model
        ORDER BY day ASC
        """,
        (since,),
    ).fetchall()

    if not rows:
        print(f"📭 No usage data in the last {days} day(s).")
        conn.close()
        return

    # Totals
    total_input = sum(r["total_input"] for r in rows)
    total_output = sum(r["total_output"] for r in rows)
    total_reqs = sum(r["requests"] for r in rows)

    print(f"{'='*50}")
    print(f"  Token Usage Report — Last {days} Day(s)")
    print(f"{'='*50}")
    print(f"  Period:  {since.split()[0]} → {datetime.now(WIB).strftime('%Y-%m-%d')}")
    print(f"  DB:      {DB_PATH}")
    print()

    print(f"{'Day':<14} {'Model':<24} {'Input':>10} {'Output':>10} {'Req':>6} {'Cost (IDR)':>14}")
    print(f"{'─'*14} {'─'*24} {'─'*10} {'─'*10} {'─'*6} {'─'*14}")

    grand_total_usd = 0.0
    for r in rows:
        pricing = get_pricing(r["model"])
        input_cost = r["total_input"] / 1_000_000 * pricing["input"]
        output_cost = r["total_output"] / 1_000_000 * pricing["output"]
        total_usd = input_cost + output_cost
        grand_total_usd += total_usd

        print(
            f"{r['day']:<14} {r['model']:<24} "
            f"{r['total_input']:>10,} {r['total_output']:>10,} "
            f"{r['requests']:>6} {fmt_idr(total_usd):>14}"
        )

    print(f"{'─'*14} {'─'*24} {'─'*10} {'─'*10} {'─'*6} {'─'*14}")
    print(
        f"{'TOTAL':<14} {'':<24} "
        f"{total_input:>10,} {total_output:>10,} "
        f"{total_reqs:>6} {fmt_idr(grand_total_usd):>14}"
    )
    print()

    # Summary
    print(f"  {'Total requests:':<25} {total_reqs:,}")
    print(f"  {'Total input tokens:':<25} {total_input:,}")
    print(f"  {'Total output tokens:':<25} {total_output:,}")
    print(f"  {'Avg input/request:':<25} {total_input // max(total_reqs, 1):,}")
    print(f"  {'Avg output/request:':<25} {total_output // max(total_reqs, 1):,}")
    print(f"  {'Total cost (USD):':<25} ${grand_total_usd:.6f}")
    print(f"  {'Total cost (IDR):':<25} {fmt_idr(grand_total_usd)}")
    print(f"  {'Rate:':<25} Rp 16,500/USD")
    print()

    # Free tier check
    daily_avg = total_reqs / max(days, 1)
    free_tier_limit = 1500
    if daily_avg > free_tier_limit:
        pct = (daily_avg / free_tier_limit - 1) * 100
        print(f"⚠️  Daily avg ({daily_avg:.0f}) exceeds free tier ({free_tier_limit}/day)")
        print(f"   Over by {pct:.0f}% — may be rate limited!")
    else:
        pct = daily_avg / free_tier_limit * 100
        print(f"✅ Daily avg {daily_avg:.0f} requests — {pct:.0f}% of free tier ({free_tier_limit}/day)")
    print()

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini API cost report")
    parser.add_argument(
        "--days", type=int, default=1,
        help="Number of days to report (default: 1 = today)",
    )
    args = parser.parse_args()
    report(args.days)


if __name__ == "__main__":
    main()
