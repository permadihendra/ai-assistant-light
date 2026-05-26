import logging

from app.database import get_db
from app.plugins.base import BotContext, Plugin, PluginRegistry

logger = logging.getLogger(__name__)


def _preview(text: str, max_len: int = 60) -> str:
    """Clean first line of note text for preview."""
    first_line = text.split('\n')[0].strip()
    if len(first_line) > max_len:
        return first_line[:max_len-3] + "..."
    return first_line


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

        preview = _preview(note_text, 80)
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
                "SELECT rowid as id, text FROM notes_fts "
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
            lines.append(f"  #{r['id']} · {_preview(r['text'])}")
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

        from datetime import datetime, timezone, timedelta
        WIB = timezone(timedelta(hours=7))
        now = datetime.now(WIB)
        today_str = now.strftime("%Y-%m-%d")
        yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        lines = [f"📋 Notes · Last {len(rows)}"]

        current_group = None
        for row in rows:
            created = datetime.fromisoformat(row["created_at"]).astimezone(WIB)
            date_key = created.strftime("%Y-%m-%d")

            # Determine group label
            if date_key == today_str:
                group = "Today"
            elif date_key == yesterday_str:
                group = "Yesterday"
            else:
                group = created.strftime("%d %b")

            if group != current_group:
                lines.append("")
                lines.append(f"── {group} ──")
                current_group = group

            preview = _preview(row["text"])
            lines.append(f"#{row['id']}  {preview}")

        lines.append("")
        lines.append("/note <id> to view  ·  /notes for all")
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
