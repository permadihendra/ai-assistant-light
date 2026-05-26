"""Cost tracker — Gemini token usage logging and report generation.

Used by BrainPlugin (logging) and SystemPlugin (/cost command).
"""

import logging
from datetime import datetime, timedelta, timezone

from app.database import get_db

logger = logging.getLogger(__name__)

# Gemini pricing per 1M tokens
PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.015, "output": 0.075},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
}
_DEFAULT_PRICE = {"input": 0.015, "output": 0.075}

USD_TO_IDR = 16500
WIB = timezone(timedelta(hours=7))


def _get_price(model: str) -> dict:
    return PRICING.get(model.strip().lower(), _DEFAULT_PRICE)


def _fmt_idr(usd: float) -> str:
    idr = usd * USD_TO_IDR
    if idr < 1:
        return f"Rp {idr:.0f}"
    return f"Rp {idr:,.0f}"


async def log_usage(
    chat_id: int, model: str, input_tokens: int, output_tokens: int
) -> None:
    """Log a single token usage record."""
    try:
        db = await get_db()
        await db.execute(
            "INSERT INTO token_usage (chat_id, model, input_tokens, output_tokens, total_tokens) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, model, input_tokens, output_tokens, input_tokens + output_tokens),
        )
        await db.commit()
    except Exception as e:
        logger.warning("Failed to log token usage: %s", e)


async def get_report(days: int = 1) -> str:
    """Generate a cost report string for the last N days."""
    db = await get_db()

    # Check table exists
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE name='token_usage'"
    )
    if not await cursor.fetchone():
        return "📭 No usage data yet. Send some messages first!"

    since = (datetime.now(WIB) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    rows = await db.execute(
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
    )
    data = await rows.fetchall()

    if not data:
        return f"📭 No usage in the last {days} day(s)."

    total_input = sum(r["total_input"] for r in data)
    total_output = sum(r["total_output"] for r in data)
    total_reqs = sum(r["requests"] for r in data)

    lines = [f"📊 *Cost Report · Last {days} Day(s)*", ""]

    # Per-day breakdown
    grand_usd = 0.0
    for r in data:
        p = _get_price(r["model"])
        cost = r["total_input"] / 1_000_000 * p["input"] + r["total_output"] / 1_000_000 * p["output"]
        grand_usd += cost
        pct_input = r["total_input"] / max(total_input, 1) * 100
        pct_output = r["total_output"] / max(total_output, 1) * 100
        lines.append(
            f"  {r['day']}  {r['requests']} req  "
            f"⬆{r['total_input']:,}  ⬇{r['total_output']:,}  "
            f"{_fmt_idr(cost)}"
        )

    lines.append("")
    lines.append(f"  *Total:* {total_reqs} requests · {total_input:,} in / {total_output:,} out · {_fmt_idr(grand_usd)}")

    # Free tier check
    daily_avg = total_reqs / max(days, 1)
    free = 1500
    pct = daily_avg / free * 100
    if pct > 100:
        lines.append(f"⚠️  {daily_avg:.0f}/day — exceeds free tier ({free}/day)!")
    else:
        lines.append(f"✅ {pct:.0f}% of free tier ({free}/day)")

    return "\n".join(lines)
