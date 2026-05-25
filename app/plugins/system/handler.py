from app.plugins.base import BotContext, Plugin, PluginRegistry


class SystemPlugin(Plugin):
    name = "system"
    commands = ["start", "help", "ping", "status"]
    description = "Basic bot commands — ping, help, status"

    async def handle(self, ctx: BotContext) -> str | None:
        cmd = ctx.message_text.strip().split()[0].split("@")[0].lower()

        if cmd == "/ping":
            return "🏓 pong"

        if cmd == "/start":
            return (
                "👋 Hello! I'm *AI Assistant Light*.\n\n"
                "Send `/help` to see what I can do."
            )

        if cmd == "/help":
            return self._build_help()

        if cmd == "/status":
            return (
                "📊 *Bot Status*\n\n"
                "✅ Running\n"
                f"🔗 Chat ID: `{ctx.chat_id}`\n"
                f"👤 Your ID: `{ctx.user_id}`\n"
            )

        return None

    def _build_help(self) -> str:
        registry = PluginRegistry.get()
        parts = [
            "🤖 *AI Assistant Light — Commands*",
            "",
            "📋 *Agenda*",
            "  `/agenda` — Today's agenda",
            "  `/agenda tomorrow` — Tomorrow's agenda",
            "  `/agenda all` — All upcoming agenda",
            "  `/done <id>` — Check off agenda item",
            "  `/done all` — Check off all today",
            "  🤖 Bot also sends agenda auto at 06:00 & 16:00",
            "",
            "⏰ *Reminders*",
            "  `/remind 10m <msg>` — Set reminder (10m, 2h, besok 09:00)",
            "  `/reminders` — List active reminders",
            "  `/cancel <id>` — Cancel a reminder",
            "  🔔 Auto alert 10min before each reminder",
            "",
            "🔍 *Search & Notes*",
            "  `/search <query>` — Web search (DuckDuckGo)",
            "  `/notes` — List all saved notes",
            "  `/note <id>` — View note or reminder source",
            "",
            "📊 *Summarizer*",
            "  `/summarize` — Summarize recent messages",
            "  `/lastsummary` — View last summary",
            "",
            "⚙️ *System*",
            "  `/ping` — Health check",
            "  `/status` — Bot status info",
            "  `/start` — Welcome message",
            "",
            "🧠 *AI Brain (Natural Language)*",
            "  Just type what you want — bot understands:",
            "  • \"search for fastapi\" → web search",
            "  • \"remind me 10m check oven\" → set reminder",
            "  • \"my wifi password is admin123\" → save note",
            "  • \"today's agenda\" → show today",
            "  • \"turn on my pc\" → PC power (GPIO)",
            "  • \"done meeting 3\" → mark agenda done",
            "  • Forward a schedule → auto-save as agenda",
            "",
            "💡 *Tips*",
            "• Reminder time formats: `10m`, `2h`, `besok 09:00`, `lusa 08:00`",
            "• /done <id> — check off any agenda item by its number",
            "• Bot remembers conversation context — reply to messages",
            "  for follow-up questions, bot will know what you mean",
        ]

        return "\n".join(parts)
