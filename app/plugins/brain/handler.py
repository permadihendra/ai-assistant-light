import logging

from app.llm.base import LLMMessage
from app.llm.prompts import BRAIN_SYSTEM_PROMPT
from app.llm.router import get_provider
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)


class BrainPlugin(Plugin):
    """Handles non-command messages using LLM understanding.

    When a user sends a message without a /command prefix, the BrainPlugin
    uses the configured LLM provider to understand intent and respond
    conversationally, or guide the user to the right command.
    """

    name = "brain"
    commands: list[str] = []  # No slash commands — handles free text
    description = "AI brain — understands natural language and routes to commands"

    async def handle(self, ctx: BotContext) -> str | None:
        """Process a non-command message through the LLM."""
        try:
            provider = get_provider()
        except RuntimeError:
            # No LLM provider is configured — guide the user
            return (
                "I can't think yet! 😅 Set up a free Gemini API key to enable me:\n\n"
                "1. Go to https://aistudio.google.com/apikey\n"
                "2. Click \"Create API Key\" (free, no credit card)\n"
                "3. Copy the key and add it to your `.env` file:\n"
                "   `GEMINI_API_KEY=your-key-here`\n"
                "4. Restart the bot\n\n"
                "Meanwhile, use /help to see available commands."
            )

        if not provider.is_configured():
            return (
                "⚠️ LLM provider is not fully configured. "
                "Set GEMINI_API_KEY in .env and restart."
            )

        try:
            messages = [
                LLMMessage(role="system", content=BRAIN_SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=ctx.message_text,
                ),
            ]

            response = await provider.chat(
                messages,
                max_tokens=512,
                timeout=15.0,
            )

            return response.text

        except Exception as e:
            logger.error("Brain plugin failed: %s", e, exc_info=True)
            return None
