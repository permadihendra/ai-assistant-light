from app.cost_tracker import get_report
from app.plugins.base import BotContext, Plugin, PluginRegistry


class SystemPlugin(Plugin):
    name = "system"
    commands = ["start", "help", "ping", "status", "cost"]
    description = "Basic bot commands — ping, help, status, cost"

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

        if cmd == "/cost":
            # Parse optional day count: /cost 7, /cost 30
            rest = ctx.message_text[len("/cost"):].strip()
            days = 7
            if rest:
                try:
                    days = max(1, min(365, int(rest)))
                except ValueError:
                    pass
            return await get_report(days)

        return None

    def _build_help(self) -> str:
        registry = PluginRegistry.get()
        parts = [
            "🤖 AI Assistant Light",
            "",
            "📋 Agenda",
            "/agenda · /done <id>  — manage daily agenda",
            "/agenda tomorrow · /agenda all",
            "",
            "⏰ Reminders",
            "/remind 10m <msg>  — set reminder",
            "/reminders · /cancel <id>",
            "",
            "🔍 Search & Notes",
            "/search <q> · /notes · /note <id>",
            "",
            "📊 Summarizer",
            "/summarize · /lastsummary",
            "",
            "⚙️ System",
            "/ping · /status · /cost <N> · /start",
            "",
            "🧠 AI Brain",
            "Free text → bot understands:",
            "  • 'set alarm 10m' → reminder",
            "  • 'search fastapi' → web search",
            "  • 'save this: ...' → note",
            "  • 'my agenda' → today's agenda",
            "  • 'done meeting 3' → check off",
            "  • 'turn on pc' → GPIO power",
            "  • forward schedule → auto save",
        ]

        return "\n".join(parts)
