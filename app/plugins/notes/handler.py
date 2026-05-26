import logging

from app.database import get_db
from app.plugins.base import BotContext, Plugin, PluginRegistry

logger = logging.getLogger(__name__)


class NotesPlugin(Plugin):
    name = "notes"
    commands = ["notes", "note"]
    description = "Save and view notes — /note <id> also works for reminders"

    async def handle(self, ctx: BotContext) -> str | None:
        text = ctx.message_text.strip()

        if text.startswith("/notes"):
            return await self._list_notes(ctx)

        if text.startswith("/note "):
            return await self._view_item(ctx)

        return None

    async def save_note(self, chat_id: int, note_text: str) -> str:
        if not note_text.strip():
            return "📝 Can't save an empty note."

        db = await get_db()
        cursor = await db.execute(
            "INSERT INTO notes (chat_id, text) VALUES (?, ?)",
            (chat_id, note_text.strip()),
        )
        note_id = cursor.lastrowid
        await db.commit()

        preview = note_text[:80] + "..." if len(note_text) > 80 else note_text
        return (
            f"📝 Note #{note_id}\n"
            f"{preview}\n"
            f"/notes to view"
        )

    async def search_notes(self, chat_id: int, query: str) -> str:
        """Search notes by keyword via FTS5."""
        if not query.strip():
            return "🔍 What should I search for?"

        from app.plugins.brain.context import _extract_keywords
        keywords = _extract_keywords(query)
        if not keywords:
            return f"🔍 No results for '{query}'"

        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, text, created_at FROM notes_fts "
                "WHERE notes_fts MATCH ? AND chat_id = ? "
                "ORDER BY rank LIMIT 5",
                (keywords, chat_id),
            )
            rows = await cursor.fetchall()
        except Exception:
            rows = []

        if not rows:
            return f"🔍 No notes match '{query}'"

        lines = [f"🔍 *Found {len(rows)} note(s)*"]
        for r in rows:
            preview = r["text"][:80] + "..." if len(r["text"]) > 80 else r["text"]
            lines.append(f"  #{r['id']} · {preview}")
        return "\n".join(lines)

    async def update_note(self, chat_id: int, note_id: str, new_text: str) -> str:
        """Update a note's content."""
        try:
            nid = int(note_id)
        except (ValueError, TypeError):
            return "❌ Invalid note ID."

        if not new_text.strip():
            return "📝 Can't save an empty note."

        db = await get_db()
        cursor = await db.execute(
            "UPDATE notes SET text = ? WHERE id = ? AND chat_id = ?",
            (new_text.strip(), nid, chat_id),
        )
        await db.commit()

        if cursor.rowcount == 0:
            return f"❌ Note #{nid} not found."

        return f"📝 Note #{nid} updated"

    async def delete_note(self, chat_id: int, note_id: str) -> str:
        """Delete a note."""
        try:
            nid = int(note_id)
        except (ValueError, TypeError):
            return "❌ Invalid note ID."

        db = await get_db()
        cursor = await db.execute(
            "DELETE FROM notes WHERE id = ? AND chat_id = ?",
            (nid, chat_id),
        )
        await db.commit()

        if cursor.rowcount == 0:
            return f"❌ Note #{nid} not found."

        return f"🗑️ Note #{nid} deleted"

    async def _list_notes(self, ctx: BotContext) -> str:
        db = await get_db()
        cursor = await db.execute(
            "SELECT id, text, created_at FROM notes "
            "WHERE chat_id = ? ORDER BY created_at DESC LIMIT 20",
            (ctx.chat_id,),
        )
        rows = list(await cursor.fetchall())

        if not rows:
            return "📭 No notes"

        lines = ["📋 Notes"]
        for row in rows:
            preview = row["text"][:80] + "..." if len(row["text"]) > 80 else row["text"]
            lines.append(f"{row['id']}. {preview}")
        return "\n".join(lines)

    async def _view_item(self, ctx: BotContext) -> str:
        """View a note by ID. Also works for reminder IDs (shows source)."""
        try:
            item_id = int(ctx.message_text[len("/note "):].strip())
        except (ValueError, IndexError):
            return "❓ Usage: `/note <id>` — view note or reminder source."

        # First try notes table
        db = await get_db()
        cursor = await db.execute(
            "SELECT id, text, created_at FROM notes WHERE id = ? AND chat_id = ?",
            (item_id, ctx.chat_id),
        )
        row = await cursor.fetchone()
        if row:
            return f"📝 Note #{row['id']}\n\n{row['text']}"

        # Fallback to reminders table — show source
        from app.plugins.reminder.handler import ReminderPlugin
        plugin = PluginRegistry.get().get_plugin("reminder")
        if isinstance(plugin, ReminderPlugin):
            src = await plugin.get_source(ctx.chat_id, item_id)
            if src:
                return src

        return "❌ Note or reminder not found."
