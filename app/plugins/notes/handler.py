import logging

from app.database import get_db
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)


class NotesPlugin(Plugin):
    name = "notes"
    commands = ["notes", "note"]
    description = "Save and view notes"

    async def handle(self, ctx: BotContext) -> str | None:
        text = ctx.message_text.strip()

        if text.startswith("/notes"):
            return await self._list_notes(ctx)

        if text.startswith("/note "):
            return await self._view_note(ctx)

        return None

    async def save_note(self, chat_id: int, note_text: str) -> str:
        """Called by BrainPlugin to save a note directly."""
        if not note_text.strip():
            return "📝 Can't save an empty note."

        db = await get_db()
        cursor = await db.execute(
            "INSERT INTO notes (chat_id, text) VALUES (?, ?)",
            (chat_id, note_text.strip()),
        )
        note_id = cursor.lastrowid
        await db.commit()

        preview = note_text[:60] + "..." if len(note_text) > 60 else note_text
        return (
            f"📝 *Note #{note_id} saved* ✅\n"
            f"```\n{preview}\n```\n"
            f"Use `/notes` to see all."
        )

    async def _list_notes(self, ctx: BotContext) -> str:
        db = await get_db()
        cursor = await db.execute(
            "SELECT id, text, created_at FROM notes "
            "WHERE chat_id = ? ORDER BY created_at DESC LIMIT 20",
            (ctx.chat_id,),
        )
        rows = list(await cursor.fetchall())

        if not rows:
            return "📭 No notes yet. Send me something worth saving!"

        lines = ["📋 *Your notes:*"]
        for row in rows:
            preview = row["text"][:80] + "..." if len(row["text"]) > 80 else row["text"]
            lines.append(f"  `{row['id']:>3}` — {preview}")

        return "\n".join(lines)

    async def _view_note(self, ctx: BotContext) -> str:
        try:
            note_id = int(ctx.message_text[len("/note "):].strip())
        except (ValueError, IndexError):
            return "❓ Usage: `/note <id>` — view a note by ID."

        db = await get_db()
        cursor = await db.execute(
            "SELECT id, text, created_at FROM notes WHERE id = ? AND chat_id = ?",
            (note_id, ctx.chat_id),
        )
        row = await cursor.fetchone()

        if not row:
            return "❌ Note not found."

        return f"📝 *Note `{row['id']}`:*\n\n{row['text']}"
