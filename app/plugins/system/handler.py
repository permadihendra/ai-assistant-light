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
        lines = ["🤖 *AI Assistant Light — Commands*", ""]

        for plugin in registry.all():
            cmds = ", ".join(f"/{c}" for c in plugin.commands)
            lines.append(f"**{cmds}** — {plugin.description}")

        lines.extend(
            [
                "",
                "💡 *Tips*",
                "• Use `/remind 10m <msg>` for relative time",
                "• Use `/remind tomorrow 09:00 <msg>` for tomorrow",
                "• Use `/search <query>` to search the web",
                "• Use `/summarize` to summarize recent messages",
            ]
        )

        return "\n".join(lines)
