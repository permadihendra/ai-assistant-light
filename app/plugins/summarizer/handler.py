import logging
from datetime import datetime

from app.config import settings
from app.database import get_db
from app.llm.base import LLMMessage
from app.llm.prompts import SUMMARIZE_SYSTEM_PROMPT
from app.llm.router import get_provider
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)

PRIVATE_CHAT_HELP = (
    "📝 Use `/summarize` to summarize recent messages in this private chat."
)
MAX_MESSAGE_LENGTH = 4000


class SummarizerPlugin(Plugin):
    name = "summarizer"
    commands = ["summarize", "lastsummary"]
    description = "Summarize recent group chat messages"

    async def handle(self, ctx: BotContext) -> str | None:
        text = ctx.message_text.strip()

        if text.startswith("/lastsummary"):
            return await self._get_last_summary(ctx)

        if text.startswith("/summarize"):
            return await self._summarize(ctx)

        return None

    async def _summarize(self, ctx: BotContext) -> str:
        db = await get_db()

        # Fetch recent messages for this chat
        cursor = await db.execute(
            "SELECT text, username, user_id, created_at FROM messages "
            "WHERE chat_id = ? ORDER BY created_at DESC LIMIT 50",
            (ctx.chat_id,),
        )
        rows = list(await cursor.fetchall())

        if not rows:
            return "📭 No messages to summarize."

        # Build conversation text (reversed to chronological order)
        parts = []
        for row in reversed(rows):
            name = row["username"] or f"User {row['user_id']}"
            parts.append(f"{name}: {row['text']}")

        conversation = "\n".join(parts)

        # Truncate if needed
        if len(conversation) > settings.summarize_max_chars:
            conversation = conversation[-settings.summarize_max_chars:]

        # Call LLM
        try:
            messages = [
                LLMMessage(role="system", content=SUMMARIZE_SYSTEM_PROMPT),
                LLMMessage(role="user", content=conversation),
            ]
            provider = get_provider()
            response = await provider.chat(
                messages,
                max_tokens=512,
                timeout=30.0,
            )
            summary = response.text
        except Exception as e:
            logger.error("Summarization failed: %s", e)
            return "⚠️ Could not generate summary. LLM provider may be unavailable."

        # Store summary
        await db.execute(
            "INSERT INTO summaries (chat_id, summary, message_count) VALUES (?, ?, ?)",
            (ctx.chat_id, summary, len(rows)),
        )
        await db.commit()

        return f"📊 Summary · {len(rows)} messages\n\n{summary}"

    async def _get_last_summary(self, ctx: BotContext) -> str:
        db = await get_db()
        cursor = await db.execute(
            "SELECT summary, message_count, created_at FROM summaries "
            "WHERE chat_id = ? ORDER BY created_at DESC LIMIT 1",
            (ctx.chat_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return "📭 No summaries yet. Use `/summarize` to create one."

        dt = datetime.fromisoformat(row["created_at"])
        return (
            f"📊 *Last summary* ({row['message_count']} messages, "
            f"<t:{int(dt.timestamp())}:R>):*\n\n{row['summary']}"
        )
